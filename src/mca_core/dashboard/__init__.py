"""
检测器仪表盘包。

提供检测器性能监控、异常检测、历史记录和趋势分析的完整工具链。

核心模块:
    - metrics: DetectorMetrics, MetricsCollector, MetricThresholds
    - anomaly: AnomalyDetector, AlertManager, Alert, AlertLevel
    - history: HistoryStore, TrendAnalyzer, HistorySnapshot
    - controller: DashboardController (不依赖 BrainCore 的独立控制器)

相关 DLC:
    - brain_dlc_dashboard.DashboardDLC: BrainDLC 子类，集成到 MCA Brain System
"""
from mca_core.dashboard.anomaly import (
    Alert,
    AlertLevel,
    AlertManager,
    AnomalyDetector,
    AnomalyRecord,
    AnomalyType,
)
from mca_core.dashboard.controller import DashboardController
from mca_core.dashboard.history import (
    HistorySnapshot,
    HistoryStore,
    TimeRange,
    TrendAnalyzer,
)
from mca_core.dashboard.metrics import (
    DetectorMetrics,
    DetectorStatus,
    MetricThresholds,
    MetricsCollector,
)

__all__ = [
    "Alert",
    "AlertLevel",
    "AlertManager",
    "AnomalyDetector",
    "AnomalyRecord",
    "AnomalyType",
    "DashboardController",
    "HistorySnapshot",
    "HistoryStore",
    "TimeRange",
    "TrendAnalyzer",
    "DetectorMetrics",
    "DetectorStatus",
    "MetricThresholds",
    "MetricsCollector",
]