"""
检测器性能度量引擎。

提供检测器运行状态、吞吐量、延迟和准确率的实时收集与统计。

模块说明:
    - DetectorMetrics: 单个检测器的性能指标快照
    - MetricsCollector: 多检测器指标收集器
    - DetectorStatus: 检测器运行状态枚举
    - MetricThresholds: 可配置的告警阈值
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DetectorStatus(Enum):
    """检测器运行状态。"""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class DetectorMetrics:
    """单个检测器的性能指标快照。

    Attributes:
        detector_name: 检测器名称
        status: 运行状态
        priority: 检测优先级
        cause_label: 关联的原因标签
        total_runs: 总执行次数
        successful_runs: 成功执行次数
        failed_runs: 失败执行次数
        total_items_processed: 总处理数据量
        avg_response_time_ms: 平均响应时间（毫秒）
        last_response_time_ms: 最近一次响应时间
        min_response_time_ms: 最小响应时间
        max_response_time_ms: 最大响应时间
        detection_rate: 检测成功率（命中率）
        false_positive_count: 误报次数
        false_negative_count: 漏报次数
        last_run_at: 最近一次运行时间
        last_error: 最近一次错误信息
        is_active: 是否处于活跃状态
    """

    detector_name: str
    status: DetectorStatus = DetectorStatus.UNKNOWN
    priority: int = 50
    cause_label: Optional[str] = None
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_items_processed: int = 0
    avg_response_time_ms: float = 0.0
    last_response_time_ms: float = 0.0
    min_response_time_ms: float = float("inf")
    max_response_time_ms: float = 0.0
    detection_rate: float = 0.0
    false_positive_count: int = 0
    false_negative_count: int = 0
    last_run_at: Optional[datetime] = None
    last_error: Optional[str] = None
    is_active: bool = False

    @property
    def success_rate(self) -> float:
        """执行成功率（非检测成功率）。"""
        if self.total_runs == 0:
            return 1.0
        return self.successful_runs / self.total_runs

    @property
    def throughput_per_second(self) -> float:
        """每秒处理数据量。"""
        if self.avg_response_time_ms <= 0:
            return 0.0
        return 1000.0 / self.avg_response_time_ms

    @property
    def false_positive_rate(self) -> float:
        """误报率。"""
        if self.total_runs == 0:
            return 0.0
        return self.false_positive_count / self.total_runs

    @property
    def stability_index(self) -> float:
        """稳定性指数 (0.0-1.0)。

        综合成功率、响应时间波动和错误频率。
        """
        if self.total_runs == 0:
            return 1.0
        success_score = self.success_rate
        volatility = 0.0
        if self.min_response_time_ms > 0 and self.max_response_time_ms > 0:
            volatility = min(
                1.0,
                (self.max_response_time_ms - self.min_response_time_ms)
                / max(self.avg_response_time_ms, 1.0),
            )
        stability = success_score * (1.0 - volatility * 0.5)
        return max(0.0, min(1.0, stability))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector_name": self.detector_name,
            "status": self.status.value,
            "priority": self.priority,
            "cause_label": self.cause_label,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "total_items_processed": self.total_items_processed,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "last_response_time_ms": round(self.last_response_time_ms, 2),
            "min_response_time_ms": round(self.min_response_time_ms, 2),
            "max_response_time_ms": round(self.max_response_time_ms, 2),
            "throughput_per_second": round(self.throughput_per_second, 2),
            "success_rate": round(self.success_rate, 4),
            "detection_rate": round(self.detection_rate, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "stability_index": round(self.stability_index, 4),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_error": self.last_error,
            "is_active": self.is_active,
        }


@dataclass
class MetricThresholds:
    """可配置的告警阈值。

    Attributes:
        max_response_time_ms: 最大响应时间阈值
        min_success_rate: 最小成功率阈值
        max_false_positive_rate: 最大误报率阈值
        max_idle_seconds: 最大空闲时间（秒）
        throughput_drop_ratio: 吞吐量骤降比例
        accuracy_drop_ratio: 准确率骤降比例
    """

    max_response_time_ms: float = 5000.0
    min_success_rate: float = 0.8
    max_false_positive_rate: float = 0.3
    max_idle_seconds: float = 300.0
    throughput_drop_ratio: float = 0.5
    accuracy_drop_ratio: float = 0.3


class MetricsCollector:
    """多检测器性能指标收集器。

    负责收集、聚合和查询所有检测器的性能指标。
    支持线程安全的指标更新和查询。
    """

    def __init__(
        self,
        thresholds: Optional[MetricThresholds] = None,
        max_history_per_detector: int = 500,
    ) -> None:
        self._metrics: Dict[str, DetectorMetrics] = {}
        self._lock = threading.RLock()
        self._thresholds = thresholds or MetricThresholds()
        self._max_history = max_history_per_detector

    def register_detector(
        self,
        name: str,
        priority: int = 50,
        cause_label: Optional[str] = None,
    ) -> DetectorMetrics:
        """注册检测器，初始化其指标。"""
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]
            metrics = DetectorMetrics(
                detector_name=name,
                priority=priority,
                cause_label=cause_label,
                status=DetectorStatus.ONLINE,
                is_active=True,
            )
            self._metrics[name] = metrics
            return metrics

    def record_run(
        self,
        name: str,
        response_time_ms: float,
        success: bool,
        items_processed: int = 1,
        detected: bool = False,
        is_false_positive: bool = False,
        is_false_negative: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """记录一次检测器运行。

        Args:
            name: 检测器名称
            response_time_ms: 响应时间（毫秒）
            success: 是否执行成功
            items_processed: 处理的数据项数
            detected: 是否检测到问题
            is_false_positive: 是否为误报
            is_false_negative: 是否为漏报
            error: 错误信息
        """
        with self._lock:
            if name not in self._metrics:
                self.register_detector(name)
            m = self._metrics[name]

            m.total_runs += 1
            if success:
                m.successful_runs += 1
            else:
                m.failed_runs += 1

            m.total_items_processed += items_processed
            m.last_response_time_ms = response_time_ms
            m.min_response_time_ms = min(m.min_response_time_ms, response_time_ms)
            m.max_response_time_ms = max(m.max_response_time_ms, response_time_ms)

            total = m.avg_response_time_ms * (m.total_runs - 1) + response_time_ms
            m.avg_response_time_ms = total / m.total_runs

            if detected:
                detected_runs = m.detection_rate * (m.total_runs - 1) + 1
                m.detection_rate = detected_runs / m.total_runs
            else:
                detected_runs = m.detection_rate * (m.total_runs - 1)
                m.detection_rate = detected_runs / m.total_runs

            if is_false_positive:
                m.false_positive_count += 1
            if is_false_negative:
                m.false_negative_count += 1

            m.last_run_at = datetime.now()
            m.last_error = error
            m.is_active = True
            m.status = DetectorStatus.ONLINE if success else DetectorStatus.DEGRADED

    def mark_inactive(self, name: str) -> None:
        """标记检测器为非活跃。"""
        with self._lock:
            if name in self._metrics:
                self._metrics[name].is_active = False
                self._metrics[name].status = DetectorStatus.OFFLINE

    def mark_active(self, name: str) -> None:
        """标记检测器为活跃。"""
        with self._lock:
            if name in self._metrics:
                self._metrics[name].is_active = True
                self._metrics[name].status = DetectorStatus.ONLINE

    def get_metrics(self, name: str) -> Optional[DetectorMetrics]:
        """获取单个检测器的指标。"""
        with self._lock:
            return self._metrics.get(name)

    def get_all_metrics(self) -> Dict[str, DetectorMetrics]:
        """获取所有检测器的指标。"""
        with self._lock:
            return dict(self._metrics)

    def get_aggregated_summary(self) -> Dict[str, Any]:
        """获取聚合摘要。"""
        with self._lock:
            if not self._metrics:
                return {
                    "total_detectors": 0,
                    "online": 0,
                    "offline": 0,
                    "degraded": 0,
                    "avg_success_rate": 1.0,
                    "avg_response_time_ms": 0.0,
                    "total_runs": 0,
                    "overall_stability": 1.0,
                }

            total = len(self._metrics)
            status_counts = {s: 0 for s in DetectorStatus}
            for m in self._metrics.values():
                status_counts[m.status] += 1

            success_rates = [m.success_rate for m in self._metrics.values()]
            avg_success = sum(success_rates) / len(success_rates) if success_rates else 1.0

            response_times = [
                m.avg_response_time_ms
                for m in self._metrics.values()
                if m.avg_response_time_ms > 0
            ]
            avg_rt = sum(response_times) / len(response_times) if response_times else 0.0

            total_runs = sum(m.total_runs for m in self._metrics.values())

            stabilities = [m.stability_index for m in self._metrics.values()]
            overall_stability = sum(stabilities) / len(stabilities) if stabilities else 1.0

            return {
                "total_detectors": total,
                "online": status_counts[DetectorStatus.ONLINE],
                "offline": status_counts[DetectorStatus.OFFLINE],
                "degraded": status_counts[DetectorStatus.DEGRADED],
                "unknown": status_counts[DetectorStatus.UNKNOWN],
                "avg_success_rate": round(avg_success, 4),
                "avg_response_time_ms": round(avg_rt, 2),
                "total_runs": total_runs,
                "overall_stability": round(overall_stability, 4),
            }

    def get_thresholds(self) -> MetricThresholds:
        return self._thresholds

    def set_thresholds(self, thresholds: MetricThresholds) -> None:
        self._thresholds = thresholds

    def reset(self) -> None:
        """重置所有指标。"""
        with self._lock:
            self._metrics.clear()