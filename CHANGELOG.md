# Changelog

当前版本见顶部第一条。本文件是唯一发布历史来源。

---

## v2.1.1 — 安全纵深加固、算力 Bug 修复与工程卫生 (2026-06-11)

### 安全 — 全仓渗透测试发现的 14 项漏洞全部修复

| ID | 严重性 | 漏洞 | 修复 |
|------|----------|------|------|
| VULN-001 | CRITICAL | DLC 直接 `exec_module` 无安全验证 | `discovery.py` — AST 分析 + 危险调用/导入拦截 |
| VULN-002 | CRITICAL | PatchDownloader SSRF（`file://` 等协议未过滤） | `patch_downloader.py` — scheme 白名单 + `ipaddress` 精确内网判断 |
| VULN-003 | CRITICAL | Admin 沙箱 `__import__` 未拦截 → 任意命令执行 | `patch_sandbox.py` — 全局 `_safe_import` 白名单；`core.py` — API 拒 admin 上传 |
| VULN-004 | HIGH | BYPASS_PATTERNS 正则回溯 ReDoS | `plugins.py` — `.*` → `.{0,200}?` 非贪婪限制 |
| VULN-005 | HIGH | 补丁上传 TOCTOU 竞态 | `core.py` — 先 hash 后写入交叉比对 |
| VULN-006 | HIGH | API 无 CSRF 保护 | `server.py` — Origin/X-CSRF-Token 中间件 |
| VULN-007 | HIGH | Auth localhost 过度宽松 | `auth.py` — Host header 验证 + 未配置 token 警告 |
| VULN-008 | HIGH | 下载路径 `../` 遍历注入 | `core.py` — basename + realpath 边界检查 |
| VULN-009 | MEDIUM | 路径脱敏不完整 | `prompt_generator.py` — 扩展盘符/APPDATA/opt/var 模式 |
| VULN-010 | MEDIUM | SQLite `read_uncommitted=ON` 脏读 | `database.py` — 改为 OFF |
| VULN-011 | MEDIUM | `sys.path.insert(0)` 劫持风险 | `patch_api.py` — 改为 append |
| VULN-012 | MEDIUM | 错误消息泄露内部路径 | `patch_api.py` — `_safe_error_message()` |
| VULN-013 | LOW | `compute_content_hash` 用途不明 | `integrity.py` — 添加密码场景警告注释 |
| VULN-014 | LOW | 日志无限增长 | 已有 10MB×5 轮转，无需额外修复 |

详细报告：`docs/security/PENTEST_REPORT_v2.1.0_COMPREHENSIVE.md`

### Fixed — 核心算力 Bug

- **BUG-C01 — 注意力池化参数留 CPU**：`torch.nn.Parameter(...).to(device)` 返回值被丢弃（`.to()` 非原地操作），每次 `encode_text` 都 GPU↔CPU 拷贝。修复为 `torch.randn(..., device=self.device)`。
- **BUG-C05 — 鲁棒聚合死代码**：`encode_text` 开头 `clear()` 缓冲区 → `_robust_aggregate` 内 `len(buffer) < 4` 永远成立。Welsch 加权/Trimmed Mean 从 v2.1.0 起从未生效。移除每调用清零，提供显式 `reset_robust_buffer()`。
- **BUG-C07 — `"warn"` 子串过匹配**：`_classify_severity` 中 `"warn"` 匹配所有含 `"warning"/"WARN"` 的日志 → 正常日志误判 MEDIUM。改为精确词汇。
- **BUG-001 — SSRF 修复的 startswith 误杀**：`startswith("127.")` 拦截 `127.example.com` 合法域名。改用 `ipaddress` 模块精确判断。
- **BUG-002 — `publish_async` 线程池泄漏**：每次调用创建+销毁 `ThreadPoolExecutor`。改为复用单例后台线程。
- **BUG-003 — `unsubscribe` 分发期间不安全**：直接重建列表绕过 `_is_dispatching` 保护。改为 `_remove_handler()` 安全路径。
- **BUG-004 — 检测器路径缺失 AI prompt**：正则回退路径生成 `ai_prompt`，检测器路径跳过。`_convert_context_to_results` 统一生成。

### Changed — 工程卫生

- **根目录整理**：`ROADMAP_v1.2.md`、`REQUIREMENTS.md`、`BUILD_SECURE.md`、`KNOWN_ISSUES.md` → `docs/`；`build_secure.py`、`pack.bat` → `scripts/build/`；`app_icon.ico` → `assets/`。更新 6 处交叉引用。
- **死目录清理**：删除 `src/data/`（冗余副本）、`src/mca_core/ui/`（空目录，零引用）。
- **依赖修复**：`requirements.txt` `PySide6` → `PyQt6`（全仓实际使用 PyQt6）。
- **.gitignore 补充**：`tools/sign_patch.py`（自动生成）、`PENETRATION_TEST_REPORT*.md`、`docs/security/`。
- **渗透报告归位**：3 份散落根目录的报告移入 `docs/security/`。

### Added

- `test_dlc_security_validation.py` — DLC AST 安全验证 10 项测试。
- `test_patch_security.py` — 更新 `test_admin_os_allowed` → `test_admin_os_import_blocked` + `test_admin_safe_math_allowed`。

### Test Coverage

- 安全测试：**32 passed**（patch 16 + input_sanitizer 5 + core_security 1 + dlc_security 10）
- 全量语法验证：11/11 修改文件编译通过

---

## v2.1.0 — 架构重构、性能优化与安全修复 (2026-06-10)

### 版本概览
本版本聚焦架构重构与性能优化：(1) BrainCore 巨型类拆分为 DLCManager 子模块；(2) EventBus/Registry 惰性优化；(3) DiagnosticEngine 策略模式解耦；(4) 多项安全漏洞修复；(5) 原生算力优化（NUMA 感知、融合算子）。

---

### Changed — 架构重构

- **BrainCore 拆分**：提取 `DLCManager` 子模块（303 行），巨型类从 1302 行瘦身，DLC 方法改为委托桩。
- **EventBus 惰性排序**：subscribe 不再立即 O(n log n) 排序，改为 publish 时惰性排序，减少冷启动开销。
- **DetectorRegistry 懒加载**：首次调用 list/run_all 时触发 load_builtins()，避免导入级联。
- **DiagnosticEngine 策略模式**：新增 `DetectorExecutionStrategy` Protocol，执行逻辑解耦为 `ThreadPoolExecutionStrategy`。

### Fixed — 安全漏洞修复

- **插件系统 `_validate_imports` 静默放行**：返回值改为 `list[str]`（违规模块列表），不再静默忽略。
- **插件系统重复 hash 计算**：`_validate_plugin_code` 返回 SHA-256 hash，调用方复用避免重复文件读取。
- **DLC DistributedComputing 竞态条件**：stop_workers 先发毒丸再设置 is_running=False，修复 worker 阻塞。
- **DLC disable() 不释放 GPU**：改为调用 _pre_shutdown/_post_shutdown 释放资源。
- **CodeBertDLC shutdown 绕过基类**：GPU 清理逻辑移入 _pre_shutdown，shutdown 调用 super()。
- **Discovery sys.modules 泄漏**：load_dlc_classes_from_file 用 try/finally 清理临时模块。
- **沙箱 `__import__` 安全漏洞**：从 RESTRICTED_BUILTINS 移除，RESTRICTED 级别禁止动态导入。
- **沙箱 open() 分配顺序脆弱**：用 pop 明确禁止，消除重复 elif 分支。

### Added — 原生算力优化

- **NUMA 感知 CPU 设备**：`NumaCPUDevice` 类支持 NUMA 节点绑定与内存池预分配。
- **融合算子**：`FusedMatMulReLU`、`FusedLinearReLU` 减少中间分配。
- **标准化算子**：`BatchNorm1D`、`LayerNorm` 支持批量训练。
- **内存优化**：TensorNode 与 Function 子类添加 `__slots__`。
- **缓存优化**：`get_numpy_compat` 使用 `@lru_cache(maxsize=8)`。

---

## v2.0.0 — TKinter→PyQt6 架构统一、补丁安全加固、检测器引擎跃升 (2026-06-08)

### 版本概览
这是一个**破坏性大版本**，覆盖三条主线：(1) **彻底移除 TKinter 旧架构**，项目从双轨制统一为纯 PyQt6；(2) 补丁系统从默认 admin 无限制执行改为三级权限沙箱 + AST 代码验证；(3) 检测器引擎大幅优化，新增 5 种检测器、诊断引擎 v3.0、UI 扁平化重设计、BrainCore 延迟初始化。

**升级注意**：TKinter 相关 API 全部移除，如有依赖请迁移至 PyQt6 版本。

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

## v1.5.3 — 仪表盘、并行检测引擎与可观测性 (2026-05-28)

### Added
- **DashboardController**：独立于 BrainCore 的仪表盘控制器（MetricsCollector + AnomalyDetector + AlertManager + HistoryStore），解决面板依赖 BrainCore 启用才能显示的问题。
- **DiagnosticEngine v3.0**：线程池并行执行（8 workers × 15s 超时），LRU+TTL 缓存，置信度评分，结果去重。
- **PatchManager v2.0**：PatchCache（mtime 失效 LRU）、PatchDownloader（指数退避重试+SHA-256 校验）、PatchMonitor（守护线程监控）。

### Fixed
- 补丁子系统序列化错误（PatchRecord 直接存入缓存 → 改为 dict）。
- 仪表盘检测率/误报率始终为 0（_dashboard_controller 未连接）。
- 检测器重复执行导致结果翻倍（AutoTestWorker 同时走 engine 和 registry）。
- 告警风暴：AnomalyDetector 添加 60s 冷却去重（消除 98.6% 重复告警）。
- Alert ID 碰撞：改为 `uuid.uuid4().hex[:16]`。
- LruTtlCache 缓存污染：添加活跃 ID 追踪。

### Changed
- 版本号统一 `brain_system/__init__.py`，`pyproject.toml` 用 dynamic attr 同步。
- 移除 `brain_system/dlcs/` pass-through shim（5 文件 + 整个目录）。
- 删除 `patch_manager/cli.py`、`run_patch_manager.py`（零引用）。
- `/ready` 移除 dlcs 字段，`/metrics` 仅限 localhost 访问。

### Tests
700+ tests passed, 0 failures

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

## v1.4.0 — Tkinter→PyQt6 UI 迁移 (2026-03-27)

重大 UI 框架迁移：从 Tkinter 全面切换至 PyQt6。3000 行单文件拆分为 styles/screen_adapter/workers/main_window 模块化结构。

### Added
- PyQt6 主窗口 `SiliconeCapsuleApp`、智能屏幕适配（QSettings 持久化）、5 种配色方案。
- `AnalysisWorker` / `AIInitWorker` / `AutoTestWorker` 工作线程系统。
- 自动化测试集成 DetectorRegistry + 检出率统计。

### Changed
- 线程池：固定 50 → `min(CPU×4, 32)`；进程池：`CPU` → `min(CPU, 8)`。
- 诊断规则新增 6 个模式（OOM、依赖缺失、Mixin、版本冲突、GL 错误、复合错误）。
- 缓存键优化：hash 替代深拷贝+JSON 序列化。

### Removed
- `app_pyqt.py` 入口，统一为 `main.py`。

## v1.3.1 — 依赖架构规范化 (2026-03-17)

### Changed
- 依赖管理升级为 Optional Dependencies 标准方案（ai/crypto/observability/server/config/ha 分组）。
- 文档安装指引同步更新，基础安装与 AI 增强路径分离。

## v1.3.0 — Brain System 算法重构与学习引擎增强 (2026-03-10)

### Added
- **断路器模式**（`retry.py`）：三态 CLOSED→OPEN→HALF_OPEN 状态机，全局重试预算。
- **动态 TTL 缓存**：热点数据自动延长过期（最多 3x），手动 refresh_ttl()。
- **健康检查系统**：`health_check()` / `is_healthy()` / `get_ready_status()`（Kubernetes 就绪探针）。
- **配置验证与回滚**：`_validate_config()` → `rollback_config()`，更新失败自动回滚。
- **学习引擎增强**：特征提取 8→11 种，加权 Jaccard 相似度（trait×3.0, exception×2.5, mod×2.0），快速索引 O(n)→O(1)。
- **检测器优先级**：PRIORITY_CRITICAL=0～LOW=100，Registry 自动排序。

### Fixed
- 缺失依赖检测器误报版本冲突；版本冲突检测器增加详情提取。
- `except Exception: pass` → 有意义的日志。Mixin 类添加 Protocol 类型注解。

### Tests
AI 准确性测试：100.0%（10/10 通过）
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

### Fixed

- 修复 5 处 `except: pass` 静默吞错，改为输出错误信息到控制台。
- 修复 `ResourceLimiter._get_memory_usage()` 返回 0 的问题，接入 psutil 实现真实的内存和 CPU 监控。
- 修复 URL 拼接使用 `replace(' ', '+')` 导致特殊字符异常的问题，改用 `urllib.parse.quote_plus`。
- 修复 `LogService` 缓存比较使用 `is` 而非 `==` 导致缓存失效的问题。

### Changed

- 硬编码的 2000 字符截断改为常量 `MAX_LOG_LINE_LENGTH`。
- 配置加载出错时增加日志提示。

---

## v1.1.0 — 大版本发布与分发优化 (2026-02-06)

### 版本概览
工程化里程碑版本，聚焦可执行分发、体积优化与文档规范化。

### Added — 构建与分发

- 引入 `LITE`/`FULL` 两套产物策略：`LITE` 包含核心可执行与配置，用于补丁发布与快速验证；`FULL` 为独立运行版（含所有依赖）。
- 实现二进制切分逻辑（`tools/package_release.py`），自动将超过 1.9GB 的 ZIP 拆分为 `.001/.002` 分卷，解决 GitHub 单文件 2GB 限制。

### Changed — 依赖与文档

- 将重量级 ML 依赖从核心模块脱钩（`mca_core` 仅保留轻量逻辑），`torch` 改为可选依赖。
- 全面清理文档措辞，README、CHANGELOG、脚本注释改为工程师风格。
- 增加签名校验说明（DLC `.sig`）、LRU 缓存策略与重试策略的文档注释。

### Notes

- DLC 接口未做大改动，依赖内置 `torch` 的老旧 DLC 需调整为可选依赖并做退化处理。
- 默认分发 LITE，完整体验（可视化 + 语义分析）需使用 FULL 并合并分卷。
- UI 处理超大文件时仍有 2–3 秒卡顿（已在 v1.2.0 解决）。

---

## v1.0.0 — 核心解耦与初版构建 (2026-02-06)

### Changed

- 拆分 `mca_core` 与外部库，核心逻辑与 PyTorch 依赖分离。

### Fixed

- 修复构建脚本 `pack.bat` 处理路径空格崩溃的问题。

### Added

- 增加 "LITE" 构建目标，完整版构建产物约 2.8GB。
- 在 `package_release.py` 实现文件切分逻辑。

---

## v0.9.0 — 内部测试版本 (Pre-1.0)

早期内部测试版本，基于启发式算法实现基础诊断能力。

---

## v0.4.0 — 原型阶段 (Pre-1.0)

原型阶段，核心诊断逻辑基于正则表达式实现。