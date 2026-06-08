"""
仪表盘 DLC 模块测试。

验证 MetricsCollector、AnomalyDetector、AlertManager、
HistoryStore、TrendAnalyzer 和 DashboardDLC 的功能。
"""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta

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
from mca_core.dashboard.controller import DashboardController


class TestMetricsCollector(unittest.TestCase):
    """性能指标收集器测试。"""

    def setUp(self):
        self.collector = MetricsCollector()

    def test_register_detector(self):
        m = self.collector.register_detector("det_a", priority=10, cause_label="test")
        self.assertEqual(m.detector_name, "det_a")
        self.assertEqual(m.priority, 10)
        self.assertEqual(m.cause_label, "test")
        self.assertEqual(m.status, DetectorStatus.ONLINE)

    def test_record_run_basic(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=50.0, success=True)
        m = self.collector.get_metrics("det_a")
        self.assertEqual(m.total_runs, 1)
        self.assertEqual(m.successful_runs, 1)
        self.assertEqual(m.avg_response_time_ms, 50.0)

    def test_record_run_updates_average(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=100.0, success=True)
        self.collector.record_run("det_a", response_time_ms=200.0, success=True)
        m = self.collector.get_metrics("det_a")
        self.assertAlmostEqual(m.avg_response_time_ms, 150.0, delta=0.1)

    def test_record_run_failed(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=100.0, success=False, error="test_error")
        m = self.collector.get_metrics("det_a")
        self.assertEqual(m.failed_runs, 1)
        self.assertEqual(m.last_error, "test_error")
        self.assertEqual(m.status, DetectorStatus.DEGRADED)

    def test_success_rate(self):
        self.collector.register_detector("det_a")
        for _ in range(3):
            self.collector.record_run("det_a", response_time_ms=10.0, success=True)
        self.collector.record_run("det_a", response_time_ms=10.0, success=False)
        m = self.collector.get_metrics("det_a")
        self.assertAlmostEqual(m.success_rate, 0.75)

    def test_detection_rate(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=10.0, success=True, detected=True)
        self.collector.record_run("det_a", response_time_ms=10.0, success=True, detected=False)
        self.collector.record_run("det_a", response_time_ms=10.0, success=True, detected=True)
        m = self.collector.get_metrics("det_a")
        self.assertAlmostEqual(m.detection_rate, 2.0 / 3.0, delta=0.01)

    def test_false_positive_tracking(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=10.0, success=True, is_false_positive=True)
        self.collector.record_run("det_a", response_time_ms=10.0, success=True, is_false_positive=True)
        m = self.collector.get_metrics("det_a")
        self.assertEqual(m.false_positive_count, 2)
        self.assertAlmostEqual(m.false_positive_rate, 1.0)

    def test_mark_inactive(self):
        self.collector.register_detector("det_a")
        self.collector.mark_inactive("det_a")
        m = self.collector.get_metrics("det_a")
        self.assertFalse(m.is_active)
        self.assertEqual(m.status, DetectorStatus.OFFLINE)

    def test_get_all_metrics(self):
        self.collector.register_detector("det_a")
        self.collector.register_detector("det_b")
        all_m = self.collector.get_all_metrics()
        self.assertEqual(len(all_m), 2)

    def test_aggregated_summary_empty(self):
        summary = self.collector.get_aggregated_summary()
        self.assertEqual(summary["total_detectors"], 0)

    def test_aggregated_summary(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=100.0, success=True)
        summary = self.collector.get_aggregated_summary()
        self.assertEqual(summary["total_detectors"], 1)
        self.assertEqual(summary["online"], 1)
        self.assertAlmostEqual(summary["avg_success_rate"], 1.0)

    def test_stability_index(self):
        self.collector.register_detector("det_a")
        for _ in range(10):
            self.collector.record_run("det_a", response_time_ms=50.0, success=True)
        m = self.collector.get_metrics("det_a")
        self.assertGreaterEqual(m.stability_index, 0.8)

    def test_reset(self):
        self.collector.register_detector("det_a")
        self.collector.reset()
        self.assertEqual(len(self.collector.get_all_metrics()), 0)

    def test_thresholds(self):
        t = self.collector.get_thresholds()
        self.assertIsInstance(t, MetricThresholds)
        self.assertEqual(t.max_response_time_ms, 5000.0)

        new_t = MetricThresholds(max_response_time_ms=1000.0)
        self.collector.set_thresholds(new_t)
        self.assertEqual(self.collector.get_thresholds().max_response_time_ms, 1000.0)

    def test_min_max_response_time(self):
        self.collector.register_detector("det_a")
        self.collector.record_run("det_a", response_time_ms=100.0, success=True)
        self.collector.record_run("det_a", response_time_ms=10.0, success=True)
        self.collector.record_run("det_a", response_time_ms=200.0, success=True)
        m = self.collector.get_metrics("det_a")
        self.assertEqual(m.min_response_time_ms, 10.0)
        self.assertEqual(m.max_response_time_ms, 200.0)


class TestAnomalyDetector(unittest.TestCase):
    """异常检测器测试。"""

    def setUp(self):
        self.detector = AnomalyDetector()
        self.thresholds = MetricThresholds(
            max_response_time_ms=1000.0,
            min_success_rate=0.7,
            max_false_positive_rate=0.3,
            max_idle_seconds=60.0,
        )

    def test_no_anomaly_on_normal_metrics(self):
        m = DetectorMetrics(
            detector_name="test",
            total_runs=100,
            successful_runs=95,
            avg_response_time_ms=500.0,
            last_run_at=datetime.now(),
        )
        anomalies = self.detector.detect(m, self.thresholds)
        self.assertEqual(len(anomalies), 0)

    def test_detect_long_idle(self):
        m = DetectorMetrics(
            detector_name="test",
            last_run_at=datetime.now() - timedelta(seconds=120),
        )
        anomalies = self.detector.detect(m, self.thresholds)
        self.assertTrue(any(a.anomaly_type == AnomalyType.LONG_IDLE for a in anomalies))

    def test_detect_high_response_time(self):
        m = DetectorMetrics(
            detector_name="test",
            avg_response_time_ms=5000.0,
            last_run_at=datetime.now(),
        )
        anomalies = self.detector.detect(m, self.thresholds)
        self.assertTrue(any(a.anomaly_type == AnomalyType.HIGH_RESPONSE_TIME for a in anomalies))

    def test_detect_low_success_rate(self):
        m = DetectorMetrics(
            detector_name="test",
            total_runs=100,
            successful_runs=50,
            last_run_at=datetime.now(),
        )
        anomalies = self.detector.detect(m, self.thresholds)
        self.assertTrue(any(a.anomaly_type == AnomalyType.HIGH_ERROR_RATE for a in anomalies))

    def test_detect_high_false_positive(self):
        m = DetectorMetrics(
            detector_name="test",
            total_runs=100,
            successful_runs=95,
            false_positive_count=50,
            last_run_at=datetime.now(),
        )
        anomalies = self.detector.detect(m, self.thresholds)
        self.assertTrue(any(a.anomaly_type == AnomalyType.HIGH_FALSE_POSITIVE for a in anomalies))

    def test_detect_throughput_drop(self):
        prev = DetectorMetrics(
            detector_name="test",
            total_runs=100,
            avg_response_time_ms=100.0,
            last_run_at=datetime.now(),
        )
        curr = DetectorMetrics(
            detector_name="test",
            total_runs=200,
            avg_response_time_ms=500.0,
            last_run_at=datetime.now(),
        )
        anomalies = self.detector.detect(curr, self.thresholds, previous_metrics=prev)
        self.assertTrue(any(a.anomaly_type == AnomalyType.THROUGHPUT_DROP for a in anomalies))

    def test_no_anomaly_when_previous_has_no_runs(self):
        prev = DetectorMetrics(detector_name="test", total_runs=0)
        curr = DetectorMetrics(detector_name="test", total_runs=10, avg_response_time_ms=200.0, last_run_at=datetime.now())
        anomalies = self.detector.detect(curr, self.thresholds, previous_metrics=prev)
        self.assertEqual(len(anomalies), 0)

    def test_critical_severity_on_extreme_response_time(self):
        m = DetectorMetrics(
            detector_name="test",
            avg_response_time_ms=5000.0,
            last_run_at=datetime.now(),
        )
        anomalies = self.detector.detect(m, self.thresholds)
        criticals = [a for a in anomalies if a.severity == AlertLevel.CRITICAL]
        self.assertGreater(len(criticals), 0)

    def test_get_anomalies_by_detector(self):
        m = DetectorMetrics(
            detector_name="sub_a",
            avg_response_time_ms=2000.0,
            last_run_at=datetime.now(),
        )
        self.detector.detect(m, self.thresholds)
        anomalies = self.detector.get_anomalies("sub_a")
        self.assertGreater(len(anomalies), 0)
        self.assertEqual(len(self.detector.get_anomalies("nonexistent")), 0)


class TestAlertManager(unittest.TestCase):
    """告警管理器测试。"""

    def setUp(self):
        self.manager = AlertManager()

    def test_create_alert(self):
        alert = self.manager.create_alert(
            "det_a", AnomalyType.HIGH_ERROR_RATE, AlertLevel.ERROR, "错误率过高"
        )
        self.assertEqual(alert.detector_name, "det_a")
        self.assertEqual(alert.level, AlertLevel.ERROR)
        self.assertFalse(alert.acknowledged)

    def test_acknowledge_alert(self):
        alert = self.manager.create_alert("det_a", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.assertTrue(self.manager.acknowledge_alert(alert.alert_id))
        alerts = self.manager.get_alerts(detector_name="det_a")
        self.assertTrue(alerts[0].acknowledged)

    def test_resolve_alert(self):
        alert = self.manager.create_alert("det_a", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.assertTrue(self.manager.resolve_alert(alert.alert_id))
        alerts = self.manager.get_alerts(detector_name="det_a")
        self.assertIsNotNone(alerts[0].resolved_at)

    def test_get_active_count(self):
        self.manager.create_alert("det_a", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.manager.create_alert("det_b", AnomalyType.LONG_IDLE, AlertLevel.ERROR, "")
        self.assertEqual(self.manager.get_active_count(), 2)
        alert = self.manager.create_alert("det_c", AnomalyType.LONG_IDLE, AlertLevel.INFO, "")
        self.manager.resolve_alert(alert.alert_id)
        self.assertEqual(self.manager.get_active_count(), 2)

    def test_get_count_by_level(self):
        self.manager.create_alert("a", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.manager.create_alert("b", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.manager.create_alert("c", AnomalyType.LONG_IDLE, AlertLevel.CRITICAL, "")
        counts = self.manager.get_count_by_level()
        self.assertEqual(counts["warning"], 2)
        self.assertEqual(counts["critical"], 1)

    def test_filter_alerts_by_level(self):
        self.manager.create_alert("a", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.manager.create_alert("b", AnomalyType.LONG_IDLE, AlertLevel.ERROR, "")
        warnings = self.manager.get_alerts(level=AlertLevel.WARNING)
        self.assertEqual(len(warnings), 1)

    def test_filter_alerts_by_detector(self):
        self.manager.create_alert("x", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        self.manager.create_alert("y", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "")
        alerts = self.manager.get_alerts(detector_name="x")
        self.assertEqual(len(alerts), 1)

    def test_notify_callback(self):
        received: list[Alert] = []

        def cb(alert):
            received.append(alert)

        self.manager.add_notify_callback(cb)
        self.manager.create_alert("det", AnomalyType.LONG_IDLE, AlertLevel.WARNING, "test")
        self.assertEqual(len(received), 1)
        self.manager.remove_notify_callback(cb)
        self.manager.create_alert("det", AnomalyType.LONG_IDLE, AlertLevel.INFO, "")
        self.assertEqual(len(received), 1)


class TestHistoryStore(unittest.TestCase):
    """历史数据存储测试。"""

    def setUp(self):
        self.store = HistoryStore()

    def test_record_and_retrieve(self):
        m = DetectorMetrics(detector_name="det_a", avg_response_time_ms=100.0, total_runs=5)
        self.store.record_snapshot(m)
        history = self.store.get_history("det_a")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].avg_response_time_ms, 100.0)

    def test_multiple_snapshots(self):
        for i in range(5):
            m = DetectorMetrics(detector_name="det_a", total_runs=i)
            self.store.record_snapshot(m)
        history = self.store.get_history("det_a")
        self.assertEqual(len(history), 5)

    def test_get_all_names(self):
        self.store.record_snapshot(DetectorMetrics(detector_name="a"))
        self.store.record_snapshot(DetectorMetrics(detector_name="b"))
        names = self.store.get_all_names()
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_get_latest_snapshot(self):
        self.store.record_snapshot(DetectorMetrics(detector_name="a", avg_response_time_ms=100.0))
        self.store.record_snapshot(DetectorMetrics(detector_name="a", avg_response_time_ms=200.0))
        latest = self.store.get_latest_snapshot("a")
        self.assertEqual(latest.avg_response_time_ms, 200.0)

    def test_time_range_filter(self):
        self.store.record_snapshot(DetectorMetrics(detector_name="a"))
        history = self.store.get_history("a", time_range=TimeRange.LAST_MINUTE)
        self.assertEqual(len(history), 1)

    def test_limit_parameter(self):
        for _ in range(10):
            self.store.record_snapshot(DetectorMetrics(detector_name="a"))
        history = self.store.get_history("a", limit=5)
        self.assertEqual(len(history), 5)


class TestTrendAnalyzer(unittest.TestCase):
    """趋势分析器测试。"""

    def test_empty_snapshots(self):
        result = TrendAnalyzer.analyze_response_time_trend([])
        self.assertEqual(result["trend"], "stable")

    def test_stable_trend(self):
        snapshots = [
            HistorySnapshot(detector_name="a", avg_response_time_ms=100.0)
            for _ in range(5)
        ]
        result = TrendAnalyzer.analyze_response_time_trend(snapshots)
        self.assertEqual(result["trend"], "stable")

    def test_increasing_trend(self):
        snapshots = [
            HistorySnapshot(detector_name="a", avg_response_time_ms=float(i * 100))
            for i in range(10)
        ]
        result = TrendAnalyzer.analyze_response_time_trend(snapshots)
        self.assertEqual(result["trend"], "increasing")
        self.assertGreater(result["rate"], 0)

    def test_decreasing_trend(self):
        snapshots = [
            HistorySnapshot(detector_name="a", avg_response_time_ms=float(1000 - i * 100))
            for i in range(10)
        ]
        result = TrendAnalyzer.analyze_response_time_trend(snapshots)
        self.assertEqual(result["trend"], "decreasing")

    def test_success_rate_improving(self):
        snapshots = [
            HistorySnapshot(detector_name="a", success_rate=0.5 + i * 0.05)
            for i in range(10)
        ]
        result = TrendAnalyzer.analyze_success_rate_trend(snapshots)
        self.assertEqual(result["trend"], "improving")

    def test_success_rate_declining(self):
        snapshots = [
            HistorySnapshot(detector_name="a", success_rate=1.0 - i * 0.05)
            for i in range(10)
        ]
        result = TrendAnalyzer.analyze_success_rate_trend(snapshots)
        self.assertEqual(result["trend"], "declining")

    def test_stability_analysis(self):
        snapshots = [
            HistorySnapshot(detector_name="a", stability_index=0.9 + i * 0.01)
            for i in range(10)
        ]
        result = TrendAnalyzer.analyze_stability_trend(snapshots)
        self.assertIn(result["trend"], ["stable", "slightly_volatile"])

    def test_get_summary(self):
        snapshots = [
            HistorySnapshot(detector_name="a", avg_response_time_ms=100.0, success_rate=0.9)
            for _ in range(5)
        ]
        summary = TrendAnalyzer.get_summary(snapshots)
        self.assertIn("response_time", summary)
        self.assertIn("success_rate", summary)
        self.assertIn("stability", summary)
        self.assertEqual(summary["sample_count"], 5)


class TestDashboardDLC(unittest.TestCase):
    """Dashboard DLC 模块测试（不依赖 BrainCore）。"""

    def test_metrics_collector_stress(self):
        """压力测试：大量运行记录。"""
        collector = MetricsCollector()
        for i in range(15):
            collector.register_detector(f"det_{i}")
        for _ in range(100):
            for i in range(15):
                collector.record_run(f"det_{i}", response_time_ms=50.0, success=True)
        summary = collector.get_aggregated_summary()
        self.assertEqual(summary["total_detectors"], 15)
        self.assertAlmostEqual(summary["avg_success_rate"], 1.0)

    def test_detector_metrics_to_dict(self):
        m = DetectorMetrics(
            detector_name="full_test",
            status=DetectorStatus.ONLINE,
            total_runs=100,
            successful_runs=95,
            failed_runs=5,
            avg_response_time_ms=250.0,
            last_response_time_ms=200.0,
            min_response_time_ms=10.0,
            max_response_time_ms=500.0,
            detection_rate=0.3,
            false_positive_count=5,
            last_run_at=datetime.now(),
        )
        d = m.to_dict()
        self.assertEqual(d["detector_name"], "full_test")
        self.assertEqual(d["total_runs"], 100)
        self.assertIn("throughput_per_second", d)
        self.assertIn("stability_index", d)

    def test_history_snapshot_to_dict(self):
        s = HistorySnapshot(
            detector_name="test",
            avg_response_time_ms=100.0,
            success_rate=0.95,
            detection_rate=0.3,
            total_runs=50,
        )
        d = s.to_dict()
        self.assertEqual(d["detector_name"], "test")
        self.assertEqual(d["avg_response_time_ms"], 100.0)

    def test_alert_to_dict(self):
        a = Alert(
            detector_name="det_a",
            level=AlertLevel.ERROR,
            message="错误测试",
            anomaly_type=AnomalyType.HIGH_RESPONSE_TIME,
        )
        d = a.to_dict()
        self.assertEqual(d["detector_name"], "det_a")
        self.assertEqual(d["level"], "error")

    def test_end_to_end_flow(self):
        """端到端测试：指标收集 -> 异常检测 -> 告警 -> 历史记录 -> 趋势分析。"""
        collector = MetricsCollector(
            thresholds=MetricThresholds(
                max_response_time_ms=500.0,
                min_success_rate=0.5,
                max_idle_seconds=99999,
            )
        )
        anomaly_detector = AnomalyDetector()
        alert_manager = AlertManager()
        history_store = HistoryStore()

        collector.register_detector("flow_det")

        for _ in range(5):
            collector.record_run("flow_det", response_time_ms=100.0, success=True, detected=True)
        for _ in range(5):
            collector.record_run("flow_det", response_time_ms=1200.0, success=True, detected=True)

        metrics = collector.get_metrics("flow_det")
        assert metrics is not None
        anomalies = anomaly_detector.detect(metrics, collector.get_thresholds())

        for a in anomalies:
            alert_manager.create_from_anomaly(a)

        history_store.record_snapshot(metrics)

        alert_count = alert_manager.get_active_count()
        self.assertGreater(alert_count, 0)

        history = history_store.get_history("flow_det")
        self.assertGreater(len(history), 0)

    def test_metrics_collector_auto_registers_on_record(self):
        """测试 record_run 在检测器未注册时自动注册。"""
        collector = MetricsCollector()
        collector.record_run("auto_det", response_time_ms=50.0, success=True)
        m = collector.get_metrics("auto_det")
        self.assertIsNotNone(m)
        self.assertEqual(m.total_runs, 1)

    def test_throughput_calculation(self):
        collector = MetricsCollector()
        collector.register_detector("tp_det")
        collector.record_run("tp_det", response_time_ms=100.0, success=True)
        m = collector.get_metrics("tp_det")
        self.assertAlmostEqual(m.throughput_per_second, 10.0, delta=0.1)

    def test_alert_manager_acknowledge_nonexistent(self):
        manager = AlertManager()
        self.assertFalse(manager.acknowledge_alert("nonexistent"))

    def test_alert_manager_resolve_nonexistent(self):
        manager = AlertManager()
        self.assertFalse(manager.resolve_alert("nonexistent"))

    def test_history_store_clear(self):
        store = HistoryStore()
        store.record_snapshot(DetectorMetrics(detector_name="a"))
        store.clear("a")
        self.assertEqual(len(store.get_history("a")), 0)

    def test_get_summary_single_active(self):
        collector = MetricsCollector()
        collector.register_detector("single")
        summary = collector.get_aggregated_summary()
        self.assertEqual(summary["online"], 1)
        self.assertEqual(summary["offline"], 0)


class TestDashboardController(unittest.TestCase):
    """DashboardController 独立控制器测试。"""

    def setUp(self):
        self.controller = DashboardController()

    def tearDown(self):
        self.controller.stop()

    def test_initialization(self):
        self.assertIsNotNone(self.controller.get_metrics_collector())

    def test_get_aggregated_summary_empty(self):
        summary = self.controller.get_aggregated_summary()
        self.assertIn("total_detectors", summary)
        self.assertIn("online", summary)

    def test_record_detector_run(self):
        self.controller.record_detector_run("test_det", response_time_ms=50.0, success=True)
        metrics = self.controller.get_detector_metrics("test_det")
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(metrics["total_runs"], 1)

    def test_get_all_metrics(self):
        self.controller.record_detector_run("det_a", response_time_ms=100.0, success=True)
        self.controller.record_detector_run("det_b", response_time_ms=200.0, success=True)
        all_m = self.controller.get_all_metrics()
        self.assertEqual(len(all_m), 2)

    def test_get_alerts_empty(self):
        alerts = self.controller.get_alerts()
        self.assertEqual(len(alerts), 0)

    def test_set_and_get_thresholds(self):
        self.controller.set_thresholds({"max_response_time_ms": 1000.0})
        t = self.controller.get_thresholds()
        self.assertEqual(t["max_response_time_ms"], 1000.0)

    def test_acknowledge_nonexistent_alert(self):
        self.assertFalse(self.controller.acknowledge_alert("nonexistent"))

    def test_resolve_nonexistent_alert(self):
        self.assertFalse(self.controller.resolve_alert("nonexistent"))

    def test_get_trend_empty(self):
        trend = self.controller.get_trend("no_such_detector")
        self.assertIn("response_time", trend)
        self.assertEqual(trend["sample_count"], 0)

    def test_get_history_empty(self):
        history = self.controller.get_history("no_such_detector")
        self.assertEqual(len(history), 0)

    def test_start_and_stop(self):
        controller = DashboardController()
        controller.start()
        controller.stop()

    def test_multiple_runs_triggers_alert(self):
        controller = DashboardController()
        controller.set_thresholds({
            "max_response_time_ms": 500.0,
            "min_success_rate": 0.5,
            "max_idle_seconds": 99999,
        })
        controller.start()
        for _ in range(5):
            controller.record_detector_run("slow_det", response_time_ms=100.0, success=True)
        for _ in range(5):
            controller.record_detector_run("slow_det", response_time_ms=1200.0, success=True)
        time.sleep(0.3)
        metrics = controller.get_detector_metrics("slow_det")
        self.assertIsNotNone(metrics)
        assert metrics is not None
        self.assertEqual(metrics["total_runs"], 10)
        self.assertGreater(metrics["avg_response_time_ms"], 500.0)
        controller.stop()