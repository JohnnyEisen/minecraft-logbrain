"""
子系统集成契约定义。

定义子系统间交互的标准化接口协议、消息格式和合同规范。

模块说明:
    本模块定义:
        - ISubsystem: 子系统必须实现的标准接口
        - IntegrationMessage: 子系统间消息标准格式
        - IntegrationContract: 集成契约元数据
        - MessagePriority: 消息优先级枚举
        - MessageDirection: 消息流向（请求/响应/事件）
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generic, Optional, TypeVar

T = TypeVar("T")


class MessagePriority(Enum):
    """消息优先级。"""
    LOW = 1
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


class MessageDirection(Enum):
    """消息流向。"""
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"


class SubsystemLifecycle(str, Enum):
    """子系统生命周期状态。"""
    UNINITIALIZED = "uninitialized"
    INITIALIZED = "initialized"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class IntegrationMessage(Generic[T]):
    """子系统间消息标准格式。

    定义跨子系统通信的统一消息信封。

    Attributes:
        message_id: 消息唯一标识
        direction: 消息流向
        source: 发送方子系统名称
        target: 接收方子系统名称
        operation: 操作名称
        payload: 消息负载
        priority: 优先级
        correlation_id: 关联 ID（用于请求-响应关联）
        timestamp: 时间戳
        protocol_version: 协议版本号
    """

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    direction: MessageDirection = MessageDirection.REQUEST
    source: str = ""
    target: str = ""
    operation: str = ""
    payload: Optional[T] = None
    priority: MessagePriority = MessagePriority.NORMAL
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    protocol_version: str = "1.0"

    def to_envelope(self) -> Dict[str, Any]:
        """转换为可序列化的信封字典。"""
        return {
            "message_id": self.message_id,
            "direction": self.direction.value,
            "source": self.source,
            "target": self.target,
            "operation": self.operation,
            "priority": self.priority.value,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "protocol_version": self.protocol_version,
        }

    @classmethod
    def from_envelope(
        cls,
        envelope: Dict[str, Any],
        payload: Optional[T] = None,
    ) -> "IntegrationMessage[T]":
        """从信封字典还原消息。"""
        return cls(
            message_id=envelope.get("message_id", ""),
            direction=MessageDirection(envelope.get("direction", "request")),
            source=envelope.get("source", ""),
            target=envelope.get("target", ""),
            operation=envelope.get("operation", ""),
            payload=payload,
            priority=MessagePriority(envelope.get("priority", 5)),
            correlation_id=envelope.get("correlation_id"),
            timestamp=datetime.fromisoformat(
                envelope.get("timestamp", datetime.now().isoformat())
            ),
            protocol_version=envelope.get("protocol_version", "1.0"),
        )


@dataclass
class IntegrationContract:
    """集成契约元数据。

    描述两个子系统之间的集成契约。

    Attributes:
        contract_id: 契约唯一标识
        source: 源子系统
        target: 目标子系统
        operations: 支持的操作列表
        protocol_version: 协议版本
        description: 契约描述
        created_at: 创建时间
    """

    contract_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    source: str = ""
    target: str = ""
    operations: list[str] = field(default_factory=list)
    protocol_version: str = "1.0"
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "source": self.source,
            "target": self.target,
            "operations": self.operations,
            "protocol_version": self.protocol_version,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }


class ISubsystem(ABC):
    """子系统标准接口。

    所有 MCA 子系统必须实现此接口，确保统一的集成能力。

    必须实现的方法:
        - name: 子系统名称
        - version: 子系统版本
        - state: 当前生命周期状态
        - initialize(): 初始化子系统
        - startup(): 启动子系统
        - shutdown(): 停止子系统
        - health_check(): 健康检查
        - status(): 获取完整状态快照

    可选覆盖:
        - supported_operations(): 返回支持的操作列表
        - handle_message(): 处理收到的集成消息
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """子系统名称。"""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """子系统版本号。"""
        ...

    @property
    @abstractmethod
    def state(self) -> SubsystemLifecycle:
        """当前生命周期状态。"""
        ...

    @abstractmethod
    def initialize(self) -> None:
        """初始化子系统资源。

        Raises:
            IntegrationError: 初始化失败
        """
        ...

    @abstractmethod
    def startup(self) -> None:
        """启动子系统。

        Raises:
            IntegrationError: 启动失败
        """
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """停止子系统，释放资源。"""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查。

        Returns:
            True 表示正常，False 表示异常
        """
        ...

    @abstractmethod
    def status(self) -> Dict[str, Any]:
        """获取子系统完整状态快照。

        Returns:
            包含状态信息的字典
        """
        ...

    def supported_operations(self) -> list[str]:
        """返回本子系统支持的操作列表。"""
        return []

    def handle_message(
        self,
        message: IntegrationMessage[Any],
    ) -> IntegrationMessage[Any]:
        """处理收到的集成消息。

        Args:
            message: 收到的消息

        Returns:
            响应消息

        Raises:
            NotImplementedError: 子类未实现消息处理
        """
        raise NotImplementedError(
            f"子系统 '{self.name}' 不支持消息处理"
        )