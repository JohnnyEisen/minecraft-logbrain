"""DLC（可下载内容）基类模块。

定义 DLC 插件的基类和接口约定。

v2.0.0: 增加可选 DI 注入支持 (config / audit / event_bus)，
       版本号统一引用 brain_system.__version__。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .models import DLCManifest, DLCState

if TYPE_CHECKING:
    from .core import BrainCore


class BrainDLC:
    """DLC 基类。

    子类约定：
    - 必须实现 get_manifest() 返回 DLC 元信息
    - 可选实现 _initialize() 进行初始化
    - 可选实现 shutdown() 进行清理
    - 可选实现 provide_computational_units() 提供计算单元
    - 可选实现 on_config_changed() 响应配置热更新

    DI 支持：
    - 子类可通过 inject() 注入 config / audit / event_bus
    - 也可在 _initialize() 中通过 self._config / self._audit / self._event_bus 访问

    生命周期状态机:
        UNLOADED -> LOADED -> INITIALIZED -> ACTIVE
                                             |-> SUSPENDED -> ACTIVE
                        DISABLED <- ACTIVE/SUSPENDED/INITIALIZED
                        FAILED (任何状态转入)

    Attributes:
        brain: 关联的 BrainCore 实例。
        manifest: DLC 清单元数据。
        state: 当前生命周期状态 (DLCState)。
    """

    def __init__(self, brain: BrainCore) -> None:
        """初始化 DLC。

        Args:
            brain: BrainCore 实例。
        """
        self.brain = brain
        self.manifest = self.get_manifest()
        self._initialized: bool = False
        self._state: DLCState = DLCState.UNLOADED
        self._config: Optional[Any] = None
        self._audit: Optional[Any] = None
        self._event_bus: Optional[Any] = None

    @property
    def state(self) -> DLCState:
        """获取当前生命周期状态。"""
        return self._state

    @property
    def enabled(self) -> bool:
        """DLC 是否处于可用状态（非 DISABLED/FAILED/UNLOADED）。"""
        return self._state not in (DLCState.DISABLED, DLCState.FAILED, DLCState.UNLOADED)

    def inject(
        self,
        *,
        config: Optional[Any] = None,
        audit: Optional[Any] = None,
        event_bus: Optional[Any] = None,
    ) -> None:
        """注入基础设施依赖。

        Args:
            config: ConfigManager 实例
            audit: AuditTrail 实例
            event_bus: EventBus 实例
        """
        if config is not None:
            self._config = config
        if audit is not None:
            self._audit = audit
        if event_bus is not None:
            self._event_bus = event_bus

    def get_manifest(self) -> DLCManifest:
        """获取 DLC 清单。

        Returns:
            DLC 元数据对象。

        Raises:
            NotImplementedError: 子类必须实现此方法。
        """
        raise NotImplementedError("子类必须实现 get_manifest 方法")

    def initialize(self) -> None:
        """初始化 DLC。"""
        if self._initialized:
            return
        self._state = DLCState.LOADING
        try:
            self._initialize()
        except Exception:
            self._state = DLCState.FAILED
            raise
        self._initialized = True
        self._state = DLCState.ACTIVE
        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PLUGIN_LOADED,
                    detail=f"DLC {self.manifest.name} 已初始化",
                    component=self.manifest.name,
                    metadata={"version": self.manifest.version, "dlc_type": self.manifest.dlc_type.value},
                )
            except Exception:
                pass

    def _initialize(self) -> None:
        """子类实现的初始化逻辑。"""
        return

    def shutdown(self) -> None:
        """关闭 DLC，释放资源。

        调用顺序:
        1. _pre_shutdown() - 子类清理前钩子
        2. 审计记录
        3. 状态更新为 UNLOADED
        4. _post_shutdown() - 子类清理后钩子
        """
        self._pre_shutdown()
        if self._audit is not None and self._initialized:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PLUGIN_UNLOADED,
                    detail=f"DLC {self.manifest.name} 已关闭",
                    component=self.manifest.name,
                )
            except Exception:
                pass
        self._initialized = False
        self._state = DLCState.UNLOADED
        self._post_shutdown()

    def _pre_shutdown(self) -> None:
        """关闭前钩子。子类可重写以在状态更新前清理资源。"""
        return

    def _post_shutdown(self) -> None:
        """关闭后钩子。子类可重写以在状态更新后执行最终清理。"""
        return

    def enable(self) -> None:
        """启用 DLC，从 DISABLED 或 FAILED 恢复到 ACTIVE 并重新初始化。"""
        if self._state in (DLCState.DISABLED, DLCState.FAILED):
            self._initialized = False
            self._state = DLCState.UNLOADED
            self.initialize()

    def disable(self) -> None:
        """禁用 DLC，释放资源并标记为 DISABLED。

        调用 _pre_shutdown() 和 _post_shutdown() 释放 GPU/内存资源。
        与 shutdown() 的区别：状态为 DISABLED 而非 UNLOADED，可被重新 enable。
        """
        if self._state in (DLCState.ACTIVE, DLCState.SUSPENDED, DLCState.INITIALIZED):
            self._pre_shutdown()
            self._post_shutdown()
            self._initialized = False
            self._state = DLCState.DISABLED

    def suspend(self) -> None:
        """挂起 DLC（暂停活动但保留已初始化状态）。"""
        if self._state == DLCState.ACTIVE:
            self._suspend_internal()
            self._state = DLCState.SUSPENDED

    def resume(self) -> None:
        """恢复挂起的 DLC。"""
        if self._state == DLCState.SUSPENDED:
            self._resume_internal()
            self._state = DLCState.ACTIVE

    def _suspend_internal(self) -> None:
        """子类可重写的挂起逻辑。"""
        return

    def _resume_internal(self) -> None:
        """子类可重写的恢复逻辑。"""
        return

    def on_config_changed(self, new_config: dict[str, Any]) -> None:
        """配置热更新回调。

        当 BrainCore 检测到配置文件变更时调用此方法。
        子类可重写以响应配置变更。

        Args:
            new_config: 更新后的配置字典。
        """
        return

    def provide_computational_units(self) -> dict[str, Any]:
        """提供的计算单元。

        Returns:
            计算单元名称到实例的映射。
        """
        return {}