"""
子系统健康监控与性能度量。

提供实时子系统健康检查、性能瓶颈检测和状态历史追踪。

模块说明:
    - HealthMonitor: 周期性健康检查引擎
    - SubsystemHealthRegistry: 子系统健康注册表
    - BottleneckDetector: 性能瓶颈检测器
    - HealthStatus: 健康状态快照

与 IntegrationBus 协作:
    IntegrationBus 负责路由和请求，
    HealthMonitor 负责周期性检查各子系统健康状况并报告。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HealthLevel(Enum):
    """健康等级。"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthStatus:
    """子系统健康状态快照。

    Attributes:
        subsystem_name: 子系统名称
        level: 健康等级
        checked_at: 检查时间
        response_time_ms: 响应时间（毫秒）
        details: 详细信息
        consecutive_failures: 连续失败次数
    """

    subsystem_name: str
    level: HealthLevel = HealthLevel.UNKNOWN
    checked_at: datetime = field(default_factory=datetime.now)
    response_time_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    consecutive_failures: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_name": self.subsystem_name,
            "level": self.level.value,
            "checked_at": self.checked_at.isoformat(),
            "response_time_ms": round(self.response_time_ms, 2),
            "details": self.details,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class BottleneckRecord:
    """性能瓶颈记录。

    Attributes:
        subsystem: 子系统名称
        operation: 操作名称
        avg_latency_ms: 平均延迟
        threshold_ms: 阈值
        detected_at: 检测时间
        severity: 严重程度
    """

    subsystem: str
    operation: str
    avg_latency_ms: float
    threshold_ms: float
    detected_at: datetime = field(default_factory=datetime.now)
    severity: str = "warning"


class SubsystemHealthRegistry:
    """子系统健康注册表。

    管理各子系统的健康状态快照，支持查询、告警和历史追踪。
    """

    def __init__(self, max_history: int = 100) -> None:
        self._statuses: Dict[str, HealthStatus] = {}
        self._history: Dict[str, List[HealthStatus]] = {}
        self._max_history = max_history
        self._lock = threading.Lock()

    def update(self, name: str, healthy: bool, response_time_ms: float = 0.0, details: Optional[Dict[str, Any]] = None) -> HealthStatus:
        """更新子系统健康状态。"""
        previous = self._statuses.get(name)
        consecutive = 0

        if healthy:
            level = HealthLevel.HEALTHY
        elif previous and previous.level == HealthLevel.HEALTHY:
            level = HealthLevel.DEGRADED
            consecutive = 1
        else:
            level = HealthLevel.UNHEALTHY
            consecutive = (previous.consecutive_failures + 1) if previous else 1

        status = HealthStatus(
            subsystem_name=name,
            level=level,
            response_time_ms=response_time_ms,
            details=details or {},
            consecutive_failures=consecutive if not healthy else 0,
        )

        with self._lock:
            self._statuses[name] = status
            if name not in self._history:
                self._history[name] = []
            self._history[name].append(status)
            if len(self._history[name]) > self._max_history:
                self._history[name] = self._history[name][-self._max_history:]

        if level in (HealthLevel.DEGRADED, HealthLevel.UNHEALTHY):
            logger.warning(
                "子系统 '%s' 健康状态: %s (连续失败: %d)",
                name, level.value, consecutive,
            )

        return status

    def get(self, name: str) -> Optional[HealthStatus]:
        """获取子系统当前健康状态。"""
        with self._lock:
            return self._statuses.get(name)

    def get_all(self) -> Dict[str, HealthStatus]:
        """获取所有子系统健康状态。"""
        with self._lock:
            return dict(self._statuses)

    def get_history(self, name: str) -> List[HealthStatus]:
        """获取子系统健康状态历史。"""
        with self._lock:
            return list(self._history.get(name, []))

    def get_unhealthy(self) -> List[HealthStatus]:
        """获取所有不健康的子系统。"""
        with self._lock:
            return [
                s for s in self._statuses.values()
                if s.level in (HealthLevel.DEGRADED, HealthLevel.UNHEALTHY)
            ]

    def get_summary(self) -> Dict[str, Any]:
        """获取整体健康摘要。"""
        with self._lock:
            total = len(self._statuses)
            if total == 0:
                return {"total": 0, "healthy": 0, "degraded": 0, "unhealthy": 0, "unknown": 0}

            counts = {level: 0 for level in HealthLevel}
            for s in self._statuses.values():
                counts[s.level] += 1

            return {
                "total": total,
                "healthy": counts[HealthLevel.HEALTHY],
                "degraded": counts[HealthLevel.DEGRADED],
                "unhealthy": counts[HealthLevel.UNHEALTHY],
                "unknown": counts[HealthLevel.UNKNOWN],
                "overall": (
                    "healthy"
                    if counts[HealthLevel.UNHEALTHY] == 0
                    else "degraded"
                    if counts[HealthLevel.UNHEALTHY] < total // 2
                    else "unhealthy"
                ),
            }

    def clear(self) -> None:
        """清除所有记录。"""
        with self._lock:
            self._statuses.clear()
            self._history.clear()


class BottleneckDetector:
    """性能瓶颈检测器。

    基于延迟阈值检测子系统间的性能瓶颈。
    """

    def __init__(
        self,
        default_threshold_ms: float = 500.0,
        per_operation_thresholds: Optional[Dict[str, float]] = None,
    ) -> None:
        self._default_threshold = default_threshold_ms
        self._thresholds = per_operation_thresholds or {}
        self._bottlenecks: List[BottleneckRecord] = []
        self._lock = threading.Lock()

    def set_threshold(self, operation: str, threshold_ms: float) -> None:
        """设置特定操作的延迟阈值。"""
        self._thresholds[operation] = threshold_ms

    def analyze(
        self,
        subsystem: str,
        operation: str,
        avg_latency_ms: float,
    ) -> Optional[BottleneckRecord]:
        """分析操作是否存在性能瓶颈。

        Args:
            subsystem: 子系统名称
            operation: 操作名称
            avg_latency_ms: 平均延迟（毫秒）

        Returns:
            瓶颈记录或 None
        """
        threshold = self._thresholds.get(
            operation,
            self._thresholds.get(subsystem, self._default_threshold),
        )

        if avg_latency_ms > threshold:
            severity = (
                "critical" if avg_latency_ms > threshold * 3
                else "error" if avg_latency_ms > threshold * 2
                else "warning"
            )
            record = BottleneckRecord(
                subsystem=subsystem,
                operation=operation,
                avg_latency_ms=avg_latency_ms,
                threshold_ms=threshold,
                severity=severity,
            )
            with self._lock:
                self._bottlenecks.append(record)
            return record
        return None

    def analyze_bus_metrics(self, metrics: Dict[str, Any]) -> List[BottleneckRecord]:
        """基于 IntegrationBus 的度量数据检测瓶颈。

        Args:
            metrics: IntegrationBus.get_metrics() 的返回值

        Returns:
            检测到的瓶颈列表
        """
        results: List[BottleneckRecord] = []
        recent = metrics.get("recent_metrics", [])
        op_latencies: Dict[Tuple[str, str], List[float]] = {}

        for m in recent:
            key = (m.get("source", ""), m.get("target", ""))
            if key not in op_latencies:
                op_latencies[key] = []
            op_latencies[key].append(m.get("latency_ms", 0.0))

        for (source, target), latencies in op_latencies.items():
            if not latencies:
                continue
            avg = sum(latencies) / len(latencies)
            operation = f"{source}->{target}"
            record = self.analyze(target, operation, avg)
            if record:
                results.append(record)

        return results

    def get_bottlenecks(self, clear: bool = False) -> List[BottleneckRecord]:
        """获取所有检测到的瓶颈。"""
        with self._lock:
            result = list(self._bottlenecks)
            if clear:
                self._bottlenecks.clear()
            return result

    def get_bottlenecks_by_severity(self, severity: str) -> List[BottleneckRecord]:
        """按严重程度筛选瓶颈。"""
        return [b for b in self.get_bottlenecks() if b.severity == severity]


class HealthMonitor:
    """周期性健康检查引擎。

    定期对注册的子系统执行健康检查，记录结果并触发告警。

    方法:
        - set_check_callback: 设置健康检查回调
        - start: 启动周期性监控
        - stop: 停止监控
        - get_registry: 获取健康注册表
    """

    def __init__(
        self,
        interval_seconds: float = 10.0,
        registry: Optional[SubsystemHealthRegistry] = None,
    ) -> None:
        self._interval = interval_seconds
        self._registry = registry or SubsystemHealthRegistry()
        self._check_callback: Optional[Callable[[], Dict[str, bool]]] = None
        self._alert_callback: Optional[Callable[[HealthStatus], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    def set_check_callback(
        self,
        callback: Callable[[], Dict[str, bool]],
    ) -> None:
        """设置健康检查回调函数。

        Args:
            callback: 返回 {子系统名称: 是否健康} 的回调
        """
        self._check_callback = callback

    def set_alert_callback(
        self,
        callback: Callable[[HealthStatus], None],
    ) -> None:
        """设置告警回调函数。"""
        self._alert_callback = callback

    @property
    def registry(self) -> SubsystemHealthRegistry:
        return self._registry

    def start(self) -> None:
        if self._running:
            logger.warning("HealthMonitor 已在运行中")
            return

        if self._check_callback is None:
            logger.warning("HealthMonitor: 未设置健康检查回调，延迟启动")
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="health-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "HealthMonitor 已启动，检查间隔: %.1fs",
            self._interval,
        )

    def stop(self) -> None:
        """停止健康监控。"""
        if not self._running:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._interval + 5.0)
        self._running = False
        logger.info("HealthMonitor 已停止")

    def _monitor_loop(self) -> None:
        """监控主循环。"""
        while not self._stop_event.is_set():
            try:
                self._check_all()
            except Exception as e:
                logger.error("HealthMonitor 检查异常: %s", e)
            self._stop_event.wait(self._interval)

    def _check_all(self) -> None:
        """执行一轮健康检查。"""
        if self._check_callback is None:
            logger.warning("HealthMonitor: 未设置健康检查回调")
            return

        try:
            results = self._check_callback()
        except Exception as e:
            logger.error("健康检查回调执行失败: %s", e)
            return

        for name, healthy in results.items():
            status = self._registry.update(name, healthy)
            if not healthy and self._alert_callback:
                try:
                    self._alert_callback(status)
                except Exception as e:
                    logger.error("告警回调执行失败: %s", e)

    def check_now(self) -> Dict[str, HealthStatus]:
        """立即执行一次健康检查。"""
        self._check_all()
        return self._registry.get_all()