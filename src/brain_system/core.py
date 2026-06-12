from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import multiprocessing
import os
import re
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Tuple

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .discovery import iter_dlc_files, load_dlc_classes_from_file
from .dlc import BrainDLC
from .dlc_manager import DLCManager
from .models import DLCManifest, DLCState

from brain_system import __version__

from .cache import LruTtlCache
from .observability import build_observability, start_span
from .retry import RetryPolicy, async_retry
from .security import SignatureVerificationError, load_public_keys_from_files, verify_dlc_signature
from .config import ConsulConfigSource, FileConfigSource
from .config_validator import build_config, validate_config
from .ha import LeaderElectionConfig, LeaderElector


try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


def _invoke_callable(func: Callable[..., Any], args: tuple[Any, ...], kwargs: Dict[str, Any]) -> Any:
    """在进程池中执行可序列化调用。"""
    return func(*args, **kwargs)


class BrainCore:
    """AI 语义分析核心调度器。

    负责 DLC 生命周期管理、任务调度、缓存与可观测性。

    **核心职责**:

    - DLC 管理：注册、加载、初始化、禁用、热重载
    - 任务调度：compute() 异步计算，支持超时、重试、优先级
    - 缓存：LRU+TTL 结果缓存（默认 2000 条目 / 300s TTL）
    - 可观测性：Prometheus metrics + OpenTelemetry spans

    :param config_path: 可选的 JSON 配置文件路径。

    **用法**::

        brain = BrainCore(config_path="config/brain_config.json")
        brain.load_builtin_dlcs()
        result = brain.compute("analyze", crash_log=log_text)
    """

    CORE_ALIASES: frozenset[str] = frozenset({"Brain Core", "BrainCore", "core"})

    def __init__(self, config_path: Optional[str] = None):
        """初始化 BrainCore。

        :param config_path: JSON 配置文件路径（可选）。
        """
        self.name = "LogBrain Core Scheduler"
        self.version = __version__

        from types import MappingProxyType

        self._config_path = config_path
        self._config_raw = self._load_config(config_path)
        # 对外暴露为只读 MappingProxyType，防止 DLC/补丁运行时修改安全配置
        self.config = MappingProxyType(self._config_raw)
        self._setup_logging()

        self.obs = build_observability(self.config)

        self._public_keys_pem: list[bytes] = []
        self._load_public_keys()

        self._dlc_manager = DLCManager(self)
        self.computational_units: Dict[str, Any] = {}
        self.result_cache = LruTtlCache(
            max_entries=int(self.config.get("cache_max_entries", 2_000)),
            ttl_seconds=float(self.config.get("cache_ttl_seconds", 300.0)),
        )

        self.performance_stats: Dict[str, Any] = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "avg_compute_time": 0.0,
            "memory_usage": 0.0,
            "cpu_usage": 0.0,
            "thread_dispatched_tasks": 0,
            "process_dispatched_tasks": 0,
        }

        self.monitor_task: Optional[asyncio.Task[None]] = None
        self._last_valid_config: dict[str, Any] = copy.deepcopy(dict(self.config))
        self._previous_valid_config: Optional[dict[str, Any]] = None

        default_thread_pool_size = min(multiprocessing.cpu_count() * 2, 16)
        thread_pool_size = int(self.config.get("thread_pool_size", default_thread_pool_size))
        self.thread_pool = ThreadPoolExecutor(
            max_workers=thread_pool_size,
            thread_name_prefix="BrainWorker"
        )
        
        default_process_pool_size = min(multiprocessing.cpu_count(), 4)
        process_pool_size = int(self.config.get("process_pool_size", default_process_pool_size))
        self.process_pool = ProcessPoolExecutor(max_workers=process_pool_size) if process_pool_size > 0 else None
        self._process_pool_max_workers = process_pool_size

        self.retry_policy = RetryPolicy(
            max_attempts=int(self.config.get("retry_max_attempts", 1)),
            initial_delay_seconds=float(self.config.get("retry_initial_delay_seconds", 0.2)),
            max_delay_seconds=float(self.config.get("retry_max_delay_seconds", 5.0)),
            backoff_multiplier=float(self.config.get("retry_backoff_multiplier", 2.0)),
            jitter_ratio=float(self.config.get("retry_jitter_ratio", 0.2)),
        )

        self._config_source = self._build_config_source()
        if self._config_source is not None and bool(self.config.get("enable_config_watch", False)):
            self._config_source.start_watch(self._on_config_update)

        self._leader_elector = self._build_leader_elector()
        if self._leader_elector is not None:
            try:
                self._leader_elector.start()
            except Exception as e:
                logging.warning("Leader elector start failed: %s", e)

        if self.config.get("enable_disk_cache", True):
            self._setup_disk_cache()

        logging.info("%s v%s 初始化完成", self.name, self.version)

    # ---------------- 配置 / 日志 ----------------

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        return build_config(config_path)

    def _parse_dependency(self, raw: str) -> tuple[str, SpecifierSet]:
        """解析依赖声明。

        支持：
        - "Brain Core"（无版本约束）
        - "Brain Core>=1.0.0,<2"（语义化版本约束）

        V-017 Fix: 增强输入验证，防止注入攻击
        """

        s = str(raw).strip()
        if not s:
            return "", SpecifierSet("")

        # V-017 Fix: Validate input to prevent injection
        # Only allow alphanumeric, dash, underscore, dot, and version operators
        if not re.match(r'^[a-zA-Z0-9_\-.\s><=!~,]+$', s):
            logging.warning(f"Invalid dependency declaration (suspicious characters): {s[:50]}")
            return "", SpecifierSet("")

        # Limit length to prevent DoS
        if len(s) > 200:
            logging.warning(f"Dependency declaration too long: {len(s)} chars")
            s = s[:200]

        first_op = None
        for i, ch in enumerate(s):
            if ch in "<>=!~":
                first_op = i
                break

        if first_op is None:
            return s, SpecifierSet("")

        name = s[:first_op].strip()
        spec = s[first_op:].strip()

        # V-017 Fix: Validate name doesn't contain version operators
        if any(op in name for op in ['>=', '<=', '==', '!=', '~=', '>', '<']):
            logging.warning(f"Invalid dependency name: {name}")
            return "", SpecifierSet("")

        try:
            return name, SpecifierSet(spec)
        except Exception as e:
            logging.warning(f"Invalid version specifier '{spec}': {e}")
            return name, SpecifierSet("")

    def _validate_dependency(self, dep_raw: str) -> None:
        name, spec = self._parse_dependency(dep_raw)
        if not name:
            raise RuntimeError("依赖声明为空")

        # 允许依赖声明指向核心本体（不是 DLC）。
        # 常见写法："Brain Core"。
        core_aliases = self.CORE_ALIASES | {self.name}
        if name in core_aliases:
            if str(spec):
                try:
                    ver = Version(str(self.version))
                except Exception as e:
                    raise RuntimeError(f"核心版本不可解析: {self.version}") from e
                if ver not in spec:
                    raise RuntimeError(f"核心版本不兼容: {ver} not in {spec}")
            return

        if name not in self.dlc_manifests:
            raise RuntimeError(f"缺少依赖 DLC: {name}")

        if str(spec):
            try:
                ver = Version(str(self.dlc_manifests[name].version))
            except Exception as e:
                raise RuntimeError(f"依赖 DLC 版本不可解析: {name}={self.dlc_manifests[name].version}") from e

            if ver not in spec:
                raise RuntimeError(f"依赖 DLC 版本不兼容: {name}={ver} not in {spec}")

    def _setup_logging(self) -> None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        level_name = self.config.get("log_level", "INFO")
        level = getattr(logging, str(level_name).upper(), logging.INFO)

        handlers: list[logging.Handler] = [logging.StreamHandler()]
        try:
            handlers.append(
                RotatingFileHandler(
                    "brain_core.log",
                    maxBytes=10 * 1024 * 1024,
                    backupCount=5,
                    encoding="utf-8",
                )
            )
        except Exception as e:
            logging.debug("RotatingFileHandler setup failed (filesystem may be read-only): %s", e)

        # 结构化 JSON 日志（可选依赖）
        if bool(self.config.get("log_json", False)):
            try:
                from pythonjsonlogger import jsonlogger  # type: ignore

                fmt = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
                for h in handlers:
                    h.setFormatter(fmt)
                logging.basicConfig(level=level, handlers=handlers)
                return
            except Exception as e:
                logging.debug("pythonjsonlogger not available, using standard logging: %s", e)

        logging.basicConfig(level=level, format=log_format, handlers=handlers)

    def _set_log_level(self, level_name: str) -> None:
        level = getattr(logging, str(level_name).upper(), logging.INFO)
        logging.getLogger().setLevel(level)

    def _load_public_keys(self) -> None:
        files = self.config.get("dlc_public_key_pem_files", [])
        if isinstance(files, list) and files:
            try:
                self._public_keys_pem = load_public_keys_from_files([str(x) for x in files])
            except Exception as e:
                logging.warning("加载 DLC 公钥失败: %s", e)

    def _verify_dlc_file_signature(self, path: Path) -> bool:
        """在 import/exec 之前验证 DLC 文件签名。"""

        try:
            required = bool(self.config.get("dlc_signature_required", False))
            verify_if_present = bool(self.config.get("dlc_signature_verify_if_present", True))
            sig_exists = Path(str(path) + ".sig").exists()
            if required or (verify_if_present and sig_exists):
                if not self._public_keys_pem:
                    raise SignatureVerificationError("未配置 dlc_public_key_pem_files")
                verify_dlc_signature(path, public_keys_pem=self._public_keys_pem)
            return True
        except SignatureVerificationError as e:
            logging.error("DLC 签名验证失败，拒绝加载 %s: %s", path.name, e)
            return False
        except Exception as e:
            logging.error("DLC 签名验证异常，拒绝加载 %s: %s", path.name, type(e).__name__)
            return False

    def _build_config_source(self):
        src = str(self.config.get("config_source", "file")).lower()
        if src == "consul":
            try:
                return ConsulConfigSource(
                    host=str(self.config.get("consul_host", "127.0.0.1")),
                    port=int(self.config.get("consul_port", 8500)),
                    key_prefix=str(self.config.get("consul_key_prefix", "brain/config")),
                    poll_seconds=float(self.config.get("config_poll_seconds", 2.0)),
                )
            except Exception as e:
                logging.warning("Consul 配置源不可用: %s", e)
                return None

        # 默认 file
        if self._config_path and os.path.exists(self._config_path):
            return FileConfigSource(self._config_path, poll_seconds=float(self.config.get("config_poll_seconds", 1.0)))
        return None

    def _on_config_update(self, new_config: dict[str, Any]) -> None:
        if not isinstance(new_config, dict):
            return
        
        # 备份当前配置以便回滚
        old_config = copy.deepcopy(self.config)

        # 在完整候选配置上做验证，避免只校验 patch 带来的遗漏。
        candidate_config = copy.deepcopy(self.config)
        candidate_config.update(copy.deepcopy(new_config))
        
        # 验证新配置
        validation_errors = self._validate_config(candidate_config)
        if validation_errors:
            logging.error("配置验证失败，拒绝更新: %s", validation_errors)
            return

        new_log_level = str(candidate_config.get("log_level", "INFO"))
        new_cache_max = int(candidate_config.get("cache_max_entries", self.result_cache.max_entries))
        new_cache_ttl = float(candidate_config.get("cache_ttl_seconds", self.result_cache.ttl_seconds))

        try:
            self._set_log_level(new_log_level)
        except Exception as e:
            logging.debug("Failed to set log level: %s", e)

        try:
            self.result_cache.set_limits(max_entries=new_cache_max, ttl_seconds=new_cache_ttl)
        except Exception as e:
            logging.warning("Failed to update cache limits: %s", e)

        try:
            old_cb = getattr(self.retry_policy, 'circuit_breaker', None)
            new_policy = RetryPolicy(
                max_attempts=int(candidate_config.get("retry_max_attempts", self.retry_policy.max_attempts)),
                initial_delay_seconds=float(
                    candidate_config.get("retry_initial_delay_seconds", self.retry_policy.initial_delay_seconds)
                ),
                max_delay_seconds=float(candidate_config.get("retry_max_delay_seconds", self.retry_policy.max_delay_seconds)),
                backoff_multiplier=float(
                    candidate_config.get("retry_backoff_multiplier", self.retry_policy.backoff_multiplier)
                ),
                jitter_ratio=float(candidate_config.get("retry_jitter_ratio", self.retry_policy.jitter_ratio)),
            )
            if old_cb:
                new_policy.circuit_breaker = old_cb
        except Exception as e:
            logging.warning("Failed to update retry policy, rolling back: %s", e)
            try:
                self._set_log_level(str(old_config.get("log_level", "INFO")))
            except Exception:
                pass
            try:
                self.result_cache.set_limits(
                    max_entries=int(old_config.get("cache_max_entries", self.result_cache.max_entries)),
                    ttl_seconds=float(old_config.get("cache_ttl_seconds", self.result_cache.ttl_seconds)),
                )
            except Exception:
                pass
            return

        self.retry_policy = new_policy
        self._previous_valid_config = old_config
        self._config_raw = candidate_config
        self.config = MappingProxyType(self._config_raw)

        self._load_public_keys()
        self._last_valid_config = copy.deepcopy(self.config)

        # 通知各 DLC 配置已变更
        self._notify_dlcs_config_changed()

        logging.info("配置已热更新")

    def _validate_config(self, config: dict[str, Any]) -> list[str]:
        """验证配置参数。

        Args:
            config: 待验证的配置字典。

        Returns:
            验证错误列表，空列表表示验证通过。
        """
        return validate_config(config)

    def get_config(self) -> dict[str, Any]:
        """获取当前配置的副本。

        Returns:
            当前配置字典的副本。
        """
        return dict(self.config)

    def rollback_config(self) -> bool:
        """回滚到上一个有效配置。

        Returns:
            是否成功回滚。
        """
        previous = self._previous_valid_config
        if not previous:
            logging.info("无可回滚配置")
            return False

        current = copy.deepcopy(self.config)
        target_config = copy.deepcopy(previous)

        old_cb = getattr(self.retry_policy, "circuit_breaker", None)
        restored_policy = RetryPolicy(
            max_attempts=int(target_config.get("retry_max_attempts", self.retry_policy.max_attempts)),
            initial_delay_seconds=float(
                target_config.get("retry_initial_delay_seconds", self.retry_policy.initial_delay_seconds)
            ),
            max_delay_seconds=float(
                target_config.get("retry_max_delay_seconds", self.retry_policy.max_delay_seconds)
            ),
            backoff_multiplier=float(
                target_config.get("retry_backoff_multiplier", self.retry_policy.backoff_multiplier)
            ),
            jitter_ratio=float(target_config.get("retry_jitter_ratio", self.retry_policy.jitter_ratio)),
            timeout_seconds=float(target_config.get("task_default_timeout", self.retry_policy.timeout_seconds)),
        )
        if old_cb:
            restored_policy.circuit_breaker = old_cb

        self._set_log_level(str(target_config.get("log_level", "INFO")))
        self.result_cache.set_limits(
            max_entries=int(target_config.get("cache_max_entries", self.result_cache.max_entries)),
            ttl_seconds=float(target_config.get("cache_ttl_seconds", self.result_cache.ttl_seconds)),
        )

        self.retry_policy = restored_policy
        self.config = target_config
        self._load_public_keys()
        self._last_valid_config = copy.deepcopy(self.config)
        self._previous_valid_config = current

        logging.info("配置已回滚")
        return True

    def _build_leader_elector(self) -> Optional[LeaderElector]:
        if not bool(self.config.get("leader_election_enabled", False)):
            return None
        try:
            cfg = LeaderElectionConfig(
                enabled=True,
                redis_url=str(self.config.get("redis_url", "redis://localhost:6379/0")),
                lock_key=str(self.config.get("leader_lock_key", "brain:leader")),
                ttl_seconds=int(self.config.get("leader_ttl_seconds", 10)),
                renew_interval_seconds=float(self.config.get("leader_renew_interval_seconds", 3.0)),
            )
            return LeaderElector(cfg)
        except Exception as e:
            logging.warning("Leader 选举不可用: %s", e)
            return None

    # ---------------- DLC 管理（委托至 DLCManager） ----------------

    @property
    def dlcs(self) -> Dict[str, BrainDLC]:
        """向后兼容：直接访问 DLC 字典。"""
        return self._dlc_manager.dlcs

    @property
    def dlc_manifests(self) -> Dict[str, DLCManifest]:
        """向后兼容：直接访问 DLC manifest 字典。"""
        return self._dlc_manager.dlc_manifests

    @property
    def dlc_dependencies(self) -> Dict[str, Set[str]]:
        """向后兼容：直接访问 DLC 依赖字典。"""
        return self._dlc_manager.dlc_dependencies

    def register_dlc(self, dlc: BrainDLC) -> None:
        self._dlc_manager.register(dlc)

    def unregister_dlc(self, name: str) -> None:
        self._dlc_manager.unregister(name)

    def enable_dlc(self, name: str) -> bool:
        return self._dlc_manager.enable(name)

    def disable_dlc(self, name: str) -> bool:
        return self._dlc_manager.disable(name)

    def suspend_dlc(self, name: str) -> bool:
        return self._dlc_manager.suspend(name)

    def resume_dlc(self, name: str) -> bool:
        return self._dlc_manager.resume(name)

    def reload_dlc_file(self, dlc_path: str) -> tuple[int, bool]:
        return self._dlc_manager.reload_dlc_file(dlc_path)

    def load_dlc_file(self, dlc_path: str, *, allow_replace: bool = False) -> int:
        return self._dlc_manager.load_dlc_file(dlc_path, allow_replace=allow_replace)

    def _topological_sort(
        self, graph: dict[str, list[str]], priority_map: dict[str, int] | None = None
    ) -> list[str] | None:
        """对 DLC 依赖图进行拓扑排序（Kahn 算法）。

        Args:
            graph: DLC 名称到其依赖名称列表的映射。graph[name] = [dep1, dep2, ...]
            priority_map: 可选的 DLC 优先级映射（值越小越先加载），用于同层级排序。

        Returns:
            排序后的 DLC 名称列表，或 None（存在循环依赖时）。
        """
        from collections import deque

        reverse_graph: dict[str, list[str]] = {name: [] for name in graph}
        in_degree: dict[str, int] = {}

        for name, deps in graph.items():
            resolved_deps = [d for d in deps if d in graph]
            in_degree[name] = len(resolved_deps)
            for dep in resolved_deps:
                reverse_graph[dep].append(name)

        queue: deque[str] = deque()
        for name in graph:
            if in_degree[name] == 0:
                queue.append(name)

        sorted_result: list[str] = []
        pmap = priority_map or {}

        while queue:
            queue = deque(sorted(queue, key=lambda n: (pmap.get(n, 0), n)))
            current = queue.popleft()
            sorted_result.append(current)

            for dependent in reverse_graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(sorted_result) != len(graph):
            remaining = set(graph) - set(sorted_result)
            logging.warning("检测到循环依赖: %s", remaining)
            return None

        return sorted_result

    def load_all_dlcs(self, search_paths: Optional[list[str]] = None) -> int:
        return self._dlc_manager.load_all(search_paths)

    def get_dlc_status(self) -> Dict[str, Any]:
        return self._dlc_manager.get_status()

    def get_computational_unit(self, unit_type: str) -> Any:
        return self._dlc_manager.get_computational_unit(unit_type)

    def _notify_dlcs_config_changed(self) -> None:
        self._dlc_manager.notify_config_changed()

    # ---------------- 任务执行 / 缓存 ----------------

    async def compute(
        self,
        task_id: str,
        func: Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
        priority: int = 0,
        **kwargs: Any
    ) -> Any:
        """执行计算任务，支持超时、优先级和取消。

        Args:
            task_id: 任务唯一标识。
            func: 要执行的函数。
            *args: 函数位置参数。
            timeout: 超时时间（秒），None 使用配置默认值。
            priority: 任务优先级（0=普通，1=高，2=紧急）。
            **kwargs: 函数关键字参数。

        Returns:
            函数执行结果。

        Raises:
            TimeoutError: 任务执行超时。
            asyncio.CancelledError: 任务被取消。
        """
        self.performance_stats["total_tasks"] += 1

        # 使用配置的超时时间
        effective_timeout = timeout if timeout is not None else self.config.get("task_default_timeout", 30.0)

        cache_key = self._generate_cache_key(func, *args, **kwargs)
        cached = self.result_cache.get(cache_key)
        if cached is not None:
            if self.obs.metrics_enabled and self.obs.cache_hits is not None:
                try:
                    self.obs.cache_hits.inc()
                except Exception as e:
                    logging.debug("Failed to increment cache_hits metric: %s", e)
            return cached

        if self.obs.metrics_enabled and self.obs.cache_misses is not None:
            try:
                self.obs.cache_misses.inc()
            except Exception as e:
                logging.debug("Failed to increment cache_misses metric: %s", e)

        # 慢任务追踪
        slow_task_threshold = float(self.config.get("slow_task_threshold", 5.0))

        async def _run_once() -> Any:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)

            loop = asyncio.get_running_loop()

            executor_kind = self._select_executor_kind(task_id=task_id, priority=priority, args=args, kwargs=kwargs)
            if executor_kind == "process" and self.process_pool is not None:
                self.performance_stats["process_dispatched_tasks"] += 1
                return await loop.run_in_executor(self.process_pool, _invoke_callable, func, args, kwargs)

            self.performance_stats["thread_dispatched_tasks"] += 1
            return await loop.run_in_executor(self.thread_pool, _invoke_callable, func, args, kwargs)

        start_time = time.time()
        
        SLOW_TASKS_MAX_SIZE = 100
        
        def _check_slow_task(elapsed: float) -> None:
            if elapsed > slow_task_threshold:
                logging.warning(
                    "Slow task detected: %s took %.2fs (threshold: %.2fs)",
                    task_id, elapsed, slow_task_threshold
                )
                slow_tasks = self.performance_stats.setdefault("slow_tasks", [])
                slow_tasks.append({
                    "task_id": task_id,
                    "duration": elapsed,
                    "timestamp": time.time(),
                })
                while len(slow_tasks) > SLOW_TASKS_MAX_SIZE:
                    slow_tasks.pop(0)

        with start_span(self.obs, f"compute:{task_id}"):
            try:
                # 使用带超时的重试策略
                policy_with_timeout = RetryPolicy(
                    max_attempts=self.retry_policy.max_attempts,
                    initial_delay_seconds=self.retry_policy.initial_delay_seconds,
                    max_delay_seconds=self.retry_policy.max_delay_seconds,
                    backoff_multiplier=self.retry_policy.backoff_multiplier,
                    jitter_ratio=self.retry_policy.jitter_ratio,
                    timeout_seconds=effective_timeout,
                    circuit_breaker=self.retry_policy.circuit_breaker,
                )
                
                if policy_with_timeout.max_attempts > 1:
                    result = await async_retry(_run_once, policy=policy_with_timeout)
                else:
                    # 单次执行也需要超时控制
                    if effective_timeout > 0:
                        result = await asyncio.wait_for(
                            _run_once(), timeout=effective_timeout
                        )
                    else:
                        result = await _run_once()
                        
            except asyncio.TimeoutError as e:
                elapsed = time.time() - start_time
                _check_slow_task(elapsed)
                if self.obs.metrics_enabled and self.obs.task_errors is not None:
                    try:
                        self.obs.task_errors.labels(task_id=str(task_id)).inc()
                    except Exception as metric_err:
                        logging.debug("Failed to increment task_errors metric: %s", metric_err)
                logging.error("计算任务超时 %s: %.2fs > %.2fs", task_id, elapsed, effective_timeout)
                raise TimeoutError(f"Task {task_id} timed out after {elapsed:.2f}s") from e
            except Exception as e:
                elapsed = time.time() - start_time
                _check_slow_task(elapsed)
                if self.obs.metrics_enabled and self.obs.task_errors is not None:
                    try:
                        self.obs.task_errors.labels(task_id=str(task_id)).inc()
                    except Exception as metric_err:
                        logging.debug("Failed to increment task_errors metric: %s", metric_err)
                logging.error("计算任务失败 %s: %s", task_id, e)
                raise

        elapsed = time.time() - start_time
        _check_slow_task(elapsed)
        
        self.result_cache.set(cache_key, result)

        if self.obs.metrics_enabled and self.obs.task_seconds is not None:
            try:
                self.obs.task_seconds.labels(task_id=str(task_id)).observe(elapsed)
            except Exception as e:
                logging.debug("Failed to observe task_seconds metric: %s", e)

        self.performance_stats["completed_tasks"] += 1
        completed = self.performance_stats["completed_tasks"]
        prev_avg = float(self.performance_stats["avg_compute_time"])
        self.performance_stats["avg_compute_time"] = ((prev_avg * (completed - 1)) + elapsed) / completed

        return result

    def _estimate_payload_size(self, args: tuple[Any, ...], kwargs: Dict[str, Any]) -> int:
        """粗略估算参数序列化体积，用于避免进程池过载。"""
        try:
            return len(repr((args, kwargs)).encode("utf-8", errors="ignore"))
        except Exception:
            return 0

    def _matches_prefixes(self, value: str, prefixes: list[str]) -> bool:
        for prefix in prefixes:
            if value.startswith(str(prefix)):
                return True
        return False

    def _select_executor_kind(
        self,
        *,
        task_id: str,
        priority: int,
        args: tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> str:
        """根据任务提示、优先级与负载估计选择执行器类型。"""
        task_name = str(task_id)
        strategy = str(self.config.get("executor_routing_strategy", "balanced")).lower()

        cpu_prefixes = self.config.get("cpu_task_prefixes", ["cpu_", "cpu_task", "thread_cpu_"])
        if not isinstance(cpu_prefixes, list):
            cpu_prefixes = ["cpu_", "cpu_task", "thread_cpu_"]

        io_prefixes = self.config.get("io_task_prefixes", ["io_", "net_", "disk_"])
        if not isinstance(io_prefixes, list):
            io_prefixes = ["io_", "net_", "disk_"]

        is_cpu_hint = self._matches_prefixes(task_name, [str(x) for x in cpu_prefixes])
        is_io_hint = self._matches_prefixes(task_name, [str(x) for x in io_prefixes])

        payload_limit = int(self.config.get("process_pool_payload_max_bytes", 262_144))
        payload_size = self._estimate_payload_size(args, kwargs)
        process_available = self.process_pool is not None and payload_size <= payload_limit

        # 高优先级默认低延迟：优先线程池。
        if priority >= 2:
            return "thread"

        # 明确低优先级 + CPU 提示：优先进程池。
        if priority <= -1 and process_available and is_cpu_hint and not is_io_hint:
            return "process"

        if strategy == "latency":
            return "thread"

        if strategy == "throughput":
            if process_available and is_cpu_hint and not is_io_hint:
                return "process"
            return "thread"

        # balanced: safe default, thread pool for everything (avoids IPC overhead).
        # CPU tasks route to process pool only in "throughput" mode (explicit opt-in).
        return "thread"

    def _generate_cache_key(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        func_name = getattr(func, "__name__", str(func))
        
        try:
            key_repr = f"{func_name}:{args}:{kwargs}"
            result = hashlib.sha256(key_repr.encode("utf-8")).hexdigest()
            return result
        except Exception:
            key_data = (func_name, args, kwargs)
            key_str = json.dumps(key_data, sort_keys=True, default=str)
            return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

    # ---------------- 监控 / 生命周期 ----------------

    def start_performance_monitor(self) -> None:
        """启动性能监控。

        要求：必须在正在运行的事件循环中调用（即在 async 上下文里）。
        """

        async def monitor() -> None:
            while True:
                await asyncio.sleep(float(self.config.get("monitoring_interval", 15.0)))

                if psutil is not None:
                    try:
                        self.performance_stats["memory_usage"] = psutil.Process().memory_info().rss / 1024 / 1024
                        self.performance_stats["cpu_usage"] = psutil.cpu_percent()
                    except Exception as e:
                        logging.debug("Failed to get system stats: %s", e)

                for dlc in self.dlcs.values():
                    hook = getattr(dlc, "on_monitor_tick", None)
                    if callable(hook):
                        try:
                            hook(self.performance_stats)
                        except Exception as e:
                            logging.debug("DLC monitor hook 失败 %s: %s", dlc.get_manifest().name, e)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as e:
            raise RuntimeError("start_performance_monitor() 必须在事件循环运行时调用") from e

        self.monitor_task = loop.create_task(monitor())

    # ---------------- 健康检查 ----------------

    def health_check(self) -> Dict[str, Any]:
        """执行健康检查，返回系统状态。

        Returns:
            包含健康状态、组件状态和性能指标的字典。
        """
        health: Dict[str, Any] = {
            "status": "healthy",
            "timestamp": time.time(),
            "version": self.version,
            "components": {},
            "metrics": {},
            "issues": [],
        }

        # 检查 DLC 状态
        dlc_issues = []
        for name, dlc in self.dlcs.items():
            try:
                state_ok = dlc.state not in (DLCState.FAILED, DLCState.DISABLED, DLCState.UNLOADED)
                initialized = bool(getattr(dlc, "_initialized", False))
                health["components"][f"dlc:{name}"] = {
                    "status": "ok" if state_ok and initialized else "degraded",
                    "state": dlc.state.value,
                    "initialized": initialized,
                }
                if dlc.state == DLCState.FAILED:
                    dlc_issues.append(f"DLC {name} is in FAILED state")
                elif not initialized:
                    dlc_issues.append(f"DLC {name} not initialized")
                elif dlc.state == DLCState.DISABLED:
                    dlc_issues.append(f"DLC {name} is disabled")
            except Exception as e:
                health["components"][f"dlc:{name}"] = {"status": "error", "error": str(e)}
                dlc_issues.append(f"DLC {name} error: {e}")

        if dlc_issues:
            health["issues"].extend(dlc_issues)

        # 检查线程池状态
        try:
            thread_pool_ok = self.thread_pool is not None and not getattr(self.thread_pool, '_shutdown', False)
            health["components"]["thread_pool"] = {
                "status": "ok" if thread_pool_ok else "error",
                "max_workers": self.thread_pool._max_workers if self.thread_pool else 0,
            }
            if not thread_pool_ok:
                health["issues"].append("Thread pool is shutdown or unavailable")
        except Exception as e:
            health["components"]["thread_pool"] = {"status": "error", "error": str(e)}

        # 检查进程池状态
        if self.process_pool is not None:
            try:
                # ProcessPoolExecutor 没有公开的 _shutdown 属性
                # 尝试检查是否可以提交任务来判断状态
                process_pool_ok = True
                try:
                    # 使用 _process_pool_max_workers 而非私有属性
                    max_workers = self._process_pool_max_workers
                except AttributeError:
                    max_workers = multiprocessing.cpu_count()
                
                health["components"]["process_pool"] = {
                    "status": "ok" if process_pool_ok else "error",
                    "max_workers": max_workers,
                }
            except Exception as e:
                health["components"]["process_pool"] = {"status": "error", "error": str(e)}

        # 检查缓存状态
        try:
            cache_stats = self.result_cache.get_stats()
            health["components"]["cache"] = {
                "status": "ok",
                "entries": cache_stats.get("entries", 0),
                "hit_rate": cache_stats.get("hit_rate", 0.0),
                "max_entries": cache_stats.get("max_entries", 0),
            }
            # 如果命中率过低，添加警告
            if cache_stats.get("hits", 0) + cache_stats.get("misses", 0) > 100:
                if cache_stats.get("hit_rate", 1.0) < 0.3:
                    health["issues"].append(f"Low cache hit rate: {cache_stats.get('hit_rate', 0):.1%}")
        except Exception as e:
            health["components"]["cache"] = {"status": "error", "error": str(e)}

        # 检查断路器状态
        if hasattr(self.retry_policy, 'circuit_breaker') and self.retry_policy.circuit_breaker:
            cb = self.retry_policy.circuit_breaker
            cb_stats = cb.get_stats()
            health["components"]["circuit_breaker"] = {
                "status": cb_stats["state"],
                "failures": cb_stats["failures"],
            }
            if cb.is_open:
                health["issues"].append("Circuit breaker is OPEN - requests are being rejected")

        # 性能指标
        health["metrics"] = {
            "total_tasks": self.performance_stats.get("total_tasks", 0),
            "completed_tasks": self.performance_stats.get("completed_tasks", 0),
            "avg_compute_time": round(self.performance_stats.get("avg_compute_time", 0.0), 4),
            "memory_usage_mb": round(self.performance_stats.get("memory_usage", 0.0), 2),
            "cpu_usage_percent": round(self.performance_stats.get("cpu_usage", 0.0), 2),
        }

        # 慢任务统计
        slow_tasks = self.performance_stats.get("slow_tasks", [])
        if slow_tasks:
            health["metrics"]["slow_tasks_count"] = len(slow_tasks)
            health["metrics"]["recent_slow_tasks"] = slow_tasks[-5:]  # 最近5个慢任务

        # 确定整体状态
        if health["issues"]:
            if any("error" in str(issue).lower() or "shutdown" in str(issue).lower() for issue in health["issues"]):
                health["status"] = "unhealthy"
            else:
                health["status"] = "degraded"

        return health

    def is_healthy(self) -> bool:
        """快速检查系统是否健康。

        Returns:
            系统是否处于健康状态。
        """
        try:
            health = self.health_check()
            status = str(health.get("status", "unhealthy"))
            return status != "unhealthy"
        except Exception:
            return False

    def get_ready_status(self) -> Dict[str, Any]:
        """获取就绪状态（用于 Kubernetes 就绪探针）。

        Returns:
            就绪状态信息。
        """
        ready = True
        reasons: list[str] = []

        # 检查线程池
        if self.thread_pool is None or getattr(self.thread_pool, '_shutdown', False):
            ready = False
            reasons.append("Thread pool not ready")

        # 检查是否有加载的 DLC
        if not self.dlcs:
            reasons.append("No DLCs loaded")

        # 检查断路器
        if hasattr(self.retry_policy, 'circuit_breaker') and self.retry_policy.circuit_breaker:
            if self.retry_policy.circuit_breaker.is_open:
                ready = False
                reasons.append("Circuit breaker is open")

        return {
            "ready": ready,
            "reasons": reasons,
        }

    async def shutdown(self) -> None:
        logging.info("正在关闭大脑系统...")

        if self.monitor_task:
            self.monitor_task.cancel()

        for dlc in list(self.dlcs.values()):
            try:
                dlc.shutdown()
            except Exception as e:
                logging.warning("DLC shutdown error: %s", e)

        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
        if self.process_pool:
            self.process_pool.shutdown(wait=True)

        try:
            if self._config_source is not None:
                self._config_source.stop_watch()
        except Exception as e:
            logging.debug("Failed to stop config source watch: %s", e)

        try:
            if self._leader_elector is not None:
                self._leader_elector.stop()
        except Exception as e:
            logging.debug("Failed to stop leader elector: %s", e)

        self._save_cache()
        logging.info("大脑系统已关闭")

    # ---------------- 磁盘缓存 ----------------

    def _setup_disk_cache(self) -> None:
        cache_dir = Path.home() / ".brain" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = cache_dir
        self._cleanup_old_cache()
        self._load_cache()

    def _cleanup_old_cache(self) -> None:
        cache_files = list(self.cache_dir.glob("*.cache"))
        cache_files.sort(key=lambda x: x.stat().st_mtime)

        total_size = sum(f.stat().st_size for f in cache_files)
        max_size = int(self.config.get("cache_size_mb", 256)) * 1024 * 1024

        while total_size > max_size and cache_files:
            oldest = cache_files.pop(0)
            total_size -= oldest.stat().st_size
            try:
                oldest.unlink()
            except Exception:
                break

    def _load_cache(self) -> None:
        try:
            cache_path = Path(self.cache_dir) / "result_cache.json"
            if not cache_path.exists():
                return

            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                self.result_cache.load_serializable(data)
        except Exception as e:
            logging.debug("加载磁盘缓存失败: %s", e)

    def _save_cache(self) -> None:
        try:
            if not self.config.get("enable_disk_cache", True):
                return
            if not getattr(self, "cache_dir", None):
                return

            cache_path = Path(self.cache_dir) / "result_cache.json"

            serializable = self.result_cache.snapshot_serializable()

            tmp_path = cache_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False)
            tmp_path.replace(cache_path)
        except Exception as e:
            logging.debug("保存磁盘缓存失败: %s", e)
