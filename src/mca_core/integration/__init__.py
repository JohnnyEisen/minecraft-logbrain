"""
MCA 子系统集成框架。

提供统一的子系统间通信协议、错误处理、健康监控和契约定义。

核心组件:
    - IntegrationBus: 统一子系统间通信总线（请求/响应 + 事件）
    - IntegrationError: 集成层异常层次结构
    - ISubsystem: 子系统必须实现的标准接口
    - HealthMonitor: 周期性健康检查引擎
    - SubsystemHealthRegistry: 健康状态注册表
    - BottleneckDetector: 性能瓶颈检测
    - IntegrationMessage: 子系统间消息标准格式
    - IntegrationContract: 集成契约元数据

用法:
    from mca_core.integration import IntegrationBus, ISubsystem, HealthMonitor

    bus = IntegrationBus(name="main")
    bus.register(my_subsystem)

    monitor = HealthMonitor(interval_seconds=10.0)
    monitor.set_check_callback(bus.health_check_all)
    monitor.start()
"""
from mca_core.integration.bus import (
    IntegrationBus,
    RequestMetrics,
    RoutingEntry,
)
from mca_core.integration.contract import (
    ISubsystem,
    IntegrationContract,
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
from mca_core.integration.monitor import (
    BottleneckDetector,
    BottleneckRecord,
    HealthLevel,
    HealthMonitor,
    HealthStatus,
    SubsystemHealthRegistry,
)
from mca_core.integration.testing import (
    CapturedMessage,
    DataIntegrityChecker,
    IntegrationTestCase,
    MessageSpy,
    MockSubsystem,
)
from mca_core.integration.coordinator import (
    ContractRegistry,
    ContractValidator,
    IntegrationCoordinator,
    StateSynchronizer,
    ValidationResult,
)

__all__ = [
    "IntegrationBus",
    "RequestMetrics",
    "RoutingEntry",
    "ISubsystem",
    "IntegrationContract",
    "IntegrationMessage",
    "MessageDirection",
    "MessagePriority",
    "SubsystemLifecycle",
    "CommunicationError",
    "IntegrationError",
    "IntegrationTimeoutError",
    "ProtocolError",
    "StateConflictError",
    "SubsystemUnavailableError",
    "BottleneckDetector",
    "BottleneckRecord",
    "HealthLevel",
    "HealthMonitor",
    "HealthStatus",
    "SubsystemHealthRegistry",
    "CapturedMessage",
    "DataIntegrityChecker",
    "IntegrationTestCase",
    "MessageSpy",
    "MockSubsystem",
    "ContractRegistry",
    "ContractValidator",
    "IntegrationCoordinator",
    "StateSynchronizer",
    "ValidationResult",
]