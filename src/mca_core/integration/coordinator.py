"""
子系统合约验证与同步协调。

提供合约合规检查、状态同步和集成契约注册表。

模块说明:
    - ContractValidator: 验证子系统是否满足合约要求
    - ContractRegistry: 集成契约注册表
    - StateSynchronizer: 跨子系统状态同步器
    - IntegrationCoordinator: 集成协调器（编排多子系统工作流）
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from mca_core.integration.contract import (
    ISubsystem,
    IntegrationContract,
    IntegrationMessage,
    MessageDirection,
    SubsystemLifecycle,
)
from mca_core.integration.errors import (
    IntegrationError,
    ProtocolError,
    StateConflictError,
    SubsystemUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """合约验证结果。

    Attributes:
        subsystem_name: 子系统名称
        contract_id: 合约 ID
        passed: 是否通过
        violations: 违规项列表
        warnings: 警告项列表
        checked_at: 验证时间
    """

    subsystem_name: str
    contract_id: str = ""
    passed: bool = True
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_name": self.subsystem_name,
            "contract_id": self.contract_id,
            "passed": self.passed,
            "violations": self.violations,
            "warnings": self.warnings,
            "checked_at": self.checked_at.isoformat(),
        }


class ContractValidator:
    """子系统合约验证器。

    验证子系统是否满足 IntegrationContract 中定义的要求。
    """

    def validate(
        self,
        subsystem: ISubsystem,
        contract: IntegrationContract,
    ) -> ValidationResult:
        """验证子系统是否满足合约。

        Args:
            subsystem: 要验证的子系统
            contract: 集成契约

        Returns:
            ValidationResult
        """
        violations: List[str] = []
        warnings: List[str] = []

        if not subsystem.name:
            violations.append("子系统名称为空")

        if not subsystem.version:
            violations.append("子系统版本为空")

        try:
            state = subsystem.state
            if not isinstance(state, SubsystemLifecycle):
                violations.append(
                    f"状态类型错误: 期望 SubsystemLifecycle, 实际 {type(state).__name__}"
                )
        except Exception as e:
            violations.append(f"无法获取子系统状态: {e}")

        try:
            supported = subsystem.supported_operations()
            if not isinstance(supported, list):
                violations.append(
                    f"supported_operations 应返回 list, 实际 {type(supported).__name__}"
                )
            else:
                missing_ops = set(contract.operations) - set(supported)
                if missing_ops:
                    violations.append(
                        f"缺失合约操作: {', '.join(missing_ops)}"
                    )
        except Exception as e:
            violations.append(f"无法获取支持的操作: {e}")

        try:
            status = subsystem.status()
            if not isinstance(status, dict):
                violations.append(
                    f"status 应返回 dict, 实际 {type(status).__name__}"
                )
        except Exception as e:
            violations.append(f"无法获取状态信息: {e}")

        try:
            healthy = subsystem.health_check()
            if not isinstance(healthy, bool):
                violations.append(
                    f"health_check 应返回 bool, 实际 {type(healthy).__name__}"
                )
            elif not healthy:
                warnings.append("子系统健康检查未通过")
        except Exception as e:
            violations.append(f"健康检查失败: {e}")

        can_handle = True
        try:
            subsystem.handle_message(IntegrationMessage(operation="__validate__"))
        except NotImplementedError:
            can_handle = False
        except Exception:
            pass

        if not can_handle:
            warnings.append("子系统未实现消息处理（handle_message 抛出 NotImplementedError）")

        return ValidationResult(
            subsystem_name=subsystem.name,
            contract_id=contract.contract_id,
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )


class ContractRegistry:
    """集成契约注册表。

    管理系统中所有已注册的集成契约。
    """

    def __init__(self) -> None:
        self._contracts: Dict[str, IntegrationContract] = {}
        self._validations: Dict[str, List[ValidationResult]] = {}
        self._lock = threading.Lock()

    def register(self, contract: IntegrationContract) -> None:
        """注册集成契约。"""
        with self._lock:
            self._contracts[contract.contract_id] = contract
        logger.info(
            "契约已注册: %s [%s -> %s]",
            contract.contract_id,
            contract.source,
            contract.target,
        )

    def get(self, contract_id: str) -> Optional[IntegrationContract]:
        """获取契约。"""
        with self._lock:
            return self._contracts.get(contract_id)

    def list_all(self) -> List[IntegrationContract]:
        """列出所有契约。"""
        with self._lock:
            return list(self._contracts.values())

    def find_by_subsystem(self, name: str) -> List[IntegrationContract]:
        """查找涉及指定子系统的所有契约。"""
        with self._lock:
            return [
                c for c in self._contracts.values()
                if c.source == name or c.target == name
            ]

    def validate_all(
        self,
        subsystems: Dict[str, ISubsystem],
        validator: Optional[ContractValidator] = None,
    ) -> Dict[str, List[ValidationResult]]:
        """验证所有子系统是否满足各自的合约。

        Args:
            subsystems: 名称到子系统实例的映射
            validator: 可选的验证器

        Returns:
            子系统名称到验证结果列表的映射
        """
        v = validator or ContractValidator()
        results: Dict[str, List[ValidationResult]] = {}

        with self._lock:
            for contract in self._contracts.values():
                for target_name in (contract.source, contract.target):
                    if target_name not in subsystems:
                        if target_name not in results:
                            results[target_name] = []
                        results[target_name].append(
                            ValidationResult(
                                subsystem_name=target_name,
                                contract_id=contract.contract_id,
                                passed=False,
                                violations=[f"子系统 '{target_name}' 未注册"],
                            )
                        )
                        continue

                    sub = subsystems[target_name]
                    result = v.validate(sub, contract)
                    if target_name not in results:
                        results[target_name] = []
                    results[target_name].append(result)

        return results


class StateSynchronizer:
    """跨子系统状态同步器。

    负责在子系统间同步状态变更，确保协调一致。
    """

    def __init__(self, sync_timeout: float = 5.0) -> None:
        self._timeout = sync_timeout
        self._sync_state: Dict[str, Dict[str, Any]] = {}
        self._callbacks: Dict[str, List[Callable[[str, Dict[str, Any]], None]]] = {}
        self._lock = threading.Lock()

    def update_state(self, subsystem_name: str, state: Dict[str, Any]) -> None:
        """更新子系统状态并通知监听者。

        Args:
            subsystem_name: 子系统名称
            state: 状态数据
        """
        with self._lock:
            old_state = self._sync_state.get(subsystem_name, {})
            self._sync_state[subsystem_name] = state

        callbacks = self._callbacks.get(subsystem_name, [])
        for callback in callbacks:
            try:
                callback(subsystem_name, state)
            except Exception as e:
                logger.warning(
                    "状态同步回调失败 (%s): %s",
                    subsystem_name,
                    e,
                )

    def get_state(self, subsystem_name: str) -> Optional[Dict[str, Any]]:
        """获取子系统同步状态。"""
        with self._lock:
            return self._sync_state.get(subsystem_name)

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有子系统同步状态。"""
        with self._lock:
            return dict(self._sync_state)

    def subscribe(
        self,
        subsystem_name: str,
        callback: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """订阅子系统状态变更。

        Args:
            subsystem_name: 子系统名称
            callback: 状态变更回调 (subsystem_name, new_state)
        """
        with self._lock:
            if subsystem_name not in self._callbacks:
                self._callbacks[subsystem_name] = []
            self._callbacks[subsystem_name].append(callback)

    def unsubscribe(
        self,
        subsystem_name: str,
        callback: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """取消订阅。"""
        with self._lock:
            if subsystem_name in self._callbacks:
                try:
                    self._callbacks[subsystem_name].remove(callback)
                except ValueError:
                    pass

    def wait_for_state(
        self,
        subsystem_name: str,
        key: str,
        expected_value: Any,
        timeout: Optional[float] = None,
    ) -> bool:
        """等待子系统状态达到预期值。

        Args:
            subsystem_name: 子系统名称
            key: 状态键
            expected_value: 预期值
            timeout: 超时时间（秒）

        Returns:
            是否在超时前达到预期状态
        """
        deadline = time.time() + (timeout or self._timeout)

        while time.time() < deadline:
            state = self.get_state(subsystem_name)
            if state and state.get(key) == expected_value:
                return True
            time.sleep(0.05)
        return False


class IntegrationCoordinator:
    """集成协调器。

    编排多子系统工作流，确保操作按正确顺序和依赖关系执行。

    支持:
        - 顺序工作流: 步骤按序执行
        - 健康前置检查: 执行前验证所有依赖子系统
        - 状态同步: 工作流执行期间的状态更新
    """

    def __init__(self) -> None:
        self._synchronizer = StateSynchronizer()
        self._registry = ContractRegistry()

    @property
    def synchronizer(self) -> StateSynchronizer:
        return self._synchronizer

    @property
    def registry(self) -> ContractRegistry:
        return self._registry

    def verify_dependencies(
        self,
        subsystems: Dict[str, ISubsystem],
        required: List[str],
    ) -> Tuple[bool, List[str]]:
        """验证所有必需的子系统是否可用且健康。

        Args:
            subsystems: 可用子系统映射
            required: 必需的子系统名称列表

        Returns:
            (全部可用, 不可用的子系统列表)
        """
        unavailable: List[str] = []
        for name in required:
            sub = subsystems.get(name)
            if sub is None:
                unavailable.append(f"{name} (未注册)")
                continue
            try:
                if sub.state not in (
                    SubsystemLifecycle.RUNNING,
                    SubsystemLifecycle.DEGRADED,
                ):
                    unavailable.append(f"{name} (状态: {sub.state.value})")
                elif not sub.health_check():
                    unavailable.append(f"{name} (不健康)")
            except Exception as e:
                unavailable.append(f"{name} (异常: {e})")

        return len(unavailable) == 0, unavailable

    def execute_sequential_workflow(
        self,
        steps: List[Tuple[str, str, str]],
        bus: Any,
        source: str = "coordinator",
    ) -> Dict[str, Any]:
        """执行顺序工作流。

        Args:
            steps: 步骤列表，每项为 (target_subsystem, operation, description)
            bus: IntegrationBus 实例
            source: 请求源

        Returns:
            {"success": bool, "steps": [...]}
        """
        results: List[Dict[str, Any]] = []
        all_success = True

        for i, (target, operation, description) in enumerate(steps):
            step_result = {
                "step": i + 1,
                "target": target,
                "operation": operation,
                "description": description,
                "success": False,
                "response": None,
                "error": None,
            }
            try:
                response = bus.request(source, target, operation)
                step_result["success"] = True
                step_result["response"] = {
                    "operation": response.operation,
                    "payload": response.payload,
                }
            except Exception as e:
                step_result["error"] = str(e)
                all_success = False

            results.append(step_result)

        return {"success": all_success, "steps": results}

    def shutdown_sequence(
        self,
        bus: Any,
        order: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """按顺序关闭子系统。

        Args:
            bus: IntegrationBus 实例
            order: 关闭顺序（子系统名称列表），None 则反序关闭

        Returns:
            关闭结果
        """
        if order is None:
            registered = bus.list_subsystems()
            order = [s["name"] for s in reversed(registered)]

        results: Dict[str, Any] = {"order": order, "results": {}}
        for name in order:
            try:
                sub = bus.get_subsystem(name)
                if sub:
                    sub.shutdown()
                    results["results"][name] = "stopped"
                else:
                    results["results"][name] = "not_found"
            except Exception as e:
                results["results"][name] = f"error: {e}"
        return results