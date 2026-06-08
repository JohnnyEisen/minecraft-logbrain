# Changelog

说明：
- 当前发布版本请看本文件顶部第一条版本记录。
- 本文件是唯一的发布历史来源，其他文档中的版本号可能是历史阶段或模板占位。

---

## v1.5.5 — TKinter→PyQt6 架构统一、补丁安全加固、检测器引擎跃升 (2026-06-08)

### 版本概览
这是一个系统性大版本，覆盖三条主线：(1) 彻底移除 TKinter 旧架构，项目从双轨制统一为纯 PyQt6；(2) 补丁系统从默认 admin 无限制执行改为三级权限沙箱 + AST 代码验证；(3) 检测器引擎大幅优化，新增 5 种检测器、诊断引擎 v3.0、UI 扁平化重设计、BrainCore 延迟初始化。

统计：`+4,014 / -8,901` 行净变更，删除约 8.9K 行死代码。

---

### Removed — TKinter 旧架构全面清理

- **删除 TKinter 主应用**：移除 `app.py`（MinecraftCrashAnalyzer，~3K 行）及全部 10 个 Mixin 文件（`app_analysis_mixin`、`app_auto_test_mixin`、`app_file_ops_mixin`、`app_graph_mixin`、`app_initialization_mixin`、`app_ui_mixin`、`ui_mixins`、`lab_mixins`、`settings_mixins`）。
- **删除 TKinter 面板**：移除 `dashboard_panel_tk.py`（449 行）、`patch_panel_tk.py`（466 行）。
- **删除 TKinter UI 组件**：移除 `ui/components/` 目录（6 文件：toolbar、log_view、main_notebook、menu_bar、brain_monitor、__init__）及 `ui/dpi_awareness.py`、`ui/styles.py`。
- **删除 brain_system 独立 TKinter UI**：移除 `brain_system/ui.py`（456 行），CLI 移除 `ui` 子命令，`pyproject.toml` 移除 `brain-ui` 入口点。
- **删除 DLC 兼容性空壳**：移除 `brain_system/dlcs/` 目录下 5 个 pass-through shim 文件。
- **删除过时测试**：移除 `test_settings_mixins.py`、`verify_database_integration.py`、`verify_startup.py`。
- **删除旧 MHC 模块**：移除 `dlcs/hardware_mhc_config.py`、`dlcs/mhc_codebert.py`、`dlcs/mhc_config.py`、`dlcs/mhc_trainer.py`、`dlcs/train_mhc.py`。
- **"legacy" 命名清理**：`threading_utils.py` `get_pool("legacy")` → `get_pool("default")`；`core.py` 移除 `strategy == "legacy"` 分支；`config_validator.py` `ROUTING_STRATEGIES` 移除 `"legacy"`；`app.py` 移除 `brain_conf_legacy` 回退路径。

### Added — 补丁系统安全加固

- **PatchValidator AST 静态代码验证器**：新增 `patch_validator.py`，上传前对补丁代码执行完整安全审查：
  - 禁止操作检测：`exec`/`eval`/`compile`/`__import__` 一律拒绝
  - 高危操作检测：`os.system`/`subprocess`/`socket`/`ctypes` 标记为 `high` 风险
  - 中危操作检测：文件写入标记为 `medium` 风险
  - 导入白名单：仅允许安全模块（math/collections/itertools 等）
  - 强制入口：补丁必须定义 `apply()` 函数
  - 自动风险分类：`safe → low → medium → high → critical → rejected`
- **PatchSandbox 沙箱执行环境**：新增 `patch_sandbox.py`，三级权限隔离：
  - `restricted`（默认）：纯计算，`open()` 只读，禁止 `__import__`
  - `standard`：允许只读文件，禁止网络和子进程
  - `admin`：需显式审批，保留完整 `open()`，仍禁止 `exec`/`eval`
- **PatchManager 集成**：`_upload_patch_locked` 增加 AST 验证 + 风险→权限匹配检查；`_apply_patch_locked` 替换 `importlib.util.exec_module` 为沙箱执行。
- **安全测试**：新增 `test_patch_security.py`，15 项测试覆盖验证器和沙箱。

### Added — 检测器系统扩展

- **新增 5 种检测器**：`StartupCrashDetector`（启动崩溃）、`WorldLoadingCrashDetector`（世界加载崩溃）、`EntityUpdateCrashDetector`（实体更新崩溃）、`OptifineDetector`（OptiFine 冲突）、`DetectorCache`（LRU+TTL 检测缓存）。
- **诊断引擎 v3.0**：从串行逐检测器运行改为并行执行，15 秒超时保护，带进度回调。
- **置信度评分系统**：`DetectionResult` 新增 `confidence` 字段 (0.0~1.0)。
- **结果去重**：基于内容哈希去重，消除重复报告。

### Changed — UI 扁平化重设计

- **玻璃拟态 → 扁平专业**：`styles_pyqt.py` 600+ 行 CSS 重构为简洁扁平配色方案。
- **AI 状态可视化**：BrainMonitorWidget 新增 5 色 AI 状态标签（未启用/加载中/已就绪/失败/下载中）。
- **AI 初始化超时**：`AIInitWorker` 新增 120s 超时机制 + 分阶段进度报告。

### Changed — 启动加速

- **BrainCore 延迟初始化**：用户点击"启用语义分析"时才在线程中初始化，节省冷启动 2-30s。
- **brain_system 惰性导入**：`__getattr__` 替代 eager import，消除导入级联。

### Changed — 版本号集中管理

- **唯一真源架构**：版本号统一在 `brain_system/__init__.py` 的 `__version__` 中定义，其他文件通过导入自动同步。
- **版本校验脚本**：新增 `tools/check_version.py`，支持静态扫描 + 运行时双重验证。

### Fixed — 关键 Bug 修复

- **mHC 设备检测一致性**：`_setup_mhc()` 使用实际运行设备而非独立查询。
- **HardwareAccelerator GPU 检测回退**：新增 PyTorch fallback（`torch.cuda.is_available()`）。
- **补丁 QTimer 缺失**：`patch_panel_pyqt.py` 补全 `QTimer` 导入。
- **自动测试结果区分**：输出从"检出(N项)"改为"规则: type1, type2 | 检测: DetectorA, DetectorB"。

### Added — 补丁管理系统全面升级 (PatchManager v2.0)

- **PatchCache 扫描缓存**：基于 mtime 失效策略的 LRU 缓存。
- **PatchDownloader HTTP 下载器**：支持指数退避重试 + SHA-256 完整性校验 + 进度回调。
- **PatchMonitor 后台监控**：守护线程持续追踪补丁状态。
- **线程安全升级**：`threading.RLock()` 保护核心操作。

### Security — 服务端安全加固

- `/ready` 端点信息泄露修复：移除 `dlcs` 字段。
- `/metrics` 端点访问控制：仅允许 `127.0.0.1` 访问。

### Test Coverage

- 新增 `test_patch_security.py` × 15 项安全测试
- 新增 `test_module_imports.py` × 全量模块导入扫描
- 新增 `test_diagnostic_engine.py` × 11 项诊断引擎测试
- 新增 `test_dashboard.py` × 12 项仪表盘测试
- 全量回归：**823 passed, 1 skipped, 0 failures**

---

## v1.5.3 — 系统可观测性、性能优化与安全加固 (2026-05-28)

### 版本概览
这一版是系统性"打磨"版本：补上仪表盘实时监控能力、将检测器引擎推至并行化、大幅提升补丁管理系统的可靠性和监控能力、封堵信息泄露漏洞，完成深度的死代码清扫，并实施版本号集中管理与导入/依赖优化。

---

### Added — 仪表盘实时监控系统

- **DashboardController 独立控制器**：创建不依赖 BrainCore 的 `DashboardController`（封装 `MetricsCollector`、`AnomalyDetector`、`AlertManager`、`HistoryStore`），解决仪表盘原先因 BrainCore 未启用而导致的三层连接断裂（DashboardDLC 未实例化 → UI 面板为 None → 所有指标显示 "--"）。
- **实时指标收集**：`MetricsCollector` 基于 `threading.RLock()` 支持检测器运行次数、成功率、平均响应时间、最后活跃时间等实时统计。
- **异常检测与告警**：`AnomalyDetector` 监控响应时间阈值（连续 3 次超 500ms 触发告警）、成功率下降趋势；`AlertManager` 管理告警生命周期（NEW → ACKNOWLEDGED → RESOLVED）。
- **历史数据存储**：`HistoryStore` 以 5 分钟为间隔持久化指标快照，支持趋势回顾。

### Added — 检测器系统全面优化 (DiagnosticEngine v3.0)

- **并行执行引擎**：`DiagnosticEngine` 从串行逐检测器运行改为 `ThreadPoolExecutor(max_workers=8)` 并行执行，15 秒超时保护，带进度回调。
- **LRU+TTL 检测缓存**：新增 `DetectorCache`（LRU 淘汰 + 10 分钟 TTL），基于日志 SHA-256 哈希作为缓存键。相同日志的重复分析零开销。
- **置信度评分系统** (`contracts.py` v2.0)：`DetectionResult` 新增 `confidence` 字段 (0.0~1.0)，支持检测器根据证据强度自评可信度。
- **结果去重**：`_seen_messages: Set[str]` 基于内容哈希去重，消除多个检测器对同一问题的重复报告。
- **预筛跳过机制**：`skip_detector` / `is_skipped` 方法支持根据日志特征提前排除不相关检测器。
- **DuplicateModsDetector 算法优化**：关键词检查从 O(N×M) 降为 O(N)，使用预编译正则 + `OrderedDict` 缓存。

### Added — 补丁管理系统全面升级 (PatchManager v2.0)

- **PatchCache 扫描缓存**：基于 mtime 失效策略的 LRU 缓存（max 200 条目），避免每次扫描都遍历磁盘。
- **PatchDownloader HTTP 下载器**：支持指数退避重试（3 次）+ SHA-256 完整性校验 + 实时进度回调。
- **PatchMonitor 后台监控**：守护线程持续追踪补丁数、安装成功率、完整性状态，异常时自动告警。
- **线程安全升级**：`PatchManager` 核心操作从普通字典操作改为 `threading.RLock()` 保护。

---

### Fixed — 三项关键 Bug 修复

- **Bug 1 — 补丁子系统扫描失败**：`_persist_state()` 曾将 `PatchRecord` 对象直接存入缓存导致反序列化失败。修复为存储 `{pid: rec.to_dict()}` 序列化格式。
- **Bug 2 — 仪表盘检测率/误报率均为 0**：`DiagnosticEngine` 的 `_dashboard_controller` 从未被设置。修复为在 `main_window_pyqt.py` 中连接 `engine.set_dashboard_controller()`，并在 `_run_single_detector()` 中追踪检测前后结果数变化。
- **Bug 3 — "unknown" 标签泛滥 + 结果数量翻倍**：`result.cause_label` 为 None 时回退为 `"unknown"` 而非检测器名称；`AutoTestWorker` 同时调用 `engine.analyze()` 和 `registry.run_all_parallel()` 导致检测器执行两遍。修复为使用 `result.detector` 作为回退名 + 移除 `registry.run_all_parallel()` 冗余调用 + 修正计数逻辑。

---

### Changed — 核心引擎优化与缺陷修复

- **DiagnosticEngine 缓存统一**：移除冗余的 `_result_cache`（OrderedDict），统一使用 `DetectorCache`（LRU+TTL）。原先两套缓存存储相同数据，浪费内存且增加维护复杂度，现简化为单一缓存路径。
- **告警风暴修复**：`AnomalyDetector` 添加 60 秒冷却期去重机制（`COOLDOWN_SECONDS = 60.0`），同一检测器+同一异常类型在冷却期内不重复生成告警。原先监控循环每 5 秒对所有检测器生成异常，18 检测器 × 6 异常类型 = 每分钟最多 1296 条重复告警，现降至 ~18/min，消除 98.6% 重复。
- **Alert ID 碰撞修复**：`alert_id` 从 `str(int(time.time() * 1000))` 改为 `uuid.uuid4().hex[:16]`，消除同一毫秒内创建多个 Alert 时 ID 冲突导致 `acknowledge/resolve` 操作错误目标的问题。
- **LruTtlCache 缓存污染修复**：`_estimate_size()` 以 `id(obj)` 缓存大小估算结果，对象被 GC 回收后新对象复用同一 `id()` 会返回错误值。添加 `_SIZE_ESTIMATE_IDS` 活跃集合追踪，防止 id 复用导致的缓存污染。
- **DetectorCache 锁优化**：`size` 属性移除不必要的 `with self._lock`，`len()` 在 CPython 中为原子操作，减少锁争用。

### Changed — 版本号集中管理

- **唯一真源架构**：版本号统一在 `brain_system/__init__.py` 的 `__version__` 中定义，其他文件通过导入或 setuptools dynamic attr 自动同步。
  - `src/__init__.py` → `from brain_system import __version__`
  - `brain_system/core.py` → `from brain_system import __version__`（`BrainCore.version` 自动同步）
  - `pyproject.toml` → `dynamic = ["version"]` + `version = {attr = "brain_system.__version__"}`
- **版本校验脚本**：新增 `tools/check_version.py`，支持静态扫描 + 运行时双重验证，以及 `--set X.Y.Z` 一键修改版本号。
- **pyproject.toml 修复**：`dependencies` 字段从 `[project.urls]` 子表（TOML 继承规则导致错误归属）移至 `[project]` 正确位置。

### Changed — 导入与依赖优化

- **server.py 重复导入修复**：移除 `create_app()` 函数体内冗余的 `from fastapi import FastAPI`（已在模块级第 10 行导入）及无意义的 `try/except` 守卫。
- **未使用依赖清理**：从 `pyproject.toml` 移除 4 个声明但代码中零引用的可选依赖：
  - `accelerate`（ai 组）— 无 `import accelerate`
  - `python-json-logger>=2.0.7`（logging 组，整组移除）— 无 `import pythonjsonlogger`
  - `watchdog>=4.0.0`（config 组）— 无 `import watchdog`
  - `sphinx>=7.2.0`（docs 组，整组移除）— 无 `import sphinx`

---

### Security — 安全加固

- **`/ready` 端点信息泄露修复**：移除返回值中的 `dlcs` 字段（原返回 `{"ready": True, "dlcs": N}`），不再对外暴露内部 DLC 数量。
- **`/metrics` 端点访问控制**：仅允许 `127.0.0.1` 访问 Prometheus 指标端点，外部请求返回 `403 Forbidden`。
- **内部方法泄露清理**：`health_check()` 和 `get_ready_status()` 中移除 `"dlc_count": len(self.dlcs)` 字段。

---

### Removed — 历史废弃代码清理

- **删除 `brain_system/dlcs/` 兼容性空壳包**（5 文件 + 整个目录）：这些文件仅为 `from dlcs.xxx import *` 的 pass-through shim。`app_initialization_mixin.py` 中 4 个 DLC 加载方法原先用 `try: from brain_system.dlcs.x` → `except: from dlcs.x` 的双层回退，现统一为直接导入 `dlcs.*`。
- **删除 `patch_manager/cli.py`**（547 行）：CLI 命令行接口（13 个子命令），全项目零引用。
- **删除 `run_patch_manager.py`**：CLI 入口脚本，唯一用途是调用 `cli.main()`。
- **清理测试引用**：`test_module_imports.py` 中移除 5 行对已删除 shim 模块的 known-optional 声明。
- **文档更新**：`patch_manager/__init__.py` 文档字符串移除 "CLI 命令行接口" 描述。

---

### Test Coverage

- 新增 `TestDashboardController` × 12 项仪表盘控制器测试
- 新增 `TestDetectorCache` × 6 项缓存机制测试
- 新增 `TestConfidenceAndDedup` × 5 项置信度与去重测试
- 全量回归：**700+ tests passed, 0 failures**

### Notes

- 升级前建议运行 `tests/test_dashboard.py` 和 `tests/test_detectors.py` 确认新仪表盘和检测器缓存功能正常。
- 删除 `brain_system/dlcs/` 后，任何硬编码 `from brain_system.dlcs.xxx import ...` 的第三方脚本需改为 `from dlcs.xxx import ...`。
- `/metrics` 端点现在仅允许 localhost 访问，若 Prometheus 部署在外部机器，需通过反向代理转发。

---

## v1.5.2 — 启动加速、UI 工程化与 AI 稳定性 (2026-05-17)

### 版本概览
- 这一版解决三个高频痛点：启动慢、AI 状态不可见、自动测试结果没区分度。同时完成 UI 工程化回炉和底层设备检测一致性修复。

### Changed — 启动加速
- **BrainCore 延迟初始化**：不再在窗口构造时创建 BrainCore，改为用户点击"启用语义分析"时才在线程中初始化。节省冷启动 2-30s。
- **brain_system 惰性导入**：`brain_system/__init__.py` 用 `__getattr__` 替代全面 eager import，消除整个 core.py 导入级联。
- **crash_log_lower 共享**：AnalysisContext 构造时计算一次 `.lower()`，6 个 detector 共享引用，减少字符串分配。

### Added — AI 状态可视化
- **BrainMonitorWidget AI 状态标签**：PyQt6 大脑指示器新增 `_ai_status_label`，5 色状态对照（未启用/加载中/已就绪/失败/下载中），颜色与圆点指示器同步。
- **AI 初始化超时与进度反馈**：`AIInitWorker` 新增 120s 超时机制 + 分阶段进度报告（BrainCore 创建 → 硬件加速器 → 语义模型下载 → 模型验证）。30s 后触发橙色警告提示"仍在下载语义模型 (~90MB)"。

### Fixed — 设备检测一致性
- **mHC 配置跟随错误设备**：`_setup_mhc()` 原先独立查询 Hardware DLC（依赖 cupy），在无 cupy 但 PyTorch CUDA 可用的环境下误走"CPU 极简模式"。修复为使用 `self.device.type`（已在 `_initialize` 中正确确定的实际运行设备）。
- **HardwareAccelerator GPU 检测回退**：`_detect_hardware()` 原来只依赖 cupy。新增 PyTorch fallback：`torch.cuda.is_available()` → `torch.cuda.get_device_properties()`。用户只装 PyTorch 不装 cupy 时也能正确报告 GPU。

### Changed — 自动测试结果区分
- **检出摘要细化**：输出从笼统的"检出(N项)"改为"规则: type1, type2 | 检测: DetectorA, DetectorB"，区分 DiagnosticEngine 模式匹配与 DetectorRegistry 检测器命中。
- **按场景统计增强**：最终统计不仅显示检出率，还列出每个场景命中的具体规则类型和检测器类型。

### Changed — UI 工程化
- **扁平专业重设计**：`styles_pyqt.py` 600+ 行玻璃拟态 CSS → 简洁扁平配色方案。去掉 9 处 Emoji、2 处 drop shadow、复杂的解剖学大脑绘图。
- **BrainMonitorWidget 布局修复**：AI 状态标签改为短固定文案（"AI: 加载中..."），长文本仅留在主状态栏，解决工具栏信息溢出问题。

### Added — 测试覆盖
- **`test_module_imports.py`**：全量模块导入扫描测试，防止导入级破坏。
- **`test_diagnostic_engine.py`**：11 项诊断引擎专项测试，覆盖所有规则匹配和边界条件。

### Notes
- HardwareAccelerator 的 `_init_devices_real` 仍需要 cupy 创建 CUDADevice 对象。如果 GPU 仅通过 PyTorch 检测到（无 cupy），device_objects 中不会有 GPU 条目。已装 cupy 则完全正常。
- launcher.py 引用已废弃的 Tkinter 入口，建议作为技术债清理。

## v1.5.1 — 检测器精度跃升与执行器路由收敛 (2026-05-15)

### 版本概览
- 这一版聚焦两件事：把 AI 检测精度推到能交付的水平，把 CPU 并行调度的路由逻辑理顺。

### Changed — 检测器精度 (F1: 71.8% → 98.4%)
- **DuplicateModsDetector**：修复 `analyzer.mods` 缺失导致检测器静默崩溃、文本模式漏检的问题。新增文本重复模式匹配（`found duplicate mod` / `duplicate mods found` / `multiple files for mod`）。
- **VersionConflictsDetector**：新增 `requires version.*but found version` 匹配模式，覆盖 mod 版本不满足场景。
- **GlErrorsDetector**：新增 `supported/required opengl version` 模式，覆盖 OpenGL 版本过低场景。
- **DependencyDetector**：修复正则跳过 `required/mandatory/dependency:` 填充词，避免误捕获 "version"/"required" 为 mod 名；增加 `INVALID_NAMES` 过滤噪声词。
- **整体效果**：0 漏检、0 误报、30/39 完全正确、F1 从 71.8% 升至 **98.4%**。

### Changed — 执行器路由收敛
- **`_select_executor_kind`**：新增 `"legacy"` 策略（始终线程池）；`"balanced"` 策略改为始终线程池（安全默认，避免小任务 IPC 开销）；仅 `"throughput"` 将 CPU 任务路由至进程池。
- **效果**：async compute 并行加速比：0.43x → **10.68x**。

### Changed — 性能：crash_log.lower() 去重
- **AnalysisContext** 新增 `crash_log_lower` 字段，构造时计算一次，6 个 detector 统一引用共享副本。消除大日志场景下 6→1 倍字符串分配。

### Fixed — 代码清理
- 删除未使用的 `_WORK_NS_PER_ITER` 常量及 `_estimate_task_work_ms` 方法。
- 修复 `test_ai_performance.py` 中 `shutdown()` 协程未 await 导致的 RuntimeWarning。
- `core.py` 局部 `import re` 提升到文件顶部。
- `version_conflicts.py` 删除两对子集冗余正则模式，消除重复冲突条目输出。

### Fixed — 测试改进
- COMP_003 预期标签补全 `"其他"`（`Critical injection failure` 触发 Mixin 检测器）。
- `test_numeric_only_modid_skipped` 补全断言（此前零断言，永远通过）。
- `TestResult` dataclass 添加 `__test__ = False` 消除 pytest 收集警告。

### Notes
- 本次改动集中在检测器和执行器层，UI 和 DLC 未变更。升级后建议跑一次 `test_ai_accuracy_full.py` 做基线复核。
- 进程池在 Windows `spawn` 下对小任务（<30ms）有 IPC 开销，仅建议在 `throughput` 模式 + 重计算场景下使用。

## v1.5.0 — 启动可信化与渲染诊断增强 (2026-04-25)

详细发布说明：见 [docs/RELEASE_NOTES_v1.5.0.md](docs/RELEASE_NOTES_v1.5.0.md)。

### 版本概览
- 这一版不是单点补丁，而是同时收敛三条主线：模型启动可信度、界面状态可观测性、渲染崩溃归因精度。

### Added
- 增加了 PyQt 大脑动画与主窗口状态联动能力，覆盖 `loading / active / error / idle` 四类运行态。
- 补充渲染异常规则，新增覆盖层注入冲突、Vulkan 原生窗口占用冲突、驱动模块访问冲突等高价值信号。
- 引入渲染模组组合冲突分析，可识别 OptiFine 与 Sodium/Embeddium/Rubidium 叠加等高风险组合。
- 新增硬件分析与 GL 检测器的专项回归测试，用于防止后续规则迭代回退。

### Changed
- AI 启动流程从“只初始化核心对象”改为“初始化 + 语义模型预热 + ready 校验”，启动状态更可信。
- 语义分析线程改为自动挂载并检测可用计算单元，同时输出更清晰的候选评分信息。
- 硬件面板建议由单一通用提示升级为分类动作建议，诊断信息可直接转化为排查步骤。
- 主界面状态文案与动画状态同步机制重构，分析进度、完成和异常路径统一了反馈节奏。

### Fixed
- 解决“模型暂不可用”误报链路，移除无效硬编码兜底提示。
- 修复 `InvalidInjectionException` 场景被渲染候选误导的问题，改为强规则优先输出。
- 修复重复模组检测中数字前缀 JAR 的伪命名误判，降低重复依赖噪声。
- 改善渲染异常建议泛化过强的问题，针对不同根因给出差异化建议。

### Notes
- 本次发布包含较大范围的工程化调整（UI、检测器、服务与测试），建议升级后先用一份已知崩溃日志做基线复核。

## v1.4.0 — UI框架迁移与性能优化 (2026-03-27)

### 影响概览
- **影响等级**: 🟢 **高** - 重大UI框架迁移(Tkinter → PyQt6) + 核心性能优化
- **关键变更**: 
  - 🎨 **UI框架升级**: 从Tkinter迁移至PyQt6，引入现代化玻璃拟态设计
  - 📱 **高分屏支持**: 新增高DPI缩放支持和智能屏幕适配系统
  - ⚡ **性能优化**: 线程池/进程池大小优化、缓存系统改进、结果缓存机制
  - 📦 **依赖分层**: AI依赖移至可选依赖，基础安装更轻量
  - 🧩 **架构增强**: 新增屏幕适配器、窗口状态管理器、工作线程系统

### Added
- **智能屏幕适配系统**：新增 `ScreenAdapter` 和 `WindowStateManager` 类。
  - 窗口尺寸根据屏幕自动计算（宽度 66%、高度 75%，带限制）。
  - 支持物理尺寸精确适配（PPI 计算），自动回退到比例法。
  - 窗口状态记忆功能，使用 QSettings 持久化。
  - 多显示器支持，记录窗口所在屏幕。
  - 公开方法：`reset_to_default()` 和 `get_current_screen_info()`。
- **自动化测试分析增强**：自动化测试现在使用完整的检测器系统。
  - 集成 `DetectorRegistry` 深度检测器（OOM、依赖缺失、Mixin冲突等）。
  - 新增"生成后自动执行分析"选项。
  - 统计报告增加检出率计算。
- **现代化样式系统**：
  - 5种配色方案: 海洋蓝、薄荷绿、暮光紫、珊瑚粉、深空灰。
  - 玻璃拟态设计: 渐变背景、阴影效果、圆角卡片。
  - 渐变按钮: 主按钮、成功、警告、错误等状态样式。
- **工作线程系统**：`AnalysisWorker`, `AIInitWorker`, `AutoTestWorker`。
  - 异步分析流程支持进度回调 (10% → 20% → 40% → 70% → 100%)。

### Changed
- **UI框架迁移 (Tkinter → PyQt6)**：
  - 新增 `main_window_pyqt.py` - 主应用窗口 `SiliconeCapsuleApp`。
  - 新增 `screen_adapter_pyqt.py` - 屏幕适配系统。
  - 新增 `workers_pyqt.py` - 后台工作线程。
  - 新增 `styles_pyqt.py` - 样式系统 `ColorPalette`。
  - 新增 `ui/dpi_awareness.py` - DPI感知支持。
- **代码架构重构**：将 3000 行的 `app_pyqt.py` 拆分为模块化结构。
  - `styles_pyqt.py`：配色方案和 CSS 生成（~450 行）。
  - `screen_adapter_pyqt.py`：智能屏幕适配（~280 行）。
  - `workers_pyqt.py`：工作线程类（~340 行）。
  - `main_window_pyqt.py`：主窗口类（~1200 行）。
  - `app_pyqt.py` 已删除，入口统一为 `main.py`。
- **诊断规则扩展**：新增 6 个诊断规则覆盖更多测试场景。
  - `out_of_memory`、`missing_dependency`、`mixin_conflict`。
  - `version_conflict`、`gl_error`、`compound_error`。
- **高DPI环境变量优化**：将环境变量设置移至文件最开头，确保在任何导入之前执行。
- **线程池/进程池优化**：
  - 线程池大小: 固定50 → `min(CPU核心数*4, 32)`。
  - 进程池大小: `CPU核心数` → `min(CPU核心数, 8)`。
  - 线程命名: 无 → `BrainWorker`。
- **缓存键生成优化**：使用hash缓存替代深拷贝+JSON序列化，大幅提升性能。
- **诊断引擎结果缓存**：新增 `OrderedDict` LRU缓存机制，最大100条。

### Fixed
- 修复 `generate_batch` 函数调用参数顺序问题。
- 修复 `QGraphicsDropShadowEffect` 导入位置错误（应从 QtWidgets 导入）。
- 修复多个导入路径问题（config_service、log_service 等）。

### Removed
- 移除 `app_pyqt.py` 入口文件，统一使用 `main.py`。

## v1.3.1 — 最新体验与依赖架构优化 (2026-03-17)

本次更新聚焦于界面体验打磨与系统依赖管理的规范化重构，全面回归开源社区通行规范。

### Added
- 新增 PyQt6 拟态主题体验路径，推进从 Tkinter 到 PyQt6 的界面演进。
- 新增高分屏适配能力，改善不同分辨率下的显示一致性。
- 新增 Python 微版本精确展示（例如 3.13.12），便于排错与环境核对。
- 新增安全与质量说明整合：将渗透测试报告与安全封装实践纳入本次更新记录。

### Changed
- 依赖管理升级为 Optional Dependencies 标准方案，重负载 AI 组件拆分为 ai 可选安装组。
- 基础安装路径继续轻量化，requirements.txt 保持核心依赖，降低无独显设备的安装成本。
- 文档安装指引同步更新：基础安装与 AI 增强安装路径分离，部署流程更清晰。
- 诊断与性能链路说明整合：补充检测器优化、正则缓存提速、数据库与历史回溯能力增强等内容。

### Removed
- 移除非标准、侵入式的安装拦截思路，避免对 CI/CD 与社区协作链路造成潜在干扰。

## v1.3.0 — Brain System 核心算法重构与学习引擎增强 (2026-03-10)
本次更新聚焦于 Brain System 核心算法的全面重构，引入断路器模式、动态 TTL 缓存、健康检查等生产级特性，同时大幅增强学习引擎的特征提取能力。

### Brain System 核心算法重构 (Core Algorithm Refactoring)
- **Feat (断路器模式)**：在 `retry.py` 中实现完整的断路器（Circuit Breaker）模式。
    - 三态断路器：CLOSED → OPEN → HALF_OPEN 自动状态机。
    - 可配置的失败阈值、恢复超时、成功阈值。
    - 全局重试预算管理（`RetryBudget`），防止重试风暴。
- **Feat (任务超时控制)**：`compute()` 方法支持可配置超时和优先级。
    - 慢任务追踪和警告日志。
    - 超时后自动取消任务。
- **Feat (动态 TTL 缓存)**：`LruTtlCache` 支持根据访问频率动态调整 TTL。
    - 热点数据自动延长过期时间（最多 3x）。
    - 手动 TTL 刷新接口 `refresh_ttl()`。
- **Feat (健康检查端点)**：新增完整的健康检查系统。
    - `health_check()`：返回系统状态、组件状态、性能指标和问题列表。
    - `is_healthy()`：快速健康状态检查。
    - `get_ready_status()`：Kubernetes 就绪探针支持。
- **Feat (配置验证和回滚)**：配置热更新增加验证和回滚机制。
    - `_validate_config()`：验证缓存、重试、线程池等配置参数。
    - `rollback_config()`：回滚到上一个有效配置。
    - 更新失败自动回滚。

### 学习引擎增强 (Learning Engine Enhancement)
- **Improve (特征提取算法)**：特征提取从 8 种扩展到 11 种。
    - 新增：错误代码 (`error_code:XXX`)、线程名称 (`thread:Render-Thread`)、关键包名 (`pkg:software.bernie`)。
    - 扩展关键模式：NPE、安全异常、文件未找到、并发修改等 24 个模式。
- **Improve (加权相似度计算)**：使用加权 Jaccard 相似度替代简单 Jaccard。
    - 关键特征权重：trait=3.0, exception=2.5, mod=2.0。
    - 关键特征匹配奖励机制。
- **Feat (快速索引系统)**：基于 trait + exception 构建快速查找键，查找效率从 O(n) 提升到 O(1)。
- **Feat (批量学习支持)**：`batch_learn()` 方法支持批量导入崩溃模式。
- **Feat (模式导入导出)**：`export_patterns()` / `import_patterns()` 支持模式持久化。

### 检测器系统改进 (Detector System Improvement)
- **Feat (检测器优先级)**：`Detector` 基类新增 `get_priority()` 和 `get_confidence()` 方法。
    - PRIORITY_CRITICAL=0, PRIORITY_HIGH=10, PRIORITY_NORMAL=50, PRIORITY_LOW=100。
    - Registry 自动按优先级排序运行检测器。
- **Fix (版本冲突误报)**：修复缺失依赖检测器误报版本冲突的问题。
    - 增加冲突指示器检测，排除纯冲突场景。
    - 版本冲突检测器增加更多冲突模式和详情提取。
- **Improve (版本冲突检测器)**：增强冲突检测能力。
    - 提取具体冲突详情（mod A vs mod B）。
    - 中文输出结果。

### DLC 系统改进 (DLC System Improvement)
- **Feat (热加载回滚)**：`reload_dlc_file()` 支持失败自动回滚。
    - 备份现有 DLC。
    - 加载失败时自动恢复旧版本。
    - 返回 `(count, success)` 元组。

### 代码质量改进 (Code Quality Improvement)
- **Fix (异常处理)**：将所有 `except Exception: pass` 改为有意义的日志记录。
- **Fix (类型注解)**：为 Mixin 类添加 Protocol 和类型注解。
    - `AnalysisMixinHost`、`FileOpsMixinHost`、`UIMixinHost` Protocol。
    - 类级别属性类型注解。
- **Fix (诊断错误)**：修复 `ProcessPoolExecutor` 私有属性访问问题。

### 测试结果 (Test Results)
- AI 准确性测试：**100.0%**（10/10 通过）
- Brain System 评分：**3.3/5 → 4.5/5**

---

## v1.2.0 — 架构与性能基石升级 (2026-03-01)
本次更新重点解决系统长期存在的高并发写入锁死、内存泄漏隐患，并将 AI 算力和传统算力性能双双推向商业级标准。这也是朝着 v1.2“核心性能与可观测性”计划迈出的实质性一步。

### 主要架构与安全修复 (Core Architecture & Security)
- **Security (修复安全漏洞)**：移除了 `launcher.py` 中危险的 `site.addsitedir` 调用，避免任意代码执行风险。
- **Fix (多线程 UI 安全)**：彻底修复了 `app_analysis_mixin.py` 中后台分析线程直接修改 Tkinter UI 元素的线程越界隐患。
- **Fix (解决内存泄漏)**：修复了 `RegexCache` 无限膨胀导致的严重内存溢出隐患，并将其缓存 `.clear()` 生命周期挂载到日志分析主管道中。
- **Refactor (数据库高并发重构)**：重写了 `DatabaseManager`，抛弃了单纯的 `is_locked` 轮询，引入基于 `queue` 和独立 `DB-Writer-Thread` 的单写多读（SWMR）架构。彻底消灭多线程解析日志时的 `database is locked` 崩溃问题。

### 引擎算力暴涨 (Engine & AI Performance)
- **Improve (AI语义引擎换代)**：将笨重的 `microsoft/codebert-base` 替换为轻量级 `sentence-transformers/all-MiniLM-L6-v2`。
    - 内存占用从 610MB 暴降至 **308MB**。
    - 单条推理耗时下降至 **7-11ms**。
- **Fix (解决Transformer各向异性)**：为 `CodeBertDLC` 引入带掩码的 `Mean Pooling` (平均池化) 与 `L2 归一化`。同类错误和异类错误的余弦相似度差距（如 0.99 降至 0.22）终于被真正拉开，实现了高准度特征对比。
- **Improve (传统正则表达式引擎提速)**：将 `CrashPatternLearner` 中的重度堆栈捕获正则提升为模块级预编译（`re.compile`），极大地降低了纯 CPU 下的迭代开销。
- **Improve (算法复杂度降级)**：对本地特征对比（Jaccard）引入 `_cached_set` 内存缓存，并在入口处前置类型转换。通过消灭 O(N) 的冗余 `set(list)` 转换，实现高并发无感检索。

---

## v1.1.1 — 错误吞没与监控修复 (2026-02-12)
跟代码里藏雷的 `except: pass` 们干了一架，总算把这些沉默杀手给揪出来了。

- **Fix**: 干掉了5处 `except: pass` 静默吞错。现在至少会往控制台吐点错误信息，排查问题不用瞎猜了。
- **Fix**: 修复了 `ResourceLimiter` 之前 `_get_memory_usage()` 永远返回0的问题。现在接上了 psutil，真正实现了内存和CPU资源监控。
- **Fix**: 修复 URL 拼接以前直接用 `replace(' ', '+')` 遇到特殊字符就炸的问题。现在改用 `urllib.parse.quote_plus`。
- **Fix**: 修复 `LogService` 缓存比较用了 `is` 而不是 `==`，导致缓存形同虚设的问题。现在按值比较，缓存终于生效了。
- **Refactor**: 把硬编码的 2000 字符截断，改成了常量 `MAX_LOG_LINE_LENGTH`。
- **Improve**: 配置加载出错时增加日志提示。

---

## v1.1.0 — 大版本发布与分发优化 (2026-02-06)
这次是工程化问题的里程碑版本：把可执行分发、体积与工程化问题当成第一要务来处理，顺手把文档和部分注释洗了个澡，让它看起来像个真实在被人维护的项目。

### 主要亮点
- **构建与分发**：引入 `LITE`/`FULL` 两套产物策略，`LITE` 包含核心可执行与配置，用于补丁发布与快速验证；`FULL` 为独立运行版（含所有依赖）。
- **大文件处理**：实现了二进制切分逻辑（`tools/package_release.py`），自动将过 1.9GB 的 ZIP 拆成 `.001/.002` 分卷，解决了 GitHub 单文件 2GB 限制的现实问题。
- **依赖拆分**：将重量级 ML 依赖从核心模块脱钩（`mca_core` 仅保留轻量逻辑），默认不强制安装 `torch`，避免“拉一堆大包只为看日志”的尴尬。
- **文档与可维护性**：全面清理了“营销式”措辞，README、CHANGELOG、脚本注释均改为实用、直白的工程师风格。
- **基础健康检查**：增加签名校验说明（DLC `.sig`）、LRU 缓存策略与重试策略的文档注释，便于运维和安全审计。

### 破坏性变更与注意事项
- **API 和插件**：DLC 接口未做大改动，但部分老旧 DLC 如果依赖于内置 `torch` 可能需要调整（把 `torch` 当作可选依赖并在 DLC 内部做退化处理）。
- **体积策略**：默认分发 LITE，若你是运维并需要完整体验（可视化 + 语义分析），请使用 FULL 并准备好合并分卷与安装可选依赖。
- **遗留问题**：UI 在处理超大文件时仍会出现短暂卡顿（2–3 秒），这是遗留代码在主线程做 I/O 的直接后果（*注：此问题已在 v1.2.0 的数据库无锁队列与主管道重构中解决*）。

---

## v1.0.0 — 核心解耦与初版构建 (2026-02-06)
总算把核心逻辑和那一大坨 PyTorch 依赖拆开了。

- **Refactor**: 拆分了 `mca_core` 和外部库。
- **Fix**: 修复了构建脚本 `pack.bat` 处理路径空格崩溃的问题（大部分情况下）。
- **Feat**: 增加了一个 "LITE" 构建目标（完整版构建出来有 2.8GB，GitHub 根本传不上去）。
- **Workaround**: 在 `package_release.py` 里手写了个文件切分逻辑。虽然丑了点，但能用。

---

## v0.9.0 — 内部测试版本 (Pre-1.0)
- 所谓的 "Neural" 分析其实就是一堆随机启发式算法。

## v0.4.0 — 原型阶段 (Pre-1.0)
- 纯纯的正则地狱。
