"""
子系统集成错误层次结构。

提供跨子系统通信、协调和集成过程中使用的统一异常类型。

模块说明:
    本模块在 mca_core.errors 的基础上扩展，定义集成层的专属异常:
        - IntegrationError: 集成基础异常
        - CommunicationError: 子系统间通信失败
        - SubsystemUnavailableError: 子系统不可用
        - IntegrationTimeoutError: 集成操作超时
        - ProtocolError: 协议格式/版本错误
        - StateConflictError: 子系统状态冲突

所有集成异常均继承自 AppError，确保与现有错误处理机制兼容。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from mca_core.errors import AppError


class IntegrationError(AppError):
    """集成层基础异常。

    所有子系统集成相关异常的基类。

    Attributes:
        source_subsystem: 发起请求的子系统名称
        target_subsystem: 目标子系统名称
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        source_subsystem: Optional[str] = None,
        target_subsystem: Optional[str] = None,
    ) -> None:
        details = details or {}
        if source_subsystem:
            details["source_subsystem"] = source_subsystem
        if target_subsystem:
            details["target_subsystem"] = target_subsystem
        super().__init__(message, code or "INTEGRATION_ERROR", details)


class CommunicationError(IntegrationError):
    """子系统间通信失败。

    当两个子系统之间无法建立或维持通信时抛出。
    适用于网络错误、序列化失败、协议不匹配等场景。
    """

    def __init__(
        self,
        message: str,
        source_subsystem: Optional[str] = None,
        target_subsystem: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message,
            code="COMMUNICATION_ERROR",
            details=details,
            source_subsystem=source_subsystem,
            target_subsystem=target_subsystem,
        )


class SubsystemUnavailableError(IntegrationError):
    """子系统不可用。

    当目标子系统未初始化、已停止或处于错误状态时抛出。
    """

    def __init__(
        self,
        subsystem_name: str,
        current_state: Optional[str] = None,
    ) -> None:
        details = {"subsystem": subsystem_name}
        if current_state:
            details["current_state"] = current_state
        super().__init__(
            f"子系统 '{subsystem_name}' 当前不可用"
            + (f"（状态: {current_state}）" if current_state else ""),
            code="SUBSYSTEM_UNAVAILABLE",
            details=details,
            target_subsystem=subsystem_name,
        )


class IntegrationTimeoutError(IntegrationError):
    """集成操作超时。

    当子系统间请求在规定时间内未得到响应时抛出。
    """

    def __init__(
        self,
        operation: str,
        timeout_seconds: float,
        source_subsystem: Optional[str] = None,
        target_subsystem: Optional[str] = None,
    ) -> None:
        super().__init__(
            f"操作 '{operation}' 超时（{timeout_seconds:.1f}s）",
            code="INTEGRATION_TIMEOUT",
            details={
                "operation": operation,
                "timeout_seconds": timeout_seconds,
            },
            source_subsystem=source_subsystem,
            target_subsystem=target_subsystem,
        )


class ProtocolError(IntegrationError):
    """协议格式或版本不匹配。

    当子系统间使用的通信协议格式不一致时抛出。
    """

    def __init__(
        self,
        message: str,
        expected_version: Optional[str] = None,
        received_version: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if expected_version:
            details["expected_version"] = expected_version
        if received_version:
            details["received_version"] = received_version
        super().__init__(
            message,
            code="PROTOCOL_ERROR",
            details=details,
        )


class StateConflictError(IntegrationError):
    """子系统状态冲突。

    当请求的操作与目标子系统的当前状态不兼容时抛出。
    """

    def __init__(
        self,
        subsystem_name: str,
        expected_state: str,
        actual_state: str,
        operation: Optional[str] = None,
    ) -> None:
        details = {
            "subsystem": subsystem_name,
            "expected_state": expected_state,
            "actual_state": actual_state,
        }
        if operation:
            details["operation"] = operation
        super().__init__(
            f"子系统 '{subsystem_name}' 状态冲突: 期望 {expected_state}，实际 {actual_state}",
            code="STATE_CONFLICT",
            details=details,
            target_subsystem=subsystem_name,
        )