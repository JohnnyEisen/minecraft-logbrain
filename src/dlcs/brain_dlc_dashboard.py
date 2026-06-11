"""
仪表盘 DLC 模块 — 检测器状态监控与性能分析。

实时监控系统中各个检测器的工作状态与性能表现，提供:
    - 检测器运行状态（在线/离线/降级）
    - 处理效率指标（吞吐量、响应时间）
    - 准确率统计（检测成功率、误报率、漏报率）
    - 异常行为识别（长时间无响应、速度骤降、准确率波动）
    - 历史数据记录与趋势分析
    - 可配置告警阈值与通知机制

作为 BrainDLC 子类，集成到 MCA Brain System 中。

v2.0.0: 桥接 DashboardController DI，版本号统一引用 __version__。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from brain_system import BrainCore, BrainDLC, BrainDLCType, DLCManifest
from brain_system import __version__

from mca_core.dashboard.anomaly import (
    Alert,
    AlertLevel,
    AlertManager,
    AnomalyDetector,
    AnomalyRecord,
    AnomalyType,
)
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

logger = logging.getLogger(__name__)


class DashboardDLC(BrainDLC):
    """仪表盘 DLC。

    监控并评估系统中所有检测器的工作状态与性能。
    作为 BrainDLC 子类，通过 provide_computational_units 暴露操作接口。

    生命周期:
        _initialize() -> 启动监控循环
        shutdown() -> 停止监控循环，清理资源

    v2.0.0: 支持通过 inject() 注入 config/audit/event_bus，
            配置驱动阈值加载，异常检测事件发布。
    """

    def __init__(self, brain: BrainCore) -> None:
        super().__init__(brain)
        self._collector = MetricsCollector()
        self._anomaly_detector = AnomalyDetector()
        self._alert_manager = AlertManager()
        self._history_store = HistoryStore()
        self._trend_analyzer = TrendAnalyzer()

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._monitor_interval: float = 5.0
        self._snapshot_interval: float = 30.0
        self._last_snapshot_time: float = 0.0
        self._previous_metrics: Dict[str, DetectorMetrics] = {}

    def get_manifest(self) -> DLCManifest:
        return DLCManifest(
            name="Detector Dashboard",
            version=__version__,
            author="MCA Brain System",
            description="实时监控检测器状态与性能的仪表盘",
            dlc_type=BrainDLCType.MANAGER,
            dependencies=["Brain Core"],
            priority=10,
        )

    def _initialize(self) -> None:
        if self._config is not None:
            self._monitor_interval = self._config.get_float("monitor.interval_seconds", 5.0)
            self._snapshot_interval = self._config.get_float("monitor.snapshot_interval", 30.0)
            self._load_thresholds_from_config()
        self._register_detectors_from_registry()
        self._start_monitor_loop()
        logger.info("DashboardDLC 初始化完成，已注册 %d 个检测器", len(self._collector.get_all_metrics()))

    def _load_thresholds_from_config(self) -> None:
        if self._config is None:
            return
        thresholds = self._collector.get_thresholds()
        t = thresholds
        t.max_response_time_ms = self._config.get_float("monitor.max_response_time_ms", t.max_response_time_ms)
        t.min_success_rate = self._config.get_float("monitor.min_success_rate", t.min_success_rate)
        t.max_false_positive_rate = self._config.get_float("monitor.max_false_positive_rate", t.max_false_positive_rate)
        t.max_idle_seconds = self._config.get_float("monitor.max_idle_seconds", t.max_idle_seconds)

    def _pre_shutdown(self) -> None:
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

    def _register_detectors_from_registry(self) -> None:
        """从 DetectorRegistry 自动注册所有检测器。"""
        try:
            from mca_core.detectors.registry import DetectorRegistry

            registry = DetectorRegistry.get_instance()
            detectors = registry.list()
            for detector in detectors:
                try:
                    name = detector.get_name()
                    priority = detector.get_priority()
                    cause_label = detector.get_cause_label()
                    self._collector.register_detector(name, priority, cause_label)
                except Exception as e:
                    logger.debug("注册检测器失败: %s", e)
        except Exception as e:
            logger.warning("无法从 DetectorRegistry 加载检测器: %s", e)

    def _start_monitor_loop(self) -> None:
        """启动后台监控循环。"""
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="dashboard-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """监控主循环。"""
        while not self._stop_event.is_set():
            try:
                self._check_all_detectors()
                self._record_history_if_needed()
            except Exception as e:
                logger.error("Dashboard 监控循环异常: %s", e)
            self._stop_event.wait(self._monitor_interval)

    def _check_all_detectors(self) -> None:
        """检查所有检测器的活跃状态。"""
        all_metrics = self._collector.get_all_metrics()
        now = time.time()

        for name, metrics in all_metrics.items():
            if metrics.last_run_at:
                idle_seconds = (datetime.now() - metrics.last_run_at).total_seconds()
                if idle_seconds > self._collector.get_thresholds().max_idle_seconds:
                    self._collector.mark_inactive(name)
            elif not metrics.is_active:
                self._collector.mark_inactive(name)

            prev = self._previous_metrics.get(name)
            anomalies = self._anomaly_detector.detect(
                metrics,
                self._collector.get_thresholds(),
                previous_metrics=prev,
            )
            for anomaly in anomalies:
                self._alert_manager.create_from_anomaly(anomaly)
                if self._audit is not None:
                    try:
                        from mca_core.audit import OperationType as OpT
                        self._audit.record(
                            op_type=OpT.ANOMALY_DETECTED,
                            detail=f"检测器 {name} 异常: {anomaly.description}",
                            component="DashboardDLC",
                            metadata={
                                "detector": name,
                                "anomaly_type": anomaly.anomaly_type.value,
                                "severity": anomaly.severity.value,
                            },
                        )
                    except Exception:
                        pass
                if self._event_bus is not None:
                    try:
                        from mca_core.events import AnalysisEvent, EventTypes
                        self._event_bus.publish_async(
                            AnalysisEvent(
                                type=EventTypes.ANALYSIS_ERROR,
                                payload={
                                    "detector": name,
                                    "anomaly": anomaly.description,
                                    "severity": anomaly.severity.value,
                                },
                                source="DashboardDLC",
                            )
                        )
                    except Exception:
                        pass

        self._previous_metrics = {
            name: metrics
            for name, metrics in all_metrics.items()
        }

    def _record_history_if_needed(self) -> None:
        """按间隔记录历史快照。"""
        now = time.time()
        if now - self._last_snapshot_time >= self._snapshot_interval:
            for metrics in self._collector.get_all_metrics().values():
                if metrics.total_runs > 0:
                    self._history_store.record_snapshot(metrics)
            self._last_snapshot_time = now

    def provide_computational_units(self) -> Dict[str, Any]:
        """提供仪表盘计算单元（暴露给外部调用）。"""
        return {
            "get_all_metrics": self.get_all_metrics,
            "get_detector_metrics": self.get_detector_metrics,
            "get_aggregated_summary": self.get_aggregated_summary,
            "get_alerts": self.get_alerts,
            "get_alert_count": self.get_alert_count,
            "get_history": self.get_history,
            "get_trend": self.get_trend,
            "get_anomalies": self.get_anomalies,
            "record_detector_run": self.record_detector_run,
            "set_thresholds": self.set_thresholds,
            "get_thresholds": self.get_thresholds,
            "acknowledge_alert": self._alert_manager.acknowledge_alert,
            "resolve_alert": self._alert_manager.resolve_alert,
        }

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """获取所有检测器的指标。"""
        return {
            name: m.to_dict()
            for name, m in self._collector.get_all_metrics().items()
        }

    def get_detector_metrics(self, name: str) -> Optional[Dict[str, Any]]:
        """获取单个检测器的指标。"""
        m = self._collector.get_metrics(name)
        return m.to_dict() if m else None

    def get_aggregated_summary(self) -> Dict[str, Any]:
        """获取聚合摘要。"""
        return self._collector.get_aggregated_summary()

    def get_alerts(
        self,
        acknowledged: Optional[bool] = None,
        level: Optional[str] = None,
        detector_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取告警列表。"""
        alert_level = AlertLevel(level) if level else None
        alerts = self._alert_manager.get_alerts(acknowledged, alert_level, detector_name, limit)
        return [a.to_dict() for a in alerts]

    def get_alert_count(self) -> Dict[str, Any]:
        """获取告警统计。"""
        return {
            "active": self._alert_manager.get_active_count(),
            "by_level": self._alert_manager.get_count_by_level(),
        }

    def get_history(
        self,
        detector_name: str,
        time_range: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """获取检测器历史数据。"""
        tr = TimeRange(time_range) if time_range else None
        snapshots = self._history_store.get_history(detector_name, tr, limit)
        return [s.to_dict() for s in snapshots]

    def get_trend(self, detector_name: str) -> Dict[str, Any]:
        """获取检测器趋势分析。"""
        snapshots = self._history_store.get_history(detector_name)
        return self._trend_analyzer.get_summary(snapshots)

    def get_anomalies(self, detector_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取异常记录。"""
        anomalies = self._anomaly_detector.get_anomalies(detector_name)
        return [
            {
                "detector_name": a.detector_name,
                "anomaly_type": a.anomaly_type.value,
                "current_value": a.current_value,
                "threshold": a.threshold,
                "description": a.description,
                "severity": a.severity.value,
                "detected_at": a.detected_at.isoformat(),
            }
            for a in anomalies
        ]

    def record_detector_run(
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
        """记录一次检测器运行。"""
        self._collector.record_run(
            name=name,
            response_time_ms=response_time_ms,
            success=success,
            items_processed=items_processed,
            detected=detected,
            is_false_positive=is_false_positive,
            is_false_negative=is_false_negative,
            error=error,
        )

    def set_thresholds(self, thresholds: Dict[str, float]) -> None:
        """设置告警阈值。"""
        current = self._collector.get_thresholds()
        for key, value in thresholds.items():
            if hasattr(current, key):
                setattr(current, key, value)
        logger.info("告警阈值已更新: %s", thresholds)

    def get_thresholds(self) -> Dict[str, float]:
        """获取当前告警阈值。"""
        t = self._collector.get_thresholds()
        return {
            "max_response_time_ms": t.max_response_time_ms,
            "min_success_rate": t.min_success_rate,
            "max_false_positive_rate": t.max_false_positive_rate,
            "max_idle_seconds": t.max_idle_seconds,
            "throughput_drop_ratio": t.throughput_drop_ratio,
            "accuracy_drop_ratio": t.accuracy_drop_ratio,
        }

    def on_config_changed(self, new_config: dict[str, Any]) -> None:
        """响应配置热更新。"""
        monitor_interval = float(new_config.get("monitor", {}).get("interval_seconds", self._monitor_interval))
        snapshot_interval = float(new_config.get("monitor", {}).get("snapshot_interval", self._snapshot_interval))
        if monitor_interval != self._monitor_interval:
            self._monitor_interval = max(1.0, monitor_interval)
            logger.info("监控间隔已更新: %.1fs", self._monitor_interval)
        if snapshot_interval != self._snapshot_interval:
            self._snapshot_interval = max(10.0, snapshot_interval)
            logger.info("快照间隔已更新: %.1fs", self._snapshot_interval)
        self._load_thresholds_from_config()
        logger.info("DashboardDLC 配置已热更新")

    def get_alert_manager(self) -> AlertManager:
        return self._alert_manager

    def get_metrics_collector(self) -> MetricsCollector:
        return self._collector

    def get_history_store(self) -> HistoryStore:
        return self._history_store

    def get_anomaly_detector(self) -> AnomalyDetector:
        return self._anomaly_detector

    def set_monitor_interval(self, seconds: float) -> None:
        self._monitor_interval = max(1.0, seconds)

    def set_snapshot_interval(self, seconds: float) -> None:
        self._snapshot_interval = max(10.0, seconds)