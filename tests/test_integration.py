"""
跨子系统集成测试。

验证子系统间通信、错误传播、健康监控和数据完整性的端到端测试。

测试覆盖:
    - IntegrationBus: 注册、请求/响应、消息路由、超时
    - 错误处理: IntegrationError 层次结构、异常传播
    - 健康监控: HealthMonitor、SubsystemHealthRegistry
    - 性能度量: 延迟追踪、BottleneckDetector
    - 数据完整性: DataIntegrityChecker
    - 契约合规: ISubsystem 接口一致性
    - 多子系统编排: 多子系统协同工作流
"""
from __future__ import annotations

import time
import unittest
from typing import Any, Dict, List

from mca_core.integration import (
    BottleneckDetector,
    CommunicationError,
    DataIntegrityChecker,
    HealthMonitor,
    HealthStatus,
    IntegrationBus,
    IntegrationError,
    IntegrationMessage,
    IntegrationTestCase,
    IntegrationTimeoutError,
    ISubsystem,
    MessageDirection,
    MessagePriority,
    MessageSpy,
    MockSubsystem,
    ProtocolError,
    StateConflictError,
    SubsystemLifecycle,
    SubsystemUnavailableError,
)
from mca_core.integration.contract import IntegrationContract
from mca_core.integration.coordinator import (
    ContractRegistry,
    ContractValidator,
    IntegrationCoordinator,
    StateSynchronizer,
)


class TestIntegrationErrors(unittest.TestCase):
    """集成错误层次结构测试。"""

    def test_integration_error_basic(self):
        err = IntegrationError("基础集成错误", code="TEST_001")
        self.assertEqual(err.message, "基础集成错误")
        self.assertEqual(err.code, "TEST_001")
        self.assertFalse(err.recoverable)
        d = err.to_dict()
        self.assertEqual(d["type"], "IntegrationError")

    def test_communication_error_with_subsystems(self):
        err = CommunicationError(
            "网络不可达",
            source_subsystem="main_app",
            target_subsystem="patch_mgr",
        )
        self.assertEqual(err.code, "COMMUNICATION_ERROR")
        d = err.to_dict()
        self.assertEqual(d["details"]["source_subsystem"], "main_app")
        self.assertEqual(d["details"]["target_subsystem"], "patch_mgr")

    def test_subsystem_unavailable_error(self):
        err = SubsystemUnavailableError("training", current_state="stopped")
        self.assertIn("training", err.message)
        self.assertIn("stopped", err.message)
        self.assertEqual(err.code, "SUBSYSTEM_UNAVAILABLE")

    def test_integration_timeout_error(self):
        err = IntegrationTimeoutError("sync_data", 5.0)
        self.assertIn("sync_data", err.message)
        self.assertIn("5.0", err.message)
        self.assertEqual(err.code, "INTEGRATION_TIMEOUT")

    def test_protocol_error_with_versions(self):
        err = ProtocolError(
            "协议版本不匹配",
            expected_version="2.0",
            received_version="1.0",
        )
        self.assertEqual(err.code, "PROTOCOL_ERROR")
        self.assertEqual(err.details["expected_version"], "2.0")

    def test_state_conflict_error(self):
        err = StateConflictError(
            "db_service",
            expected_state="running",
            actual_state="uninitialized",
            operation="save_record",
        )
        self.assertEqual(err.code, "STATE_CONFLICT")
        self.assertIn("save_record", str(err.details))

    def test_integration_errors_inherit_from_app_error(self):
        from mca_core.errors import AppError

        self.assertIsInstance(IntegrationError("test"), AppError)
        self.assertIsInstance(CommunicationError("test"), AppError)
        self.assertIsInstance(SubsystemUnavailableError("test"), AppError)

    def test_subclass_of_integration_error(self):
        self.assertIsInstance(CommunicationError("test"), IntegrationError)
        self.assertIsInstance(SubsystemUnavailableError("test"), IntegrationError)
        self.assertIsInstance(IntegrationTimeoutError("test", 1.0), IntegrationError)


class TestIntegrationContract(unittest.TestCase):
    """集成契约测试。"""

    def test_contract_creation(self):
        contract = IntegrationContract(
            source="app",
            target="db_service",
            operations=["save", "query", "delete"],
            description="数据库集成契约",
        )
        d = contract.to_dict()
        self.assertEqual(d["source"], "app")
        self.assertEqual(d["target"], "db_service")
        self.assertEqual(len(d["operations"]), 3)

    def test_contract_unique_ids(self):
        c1 = IntegrationContract()
        c2 = IntegrationContract()
        self.assertNotEqual(c1.contract_id, c2.contract_id)

    def test_message_envelope_roundtrip(self):
        msg = IntegrationMessage[str](
            source="app",
            target="db",
            operation="query",
            payload="SELECT *",
            priority=MessagePriority.HIGH,
        )
        envelope = msg.to_envelope()
        restored = IntegrationMessage.from_envelope(envelope, payload="SELECT *")
        self.assertEqual(restored.source, "app")
        self.assertEqual(restored.target, "db")
        self.assertEqual(restored.operation, "query")
        self.assertEqual(restored.payload, "SELECT *")

    def test_message_default_values(self):
        msg = IntegrationMessage[Any]()
        self.assertIsNotNone(msg.message_id)
        self.assertEqual(msg.protocol_version, "1.0")
        self.assertEqual(msg.direction, MessageDirection.REQUEST)


class TestIntegrationBus(unittest.TestCase):
    """IntegrationBus 核心功能测试。"""

    def setUp(self):
        from mca_core.events import reset_event_bus
        reset_event_bus()

    def test_bus_initialization(self):
        bus = IntegrationBus(name="test_bus")
        self.assertEqual(bus.name, "test_bus")
        self.assertEqual(len(bus.list_subsystems()), 0)

    def test_register_subsystem(self):
        bus = IntegrationBus()
        mock = MockSubsystem("test_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        self.assertTrue(bus.is_registered("test_sub"))
        self.assertEqual(bus.get_subsystem("test_sub"), mock)

    def test_unregister_subsystem(self):
        bus = IntegrationBus()
        mock = MockSubsystem("test_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        self.assertTrue(bus.unregister("test_sub"))
        self.assertFalse(bus.is_registered("test_sub"))

    def test_register_empty_name_raises(self):
        bus = IntegrationBus()
        mock = MockSubsystem("", state=SubsystemLifecycle.RUNNING)
        with self.assertRaises(IntegrationError):
            bus.register(mock)

    def test_request_ping(self):
        bus = IntegrationBus()
        mock = MockSubsystem("pinger", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        response = bus.request("app", "pinger", "ping")
        self.assertEqual(response.direction, MessageDirection.RESPONSE)
        self.assertEqual(response.payload["status"], "ok")

    def test_request_status(self):
        bus = IntegrationBus()
        mock = MockSubsystem("status_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        response = bus.request("app", "status_sub", "status")
        self.assertEqual(response.payload["name"], "status_sub")

    def test_request_unregistered_subsystem(self):
        bus = IntegrationBus()
        with self.assertRaises(SubsystemUnavailableError) as ctx:
            bus.request("app", "nonexistent", "ping")
        self.assertIn("not_registered", str(ctx.exception.details))

    def test_request_stopped_subsystem(self):
        bus = IntegrationBus()
        mock = MockSubsystem("stopped_sub", state=SubsystemLifecycle.STOPPED)
        bus.register(mock)
        with self.assertRaises(StateConflictError):
            bus.request("app", "stopped_sub", "ping")

    def test_request_uninitialized_subsystem(self):
        bus = IntegrationBus()
        mock = MockSubsystem("uninit_sub", state=SubsystemLifecycle.UNINITIALIZED)
        bus.register(mock)
        with self.assertRaises(StateConflictError):
            bus.request("app", "uninit_sub", "ping")

    def test_request_timeout(self):
        bus = IntegrationBus(default_timeout=0.1)
        mock = MockSubsystem("slow_sub", state=SubsystemLifecycle.RUNNING)

        def slow_handler(msg):
            time.sleep(0.5)
            return IntegrationMessage()

        mock._message_handler = slow_handler
        bus.register(mock)
        with self.assertRaises(IntegrationTimeoutError):
            bus.request("app", "slow_sub", "ping")

    def test_request_degraded_subsystem_works(self):
        bus = IntegrationBus()
        mock = MockSubsystem("degraded_sub", state=SubsystemLifecycle.DEGRADED)
        bus.register(mock)
        response = bus.request("app", "degraded_sub", "ping")
        self.assertEqual(response.payload["status"], "ok")

    def test_echo_payload(self):
        bus = IntegrationBus()
        mock = MockSubsystem("echo_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        payload = {"data": [1, 2, 3], "nested": {"key": "value"}}
        response = bus.request("app", "echo_sub", "echo", payload=payload)
        self.assertEqual(response.payload, payload)

    def test_list_subsystems(self):
        bus = IntegrationBus()
        bus.register(MockSubsystem("sub_a", state=SubsystemLifecycle.RUNNING))
        bus.register(MockSubsystem("sub_b", health=False, state=SubsystemLifecycle.RUNNING))
        subsystems = bus.list_subsystems()
        self.assertEqual(len(subsystems), 2)
        names = [s["name"] for s in subsystems]
        self.assertIn("sub_a", names)
        self.assertIn("sub_b", names)

    def test_health_check_all(self):
        bus = IntegrationBus()
        bus.register(MockSubsystem("healthy", health=True, state=SubsystemLifecycle.RUNNING))
        bus.register(MockSubsystem("unhealthy", health=False, state=SubsystemLifecycle.RUNNING))
        results = bus.health_check_all()
        self.assertTrue(results["healthy"])
        self.assertFalse(results["unhealthy"])

    def test_shutdown_all(self):
        bus = IntegrationBus()
        mock = MockSubsystem("shutdown_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        results = bus.shutdown_all()
        self.assertTrue(results["shutdown_sub"])
        self.assertTrue(mock.was_shutdown)

    def test_get_metrics_initial(self):
        bus = IntegrationBus()
        metrics = bus.get_metrics()
        self.assertIn("total_requests", metrics)
        self.assertEqual(metrics["total_requests"], 0)

    def test_get_metrics_after_requests(self):
        bus = IntegrationBus()
        mock = MockSubsystem("metrics_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        for _ in range(5):
            bus.request("app", "metrics_sub", "ping")
        metrics = bus.get_metrics()
        self.assertEqual(metrics["total_requests"], 5)
        self.assertEqual(metrics["success_count"], 5)
        self.assertGreaterEqual(metrics["avg_latency_ms"], 0.0)
        self.assertIn("recent_metrics", metrics)

    def test_get_integration_graph(self):
        bus = IntegrationBus()
        mock = MockSubsystem("graph_sub", state=SubsystemLifecycle.RUNNING)
        bus.register(mock)
        bus.request("app", "graph_sub", "ping")
        graph = bus.get_integration_graph()
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertEqual(len(graph["nodes"]), 1)

    def test_register_replaces_existing(self):
        bus = IntegrationBus()
        mock1 = MockSubsystem("dup", version="1.0", state=SubsystemLifecycle.RUNNING)
        mock2 = MockSubsystem("dup", version="2.0", state=SubsystemLifecycle.RUNNING)
        bus.register(mock1)
        bus.register(mock2)
        sub = bus.get_subsystem("dup")
        self.assertEqual(sub.version, "2.0")

    def test_publish_event_through_bus(self):
        bus = IntegrationBus()
        from mca_core.events import EventTypes

        received = []

        def handler(event):
            received.append(event.payload)

        bus._event_bus.subscribe("test_integration_event", handler)
        bus.publish_event("test_integration_event", {"key": "val"}, source="test")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["key"], "val")


class TestHealthMonitor(unittest.TestCase):
    """健康监控测试。"""

    def setUp(self):
        self.bus = IntegrationBus(name="monitor_test")
        self.bus.register(MockSubsystem("sub_a", health=True, state=SubsystemLifecycle.RUNNING))
        self.bus.register(MockSubsystem("sub_b", health=True, state=SubsystemLifecycle.RUNNING))

    def test_monitor_initialization(self):
        monitor = HealthMonitor(interval_seconds=5.0)
        self.assertFalse(monitor._running)

    def test_monitor_start_stop(self):
        monitor = HealthMonitor(interval_seconds=0.1)
        monitor.set_check_callback(self.bus.health_check_all)
        monitor.start()
        self.assertTrue(monitor._running)
        time.sleep(0.3)
        monitor.stop()
        self.assertFalse(monitor._running)

    def test_check_now(self):
        monitor = HealthMonitor(interval_seconds=10.0)
        monitor.set_check_callback(self.bus.health_check_all)
        results = monitor.check_now()
        self.assertIn("sub_a", results)
        self.assertIn("sub_b", results)
        self.assertEqual(results["sub_a"].level.value, "healthy")

    def test_registry_tracks_unhealthy(self):
        monitor = HealthMonitor(interval_seconds=10.0)

        def bad_check():
            return {"sub_a": False, "sub_b": True}

        monitor.set_check_callback(bad_check)
        monitor.check_now()
        unhealthy = monitor.registry.get_unhealthy()
        self.assertTrue(any(u.subsystem_name == "sub_a" for u in unhealthy))

    def test_registry_consecutive_failures(self):
        monitor = HealthMonitor(interval_seconds=10.0)

        def bad_check():
            return {"sub": False}

        monitor.set_check_callback(bad_check)
        monitor.check_now()
        monitor.check_now()
        monitor.check_now()
        status = monitor.registry.get("sub")
        self.assertEqual(status.consecutive_failures, 3)

    def test_registry_summary(self):
        monitor = HealthMonitor(interval_seconds=10.0)
        monitor.set_check_callback(self.bus.health_check_all)
        monitor.check_now()
        summary = monitor.registry.get_summary()
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["healthy"], 2)
        self.assertEqual(summary["unhealthy"], 0)

    def test_health_history(self):
        monitor = HealthMonitor(interval_seconds=10.0)
        monitor.set_check_callback(self.bus.health_check_all)
        for _ in range(3):
            monitor.check_now()
        history = monitor.registry.get_history("sub_a")
        self.assertEqual(len(history), 3)


class TestBottleneckDetector(unittest.TestCase):
    """瓶颈检测器测试。"""

    def test_no_bottleneck_below_threshold(self):
        detector = BottleneckDetector(default_threshold_ms=100.0)
        result = detector.analyze("sub", "op", 50.0)
        self.assertIsNone(result)

    def test_bottleneck_above_threshold(self):
        detector = BottleneckDetector(default_threshold_ms=100.0)
        result = detector.analyze("sub", "op", 200.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "warning")

    def test_critical_bottleneck(self):
        detector = BottleneckDetector(default_threshold_ms=100.0)
        result = detector.analyze("sub", "op", 350.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "critical")

    def test_per_operation_threshold(self):
        detector = BottleneckDetector(default_threshold_ms=500.0)
        detector.set_threshold("slow_op", 50.0)
        result = detector.analyze("sub", "slow_op", 100.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "warning")

    def test_get_bottlenecks(self):
        detector = BottleneckDetector(default_threshold_ms=50.0)
        detector.analyze("sub_a", "op1", 200.0)
        detector.analyze("sub_b", "op2", 300.0)
        bottlenecks = detector.get_bottlenecks()
        self.assertEqual(len(bottlenecks), 2)

    def test_get_bottlenecks_by_severity(self):
        detector = BottleneckDetector(default_threshold_ms=50.0)
        detector.analyze("sub", "op", 200.0)
        criticals = detector.get_bottlenecks_by_severity("critical")
        self.assertEqual(len(criticals), 1)

    def test_analyze_bus_metrics(self):
        detector = BottleneckDetector(default_threshold_ms=10.0)
        metrics = {
            "recent_metrics": [
                {"source": "a", "target": "b", "latency_ms": 100, "success": True},
                {"source": "a", "target": "b", "latency_ms": 200, "success": True},
            ]
        }
        results = detector.analyze_bus_metrics(metrics)
        self.assertGreater(len(results), 0)


class TestDataIntegrityChecker(unittest.TestCase):
    """数据完整性检查器测试。"""

    def test_verify_matching_data(self):
        checker = DataIntegrityChecker()
        checker.record_sent("id1", {"key": "value"})
        checker.record_received("id1", {"key": "value"})
        self.assertTrue(checker.verify("id1"))

    def test_verify_mismatched_data(self):
        checker = DataIntegrityChecker()
        checker.record_sent("id1", {"key": "value"})
        checker.record_received("id1", {"key": "different"})
        self.assertFalse(checker.verify("id1"))

    def test_verify_missing_received(self):
        checker = DataIntegrityChecker()
        checker.record_sent("id1", {"key": "value"})
        self.assertFalse(checker.verify("id1"))

    def test_verify_all(self):
        checker = DataIntegrityChecker()
        checker.record_sent("a", {"key": "a"})
        checker.record_received("a", {"key": "a"})
        checker.record_sent("b", {"key": "b"})
        checker.record_received("b", {"key": "wrong"})
        results = checker.verify_all()
        self.assertTrue(results["a"])
        self.assertFalse(results["b"])

    def test_get_diff(self):
        checker = DataIntegrityChecker()
        checker.record_sent("id1", {"key": "sent_value"})
        checker.record_received("id1", {"key": "received_value"})
        diff = checker.get_diff("id1")
        self.assertIsNotNone(diff)
        self.assertIn("key", diff)

    def test_checksum_returns_string(self):
        checker = DataIntegrityChecker()
        cs = checker.record_sent("id1", [1, 2, 3])
        self.assertIsInstance(cs, str)
        self.assertEqual(len(cs), 64)

    def test_nested_data_integrity(self):
        checker = DataIntegrityChecker()
        nested = {"level1": {"level2": [1, 2, {"key": "val"}]}}
        checker.record_sent("nested", nested)
        checker.record_received("nested", nested)
        self.assertTrue(checker.verify("nested"))


class TestIntegrationTestCase(unittest.TestCase):
    """IntegrationTestCase 基类测试。"""

    def setUp(self):
        from mca_core.events import reset_event_bus
        reset_event_bus()

    def test_setup_teardown(self):
        tc = IntegrationTestCase()
        bus = tc.setup("test_env")
        self.assertIsNotNone(bus)
        tc.teardown()

    def test_register_mock(self):
        tc = IntegrationTestCase()
        tc.setup()
        mock = tc.register_mock("test_sub")
        self.assertEqual(mock.name, "test_sub")
        self.assertIsNotNone(tc.get_mock("test_sub"))
        tc.teardown()

    def test_assert_message_flow(self):
        tc = IntegrationTestCase()
        tc.setup()
        tc.register_mock("sub_a")
        tc.register_mock("sub_b")
        tc.bus.request("sub_a", "sub_b", "ping")
        tc.assert_message_flow("sub_a", "sub_b", "ping")

    def test_multiple_mocks_communication(self):
        tc = IntegrationTestCase()
        tc.setup()
        tc.register_mock("producer")
        tc.register_mock("consumer")
        response = tc.bus.request("producer", "consumer", "status")
        self.assertEqual(response.payload["name"], "consumer")
        tc.teardown()

    def test_get_mock_raises_keyerror(self):
        tc = IntegrationTestCase()
        tc.setup()
        with self.assertRaises(KeyError):
            tc.get_mock("nonexistent")
        tc.teardown()


class TestMultiSubsystemOrchestration(unittest.TestCase):
    """多子系统编排测试。"""

    def setUp(self):
        from mca_core.events import reset_event_bus
        reset_event_bus()
        self.bus = IntegrationBus(name="orchestration_test")

    def test_three_subsystem_pipeline(self):
        """测试三个子系统的流水线通信。"""
        mock_a = MockSubsystem("sub_a", state=SubsystemLifecycle.RUNNING)
        mock_b = MockSubsystem("sub_b", state=SubsystemLifecycle.RUNNING)
        mock_c = MockSubsystem("sub_c", state=SubsystemLifecycle.RUNNING)
        self.bus.register(mock_a)
        self.bus.register(mock_b)
        self.bus.register(mock_c)

        r1 = self.bus.request("sub_a", "sub_b", "ping")
        self.assertEqual(r1.payload["status"], "ok")

        r2 = self.bus.request("sub_b", "sub_c", "status")
        self.assertEqual(r2.payload["name"], "sub_c")

        metrics = self.bus.get_metrics()
        self.assertEqual(metrics["total_requests"], 2)
        self.assertEqual(metrics["success_count"], 2)

    def test_subsystem_failure_isolation(self):
        """测试子系统故障不影响其他子系统。"""
        self.bus.register(MockSubsystem("healthy_a", state=SubsystemLifecycle.RUNNING))

        failing = MockSubsystem("failing", state=SubsystemLifecycle.RUNNING)
        failing._message_handler = lambda msg: (_ for _ in ()).throw(
            RuntimeError("内部故障")
        )
        self.bus.register(failing)

        self.bus.register(MockSubsystem("healthy_b", state=SubsystemLifecycle.RUNNING))

        r1 = self.bus.request("test", "healthy_a", "ping")
        self.assertEqual(r1.payload["status"], "ok")

        with self.assertRaises(CommunicationError):
            self.bus.request("test", "failing", "ping")

        r2 = self.bus.request("test", "healthy_b", "ping")
        self.assertEqual(r2.payload["status"], "ok")

    def test_health_degradation_detection(self):
        """测试健康状态降级检测。"""
        healthy = MockSubsystem("healthy", health=True, state=SubsystemLifecycle.RUNNING)
        unhealthy = MockSubsystem("unhealthy", health=False, state=SubsystemLifecycle.RUNNING)
        self.bus.register(healthy)
        self.bus.register(unhealthy)

        results = self.bus.health_check_all()
        self.assertTrue(results["healthy"])
        self.assertFalse(results["unhealthy"])

    def test_shutdown_all_order(self):
        """测试 shutdown_all 正确关闭所有子系统。"""
        mocks = [
            MockSubsystem(f"sub_{i}", state=SubsystemLifecycle.RUNNING)
            for i in range(5)
        ]
        for m in mocks:
            self.bus.register(m)
        results = self.bus.shutdown_all()
        self.assertEqual(len(results), 5)
        for m in mocks:
            self.assertTrue(m.was_shutdown)
            self.assertEqual(m.state, SubsystemLifecycle.STOPPED)

    def test_metrics_track_cross_subsystem_latency(self):
        """测试跨子系统延迟追踪。"""
        self.bus.register(MockSubsystem("sub_a", state=SubsystemLifecycle.RUNNING))
        self.bus.register(MockSubsystem("sub_b", state=SubsystemLifecycle.RUNNING))
        self.bus.request("sub_a", "sub_b", "ping")
        metrics = self.bus.get_metrics()
        self.assertIn("recent_metrics", metrics)
        self.assertGreater(len(metrics["recent_metrics"]), 0)

    def test_event_propagation_across_bus(self):
        """测试事件通过总线跨子系统传播。"""
        events: List[Dict[str, Any]] = []

        def listener(event):
            events.append(event.payload)

        self.bus._event_bus.subscribe("cross_event", listener)
        self.bus.publish_event("cross_event", {"from": "sub_a", "to": "all"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["from"], "sub_a")


class TestMessageSpy(unittest.TestCase):
    """消息拦截器测试。"""

    def test_capture_and_verify(self):
        spy = MessageSpy()
        msg = IntegrationMessage(source="a", target="b", operation="test")
        spy.capture(msg)
        self.assertEqual(spy.message_count(), 1)
        self.assertTrue(spy.has_message_to("b", "test"))
        self.assertTrue(spy.has_message_from("a"))

    def test_filter_by_operation(self):
        spy = MessageSpy()
        spy.capture(IntegrationMessage(source="a", target="b", operation="op1"))
        spy.capture(IntegrationMessage(source="a", target="b", operation="op2"))
        ops = spy.get_messages_by_operation("op1")
        self.assertEqual(len(ops), 1)

    def test_clear_messages(self):
        spy = MessageSpy()
        spy.capture(IntegrationMessage())
        spy.clear()
        self.assertEqual(spy.message_count(), 0)

    def test_to_list_format(self):
        spy = MessageSpy()
        spy.capture(IntegrationMessage(source="x", target="y", operation="z"))
        lst = spy.to_list()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["source"], "x")


class TestSubsystemLifecycle(unittest.TestCase):
    """子系统生命周期测试。"""

    def test_lifecycle_transitions(self):
        mock = MockSubsystem("lifecycle_sub")
        self.assertEqual(mock.state, SubsystemLifecycle.RUNNING)

        mock.initialize()
        self.assertEqual(mock.state, SubsystemLifecycle.INITIALIZED)
        self.assertTrue(mock.was_initialized)

        mock.startup()
        self.assertEqual(mock.state, SubsystemLifecycle.RUNNING)
        self.assertTrue(mock.was_started)

        mock.shutdown()
        self.assertEqual(mock.state, SubsystemLifecycle.STOPPED)
        self.assertTrue(mock.was_shutdown)

    def test_subsystem_interface_compliance(self):
        """验证 MockSubsystem 实现了 ISubsystem 的完整接口。"""
        mock = MockSubsystem("compliance_sub")
        self.assertIsInstance(mock, ISubsystem)
        self.assertEqual(mock.name, "compliance_sub")
        self.assertEqual(mock.version, "0.0.0")
        self.assertIsInstance(mock.state, SubsystemLifecycle)
        self.assertIsInstance(mock.health_check(), bool)
        self.assertIsInstance(mock.status(), dict)
        self.assertIsInstance(mock.supported_operations(), list)

    def test_degraded_state_supports_requests(self):
        mock = MockSubsystem("degraded_sub", state=SubsystemLifecycle.DEGRADED)
        bus = IntegrationBus()
        bus.register(mock)
        response = bus.request("app", "degraded_sub", "ping")
        self.assertEqual(response.payload["status"], "ok")

    def test_error_state_rejects_requests(self):
        mock = MockSubsystem("error_sub", state=SubsystemLifecycle.ERROR)
        bus = IntegrationBus()
        bus.register(mock)
        with self.assertRaises(StateConflictError):
            bus.request("app", "error_sub", "ping")

    def test_stopping_state_rejects_requests(self):
        mock = MockSubsystem("stopping_sub", state=SubsystemLifecycle.STOPPING)
        bus = IntegrationBus()
        bus.register(mock)
        with self.assertRaises(StateConflictError):
            bus.request("app", "stopping_sub", "ping")


class TestContractValidator(unittest.TestCase):
    """合约验证器测试。"""

    def test_valid_subsystem_passes(self):
        validator = ContractValidator()
        mock = MockSubsystem("valid_sub", state=SubsystemLifecycle.RUNNING)
        contract = IntegrationContract(
            source="app",
            target="valid_sub",
            operations=["ping", "status"],
        )
        result = validator.validate(mock, contract)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.violations), 0)

    def test_missing_operations_detected(self):
        validator = ContractValidator()
        mock = MockSubsystem("limited_sub", supported_ops=["ping"], state=SubsystemLifecycle.RUNNING)
        contract = IntegrationContract(
            source="app",
            target="limited_sub",
            operations=["ping", "query", "delete"],
        )
        result = validator.validate(mock, contract)
        self.assertFalse(result.passed)
        self.assertIn("query", str(result.violations))

    def test_unhealthy_subsystem_warns(self):
        validator = ContractValidator()
        mock = MockSubsystem("unhealthy_sub", health=False, state=SubsystemLifecycle.RUNNING)
        contract = IntegrationContract(operations=["ping"])
        result = validator.validate(mock, contract)
        self.assertTrue(any("健康" in w for w in result.warnings))


class TestContractRegistry(unittest.TestCase):
    """契约注册表测试。"""

    def test_register_and_get(self):
        registry = ContractRegistry()
        contract = IntegrationContract(source="a", target="b")
        registry.register(contract)
        self.assertIsNotNone(registry.get(contract.contract_id))

    def test_find_by_subsystem(self):
        registry = ContractRegistry()
        c1 = IntegrationContract(source="app", target="db")
        c2 = IntegrationContract(source="db", target="cache")
        registry.register(c1)
        registry.register(c2)
        db_contracts = registry.find_by_subsystem("db")
        self.assertEqual(len(db_contracts), 2)

    def test_validate_all(self):
        registry = ContractRegistry()
        contract = IntegrationContract(
            source="app",
            target="test_sub",
            operations=["ping"],
        )
        registry.register(contract)

        mock = MockSubsystem("test_sub", state=SubsystemLifecycle.RUNNING)
        subsystems = {"test_sub": mock}

        results = registry.validate_all(subsystems)
        self.assertIn("test_sub", results)
        self.assertTrue(results["test_sub"][0].passed)


class TestStateSynchronizer(unittest.TestCase):
    """状态同步器测试。"""

    def test_update_and_get(self):
        sync = StateSynchronizer()
        sync.update_state("sub_a", {"status": "active", "count": 42})
        state = sync.get_state("sub_a")
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["count"], 42)

    def test_callback_notification(self):
        sync = StateSynchronizer()
        notified: List[tuple] = []

        def callback(name, state):
            notified.append((name, state))

        sync.subscribe("sub_a", callback)
        sync.update_state("sub_a", {"key": "new_value"})
        self.assertEqual(len(notified), 1)
        self.assertEqual(notified[0][0], "sub_a")

    def test_get_nonexistent_state(self):
        sync = StateSynchronizer()
        self.assertIsNone(sync.get_state("nonexistent"))

    def test_get_all_states(self):
        sync = StateSynchronizer()
        sync.update_state("sub_a", {"key": "a"})
        sync.update_state("sub_b", {"key": "b"})
        all_states = sync.get_all_states()
        self.assertIn("sub_a", all_states)
        self.assertIn("sub_b", all_states)

    def test_wait_for_state(self):
        sync = StateSynchronizer()
        import threading

        def delayed_update():
            import time
            time.sleep(0.1)
            sync.update_state("sub", {"ready": True})

        t = threading.Thread(target=delayed_update, daemon=True)
        t.start()
        result = sync.wait_for_state("sub", "ready", True, timeout=1.0)
        self.assertTrue(result)

    def test_unsubscribe_stops_notification(self):
        sync = StateSynchronizer()
        notified: List[tuple] = []

        def callback(name, state):
            notified.append((name, state))

        sync.subscribe("sub", callback)
        sync.unsubscribe("sub", callback)
        sync.update_state("sub", {"key": "val"})
        self.assertEqual(len(notified), 0)


class TestIntegrationCoordinator(unittest.TestCase):
    """集成协调器测试。"""

    def setUp(self):
        from mca_core.events import reset_event_bus
        reset_event_bus()
        self.bus = IntegrationBus(name="coordinator_test")
        self.coordinator = IntegrationCoordinator()

    def test_verify_dependencies_all_available(self):
        subs = {
            "sub_a": MockSubsystem("sub_a", state=SubsystemLifecycle.RUNNING),
            "sub_b": MockSubsystem("sub_b", state=SubsystemLifecycle.RUNNING),
        }
        ok, unavailable = self.coordinator.verify_dependencies(
            subs, ["sub_a", "sub_b"]
        )
        self.assertTrue(ok)
        self.assertEqual(len(unavailable), 0)

    def test_verify_dependencies_missing(self):
        subs = {"sub_a": MockSubsystem("sub_a", state=SubsystemLifecycle.RUNNING)}
        ok, unavailable = self.coordinator.verify_dependencies(
            subs, ["sub_a", "sub_b"]
        )
        self.assertFalse(ok)
        self.assertGreater(len(unavailable), 0)

    def test_verify_dependencies_unhealthy(self):
        subs = {"sub_a": MockSubsystem("sub_a", health=False, state=SubsystemLifecycle.RUNNING)}
        ok, unavailable = self.coordinator.verify_dependencies(subs, ["sub_a"])
        self.assertFalse(ok)
        self.assertIn("不健康", unavailable[0])

    def test_sequential_workflow(self):
        self.bus.register(MockSubsystem("step_a", state=SubsystemLifecycle.RUNNING))
        self.bus.register(MockSubsystem("step_b", state=SubsystemLifecycle.RUNNING))

        steps = [
            ("step_a", "ping", "ping step_a"),
            ("step_b", "status", "get status from step_b"),
        ]
        result = self.coordinator.execute_sequential_workflow(steps, self.bus)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["steps"]), 2)

    def test_sequential_workflow_partial_failure(self):
        self.bus.register(MockSubsystem("good", state=SubsystemLifecycle.RUNNING))

        failing = MockSubsystem("bad", state=SubsystemLifecycle.RUNNING)
        failing._message_handler = lambda msg: (_ for _ in ()).throw(
            RuntimeError("broken")
        )
        self.bus.register(failing)

        steps = [
            ("good", "ping", "should work"),
            ("bad", "ping", "will fail"),
        ]
        result = self.coordinator.execute_sequential_workflow(steps, self.bus)
        self.assertFalse(result["success"])
        self.assertTrue(result["steps"][0]["success"])
        self.assertFalse(result["steps"][1]["success"])

    def test_shutdown_sequence(self):
        mocks = [
            MockSubsystem(f"sub_{i}", state=SubsystemLifecycle.RUNNING)
            for i in range(3)
        ]
        for m in mocks:
            self.bus.register(m)

        result = self.coordinator.shutdown_sequence(self.bus)
        self.assertIn("order", result)
        for m in mocks:
            self.assertTrue(m.was_shutdown)

    def test_contract_registry_on_coordinator(self):
        contract = IntegrationContract(source="app", target="db", operations=["ping"])
        self.coordinator.registry.register(contract)
        retrieved = self.coordinator.registry.get(contract.contract_id)
        self.assertIsNotNone(retrieved)