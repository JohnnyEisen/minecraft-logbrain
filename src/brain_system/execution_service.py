"""BrainCore 任务执行服务。

该模块承载异步任务执行、缓存、执行器路由、重试和指标更新。
BrainCore 通过兼容委托暴露原有 API，服务本身只依赖运行时对象协议。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict

from .observability import start_span
from .retry import RetryPolicy, async_retry

logger = logging.getLogger(__name__)


def _invoke_callable(func: Callable[..., Any], args: tuple[Any, ...], kwargs: Dict[str, Any]) -> Any:
    """在进程池中执行可序列化调用。"""
    return func(*args, **kwargs)


class BrainExecutionService:
    """BrainCore 的任务执行协调器。"""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    async def compute(
        self,
        task_id: str,
        func: Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
        priority: int = 0,
        **kwargs: Any,
    ) -> Any:
        runtime = self._runtime
        runtime.performance_stats["total_tasks"] += 1
        effective_timeout = (
            timeout if timeout is not None else runtime.config.get("task_default_timeout", 30.0)
        )

        cache_key = self.generate_cache_key(func, *args, **kwargs)
        cached = runtime.result_cache.get(cache_key)
        if cached is not None:
            self._increment_metric(runtime.obs, "cache_hits")
            return cached
        self._increment_metric(runtime.obs, "cache_misses")

        slow_task_threshold = float(runtime.config.get("slow_task_threshold", 5.0))

        async def run_once() -> Any:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)

            loop = asyncio.get_running_loop()
            executor_kind = self.select_executor_kind(
                task_id=task_id,
                priority=priority,
                args=args,
                kwargs=kwargs,
            )
            if executor_kind == "process" and runtime.process_pool is not None:
                runtime.performance_stats["process_dispatched_tasks"] += 1
                return await loop.run_in_executor(
                    runtime.process_pool,
                    _invoke_callable,
                    func,
                    args,
                    kwargs,
                )

            runtime.performance_stats["thread_dispatched_tasks"] += 1
            return await loop.run_in_executor(
                runtime.thread_pool,
                _invoke_callable,
                func,
                args,
                kwargs,
            )

        start_time = time.time()

        def check_slow_task(elapsed: float) -> None:
            if elapsed <= slow_task_threshold:
                return
            logger.warning(
                "Slow task detected: %s took %.2fs (threshold: %.2fs)",
                task_id,
                elapsed,
                slow_task_threshold,
            )
            slow_tasks = runtime.performance_stats.setdefault("slow_tasks", [])
            slow_tasks.append({
                "task_id": task_id,
                "duration": elapsed,
                "timestamp": time.time(),
            })
            del slow_tasks[:-100]

        with start_span(runtime.obs, f"compute:{task_id}"):
            try:
                policy = RetryPolicy(
                    max_attempts=runtime.retry_policy.max_attempts,
                    initial_delay_seconds=runtime.retry_policy.initial_delay_seconds,
                    max_delay_seconds=runtime.retry_policy.max_delay_seconds,
                    backoff_multiplier=runtime.retry_policy.backoff_multiplier,
                    jitter_ratio=runtime.retry_policy.jitter_ratio,
                    timeout_seconds=effective_timeout,
                    circuit_breaker=runtime.retry_policy.circuit_breaker,
                )
                if policy.max_attempts > 1:
                    result = await async_retry(run_once, policy=policy)
                elif effective_timeout > 0:
                    result = await asyncio.wait_for(run_once(), timeout=effective_timeout)
                else:
                    result = await run_once()
            except asyncio.TimeoutError as exc:
                elapsed = time.time() - start_time
                check_slow_task(elapsed)
                self._increment_task_error(runtime.obs, task_id)
                logger.error(
                    "计算任务超时 %s: %.2fs > %.2fs",
                    task_id,
                    elapsed,
                    effective_timeout,
                )
                raise TimeoutError(
                    f"Task {task_id} timed out after {elapsed:.2f}s"
                ) from exc
            except Exception:
                elapsed = time.time() - start_time
                check_slow_task(elapsed)
                self._increment_task_error(runtime.obs, task_id)
                logger.exception("计算任务失败 %s", task_id)
                raise

        elapsed = time.time() - start_time
        check_slow_task(elapsed)
        runtime.result_cache.set(cache_key, result)
        if runtime.obs.metrics_enabled and runtime.obs.task_seconds is not None:
            try:
                runtime.obs.task_seconds.labels(task_id=str(task_id)).observe(elapsed)
            except Exception as exc:
                logger.debug("Failed to observe task_seconds metric: %s", exc)

        runtime.performance_stats["completed_tasks"] += 1
        completed = runtime.performance_stats["completed_tasks"]
        previous_average = float(runtime.performance_stats["avg_compute_time"])
        runtime.performance_stats["avg_compute_time"] = (
            (previous_average * (completed - 1)) + elapsed
        ) / completed
        return result

    def estimate_payload_size(self, args: tuple[Any, ...], kwargs: Dict[str, Any]) -> int:
        try:
            return len(repr((args, kwargs)).encode("utf-8", errors="ignore"))
        except Exception:
            return 0

    @staticmethod
    def matches_prefixes(value: str, prefixes: list[str]) -> bool:
        return any(value.startswith(str(prefix)) for prefix in prefixes)

    def select_executor_kind(
        self,
        *,
        task_id: str,
        priority: int,
        args: tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> str:
        runtime = self._runtime
        task_name = str(task_id)
        strategy = str(runtime.config.get("executor_routing_strategy", "balanced")).lower()
        cpu_prefixes = runtime.config.get(
            "cpu_task_prefixes", ["cpu_", "cpu_task", "thread_cpu_"]
        )
        if not isinstance(cpu_prefixes, list):
            cpu_prefixes = ["cpu_", "cpu_task", "thread_cpu_"]
        io_prefixes = runtime.config.get("io_task_prefixes", ["io_", "net_", "disk_"])
        if not isinstance(io_prefixes, list):
            io_prefixes = ["io_", "net_", "disk_"]

        is_cpu_hint = self.matches_prefixes(task_name, [str(x) for x in cpu_prefixes])
        is_io_hint = self.matches_prefixes(task_name, [str(x) for x in io_prefixes])
        payload_limit = int(runtime.config.get("process_pool_payload_max_bytes", 262_144))
        payload_size = self.estimate_payload_size(args, kwargs)
        process_available = runtime.process_pool is not None and payload_size <= payload_limit

        if priority >= 2:
            return "thread"
        if priority <= -1 and process_available and is_cpu_hint and not is_io_hint:
            return "process"
        if strategy == "latency":
            return "thread"
        if strategy == "throughput":
            return "process" if process_available and is_cpu_hint and not is_io_hint else "thread"
        return "thread"

    @staticmethod
    def generate_cache_key(func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        func_name = getattr(func, "__name__", str(func))
        try:
            key_repr = f"{func_name}:{args}:{kwargs}"
            return hashlib.sha256(key_repr.encode("utf-8")).hexdigest()
        except Exception:
            key_data = (func_name, args, kwargs)
            key_str = json.dumps(key_data, sort_keys=True, default=str)
            return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _increment_metric(observability: Any, metric_name: str) -> None:
        if not observability.metrics_enabled:
            return
        metric = getattr(observability, metric_name, None)
        if metric is None:
            return
        try:
            metric.inc()
        except Exception as exc:
            logger.debug("Failed to increment %s metric: %s", metric_name, exc)

    @staticmethod
    def _increment_task_error(observability: Any, task_id: str) -> None:
        if not observability.metrics_enabled or observability.task_errors is None:
            return
        try:
            observability.task_errors.labels(task_id=str(task_id)).inc()
        except Exception as exc:
            logger.debug("Failed to increment task_errors metric: %s", exc)
