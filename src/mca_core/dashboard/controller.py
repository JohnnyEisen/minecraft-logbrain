"""
仪表盘控制器 — 不依赖 BrainCore 的独立控制层。

提供与 DashboardDLC 相同的 API，但无需 BrainCore 即可运行。
在应用启动时自动创建并连接到 UI 面板。

模块说明:
    - DashboardController: 封装 MetricsCollector、AnomalyDetector、AlertManager 等核心组件

v2.0: 支持通过 DI 注入 ConfigManager / AuditTrail / EventBus，
      实现配置集中管理、告警审计和事件通知。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

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


class DashboardController:
    """仪表盘独立控制器。

    不依赖 BrainCore，可在应用启动时直接使用。
    封装所有仪表盘核心组件并提供统一 API。

    v2.0: 支持通过 DI 注入 ConfigManager / AuditTrail / EventBus。

    用法:
        controller = DashboardController()
        controller.start()
        panel.set_dashboard(controller)
    """

    def __init__(
        self,
        *,
        config: Any = None,
        audit: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._collector = MetricsCollector()
        self._anomaly_detector = AnomalyDetector()
        self._alert_manager = AlertManager()
        self._history_store = HistoryStore()
        self._trend_analyzer = TrendAnalyzer()

        self._config = config
        self._audit = audit
        self._event_bus = event_bus

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._monitor_interval: float = 5.0
        self._snapshot_interval: float = 30.0
        self._last_snapshot_time: float = 0.0
        self._previous_metrics: Dict[str, DetectorMetrics] = {}

        if config is not None:
            self._monitor_interval = config.get_float("monitor.interval_seconds", 5.0)
            self._snapshot_interval = config.get_float("monitor.snapshot_interval", 30.0)
            self._load_thresholds_from_config()

    def _load_thresholds_from_config(self) -> None:
        if self._config is None:
            return
        thresholds = self._collector.get_thresholds()
        t = thresholds
        t.max_response_time_ms = self._config.get_float("monitor.max_response_time_ms", t.max_response_time_ms)
        t.min_success_rate = self._config.get_float("monitor.min_success_rate", t.min_success_rate)
        t.max_false_positive_rate = self._config.get_float("monitor.max_false_positive_rate", t.max_false_positive_rate)
        t.max_idle_seconds = self._config.get_float("monitor.max_idle_seconds", t.max_idle_seconds)

    def start(self) -> None:
        self._register_detectors()
        self._start_monitor_loop()
        logger.info("DashboardController 已启动，注册 %d 个检测器",
                     len(self._collector.get_all_metrics()))
        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.SYSTEM_START,
                    detail="DashboardController 已启动",
                    component="dashboard",
                    metadata={"detectors_registered": len(self._collector.get_all_metrics())},
                )
            except Exception:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
        logger.info("DashboardController 已停止")
        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.SYSTEM_STOP,
                    detail="DashboardController 已停止",
                    component="dashboard",
                )
            except Exception:
                pass

    def _register_detectors(self) -> None:
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
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="dashboard-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_all_detectors()
                self._record_history_if_needed()
            except Exception as e:
                logger.error("Dashboard 监控循环异常: %s", e)
            self._stop_event.wait(self._monitor_interval)

    def _check_all_detectors(self) -> None:
        all_metrics = self._collector.get_all_metrics()

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
                            component="dashboard",
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
                                source="dashboard",
                            )
                        )
                    except Exception:
                        pass

        self._previous_metrics = {
            name: metrics
            for name, metrics in all_metrics.items()
        }

    def _record_history_if_needed(self) -> None:
        now = time.time()
        if now - self._last_snapshot_time >= self._snapshot_interval:
            for metrics in self._collector.get_all_metrics().values():
                if metrics.total_runs > 0:
                    self._history_store.record_snapshot(metrics)
            self._last_snapshot_time = now

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: m.to_dict()
            for name, m in self._collector.get_all_metrics().items()
        }

    def get_detector_metrics(self, name: str) -> Optional[Dict[str, Any]]:
        m = self._collector.get_metrics(name)
        return m.to_dict() if m else None

    def get_aggregated_summary(self) -> Dict[str, Any]:
        return self._collector.get_aggregated_summary()

    def get_alerts(
        self,
        acknowledged: Optional[bool] = None,
        level: Optional[str] = None,
        detector_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        alert_level = AlertLevel(level) if level else None
        alerts = self._alert_manager.get_alerts(acknowledged, alert_level, detector_name, limit)
        return [a.to_dict() for a in alerts]

    def get_alert_count(self) -> Dict[str, Any]:
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
        tr = TimeRange(time_range) if time_range else None
        snapshots = self._history_store.get_history(detector_name, tr, limit)
        return [s.to_dict() for s in snapshots]

    def get_trend(self, detector_name: str) -> Dict[str, Any]:
        snapshots = self._history_store.get_history(detector_name)
        return self._trend_analyzer.get_summary(snapshots)

    def get_anomalies(self, detector_name: Optional[str] = None) -> List[Dict[str, Any]]:
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
        current = self._collector.get_thresholds()
        for key, value in thresholds.items():
            if hasattr(current, key):
                setattr(current, key, value)
        logger.info("告警阈值已更新: %s", thresholds)

    def get_thresholds(self) -> Dict[str, float]:
        t = self._collector.get_thresholds()
        return {
            "max_response_time_ms": t.max_response_time_ms,
            "min_success_rate": t.min_success_rate,
            "max_false_positive_rate": t.max_false_positive_rate,
            "max_idle_seconds": t.max_idle_seconds,
            "throughput_drop_ratio": t.throughput_drop_ratio,
            "accuracy_drop_ratio": t.accuracy_drop_ratio,
        }

    def acknowledge_alert(self, alert_id: str) -> bool:
        return self._alert_manager.acknowledge_alert(alert_id)

    def resolve_alert(self, alert_id: str) -> bool:
        return self._alert_manager.resolve_alert(alert_id)

    def get_metrics_collector(self) -> MetricsCollector:
        return self._collector

    def set_monitor_interval(self, seconds: float) -> None:
        self._monitor_interval = max(1.0, seconds)

    def set_snapshot_interval(self, seconds: float) -> None:
        self._snapshot_interval = max(10.0, seconds)