"""
历史数据记录与趋势分析。

提供检测器性能指标的历史存储和时间趋势分析。

模块说明:
    - HistorySnapshot: 历史数据快照
    - HistoryStore: 历史数据存储（环形缓冲区）
    - TrendAnalyzer: 趋势分析器（增速、周期性、预测）
    - TimeRange: 时间范围枚举
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from mca_core.dashboard.metrics import DetectorMetrics


class TimeRange(Enum):
    """时间范围。"""
    LAST_MINUTE = "1m"
    LAST_5_MINUTES = "5m"
    LAST_15_MINUTES = "15m"
    LAST_HOUR = "1h"
    LAST_6_HOURS = "6h"
    LAST_24_HOURS = "24h"
    LAST_7_DAYS = "7d"


@dataclass
class HistorySnapshot:
    """历史数据快照。

    Attributes:
        detector_name: 检测器名称
        timestamp: 时间戳
        avg_response_time_ms: 平均响应时间
        success_rate: 成功率
        detection_rate: 检测率
        throughput: 吞吐量
        total_runs: 累计运行次数
        stability_index: 稳定性指数
    """

    detector_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    avg_response_time_ms: float = 0.0
    success_rate: float = 1.0
    detection_rate: float = 0.0
    throughput: float = 0.0
    total_runs: int = 0
    stability_index: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector_name": self.detector_name,
            "timestamp": self.timestamp.isoformat(),
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "detection_rate": round(self.detection_rate, 4),
            "throughput": round(self.throughput, 2),
            "total_runs": self.total_runs,
            "stability_index": round(self.stability_index, 4),
        }


class HistoryStore:
    """历史数据存储。

    使用环形缓冲区（deque）存储每个检测器的历史快照，
    支持按时间范围查询和清理。
    """

    def __init__(self, max_snapshots_per_detector: int = 1000) -> None:
        self._history: Dict[str, deque[HistorySnapshot]] = {}
        self._lock = threading.Lock()
        self._max_snapshots = max_snapshots_per_detector

    def record_snapshot(self, metrics: DetectorMetrics) -> Optional[HistorySnapshot]:
        """记录检测器当前指标快照。"""
        snapshot = HistorySnapshot(
            detector_name=metrics.detector_name,
            avg_response_time_ms=metrics.avg_response_time_ms,
            success_rate=metrics.success_rate,
            detection_rate=metrics.detection_rate,
            throughput=metrics.throughput_per_second,
            total_runs=metrics.total_runs,
            stability_index=metrics.stability_index,
        )

        with self._lock:
            if metrics.detector_name not in self._history:
                self._history[metrics.detector_name] = deque(maxlen=self._max_snapshots)
            self._history[metrics.detector_name].append(snapshot)

        return snapshot

    def get_history(
        self,
        detector_name: str,
        time_range: Optional[TimeRange] = None,
        limit: Optional[int] = None,
    ) -> List[HistorySnapshot]:
        """获取检测器的历史数据。

        Args:
            detector_name: 检测器名称
            time_range: 时间范围筛选
            limit: 最大返回数量

        Returns:
            历史快照列表（按时间升序）
        """
        with self._lock:
            if detector_name not in self._history:
                return []
            snapshots = list(self._history[detector_name])

        if time_range is not None:
            cutoff = self._get_cutoff(time_range)
            snapshots = [s for s in snapshots if s.timestamp >= cutoff]

        if limit is not None:
            snapshots = snapshots[-limit:]

        return snapshots

    def get_all_names(self) -> List[str]:
        """获取所有已记录检测器的名称。"""
        with self._lock:
            return list(self._history.keys())

    def get_latest_snapshot(self, detector_name: str) -> Optional[HistorySnapshot]:
        """获取最新快照。"""
        with self._lock:
            if detector_name in self._history and self._history[detector_name]:
                return self._history[detector_name][-1]
        return None

    def clear(self, detector_name: Optional[str] = None) -> None:
        """清除历史数据。"""
        with self._lock:
            if detector_name:
                self._history.pop(detector_name, None)
            else:
                self._history.clear()

    @staticmethod
    def _get_cutoff(time_range: TimeRange) -> datetime:
        """根据时间范围计算截止时间。"""
        now = datetime.now()
        mapping = {
            TimeRange.LAST_MINUTE: timedelta(minutes=1),
            TimeRange.LAST_5_MINUTES: timedelta(minutes=5),
            TimeRange.LAST_15_MINUTES: timedelta(minutes=15),
            TimeRange.LAST_HOUR: timedelta(hours=1),
            TimeRange.LAST_6_HOURS: timedelta(hours=6),
            TimeRange.LAST_24_HOURS: timedelta(hours=24),
            TimeRange.LAST_7_DAYS: timedelta(days=7),
        }
        return now - mapping.get(time_range, timedelta(hours=1))


class TrendAnalyzer:
    """趋势分析器。

    分析检测器性能指标的时间趋势:
        - 增速/减速趋势
        - 周期性波动检测
        - 短期预测
    """

    @staticmethod
    def analyze_response_time_trend(
        snapshots: List[HistorySnapshot],
    ) -> Dict[str, Any]:
        """分析响应时间趋势。

        Returns:
            {"trend": "increasing"|"decreasing"|"stable", "rate": float, "prediction": float}
        """
        if len(snapshots) < 2:
            return {"trend": "stable", "rate": 0.0, "prediction": 0.0}

        values = [s.avg_response_time_ms for s in snapshots if s.avg_response_time_ms > 0]
        if len(values) < 2:
            return {"trend": "stable", "rate": 0.0, "prediction": 0.0}

        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return {"trend": "stable", "rate": 0.0, "prediction": y_mean}

        slope = numerator / denominator
        relative_change = slope / y_mean if y_mean > 0 else 0.0

        if abs(relative_change) < 0.05:
            trend = "stable"
        elif slope > 0:
            trend = "increasing"
        else:
            trend = "decreasing"

        prediction = values[-1] + slope * (n * 0.2)

        return {
            "trend": trend,
            "rate": round(slope, 4),
            "relative_change": round(relative_change, 4),
            "prediction": round(max(0.0, prediction), 2),
        }

    @staticmethod
    def analyze_success_rate_trend(
        snapshots: List[HistorySnapshot],
    ) -> Dict[str, Any]:
        """分析成功率趋势。"""
        if len(snapshots) < 2:
            return {"trend": "stable", "rate": 0.0, "prediction": 1.0}

        values = [s.success_rate for s in snapshots]
        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return {"trend": "stable", "rate": 0.0, "prediction": y_mean}

        slope = numerator / denominator

        if abs(slope) < 0.001:
            trend = "stable"
        elif slope > 0:
            trend = "improving"
        else:
            trend = "declining"

        prediction = min(1.0, max(0.0, values[-1] + slope * (n * 0.2)))

        return {
            "trend": trend,
            "rate": round(slope, 6),
            "prediction": round(prediction, 4),
        }

    @staticmethod
    def analyze_stability_trend(
        snapshots: List[HistorySnapshot],
    ) -> Dict[str, Any]:
        """分析稳定性趋势。"""
        if len(snapshots) < 2:
            return {"trend": "stable", "volatility": 0.0}

        values = [s.stability_index for s in snapshots]
        if len(values) < 2:
            return {"trend": "stable", "volatility": 0.0}

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        volatility = variance ** 0.5

        if volatility < 0.05:
            trend = "stable"
        elif volatility < 0.15:
            trend = "slightly_volatile"
        else:
            trend = "volatile"

        return {
            "trend": trend,
            "volatility": round(volatility, 4),
            "mean": round(mean, 4),
        }

    @staticmethod
    def get_summary(
        snapshots: List[HistorySnapshot],
    ) -> Dict[str, Any]:
        """获取综合趋势摘要。"""
        return {
            "response_time": TrendAnalyzer.analyze_response_time_trend(snapshots),
            "success_rate": TrendAnalyzer.analyze_success_rate_trend(snapshots),
            "stability": TrendAnalyzer.analyze_stability_trend(snapshots),
            "sample_count": len(snapshots),
        }