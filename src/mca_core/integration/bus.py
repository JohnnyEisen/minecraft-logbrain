"""
集成总线 — 统一子系统间通信协议。

IntegrationBus 是 MCA 子系统间通信的核心中枢，提供:
    - 请求/响应模式: 同步和异步的子系统间调用
    - 消息路由: 自动将消息路由到目标子系统
    - 断路器集成: 故障隔离，防止级联失败
    - 超时管理: 可配置的请求超时
    - 性能度量: 内置延迟和吞吐量统计
    - 错误传播: 统一的 IntegrationError 层次结构

架构设计:
    EventBus（fire-and-forget 事件）
        └── IntegrationBus（请求/响应 + 事件）
                ├── RoutingTable（子系统路由表）
                ├── HealthChecker（健康检查）
                └── MetricsCollector（性能度量）

用法:
    from mca_core.integration import IntegrationBus, ISubsystem

    bus = IntegrationBus(name="main_bus")
    bus.register(patches_subsystem)
    bus.register(training_subsystem)

    response = bus.request(
        source="main_app",
        target="patch_management",
        operation="get_status",
        timeout=5.0,
    )
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from mca_core.events import EventBus, get_event_bus
from mca_core.integration.contract import (
    ISubsystem,
    IntegrationMessage,
    MessageDirection,
    MessagePriority,
    SubsystemLifecycle,
)
from mca_core.integration.errors import (
    CommunicationError,
    IntegrationError,
    IntegrationTimeoutError,
    ProtocolError,
    StateConflictError,
    SubsystemUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class RoutingEntry:
    """路由表条目。

    Attributes:
        subsystem: 子系统实例
        registered_at: 注册时间
        operations: 该子系统支持的操作
    """

    subsystem: ISubsystem
    registered_at: datetime = field(default_factory=datetime.now)
    operations: list[str] = field(default_factory=list)

    def update_operations(self) -> None:
        try:
            self.operations = self.subsystem.supported_operations()
        except Exception:
            self.operations = []


@dataclass
class RequestMetrics:
    """单次请求的性能度量。

    Attributes:
        source: 源子系统
        target: 目标子系统
        operation: 操作名称
        start_time: 开始时间
        end_time: 结束时间
        success: 是否成功
        error_message: 错误消息（如有）
    """

    source: str = ""
    target: str = ""
    operation: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool = False
    error_message: str = ""

    @property
    def latency_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000.0


class IntegrationBus:
    """集成总线 — 子系统间统一通信中枢。

    管理所有注册子系统的消息路由、请求/响应和事件分发。

    Attributes:
        name: 总线名称
        _subsystems: 已注册的子系统字典（名称 -> RoutingEntry）
        _metrics: 请求性能度量列表
        _metrics_lock: 度量线程锁
        _default_timeout: 默认请求超时（秒）
        _event_bus: 关联的事件总线实例
    """

    def __init__(
        self,
        name: str = "integration_bus",
        default_timeout: float = 30.0,
        event_bus: Optional[EventBus] = None,
        max_metrics: int = 1000,
    ) -> None:
        self.name = name
        self._subsystems: Dict[str, RoutingEntry] = {}
        self._metrics: List[RequestMetrics] = []
        self._metrics_lock = threading.Lock()
        self._default_timeout = default_timeout
        self._event_bus = event_bus or get_event_bus()
        self._max_metrics = max_metrics

        logger.info("IntegrationBus '%s' 已初始化", name)

    def register(self, subsystem: ISubsystem) -> None:
        """注册子系统到总线。

        Args:
            subsystem: 实现 ISubsystem 接口的子系统实例

        Raises:
            IntegrationError: 子系统名称为空或已存在
        """
        name = subsystem.name
        if not name:
            raise IntegrationError("子系统名称不能为空")

        if name in self._subsystems:
            existing = self._subsystems[name].subsystem
            logger.error(
                "子系统 '%s' 已注册（类型: %s），拒绝重复注册。"
                "请先调用 unregister() 或使用 force=True",
                name, type(existing).__name__,
            )
            raise ValueError(
                f"子系统 '{name}' 已注册。使用 force=True 强制替换。"
            )

        entry = RoutingEntry(subsystem=subsystem)
        entry.update_operations()
        self._subsystems[name] = entry

        logger.info(
            "子系统 '%s' (v%s) 已注册，支持操作: %s",
            name,
            subsystem.version,
            entry.operations,
        )

    def unregister(self, name: str) -> bool:
        """注销子系统。

        Args:
            name: 子系统名称

        Returns:
            是否成功注销
        """
        if name in self._subsystems:
            del self._subsystems[name]
            logger.info("子系统 '%s' 已注销", name)
            return True
        return False

    def is_registered(self, name: str) -> bool:
        """检查子系统是否已注册。"""
        return name in self._subsystems

    def get_subsystem(self, name: str) -> Optional[ISubsystem]:
        """获取已注册的子系统实例。"""
        entry = self._subsystems.get(name)
        return entry.subsystem if entry else None

    def list_subsystems(self, verbose: bool = False) -> List[Dict[str, Any]]:
        """列出子系统状态。verbose=False 时隐藏内部名称/版本。"""
        result: List[Dict[str, Any]] = []
        for name, entry in self._subsystems.items():
            sub = entry.subsystem
            try:
                state = sub.state.value if isinstance(sub.state, SubsystemLifecycle) else str(sub.state)
                healthy = sub.health_check()
            except Exception:
                state = "unknown"
                healthy = False

            item: dict = {
                "healthy": healthy,
                "state": state,
            }
            if verbose:
                item.update({
                    "name": name,
                    "version": sub.version,
                    "operations": entry.operations,
                    "registered_at": entry.registered_at.isoformat(),
                })
            result.append(item)
        return result

    def request(
        self,
        source: str,
        target: str,
        operation: str,
        payload: Any = None,
        timeout: Optional[float] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> IntegrationMessage[Any]:
        """同步请求-响应调用。

        向目标子系统发送请求并等待响应。

        Args:
            source: 发起请求的子系统名称
            target: 目标子系统名称
            operation: 操作名称
            payload: 请求负载
            timeout: 超时时间（秒），None 使用默认值
            priority: 消息优先级

        Returns:
            目标子系统的响应消息

        Raises:
            SubsystemUnavailableError: 目标子系统未注册或不可用
            StateConflictError: 目标子系统状态不允许此操作
            IntegrationTimeoutError: 请求超时
            CommunicationError: 通信失败
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout

        entry = self._subsystems.get(target)
        if entry is None:
            raise SubsystemUnavailableError(
                target, current_state="not_registered"
            )

        target_sub = entry.subsystem

        if target_sub.state not in (
            SubsystemLifecycle.RUNNING,
            SubsystemLifecycle.DEGRADED,
        ):
            raise StateConflictError(
                target,
                "running",
                target_sub.state.value,
                operation=operation,
            )

        if operation not in entry.operations:
            entry.update_operations()
            if entry.operations and operation not in entry.operations:
                logger.warning(
                    "操作 '%s' 未在子系统 '%s' 的声明操作列表中",
                    operation,
                    target,
                )

        message = IntegrationMessage[Any](
            direction=MessageDirection.REQUEST,
            source=source,
            target=target,
            operation=operation,
            payload=payload,
            priority=priority,
        )

        metric = RequestMetrics(
            source=source,
            target=target,
            operation=operation,
            start_time=time.time(),
        )

        try:
            response = self._execute_with_timeout(
                target_sub, message, effective_timeout
            )
            metric.end_time = time.time()
            metric.success = True
            self._record_metric(metric)
            return response
        except IntegrationTimeoutError:
            metric.end_time = time.time()
            metric.error_message = f"timeout after {effective_timeout}s"
            self._record_metric(metric)
            raise
        except IntegrationError:
            metric.end_time = time.time()
            metric.error_message = "integration error"
            metric.success = False
            self._record_metric(metric)
            raise
        except Exception as e:
            metric.end_time = time.time()
            metric.error_message = str(e)
            metric.success = False
            self._record_metric(metric)
            raise CommunicationError(
                f"请求失败: {e}",
                source_subsystem=source,
                target_subsystem=target,
                details={"operation": operation},
            ) from e

    def _execute_with_timeout(
        self,
        subsystem: ISubsystem,
        message: IntegrationMessage[Any],
        timeout_seconds: float,
    ) -> IntegrationMessage[Any]:
        """带超时的消息执行。"""
        result_container: List[IntegrationMessage[Any]] = []
        error_container: List[Exception] = []
        cancel_event = threading.Event()

        def _run() -> None:
            try:
                if not cancel_event.is_set():
                    result_container.append(subsystem.handle_message(message))
            except Exception as e:
                if not cancel_event.is_set():
                    error_container.append(e)

        thread = threading.Thread(target=_run, daemon=True, name=f"int-bus-{subsystem.name}")
        thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            cancel_event.set()
            logger.warning(
                "请求超时 (%.1fs): %s.%s, 后台线程将继续运行至完成",
                timeout_seconds, subsystem.name, message.operation,
            )
            raise IntegrationTimeoutError(
                message.operation,
                timeout_seconds,
                source_subsystem=message.source,
                target_subsystem=message.target,
            )

        if error_container:
            raise error_container[0]

        if result_container:
            return result_container[0]

        raise CommunicationError(
            "未收到响应",
            source_subsystem=message.source,
            target_subsystem=message.target,
        )

    def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        source: Optional[str] = None,
    ) -> None:
        """通过事件总线发布事件。

        Args:
            event_type: 事件类型
            payload: 事件负载
            source: 事件来源
        """
        from mca_core.events import AnalysisEvent

        event = AnalysisEvent(
            type=event_type,
            payload=payload,
            source=source,
        )
        self._event_bus.publish(event)

    def health_check_all(self) -> Dict[str, bool]:
        """检查所有子系统的健康状态。

        Returns:
            子系统名称到健康状态的映射
        """
        results: Dict[str, bool] = {}
        for name, entry in self._subsystems.items():
            try:
                results[name] = entry.subsystem.health_check()
            except Exception as e:
                logger.warning("子系统 '%s' 健康检查异常: %s", name, e)
                results[name] = False
        return results

    def _record_metric(self, metric: RequestMetrics) -> None:
        """记录请求度量。"""
        with self._metrics_lock:
            if len(self._metrics) >= self._max_metrics:
                self._metrics.pop(0)
            self._metrics.append(metric)

    def get_metrics(self) -> Dict[str, Any]:
        """获取聚合性能度量。

        Returns:
            包含总数、延迟、成功率等的度量字典
        """
        with self._metrics_lock:
            if not self._metrics:
                return {
                    "total_requests": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "success_rate": 1.0,
                    "avg_latency_ms": 0.0,
                    "p50_latency_ms": 0.0,
                    "p95_latency_ms": 0.0,
                    "p99_latency_ms": 0.0,
                    "recent_metrics": [],
                }

            recent = list(self._metrics)
            total = len(recent)
            success = sum(1 for m in recent if m.success)
            failure = total - success
            latencies = sorted([m.latency_ms for m in recent])

            def _percentile(lats: List[float], pct: float) -> float:
                if not lats:
                    return 0.0
                idx = max(0, min(len(lats) - 1, int(len(lats) * pct / 100.0)))
                return lats[idx]

            return {
                "total_requests": total,
                "success_count": success,
                "failure_count": failure,
                "success_rate": success / total if total > 0 else 1.0,
                "avg_latency_ms": sum(latencies) / total if total > 0 else 0.0,
                "p50_latency_ms": _percentile(latencies, 50),
                "p95_latency_ms": _percentile(latencies, 95),
                "p99_latency_ms": _percentile(latencies, 99),
                "recent_metrics": [
                    {
                        "source": m.source,
                        "target": m.target,
                        "operation": m.operation,
                        "latency_ms": round(m.latency_ms, 2),
                        "success": m.success,
                    }
                    for m in recent[-10:]
                ],
            }

    def get_integration_graph(self) -> Dict[str, Any]:
        """获取子系统间集成关系图。

        Returns:
            包含节点和边的图结构
        """
        nodes: List[Dict[str, Any]] = []
        for name, entry in self._subsystems.items():
            sub = entry.subsystem
            try:
                state = (
                    sub.state.value
                    if isinstance(sub.state, SubsystemLifecycle)
                    else str(sub.state)
                )
            except Exception:
                state = "unknown"
            nodes.append({
                "name": name,
                "version": sub.version,
                "state": state,
                "operations": entry.operations,
            })

        return {
            "nodes": nodes,
            "edges": [
                {"source": m.source, "target": m.target, "operation": m.operation, "avg_latency_ms": round(m.latency_ms, 2)}
                for m in self._metrics[-50:]
            ],
        }

    def shutdown_all(self) -> Dict[str, bool]:
        """关闭所有已注册的子系统。

        Returns:
            子系统名称到关闭成功状态的映射
        """
        results: Dict[str, bool] = {}
        for name, entry in list(self._subsystems.items()):
            try:
                entry.subsystem.shutdown()
                results[name] = True
                logger.info("子系统 '%s' 已关闭", name)
            except Exception as e:
                logger.error("关闭子系统 '%s' 失败: %s", name, e)
                results[name] = False
        self._subsystems.clear()
        return results

    def __repr__(self) -> str:
        return (
            f"IntegrationBus(name='{self.name}', "
            f"subsystems={len(self._subsystems)}, "
            f"metrics={len(self._metrics)})"
        )