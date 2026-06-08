# MCA Brain System — Unified Architecture Documentation

> 版本号唯一真源: `src/brain_system/__init__.py` → `__version__`

## 目录

1. [架构概览](#架构概览)
2. [模块划分与职责](#模块划分与职责)
3. [分层设计](#分层设计)
4. [接口定义规范](#接口定义规范)
5. [配置管理体系](#配置管理体系)
6. [变更管理机制](#变更管理机制)
7. [依赖注入系统](#依赖注入系统)
8. [事件驱动通信](#事件驱动通信)
9. [启动与生命周期](#启动与生命周期)
10. [扩展指南](#扩展指南)

---

## 架构概览

MCA Brain System 采用**分层架构 + 依赖注入 + 事件驱动**的统一设计模式，实现了业务逻辑、数据处理及接口交互的归一化管理。

### 架构设计图

```
┌────────────────────────────────────────────────────────────────────┐
│                         Applications Layer                        │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │   main.py    │  │  AppBootstrap    │  │ BCManager (GUI)    │  │
│  │ (headless)   │  │  (unified entry) │  │ + DashboardDLC     │  │
│  └──────────────┘  └──────────────────┘  └────────────────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                        Core Services Layer                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ Diagnostic │  │ Dashboard  │  │  Patch     │  │   Config   │  │
│  │  Engine    │  │ Controller │  │  Manager   │  │  Manager   │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │DetectorReg │  │MetricsColl │  │PatchStore  │  │AuditTrail  │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                     Infrastructure Layer                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │DIContainer │  │ EventBus   │  │Integration │  │   State    │  │
│  │ (resolve)  │  │ (pub/sub)  │  │    Bus     │  │  Manager   │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                       Data & Storage Layer                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │PatternRepo │  │DetectorCache│  │HistoryStore│  │  Database  │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 核心设计原则

| 原则 | 实现方式 |
|------|----------|
| **低耦合高内聚** | 分层设计 + 接口注入 + 事件解耦 |
| **配置归一化** | ConfigManager 集中管理，支持多源合并与版本回溯 |
| **变更可追溯** | AuditTrail 操作日志 + ChangeRecord 变更追踪 |
| **组件可替换** | DIContainer 依赖注入，注册即使用 |
| **启动统一化** | AppBootstrap 五阶段生命周期管理 |

---

## 模块划分与职责

### 应用层 (Applications Layer)

| 模块 | 路径 | 职责 |
|------|------|------|
| `main.py` | `/main.py` | 无头模式(headless)入口，使用 AppBootstrap 启动 |
| `AppBootstrap` | `src/mca_core/bootstrap.py` | 统一启动器：五阶段启动、生命周期管理、健康检查 |
| `MCABrainCore` | `src/mca_core/app.py` | GUI 模式应用核心，保留向后兼容 |
| `DashboardController` | `src/mca_core/dashboard/controller.py` | 仪表盘独立控制器，封装 Metrics/Anomaly/Alert/History |
| `DashboardDLC` | `src/mca_core/dashboard/dlc.py` | 仪表盘展示层，连接 GUI 面板 |

### 核心服务层 (Core Services Layer)

| 模块 | 路径 | 职责 |
|------|------|------|
| `DiagnosticEngine` | `src/mca_core/diagnostic_engine.py` | 诊断引擎：并行检测、缓存、置信度评分 |
| `PatchManager` | `src/mca_core/patch_manager/core.py` | 补丁管理：扫描、安装、回滚、监控 |
| `ConfigManager` | `src/config/config_manager.py` | 配置管理：多源读取、快照/差异/回滚 |
| `AuditTrail` | `src/mca_core/audit.py` | 审计追踪：操作日志、变更记录、导出 |
| `DetectorRegistry` | `src/mca_core/detectors/registry.py` | 检测器注册表：动态注册、管理 |

### 基础设施层 (Infrastructure Layer)

| 模块 | 路径 | 职责 |
|------|------|------|
| `DIContainer` | `src/mca_core/di.py` | 依赖注入容器：服务注册、解析、生命周期管理 |
| `EventBus` | `src/mca_core/events.py` | 事件总线：发布/订阅、异步事件、一次性订阅 |
| `IntegrationBus` | `src/mca_core/integration/bus.py` | 集成总线：子系统生命周期管理、健康检查 |

### 数据与存储层 (Data & Storage Layer)

| 模块 | 路径 | 职责 |
|------|------|------|
| `PatternRepository` | `src/mca_core/pattern_repository.py` | 诊断规则持久化：JSON 文件加载/保存 |
| `DetectorCache` | `src/mca_core/detectors/detector_cache.py` | 检测结果缓存：LRU+TTL 策略 |
| `HistoryStore` | `src/mca_core/dashboard/history.py` | 仪表盘历史数据：快照存储、趋势分析 |
| `PatchStore` | `src/mca_core/patch_manager/core.py` | 补丁文件存储：元数据、状态、回滚点 |

---

## 分层设计

### 依赖方向（自上而下）

```
Applications ──► Core Services ──► Infrastructure ──► Data & Storage
     │                  │                  │                  │
     │                  │                  │                  │
     ▼                  ▼                  ▼                  ▼
  用户交互          业务逻辑            系统机制           数据持久化
```

**规则**:
- 上层可以依赖下层，下层不能依赖上层
- 同层模块仅通过接口（EventBus / DI）通信
- 跨层调用通过 DI Container 解析
- 所有外部依赖通过接口抽象

### 组件关系图

```
                    ┌──────────────────┐
                    │   AppBootstrap   │
                    │  (启动协调层)     │
                    └────────┬─────────┘
                             │ 创建并装配
           ┌─────────────────┼─────────────────┐
           │                 │                  │
           ▼                 ▼                  ▼
  ┌────────────────┐  ┌──────────┐  ┌──────────────────┐
  │DiagnosticEngine│  │PatchMgr  │  │DashboardController│
  │                │  │          │  │                  │
  │ ← config       │  │ ← config │  │ ← config         │
  │ ← audit        │  │ ← audit  │  │ ← audit          │
  │ ← event_bus    │  │          │  │ ← event_bus       │
  └───────┬────────┘  └────┬─────┘  └────────┬─────────┘
          │                │                 │
          │    ┌───────────┴─────────────┐   │
          │    │                         │   │
          ▼    ▼                         ▼   ▼
  ┌─────────────────────────────────────────────┐
  │              EventBus (事件总线)              │
  │  ANALYSIS_COMPLETE │ PLUGIN_LOADED │ ERROR  │
  └─────────────────────────────────────────────┘
          │                         │
          ▼                         ▼
  ┌──────────────┐        ┌──────────────────┐
  │ AuditTrail   │        │  IntegrationBus  │
  │ (审计追踪)    │        │  (集成总线)       │
  └──────────────┘        └──────────────────┘
```

---

## 接口定义规范

### 1. 构造函数注入标准

所有核心组件通过 `__init__` 接受 DI 参数，**所有 DI 参数均为可选**（向后兼容）：

```python
class AnyComponent:
    def __init__(
        self,
        # ... 业务参数
        *,
        config: Optional[Any] = None,     # ConfigManager
        audit: Optional[Any] = None,      # AuditTrail
        event_bus: Optional[Any] = None,  # EventBus
    ) -> None:
```

### 2. 生命周期接口

所有受管理的组件应实现以下标准方法：

```python
class ManagedComponent:
    def start(self) -> None:
        """启动组件（后台线程、定时器等）"""
        ...

    def stop(self) -> None:
        """停止组件（清理线程、释放资源）"""
        ...
```

### 3. 服务注册接口 (DIContainer)

```python
class DIContainer:
    def register_singleton(service_type: type[T], factory: Callable | None = None) -> None
    def register_transient(service_type: type[T], factory: Callable | None = None) -> None
    def register_instance(service_type: type[T], instance: T) -> None
    def register_instance_by_key(key: str, instance: Any) -> None
    def resolve(service_type: type[T]) -> T
    def has(service_type: type[T]) -> bool
    def has_key(key: str) -> bool
    def get_registered_services() -> List[type]
```

### 4. 事件接口 (EventBus)

```python
class EventBus:
    def subscribe(event_type: EventTypes, handler: Callable, priority: int = 0) -> None
    def subscribe_once(event_type: EventTypes, handler: Callable, priority: int = 0) -> None
    def unsubscribe(event_type: EventTypes, handler: Callable) -> None
    def publish(event: AnalysisEvent) -> None
    def publish_async(event: AnalysisEvent) -> None
    def get_subscriber_count(event_type: EventTypes = None) -> int
```

### 5. 配置接口 (ConfigManager)

```python
class ConfigManager:
    def add_source(source: ConfigSource) -> None
    def get(key: str, default: Any = None) -> Any
    def get_str(key: str, default: str = "") -> str
    def get_int(key: str, default: int = 0) -> int
    def get_float(key: str, default: float = 0.0) -> float
    def get_bool(key: str, default: bool = False) -> bool
    def set(key: str, value: Any) -> None
    def snapshot(description: str = "") -> int
    def rollback(version: int) -> bool
    def diff(version_a: int, version_b: int) -> Dict[str, Any]
    def list_snapshots() -> List[Dict[str, Any]]
    def set_audit_trail(audit: Any) -> None
    def to_dict() -> Dict[str, Any]
```

### 6. 审计接口 (AuditTrail)

```python
class AuditTrail:
    def record(
        op_type: OperationType,
        detail: str = "",
        *,
        component: str = "unknown",
        metadata: Dict[str, Any] = None,
        success: bool = True,
        user_id: str = "system",
    ) -> AuditEntry

    def record_change(
        entity_type: str,
        entity_id: str,
        old_value: Any,
        new_value: Any,
        *,
        component: str = "unknown",
        reason: str = "",
    ) -> ChangeRecord

    def get_entries(op_type: OperationType = None, limit: int = 100) -> List[AuditEntry]
    def get_changes(entity_type: str, entity_id: str) -> List[ChangeRecord]
    def get_recent(limit: int = 100) -> List[AuditEntry]
    def export_entries() -> List[Dict[str, Any]]
    def count() -> int
    def change_count() -> int
```

---

## 配置管理体系

### 配置源层次

```
┌─────────────────────────────────────────────┐
│             ConfigManager                    │
│  ┌───────────────────────────────────────┐  │
│  │ 优先级低 ←                           │  │
│  │  [0] DictConfigSource  "defaults"     │  │
│  │  [1] FileConfigSource  "user.json"    │  │
│  │  [2] EnvConfigSource   "MCA_"         │  │
│  │       → 优先级高                      │  │
│  │  [10] Runtime set()  (memory)          │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │  版本管理                             │  │
│  │  snapshot("描述") → v1 → v2 → ...     │  │
│  │  rollback(ver)    → 回退到指定版本    │  │
│  │  diff(v1, v2)     → 变更差异报告      │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### 预定义配置项

| 配置键 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `app.name` | str | "MCA Brain System" | 应用名称 |
| `app.env` | str | "production" | 运行环境 |
| `ui.theme` | str | "dark" | UI 主题 |
| `ui.scroll_sensitivity` | int | 6 | 滚动灵敏度 |
| `engine.max_workers` | int | 8 | 并行工作线程数 |
| `engine.detector_timeout` | float | 15.0 | 检测器超时(秒) |
| `engine.cache_size` | int | 128 | 缓存容量 |
| `engine.cache_ttl` | float | 600.0 | 缓存生存时间(秒) |
| `patch.scan_directory` | str | "./patches" | 补丁目录 |
| `patch.max_retries` | int | 3 | 最大重试次数 |
| `patch.auto_monitor` | bool | True | 自动启动监控 |
| `monitor.interval_seconds` | float | 5.0 | 监控间隔(秒) |
| `monitor.snapshot_interval` | float | 30.0 | 快照间隔(秒) |
| `monitor.alert_cooldown` | float | 60.0 | 告警冷却(秒) |
| `security.rate_limit` | int | 100 | 速率限制 |
| `security.max_file_size` | int | 104857600 | 最大文件大小(字节) |

---

## 变更管理机制

### 审计追踪系统

```
操作发生
    │
    ▼
AuditTrail.record(op_type, detail, ...)
    │
    ├──► AuditEntry (frozen dataclass)
    │    ├─ entry_id: 唯一标识
    │    ├─ timestamp: 时间戳
    │    ├─ op_type: 操作类型
    │    ├─ component: 来源模块
    │    ├─ detail: 操作描述
    │    ├─ metadata: 附加数据
    │    ├─ success: 成功标记
    │    └─ user_id: 操作用户
    │
    ▼
ChangeRecord (实体变更)
    ├─ entity_type: 实体类型
    ├─ entity_id: 实体ID
    ├─ old_value: 旧值
    ├─ new_value: 新值
    ├─ reason: 变更原因
    └─ change_id: 变更ID
```

### 操作类型枚举

```python
class OperationType(Enum):
    # 系统级
    SYSTEM_START      = "system.start"
    SYSTEM_STOP       = "system.stop"
    CUSTOM            = "system.custom"
    ERROR             = "system.error"

    # 配置级
    CONFIG_LOAD       = "config.load"
    CONFIG_SAVE       = "config.save"
    CONFIG_CHANGE     = "config.change"

    # 补丁级
    PATCH_INSTALL     = "patch.install"
    PATCH_REMOVE      = "patch.remove"
    PATCH_VERIFY      = "patch.verify"
    PATCH_ROLLBACK    = "patch.rollback"
    PATCH_SCAN        = "patch.scan"

    # 诊断级
    DIAGNOSTIC_START  = "diagnostic.start"
    DIAGNOSTIC_COMPLETE = "diagnostic.complete"

    # 仪表盘级
    ANOMALY_DETECTED  = "anomaly.detected"
    THRESHOLD_BREACH  = "threshold.breach"
```

### 版本回溯流程

```
发现问题
    │
    ├──► 查询审计日志   audit.get_entries()
    ├──► 查看变更记录   audit.get_changes(type, id)
    ├──► 定位问题版本   config.list_snapshots()
    ├──► 比较差异       config.diff(bad, good)
    ├──► 确认回滚方案
    ├──► 执行回滚       config.rollback(good_version)
    └──► 验证恢复结果
```

---

## 依赖注入系统

### 服务生命周期

| 生命周期 | 说明 | 适用场景 |
|----------|------|----------|
| `SINGLETON` | 全应用唯一实例 | 基础设施组件(Config/Audit/Bus) |
| `TRANSIENT` | 每次解析创建新实例 | 临时服务 |
| `INSTANCE` | 外部预先创建后注册 | 需要自定义构建的服务 |

### 注册流程

```python
# 1. 创建基础设施
config = ConfigManager()
audit = AuditTrail()
event_bus = EventBus()

# 2. 注册到容器
container = DIContainer()
container.register_instance(ConfigManager, config)
container.register_instance(AuditTrail, audit)
container.register_instance(EventBus, event_bus)

# 3. 创建业务组件(注入基础设施)
engine = DiagnosticEngine(data_dir="data",
                          config=config, audit=audit, event_bus=event_bus)
container.register_instance(DiagnosticEngine, engine)

# 4. 任意位置解析
engine = container.resolve(DiagnosticEngine)
```

---

## 事件驱动通信

### 事件类型

```python
class EventTypes(Enum):
    ANALYSIS_START    = "analysis.start"
    ANALYSIS_COMPLETE = "analysis.complete"
    ANALYSIS_ERROR    = "analysis.error"
    PLUGIN_LOADED     = "plugin.loaded"
    PLUGIN_UNLOADED   = "plugin.unloaded"
    CONFIG_CHANGED    = "config.changed"
    PATCH_APPLIED     = "patch.applied"
    PATCH_FAILED      = "patch.failed"
    SYSTEM_SHUTDOWN   = "system.shutdown"
```

### 通信模式

```
组件A ──publish(AnalysisEvent(COMPLETE, {...}))──► EventBus
                                                      │
                        ┌─────────────────────────────┤
                        │                             │
                        ▼                             ▼
                   组件B.handle(...)           组件C.handle(...)
                   (持久订阅)                 (一次性订阅)
```

---

## 启动与生命周期

### 五阶段启动流程

```
Phase 1: INITIALIZE ──► 创建基础设施
│  ├─ ConfigManager (多源配置)
│  ├─ EventBus (事件总线)
│  ├─ AuditTrail (审计追踪)
│  ├─ IntegrationBus (集成总线)
│  └─ DIContainer (依赖注入容器)
│
├─► Phase 2: SERVICES ──► 注册默认服务
│  ├─ SystemService
│  ├─ DatabaseManager
│  ├─ LogService
│  └─ DetectorRegistry
│
├─► Phase 3: COMPONENTS ──► 创建功能组件
│  ├─ DiagnosticEngine
│  ├─ PatchManager
│  └─ DashboardController
│
├─► Phase 4: ASSEMBLY ──► 装配子系统
│  ├─ DiagnosticEngine ←→ DashboardController
│  ├─ 子系统注册 (自定义回调)
│  └─ 事件处理器注册
│
└─► Phase 5: RUNNING ──► 启动服务
   ├─ PatchManager.scan()
   ├─ PatchMonitor.start()
   └─ DashboardController.start()
```

### 关闭流程

```
AppBootstrap.shutdown(ctx)
    │
    ├─► 1. 执行关闭钩子 (shutdown_hooks)
    ├─► 2. DashboardController.stop()
    ├─► 3. PatchMonitor.stop()
    ├─► 4. DiagnosticEngine.shutdown()
    ├─► 5. IntegrationBus.shutdown_all()
    ├─► 6. AuditTrail.record(SYSTEM_STOP)
    └─► 7. 清理所有引用
```

### 使用示例

```python
# 一行启动
from mca_core.bootstrap import AppBootstrap

ctx = AppBootstrap.create()                    # Phase 1→5 自动完成

# 或分阶段控制
bootstrap = AppBootstrap()
ctx = bootstrap.initialize()                   # Phase 1
ctx = bootstrap.register_defaults(ctx)         # Phase 2
ctx = bootstrap.create_components(ctx)         # Phase 3
ctx = bootstrap.assemble(ctx)                  # Phase 4
bootstrap.start_services(ctx)                  # Phase 5

# 健康检查
health = bootstrap.health_check(ctx)
print(health["status"])  # "healthy"

# 安全关闭
bootstrap.shutdown(ctx)
```

---

## 扩展指南

### 添加新的核心组件

1. 在构造函数中添加 DI 参数：

```python
class NewComponent:
    def __init__(self, *, config=None, audit=None, event_bus=None):
        self._config = config
        self._audit = audit
        self._event_bus = event_bus
```

2. 在 `AppBootstrap.create_components()` 中注册：

```python
new_comp = NewComponent(config=self._config, audit=self._audit, event_bus=self._event_bus)
self._container.register_instance(NewComponent, new_comp)
```

3. 在 `AppBootstrap.assemble()` 中装配：

```python
# 连接组件
engine.set_new_controller(new_comp)
```

4. 在 `AppBootstrap.start_services()` 中启动：

```python
new_comp.start()
```

5. 在 `AppBootstrap.shutdown()` 中关闭：

```python
new_comp.stop()
```

### 添加新的配置项

在 `AppBootstrap.DEFAULT_CONFIG` 中添加默认值：

```python
DEFAULT_CONFIG = {
    "new_module.feature_enabled": True,
    "new_module.timeout": 30.0,
    # ...
}
```

### 添加新的事件类型

在 `events.py` 的 `EventTypes` 中添加：

```python
class EventTypes(Enum):
    NEW_EVENT = "module.event_name"
```

### 添加新的操作类型

在 `audit.py` 的 `OperationType` 中添加：

```python
class OperationType(Enum):
    NEW_OPERATION = "module.operation"
```

---

## 文件索引

| 文件 | 说明 |
|------|------|
| `src/mca_core/bootstrap.py` | 统一启动器 (五阶段生命周期) |
| `src/mca_core/di.py` | 依赖注入容器 |
| `src/mca_core/audit.py` | 审计追踪系统 |
| `src/mca_core/events.py` | 事件总线 |
| `src/mca_core/integration/bus.py` | 集成总线 |
| `src/mca_core/diagnostic_engine.py` | 诊断引擎 (DI 集成) |
| `src/mca_core/dashboard/controller.py` | 仪表盘控制器 (DI 集成) |
| `src/mca_core/patch_manager/core.py` | 补丁管理器 (DI 集成) |
| `src/config/config_manager.py` | 配置管理器 (版本化) |
| `src/config/constants.py` | 系统常量定义 |
| `src/config/__init__.py` | 配置包入口 |
| `src/mca_core/app.py` | GUI 应用核心 (向后兼容) |
| `main.py` | 无头模式入口 |
| `tools/_test_unified_architecture.py` | 统一架构集成测试 (12 cases) |
| `tools/_test_config_v2.py` | 配置管理器 v2.0 测试 |