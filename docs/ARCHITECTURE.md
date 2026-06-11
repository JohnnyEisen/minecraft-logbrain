# 架构文档

> 版本号唯一真源: `src/brain_system/__init__.py` → `__version__`

---

## 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  Applications:  main.py / AppBootstrap / DashboardController │
├──────────────────────────────────────────────────────────────┤
│  Core Services: DiagnosticEngine / PatchManager / Config     │
├──────────────────────────────────────────────────────────────┤
│  Infrastructure: DIContainer / EventBus / State              │
├──────────────────────────────────────────────────────────────┤
│  Data & Storage: PatternRepo / DetectorCache / HistoryStore  │
└──────────────────────────────────────────────────────────────┘
```

规则：上层可依赖下层，下层不可依赖上层。跨层通信通过 EventBus 或 DI Container。

---

## 模块清单

### 应用层

| 模块 | 路径 | 职责 |
|------|------|------|
| AppBootstrap | `src/mca_core/bootstrap.py` | 五阶段启动、生命周期、健康检查 |
| DiagnosticEngine | `src/mca_core/diagnostic_engine.py` | 并行检测、缓存、置信度评分 |
| PatchManager | `src/mca_core/patch_manager/core.py` | 补丁扫描/安装/回滚/监控 |
| DashboardController | `src/mca_core/dashboard/controller.py` | 指标/异常/告警/历史 |
| DetectorRegistry | `src/mca_core/detectors/registry.py` | 21 种检测器注册与调度 |

### 基础设施层

| 模块 | 路径 | 职责 |
|------|------|------|
| DIContainer | `src/mca_core/di.py` | 依赖注入：注册、解析、生命周期 |
| EventBus | `src/mca_core/events.py` | 发布/订阅、异步事件、优先级 |
| ConfigManager | `src/config/config_manager.py` | 多源配置读取、快照/回滚 |
| AuditTrail | `src/mca_core/audit.py` | 操作审计日志 |

### Brain AI 层

| 模块 | 路径 | 职责 |
|------|------|------|
| BrainCore | `src/brain_system/core.py` | 任务调度、DLC 管理、缓存 |
| DLCManager | `src/brain_system/dlc_manager.py` | DLC 注册/热加载/生命周期 |
| PatchAPI | `src/brain_system/patch_api.py` | FastAPI 补丁管理 REST 接口 |
| Server | `src/brain_system/server.py` | HTTP 服务（health/ready/metrics） |

---

## 核心设计原则

| 原则 | 实现 |
|------|------|
| 低耦合高内聚 | 分层 + 接口注入 + 事件解耦 |
| 配置归一化 | ConfigManager 多源合并 + 版本回溯 |
| 变更可追溯 | AuditTrail + ChangeRecord |
| 组件可替换 | DIContainer 注册即使用 |
| 启动统一 | AppBootstrap 五阶段生命周期 |

---

## DI 注入规范

所有核心组件 `__init__` 接受可选 DI 参数：

```python
class DiagnosticEngine:
    def __init__(self, data_dir, *, config=None, audit=None, event_bus=None):
```

注入优先级: **显式参数 > DI Container > 默认实例**

每个服务有对应的内部接口（`services/interfaces.py`），支持 Mock/Stub。

---

## EventBus 通信

事件类型 (`events.py`): `ANALYSIS_START/PROGRESS/COMPLETE/ERROR`, `DETECTOR_COMPLETE`, `PLUGIN_LOADED`, `CONFIG_CHANGED`

```python
bus.publish(AnalysisEvent(EventTypes.ANALYSIS_COMPLETE, {"result_count": 3}))
```

跨子系统通信通过 IntegrationBus (`integration/bus.py`) 协调生命周期和健康检查。

---

## 启动流程

```
Phase 1: PRE_INIT  → 加载配置、验证环境
Phase 2: INIT      → 创建 DIContainer、注册核心服务
Phase 3: POST_INIT → 装配 EventBus、创建 DiagnosticEngine
Phase 4: STARTUP   → 扫描补丁、启动 Dashboard、加载 DLC
Phase 5: RUNNING   → 进入事件循环、等待用户输入
```

---

## 扩展指南

| 扩展类型 | 步骤 |
|----------|------|
| 新检测器 | 继承 `Detector` → 实现 `detect()` / `get_name()` → 注册到 DetectorRegistry |
| 新 DLC | 继承 `BrainDLC` → 实现 `get_manifest()` / `_initialize()` → 放入 `src/dlcs/` |
| 新补丁 | 创建 `.py` + `.meta.json` → AST 验证 → 沙箱执行 |
| 新事件类型 | `EventTypes` 添加常量 → `AnalysisEvent` 发布 |

---

## 配置管理

- 源: 文件 JSON (`data/config.json`) + 可选 Consul
- 热更新: FileConfigSource 定时轮询 mtime 变化
- 回滚: `ConfigManager.rollback()` 恢复上一个有效配置
- 安全: Consul 配置项上限 1024 条，单值 ≤ 256KB
