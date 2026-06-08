"""
集成测试工具 — 跨子系统测试辅助。

提供 MockSubsystem、IntegrationTestCase 和 DataIntegrityChecker，
用于编写跨子系统的端到端测试。

模块说明:
    - MockSubsystem: ISubsystem 的 mock 实现，用于隔离测试
    - IntegrationTestCase: 提供 IntegrationBus 的测试基类
    - DataIntegrityChecker: 跨子系统数据完整性验证工具
    - MessageSpy: 消息拦截器，用于验证子系统间通信
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from mca_core.integration.bus import IntegrationBus
from mca_core.integration.contract import (
    ISubsystem,
    IntegrationMessage,
    MessageDirection,
    SubsystemLifecycle,
)
from mca_core.integration.errors import IntegrationError


@dataclass
class CapturedMessage:
    """被拦截的消息记录。"""
    message: IntegrationMessage[Any]
    captured_at: datetime = field(default_factory=datetime.now)
    direction: MessageDirection = MessageDirection.REQUEST

    def has_payload_key(self, key: str) -> bool:
        if isinstance(self.message.payload, dict):
            return key in self.message.payload
        return False

    def get_payload_value(self, key: str, default: Any = None) -> Any:
        if isinstance(self.message.payload, dict):
            return self.message.payload.get(key, default)
        return default


class MessageSpy:
    """消息拦截器。

    用于在集成测试中验证子系统之间的消息传递。

    Example:
        >>> spy = MessageSpy()
        >>> sub = MockSubsystem("test", spy_callback=spy.capture)
        >>> # ... run integration test ...
        >>> assert spy.has_message_to("test", operation="health_check")
    """

    def __init__(self) -> None:
        self._messages: List[CapturedMessage] = []
        self._lock = threading.Lock()

    def capture(self, msg: IntegrationMessage[Any], direction: MessageDirection = MessageDirection.REQUEST) -> None:
        """捕获消息。"""
        with self._lock:
            self._messages.append(CapturedMessage(message=msg, direction=direction))

    def has_message_to(
        self,
        target: str,
        operation: Optional[str] = None,
    ) -> bool:
        """检查是否有发送到特定目标的消息。"""
        with self._lock:
            for captured in self._messages:
                if captured.message.target == target:
                    if operation is None or captured.message.operation == operation:
                        return True
        return False

    def has_message_from(
        self,
        source: str,
        operation: Optional[str] = None,
    ) -> bool:
        """检查是否有从特定来源发送的消息。"""
        with self._lock:
            for captured in self._messages:
                if captured.message.source == source:
                    if operation is None or captured.message.operation == operation:
                        return True
        return False

    def get_messages_to(self, target: str) -> List[CapturedMessage]:
        """获取发送到特定目标的所有消息。"""
        with self._lock:
            return [m for m in self._messages if m.message.target == target]

    def get_messages_by_operation(self, operation: str) -> List[CapturedMessage]:
        """获取特定操作的所有消息。"""
        with self._lock:
            return [m for m in self._messages if m.message.operation == operation]

    def message_count(self) -> int:
        with self._lock:
            return len(self._messages)

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def to_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "source": m.message.source,
                    "target": m.message.target,
                    "operation": m.message.operation,
                    "direction": m.direction.value,
                    "timestamp": m.captured_at.isoformat(),
                }
                for m in self._messages
            ]


class MockSubsystem(ISubsystem):
    """ISubsystem 的 Mock 实现。

    用于在集成测试中模拟子系统行为，验证消息传递和状态转换。

    Example:
        >>> mock = MockSubsystem("test_sub", state=SubsystemLifecycle.RUNNING)
        >>> bus = IntegrationBus("test")
        >>> bus.register(mock)
        >>> response = bus.request("app", "test_sub", "ping")
        >>> assert response.payload == {"status": "ok"}
    """

    def __init__(
        self,
        name: str = "mock_subsystem",
        version: str = "0.0.0",
        state: SubsystemLifecycle = SubsystemLifecycle.RUNNING,
        health: bool = True,
        supported_ops: Optional[List[str]] = None,
        message_handler: Optional[Callable[[IntegrationMessage[Any]], IntegrationMessage[Any]]] = None,
        spy_callback: Optional[Callable[[IntegrationMessage[Any], MessageDirection], None]] = None,
    ) -> None:
        self._name = name
        self._version = version
        self._state = state
        self._health = health
        self._supported_ops = supported_ops or ["ping", "status", "health_check"]
        self._message_handler = message_handler or self._default_handler
        self._spy_callback = spy_callback
        self._received_messages: List[IntegrationMessage[Any]] = []
        self._initialize_called = False
        self._startup_called = False
        self._shutdown_called = False
        self._health_check_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def state(self) -> SubsystemLifecycle:
        return self._state

    def set_state(self, state: SubsystemLifecycle) -> None:
        self._state = state

    def set_health(self, healthy: bool) -> None:
        self._health = healthy

    def initialize(self) -> None:
        self._initialize_called = True
        self._state = SubsystemLifecycle.INITIALIZED

    def startup(self) -> None:
        self._startup_called = True
        self._state = SubsystemLifecycle.RUNNING

    def shutdown(self) -> None:
        self._shutdown_called = True
        self._state = SubsystemLifecycle.STOPPED

    def health_check(self) -> bool:
        self._health_check_count += 1
        return self._health

    def status(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "version": self._version,
            "state": self._state.value,
            "healthy": self._health,
            "health_check_count": self._health_check_count,
        }

    def supported_operations(self) -> List[str]:
        return list(self._supported_ops)

    def handle_message(
        self,
        message: IntegrationMessage[Any],
    ) -> IntegrationMessage[Any]:
        self._received_messages.append(message)
        if self._spy_callback:
            self._spy_callback(message, MessageDirection.REQUEST)
        return self._message_handler(message)

    def _default_handler(
        self,
        message: IntegrationMessage[Any],
    ) -> IntegrationMessage[Any]:
        """默认消息处理器。"""
        if message.operation == "ping":
            return IntegrationMessage(
                message_id=message.message_id,
                direction=MessageDirection.RESPONSE,
                source=self._name,
                target=message.source,
                operation="pong",
                payload={"status": "ok"},
                correlation_id=message.correlation_id or message.message_id,
            )
        if message.operation == "status":
            return IntegrationMessage(
                message_id=message.message_id,
                direction=MessageDirection.RESPONSE,
                source=self._name,
                target=message.source,
                operation="status_response",
                payload=self.status(),
                correlation_id=message.correlation_id or message.message_id,
            )
        if message.operation == "echo":
            return IntegrationMessage(
                message_id=message.message_id,
                direction=MessageDirection.RESPONSE,
                source=self._name,
                target=message.source,
                operation="echo_response",
                payload=message.payload,
                correlation_id=message.correlation_id or message.message_id,
            )
        return IntegrationMessage(
            message_id=message.message_id,
            direction=MessageDirection.RESPONSE,
            source=self._name,
            target=message.source,
            operation="unknown",
            payload={"error": f"unknown operation: {message.operation}"},
            correlation_id=message.correlation_id or message.message_id,
        )

    @property
    def received_messages(self) -> List[IntegrationMessage[Any]]:
        return list(self._received_messages)

    @property
    def was_initialized(self) -> bool:
        return self._initialize_called

    @property
    def was_started(self) -> bool:
        return self._startup_called

    @property
    def was_shutdown(self) -> bool:
        return self._shutdown_called


class IntegrationTestCase:
    """集成测试基类。

    提供预设的 IntegrationBus 和子系统生命周期管理。

    Usage:
        class MyIntegrationTest(IntegrationTestCase):
            def test_cross_subsystem_flow(self):
                self.register_mock("sub_a")
                self.register_mock("sub_b")
                response = self.bus.request("sub_a", "sub_b", "ping")
                self.assert_healthy(response)
    """

    def __init__(self) -> None:
        self.bus: Optional[IntegrationBus] = None
        self._mocks: Dict[str, MockSubsystem] = {}
        self._spies: Dict[str, MessageSpy] = {}
        self._test_errors: List[Exception] = []

    def setup(self, bus_name: str = "integration_test") -> IntegrationBus:
        """初始化测试环境。"""
        from mca_core.events import reset_event_bus

        reset_event_bus()
        self.bus = IntegrationBus(name=bus_name)
        self._mocks.clear()
        self._spies.clear()
        self._test_errors.clear()
        return self.bus

    def teardown(self) -> None:
        """清理测试环境。"""
        if self.bus:
            self.bus.shutdown_all()
        self._mocks.clear()
        self._spies.clear()

    def register_mock(
        self,
        name: str,
        version: str = "1.0.0",
        state: SubsystemLifecycle = SubsystemLifecycle.RUNNING,
        health: bool = True,
        supported_ops: Optional[List[str]] = None,
        message_handler: Optional[Callable] = None,
    ) -> MockSubsystem:
        """注册 Mock 子系统。"""
        spy = MessageSpy()
        mock = MockSubsystem(
            name=name,
            version=version,
            state=state,
            health=health,
            supported_ops=supported_ops,
            message_handler=message_handler,
            spy_callback=spy.capture,
        )
        self._mocks[name] = mock
        self._spies[name] = spy
        if self.bus:
            self.bus.register(mock)
        return mock

    def get_mock(self, name: str) -> MockSubsystem:
        mock = self._mocks.get(name)
        if mock is None:
            raise KeyError(f"Mock 子系统 '{name}' 未找到")
        return mock

    def get_spy(self, name: str) -> MessageSpy:
        spy = self._spies.get(name)
        if spy is None:
            raise KeyError(f"Spy '{name}' 未找到")
        return spy

    def assert_healthy(self, response: IntegrationMessage[Any]) -> None:
        """断言响应消息表示系统健康。"""
        assert response.direction == MessageDirection.RESPONSE, (
            f"期望 RESPONSE 方向，实际 {response.direction}"
        )

    def assert_message_flow(
        self,
        source: str,
        target: str,
        operation: str,
    ) -> None:
        """断言存在从 source 到 target 的指定操作消息流。"""
        spy = self.get_spy(target)
        assert spy.has_message_from(source, operation), (
            f"未找到来自 '{source}' 到 '{target}' 的 '{operation}' 消息"
        )

    def collect_error(self, error: Exception) -> None:
        """收集测试过程中的错误（用于非致命断言）。"""
        self._test_errors.append(error)

    def has_errors(self) -> bool:
        return len(self._test_errors) > 0


class DataIntegrityChecker:
    """跨子系统数据完整性验证工具。

    验证数据在子系统间传递后是否保持一致。

    Example:
        >>> checker = DataIntegrityChecker()
        >>> checker.record_sent("my_data", {"key": "value"})
        >>> checker.record_received("my_data", {"key": "value"})
        >>> assert checker.verify("my_data")
    """

    def __init__(self) -> None:
        self._sent: Dict[str, Any] = {}
        self._received: Dict[str, Any] = {}
        self._checksums: Dict[str, str] = {}

    def record_sent(self, data_id: str, data: Any) -> str:
        """记录发送的数据并生成校验和。"""
        checksum = self._compute_checksum(data)
        self._sent[data_id] = copy.deepcopy(data)
        self._checksums[data_id] = checksum
        return checksum

    def record_received(self, data_id: str, data: Any) -> None:
        """记录接收到的数据。"""
        self._received[data_id] = copy.deepcopy(data)

    def verify(self, data_id: str) -> bool:
        """验证数据完整性。

        Returns:
            数据是否一致
        """
        if data_id not in self._sent:
            return False
        if data_id not in self._received:
            return False
        sent_checksum = self._checksums[data_id]
        received_checksum = self._compute_checksum(self._received[data_id])
        return sent_checksum == received_checksum

    def verify_all(self) -> Dict[str, bool]:
        """验证所有已记录的数据。"""
        results: Dict[str, bool] = {}
        for data_id in self._sent:
            results[data_id] = self.verify(data_id)
        return results

    def get_diff(self, data_id: str) -> Optional[Dict[str, Tuple[Any, Any]]]:
        """获取发送和接收数据的差异。"""
        if data_id not in self._sent or data_id not in self._received:
            return None

        sent = self._sent[data_id]
        received = self._received[data_id]

        if not isinstance(sent, dict) or not isinstance(received, dict):
            return {"value": (sent, received)}

        diff: Dict[str, Tuple[Any, Any]] = {}
        all_keys = set(sent.keys()) | set(received.keys())
        for key in all_keys:
            sv = sent.get(key, "<MISSING>")
            rv = received.get(key, "<MISSING>")
            if sv != rv:
                diff[key] = (sv, rv)
        return diff if diff else None

    @staticmethod
    def _compute_checksum(data: Any) -> str:
        """计算数据校验和。"""
        serialized = str(data).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def clear(self) -> None:
        """清除所有记录。"""
        self._sent.clear()
        self._received.clear()
        self._checksums.clear()