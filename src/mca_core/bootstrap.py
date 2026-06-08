"""
统一应用启动器 — System Bootstrap

全系统唯一入口，职责：
    Phase 1: 初始化基础设施（DI 容器、配置、日志、事件总线、审计）
    Phase 2: 注册核心服务（系统服务、数据库、集成总线）
    Phase 3: 创建功能组件（BrainCore、DiagnosticEngine、PatchManager、Dashboard）
    Phase 4: 装配子系统（集成总线注册、事件订阅）
    Phase 5: 启动运行（健康检查、生命周期回调）

架构原则：
    - 所有组件通过 DIContainer 注入，禁止直接 new
    - 配置通过 ConfigManager 统一读取，禁止硬编码
    - 操作通过 AuditTrail 记录，禁止无日志状态变更
    - 组件间通信通过 IntegrationBus（请求/响应）或 EventBus（事件）
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Type

from config.config_manager import ConfigManager, DictConfigSource, FileConfigSource
from config.constants import CONFIG_FILE, ensure_app_dirs
from mca_core.audit import AuditTrail, OperationType
from mca_core.di import DIContainer, ServiceLifetime
from mca_core.events import AnalysisEvent, EventBus, EventTypes
from mca_core.integration.bus import IntegrationBus
import os as _os

logger = logging.getLogger(__name__)


class AppPhase(Enum):
    """应用启动阶段。"""
    INIT = auto()
    SERVICES = auto()
    COMPONENTS = auto()
    ASSEMBLY = auto()
    RUNNING = auto()
    SHUTDOWN = auto()


@dataclass
class AppContext:
    """应用全局上下文 — 持有所有核心依赖。

    Attributes:
        container: DI 容器
        config: 配置管理器
        event_bus: 事件总线
        audit: 审计追踪
        integration_bus: 集成总线
        brain: BrainCore 实例
        phase: 当前启动阶段
        started_at: 启动时间
        metadata: 扩展元数据
    """
    container: DIContainer
    config: ConfigManager
    event_bus: EventBus
    audit: AuditTrail
    integration_bus: IntegrationBus
    brain: Any = None
    phase: AppPhase = AppPhase.INIT
    started_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AppBootstrap:
    """统一应用启动器。

    管理从初始化到关闭的完整生命周期。

    使用方式:
        bootstrap = AppBootstrap()
        ctx = bootstrap.initialize()
        ctx = bootstrap.register_defaults(ctx)
        ctx = bootstrap.create_components(ctx)
        bootstrap.start_services(ctx)

        # 应用运行期间...
        # ctx.container.resolve(SomeService)

        bootstrap.shutdown(ctx)

    快捷一键启动:
        ctx = AppBootstrap.create()
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        "app.name": "MCA Brain System",
        "app.env": "production",
        "ui.theme": "dark",
        "ui.scroll_sensitivity": 6,
        "engine.max_workers": 8,
        "engine.detector_timeout": 15.0,
        "engine.cache_size": 128,
        "engine.cache_ttl": 600.0,
        "patch.scan_directory": "./patches",
        "patch.max_retries": 3,
        "patch.auto_monitor": True,
        "monitor.interval_seconds": 5.0,
        "monitor.snapshot_interval": 30.0,
        "monitor.alert_cooldown": 60.0,
        "monitor.max_response_time_ms": 500.0,
        "monitor.min_success_rate": 0.95,
        "monitor.max_false_positive_rate": 0.05,
        "monitor.max_idle_seconds": 300.0,
        "integration.default_timeout": 30.0,
        "security.rate_limit": 100,
        "security.max_file_size": 104857600,
    }

    def __init__(self) -> None:
        self._container: Optional[DIContainer] = None
        self._config: Optional[ConfigManager] = None
        self._event_bus: Optional[EventBus] = None
        self._audit: Optional[AuditTrail] = None
        self._integration_bus: Optional[IntegrationBus] = None
        self._ctx: Optional[AppContext] = None
        self._lock = threading.Lock()
        self._shutdown_hooks: List[Callable[[], None]] = []
        self._diagnostic_engine: Any = None
        self._patch_manager: Any = None
        self._dashboard: Any = None
        self._system_service: Any = None
        self._database_manager: Any = None

    def initialize(self, config_path: Optional[str] = None) -> AppContext:
        """Phase 1: 初始化基础设施。"""
        with self._lock:
            ensure_app_dirs()

            self._config = ConfigManager()
            self._config.add_source(DictConfigSource("defaults", self.DEFAULT_CONFIG, priority=0))
            if config_path:
                self._config.add_source(FileConfigSource(config_path, priority=10))
            elif CONFIG_FILE and _os.path.exists(CONFIG_FILE):
                self._config.add_source(FileConfigSource(CONFIG_FILE, priority=10))

            self._event_bus = EventBus()
            self._audit = AuditTrail()
            self._integration_bus = IntegrationBus(
                name=self._config.get_str("app.name", "mca_bus"),
                default_timeout=self._config.get_float("integration.default_timeout", 30.0),
                event_bus=self._event_bus,
            )

            self._container = DIContainer()
            self._register_infrastructure()

            self._ctx = AppContext(
                container=self._container,
                config=self._config,
                event_bus=self._event_bus,
                audit=self._audit,
                integration_bus=self._integration_bus,
                phase=AppPhase.INIT,
            )

            self._audit.record(
                op_type=OperationType.SYSTEM_START,
                detail="基础设施初始化完成",
                component="bootstrap",
            )

            logger.info("Phase 1 完成: 基础设施已就绪")
            return self._ctx

    def _register_infrastructure(self) -> None:
        """向 DI 容器注册基础设施实例。"""
        if self._container is None:
            raise RuntimeError("DI 容器未初始化，无法注册基础设施")
        self._container.register_instance(ConfigManager, self._config)
        self._container.register_instance(EventBus, self._event_bus)
        self._container.register_instance(AuditTrail, self._audit)
        self._container.register_instance(IntegrationBus, self._integration_bus)
        self._container.register_instance(DIContainer, self._container)

    def register_defaults(self, ctx: AppContext) -> AppContext:
        """Phase 2: 注册默认服务与子系统。"""
        ctx.phase = AppPhase.SERVICES

        self._audit.record(
            op_type=OperationType.SYSTEM_START,
            detail="开始注册默认服务",
            component="bootstrap",
        )

        from config.constants import BASE_DIR, DATABASE_FILE

        try:
            from mca_core.services.system_service import SystemService
            self._system_service = SystemService()
            self._container.register_instance(SystemService, self._system_service)
        except Exception as e:
            logger.warning("SystemService 注册失败: %s", e)

        try:
            from mca_core.services.database import DatabaseManager
            db_path = DATABASE_FILE
            self._database_manager = DatabaseManager.get_instance(db_path)
            self._container.register_instance(DatabaseManager, self._database_manager)
        except Exception as e:
            logger.warning("DatabaseManager 注册失败: %s", e)

        try:
            from mca_core.services.log_service import LogService
            self._container.register_transient(LogService)
        except Exception as e:
            logger.warning("LogService 注册失败: %s", e)

        from mca_core.detectors import DetectorRegistry
        try:
            registry = DetectorRegistry.get_instance()
            self._container.register_instance(DetectorRegistry, registry)
        except Exception as e:
            logger.warning("DetectorRegistry 注册失败: %s", e)

        logger.info("Phase 2 完成: 默认服务已注册 (%d services)",
                     len(self._container.get_registered_services()))
        return ctx

    def create_components(self, ctx: AppContext) -> AppContext:
        """Phase 3: 创建核心功能组件。"""
        ctx.phase = AppPhase.COMPONENTS

        self._audit.record(
            op_type=OperationType.SYSTEM_START,
            detail="开始创建功能组件",
            component="bootstrap",
        )

        from config.constants import DATA_DIR

        try:
            from mca_core.diagnostic_engine import DiagnosticEngine
            self._diagnostic_engine = DiagnosticEngine(
                data_dir=DATA_DIR,
                config=self._config,
                audit=self._audit,
                event_bus=self._event_bus,
            )
            self._container.register_instance(DiagnosticEngine, self._diagnostic_engine)
            logger.info("DiagnosticEngine 已创建")
        except Exception as e:
            logger.warning("DiagnosticEngine 创建失败: %s", e)

        try:
            from mca_core.patch_manager.core import PatchManager
            patch_dir = self._config.get_str("patch.scan_directory", "./patches")
            import os as _os
            if not _os.path.isabs(patch_dir):
                from config.constants import ROOT_DIR
                patch_dir = _os.path.join(ROOT_DIR, patch_dir)
            self._patch_manager = PatchManager(
                patch_dir=patch_dir,
                config=self._config,
                audit=self._audit,
            )
            self._container.register_instance(PatchManager, self._patch_manager)
            logger.info("PatchManager 已创建 (patch_dir=%s)", patch_dir)
        except Exception as e:
            logger.warning("PatchManager 创建失败: %s", e)

        try:
            from mca_core.dashboard.controller import DashboardController
            self._dashboard = DashboardController(
                config=self._config,
                audit=self._audit,
                event_bus=self._event_bus,
            )
            self._container.register_instance(DashboardController, self._dashboard)
            logger.info("DashboardController 已创建")
        except Exception as e:
            logger.warning("DashboardController 创建失败: %s", e)

        logger.info("Phase 3 完成: 功能组件已创建")
        return ctx

    def assemble(
        self,
        ctx: AppContext,
        extra_registrations: Optional[List[Callable[[AppContext], None]]] = None,
    ) -> AppContext:
        """Phase 4: 装配子系统、注册事件、建立集成关系。"""
        ctx.phase = AppPhase.ASSEMBLY

        self._audit.record(
            op_type=OperationType.SYSTEM_START,
            detail="开始装配子系统",
            component="bootstrap",
        )

        if extra_registrations:
            for callback in extra_registrations:
                try:
                    callback(ctx)
                except Exception as e:
                    logger.error("子系统注册回调失败: %s", e)
                    self._audit.record(
                        op_type=OperationType.ERROR,
                        detail=f"子系统注册失败: {e}",
                        component="bootstrap",
                        success=False,
                    )

        if self._diagnostic_engine is not None and self._dashboard is not None:
            try:
                self._diagnostic_engine.set_dashboard_controller(self._dashboard)
                logger.info("DiagnosticEngine <-> DashboardController 已装配")
            except Exception as e:
                logger.warning("DiagnosticEngine/Dashboard 装配失败: %s", e)

        logger.info("Phase 4 完成: 子系统已装配")
        return ctx

    def start_services(self, ctx: AppContext) -> None:
        """Phase 5: 启动所有服务。"""
        ctx.phase = AppPhase.RUNNING

        self._event_bus.publish_async(
            AnalysisEvent(
                type=EventTypes.PLUGIN_LOADED,
                payload={"bootstrap": "started", "timestamp": ctx.started_at.isoformat()},
            )
        )

        if self._patch_manager is not None:
            try:
                self._patch_manager.scan()
                logger.info("PatchManager 扫描完成")
                if self._config.get_bool("patch.auto_monitor", True):
                    self._patch_manager.start_monitor(
                        interval=self._config.get_float("monitor.interval_seconds", 30.0)
                    )
                    logger.info("PatchMonitor 已启动")
            except Exception as e:
                logger.warning("PatchManager 启动失败: %s", e)

        if self._dashboard is not None:
            try:
                self._dashboard.start()
                logger.info("DashboardController 已启动")
            except Exception as e:
                logger.warning("DashboardController 启动失败: %s", e)

        self._audit.record(
            op_type=OperationType.SYSTEM_START,
            detail="系统启动完成",
            component="bootstrap",
        )

        logger.info("系统启动完成，Phase 5: 运行中")
        logger.info("  - 配置源: %d 个", len(self._config._sources))
        logger.info("  - DI 服务: %d 个", len(self._container.get_registered_services()))
        logger.info("  - 审计条目: %d 条", self._audit.count())

    def shutdown(self, ctx: Optional[AppContext] = None) -> None:
        """安全关闭系统。"""
        with self._lock:
            target = ctx or self._ctx
            if target is not None:
                target.phase = AppPhase.SHUTDOWN

            for hook in reversed(self._shutdown_hooks):
                try:
                    hook()
                except Exception as e:
                    logger.warning("关闭钩子失败: %s", e)

            if self._dashboard is not None:
                try:
                    self._dashboard.stop()
                    logger.info("DashboardController 已停止")
                except Exception as e:
                    logger.warning("DashboardController 停止失败: %s", e)

            if self._patch_manager is not None:
                try:
                    self._patch_manager.stop_monitor()
                    logger.info("PatchMonitor 已停止")
                except Exception as e:
                    logger.warning("PatchMonitor 停止失败: %s", e)

            if self._diagnostic_engine is not None:
                try:
                    self._diagnostic_engine.shutdown()
                    logger.info("DiagnosticEngine 已关闭")
                except Exception as e:
                    logger.warning("DiagnosticEngine 关闭失败: %s", e)

            if self._integration_bus is not None:
                try:
                    self._integration_bus.shutdown_all()
                except Exception as e:
                    logger.warning("集成总线关闭失败: %s", e)

            if self._audit is not None:
                self._audit.record(
                    op_type=OperationType.SYSTEM_STOP,
                    detail="系统已关闭",
                    component="bootstrap",
                )

            self._container = None
            self._config = None
            self._event_bus = None
            self._audit = None
            self._integration_bus = None
            self._diagnostic_engine = None
            self._patch_manager = None
            self._dashboard = None
            self._ctx = None

            logger.info("系统已安全关闭")

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        """注册关闭钩子。"""
        self._shutdown_hooks.append(hook)

    def health_check(self, ctx: Optional[AppContext] = None) -> Dict[str, Any]:
        """系统健康检查。"""
        target = ctx or self._ctx
        if target is None:
            return {"status": "not_initialized", "phase": "none"}

        checks: Dict[str, Any] = {
            "status": "healthy",
            "phase": target.phase.name,
            "uptime_seconds": (datetime.now() - target.started_at).total_seconds(),
            "components": {},
        }

        if target.phase == AppPhase.RUNNING:
            bus_health = self._integration_bus.health_check_all() if self._integration_bus else {}
            checks["components"]["integration_bus"] = bus_health
            checks["components"]["event_bus_subs"] = (
                self._event_bus.get_subscriber_count() if self._event_bus else 0
            )
            checks["components"]["audit_entries"] = self._audit.count() if self._audit else 0
            checks["components"]["diagnostic_engine"] = (
                self._diagnostic_engine is not None
            )
            checks["components"]["patch_manager"] = (
                self._patch_manager is not None and self._patch_manager.is_initialized
            )
            checks["components"]["dashboard"] = (
                self._dashboard is not None
            )

        return checks

    @classmethod
    def create(
        cls,
        config_path: Optional[str] = None,
        extra_registrations: Optional[List[Callable[[AppContext], None]]] = None,
    ) -> AppContext:
        """一键创建并启动完整系统。"""
        bootstrap = cls()
        ctx = bootstrap.initialize(config_path=config_path)
        ctx = bootstrap.register_defaults(ctx)
        ctx = bootstrap.create_components(ctx)
        ctx = bootstrap.assemble(ctx, extra_registrations=extra_registrations)
        bootstrap.start_services(ctx)
        return ctx


def get_bootstrap() -> Optional[AppBootstrap]:
    """获取全局启动器实例。"""
    return _global_bootstrap


def set_bootstrap(bootstrap: AppBootstrap) -> None:
    """设置全局启动器实例。"""
    global _global_bootstrap
    _global_bootstrap = bootstrap


_global_bootstrap: Optional[AppBootstrap] = None