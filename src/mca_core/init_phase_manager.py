"""
初始化阶段管理器模块。

提供 InitializationPhaseManager 类，用于管理应用程序的初始化阶段和步骤。
通过显式声明依赖关系和阶段划分，确保初始化流程的可维护性和正确性。

主要组件:
    - InitializationPhase: 初始化阶段枚举
    - InitializationStep: 初始化步骤数据类
    - InitializationPhaseManager: 初始化阶段管理器

使用示例:
    manager = InitializationPhaseManager()
    manager.register_step(InitializationStep(
        name="init_services",
        phase=InitializationPhase.CORE_SERVICES,
        handler=self._init_services,
        dependencies=[],
        description="初始化服务层组件"
    ))
    manager.execute()
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class InitializationPhase(Enum):
    """初始化阶段枚举，定义初始化流程的逻辑阶段。"""

    INFRASTRUCTURE = "infrastructure"
    CORE_SERVICES = "core_services"
    DEPENDENCY_INJECTION = "di"
    EXTENSIONS = "extensions"
    FINALIZATION = "finalization"


@dataclass
class InitializationStep:
    """初始化步骤数据类，描述单个初始化步骤的元数据。"""

    name: str
    phase: InitializationPhase
    handler: Callable[[], None]
    dependencies: List[str] = field(default_factory=list)
    description: str = ""


class InitializationError(Exception):
    """初始化异常基类。"""


class CircularDependencyError(InitializationError):
    """循环依赖异常。"""


class MissingDependencyError(InitializationError):
    """缺失依赖异常。"""


class StepExecutionError(InitializationError):
    """步骤执行异常。"""


class InitializationPhaseManager:
    """初始化阶段管理器。

    负责注册初始化步骤、验证依赖关系、按阶段和拓扑顺序执行初始化流程。

    特性:
        - 阶段化执行：按预定义阶段顺序执行初始化步骤
        - 依赖验证：自动检测循环依赖和缺失依赖
        - 拓扑排序：在阶段内按依赖关系排序步骤
        - 执行跟踪：记录每个步骤的执行状态和时间
    """

    _PHASE_ORDER: List[InitializationPhase] = [
        InitializationPhase.INFRASTRUCTURE,
        InitializationPhase.CORE_SERVICES,
        InitializationPhase.DEPENDENCY_INJECTION,
        InitializationPhase.EXTENSIONS,
        InitializationPhase.FINALIZATION,
    ]

    def __init__(self) -> None:
        self._steps: Dict[str, InitializationStep] = {}
        self._executed_steps: List[str] = []
        self._callback_before_step: Optional[Callable[[str], None]] = None
        self._callback_after_step: Optional[Callable[[str], None]] = None
        self._callback_on_error: Optional[Callable[[str, Exception], None]] = None

    def register_step(self, step: InitializationStep) -> None:
        """注册初始化步骤。

        Args:
            step: 要注册的初始化步骤

        Raises:
            ValueError: 如果步骤名称为空或已注册
        """
        if not step.name:
            raise ValueError("步骤名称不能为空")
        if step.name in self._steps:
            raise ValueError(f"步骤 '{step.name}' 已注册")
        self._steps[step.name] = step
        logger.debug("注册初始化步骤: %s (阶段: %s)", step.name, step.phase.value)

    def register_steps(self, steps: List[InitializationStep]) -> None:
        """批量注册初始化步骤。

        Args:
            steps: 要注册的初始化步骤列表
        """
        for step in steps:
            self.register_step(step)

    def set_callbacks(
        self,
        before_step: Optional[Callable[[str], None]] = None,
        after_step: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str, Exception], None]] = None,
    ) -> None:
        """设置初始化过程中的回调函数。

        Args:
            before_step: 每个步骤执行前调用，参数为步骤名称
            after_step: 每个步骤执行后调用，参数为步骤名称
            on_error: 步骤执行出错时调用，参数为步骤名称和异常
        """
        self._callback_before_step = before_step
        self._callback_after_step = after_step
        self._callback_on_error = on_error

    def validate_dependencies(self) -> List[str]:
        """验证所有注册步骤的依赖关系。

        Returns:
            错误信息列表，如果没有错误则为空列表
        """
        errors: List[str] = []
        phase_order_index = {
            phase: index for index, phase in enumerate(self._PHASE_ORDER)
        }

        for step_name, step in self._steps.items():
            for dep in step.dependencies:
                if dep not in self._steps:
                    errors.append(
                        f"步骤 '{step_name}' 依赖不存在的步骤 '{dep}'"
                    )
                    continue

                dep_step = self._steps[dep]
                step_phase_index = phase_order_index.get(step.phase)
                dep_phase_index = phase_order_index.get(dep_step.phase)
                if (
                    step_phase_index is not None
                    and dep_phase_index is not None
                    and dep_phase_index > step_phase_index
                ):
                    errors.append(
                        f"步骤 '{step_name}' 跨阶段依赖顺序非法: "
                        f"依赖 '{dep}' 位于更晚阶段 "
                        f"'{dep_step.phase.value}'，当前阶段为 '{step.phase.value}'"
                    )

        try:
            self._detect_circular_dependencies()
        except CircularDependencyError as e:
            errors.append(str(e))

        return errors

    def _detect_circular_dependencies(self) -> None:
        """检测所有步骤中的循环依赖。

        Raises:
            CircularDependencyError: 如果检测到循环依赖
        """
        for step_name in self._steps:
            visited: Set[str] = set()
            in_stack: Set[str] = set()
            self._dfs_check_cycle(step_name, visited, in_stack, [])

    def _dfs_check_cycle(
        self,
        current: str,
        visited: Set[str],
        in_stack: Set[str],
        path: List[str],
    ) -> None:
        """使用 DFS 检测循环依赖。

        Args:
            current: 当前检查的步骤名称
            visited: 已访问的步骤集合
            in_stack: 当前递归栈中的步骤集合
            path: 当前依赖路径

        Raises:
            CircularDependencyError: 如果检测到循环依赖
        """
        if current in in_stack:
            cycle = path[path.index(current):]
            cycle.append(current)
            raise CircularDependencyError(
                f"检测到循环依赖: {' -> '.join(cycle)}"
            )
        if current in visited:
            return
        if current not in self._steps:
            return

        visited.add(current)
        in_stack.add(current)
        path.append(current)

        current_step = self._steps[current]
        for dep in current_step.dependencies:
            self._dfs_check_cycle(dep, visited, in_stack, path)

        path.pop()
        in_stack.remove(current)

    def get_execution_order(self) -> List[InitializationStep]:
        """获取所有步骤的拓扑排序执行顺序。

        先按阶段分组，再在阶段内进行拓扑排序。

        Returns:
            按执行顺序排列的初始化步骤列表

        Raises:
            CircularDependencyError: 如果存在循环依赖
            MissingDependencyError: 如果阶段内存在无法满足的跨阶段依赖
        """
        self._detect_circular_dependencies()

        phase_groups: Dict[InitializationPhase, List[InitializationStep]] = {
            phase: [] for phase in self._PHASE_ORDER
        }

        for step in self._steps.values():
            if step.phase in phase_groups:
                phase_groups[step.phase].append(step)

        execution_order: List[InitializationStep] = []
        for phase in self._PHASE_ORDER:
            phase_steps = phase_groups[phase]
            if not phase_steps:
                continue
            sorted_steps = self._topological_sort(phase_steps)
            execution_order.extend(sorted_steps)

        return execution_order

    def _topological_sort(
        self, steps: List[InitializationStep]
    ) -> List[InitializationStep]:
        """对同阶段内的步骤进行拓扑排序（Kahn 算法）。

        Args:
            steps: 同一阶段内的步骤列表

        Returns:
            拓扑排序后的步骤列表

        Raises:
            CircularDependencyError: 如果阶段内存在循环依赖
        """
        step_map = {step.name: step for step in steps}
        in_degree: Dict[str, int] = {step.name: 0 for step in steps}
        graph: Dict[str, List[str]] = {step.name: [] for step in steps}

        for step in steps:
            for dep in step.dependencies:
                if dep in step_map:
                    graph[dep].append(step.name)
                    in_degree[step.name] += 1

        queue: deque[str] = deque(
            name for name, degree in in_degree.items() if degree == 0
        )
        result: List[InitializationStep] = []

        while queue:
            current = queue.popleft()
            result.append(step_map[current])
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(steps):
            unfinished = [n for n, d in in_degree.items() if d > 0]
            raise CircularDependencyError(
                f"阶段内存在无法解析的依赖: {', '.join(unfinished)}"
            )

        return result

    def execute(self) -> None:
        """执行完整的初始化流程。

        依次执行:
        1. 依赖关系验证
        2. 计算执行顺序
        3. 按顺序执行每个步骤

        Raises:
            MissingDependencyError: 依赖关系验证失败
            CircularDependencyError: 存在循环依赖
            StepExecutionError: 步骤执行失败
        """
        errors = self.validate_dependencies()
        if errors:
            raise MissingDependencyError(
                f"依赖验证失败 ({len(errors)} 个错误): {'; '.join(errors)}"
            )

        execution_order = self.get_execution_order()

        logger.info(
            "开始执行初始化流程，共 %d 个阶段，%d 个步骤",
            len({s.phase for s in execution_order}),
            len(execution_order),
        )

        for step in execution_order:
            self._execute_step(step)

        self._executed_steps = [s.name for s in execution_order]
        logger.info("初始化流程完成")

    def _execute_step(self, step: InitializationStep) -> None:
        """执行单个初始化步骤。

        Args:
            step: 要执行的初始化步骤

        Raises:
            StepExecutionError: 步骤执行失败
        """
        logger.info(
            "[%s] 执行步骤: %s - %s",
            step.phase.value,
            step.name,
            step.description,
        )

        if self._callback_before_step:
            try:
                self._callback_before_step(step.name)
            except Exception:
                pass

        try:
            step.handler()
        except Exception as e:
            if self._callback_on_error:
                try:
                    self._callback_on_error(step.name, e)
                except Exception:
                    pass
            raise StepExecutionError(
                f"初始化步骤 '{step.name}' 执行失败: {e}"
            ) from e

        if self._callback_after_step:
            try:
                self._callback_after_step(step.name)
            except Exception:
                pass

    def get_step(self, name: str) -> Optional[InitializationStep]:
        """获取指定名称的步骤。

        Args:
            name: 步骤名称

        Returns:
            步骤对象，如果不存在则返回 None
        """
        return self._steps.get(name)

    def get_executed_steps(self) -> List[str]:
        """获取已执行步骤的名称列表。

        Returns:
            已执行步骤名称列表
        """
        return list(self._executed_steps)

    def get_steps_by_phase(
        self, phase: InitializationPhase
    ) -> List[InitializationStep]:
        """获取指定阶段的所有步骤。

        Args:
            phase: 初始化阶段

        Returns:
            该阶段的步骤列表
        """
        return [s for s in self._steps.values() if s.phase == phase]

    def clear(self) -> None:
        """清除所有注册的步骤和执行记录。"""
        self._steps.clear()
        self._executed_steps.clear()
