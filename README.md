# Minecraft Crash Analyzer (MCA)

<div align="center">
  <img src="docs/OIP-C.jpg" alt="MCA Icon" width="150" style="border-radius: 20px;">
  <p><b>面向复杂 Mod 环境的 Minecraft 崩溃诊断平台：高并发解析 + AI 语义分析 + 可扩展检测器。</b></p>
</div>

---

## 为什么是 MCA

MCA 的目标不是"只告诉你崩了"，而是尽量回答三件事：
- 崩溃由哪个组件触发。
- 多个候选根因里哪个最可疑。
- 下一步该怎么修。

它由规则检测器、特征提取器、学习组件和可选 AI 语义层共同工作，适用于以下场景：
- 大型整合包启动崩溃排查。
- 服务端高频报错归因。
- 版本升级后的兼容性回归定位。
- 团队协作时的统一故障分析口径。

---

## 核心能力

- **高并发日志分析管线**：面向大体量日志与高频问题复现。
- **并行诊断引擎 v3.0**：多检测器并发执行，15 秒超时保护，F1 精度达 98.4%。
- **补丁系统安全加固**：AST 静态代码验证 + 三级权限沙箱（restricted/standard/admin）。
- **仪表盘实时监控**：异常检测、告警管理、历史数据持久化。
- **可扩展 DLC 生态**：可持续叠加检测规则与策略。
- **启动加速**：BrainCore 延迟初始化，冷启动减少 2-30s。

---

## 安装矩阵

本项目采用 Python Optional Dependencies 标准管理依赖，不劫持安装流程。

### 1) 基础安装（推荐）

适合无独显、轻薄本、CI 验证、纯规则分析场景。

```bash
pip install -r requirements.txt
```

### 2) AI 增强安装（可选）

在基础能力之上追加语义分析组件。

```bash
pip install -e .[ai]
```

说明：仓库已提供安装与检测脚本，建议优先使用。
- Windows 一键安装（含 CUDA 12.1 选项）：`scripts\setup\install_env.bat`
- 安装后检测 PyTorch/CUDA 状态：`python scripts/check_gpu.py`
- 若需自定义 CUDA 版本，再按 PyTorch 官方命令安装对应 wheel 后执行 `pip install -e .[ai]`。

---

## 快速开始

### 1) 环境准备

建议 Python 3.13.x（当前已验证 3.13.12）。

```bash
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate    # Linux/Mac

pip install -r requirements.txt
```

### 2) 启动

```bash
python main.py
```

默认启动 PyQt6 客户端，包含高分屏适配与状态栏 Python 精确版本展示。

### 3) 基本使用流程

- 导入崩溃日志或粘贴日志内容。
- 执行分析并查看主结论与置信信息。
- 根据建议项处理依赖、冲突、JVM 参数或版本不匹配问题。
- 如需更深入的语义推断，再开启 AI 增强组件。

---

## 项目结构

- `src/mca_core/`: 核心解析引擎、检测器、补丁管理系统、仪表盘、服务层。
- `src/mca_core/detectors/`: 可扩展检测器（12 种：依赖缺失、模组冲突、启动崩溃等）。
- `src/mca_core/dashboard/`: 仪表盘控制器（指标收集、异常检测、告警管理）。
- `src/mca_core/patch_manager/`: 补丁管理（验证器、沙箱、下载器、缓存）。
- `src/brain_system/`: AI 语义分析与学习核心（BrainCore/DLC 框架）。
- `src/dlcs/`: DLC 扩展包入口。
- `plugins/`: 可插拔检查器与扩展能力。
- `data/`: 规则库、历史数据与运行时数据。
- `tests/`: 单元测试、集成测试、安全测试与性能验证。
- `scripts/`: 开发辅助、基准测试、构建与维护脚本。

---

## 质量与安全

- **测试覆盖**：823 项测试，覆盖核心链路（规则、服务、缓存、安全、仪表盘等）。
- **补丁安全**：AST 静态分析禁止 `exec/eval/compile`，三级权限沙箱隔离执行环境。
- **服务端安全**：`/ready` 移除敏感字段，`/metrics` 仅允许本地访问。
- **依赖策略**：遵循社区标准，避免隐式安装行为影响 CI/CD 与协作可追踪性。

---

## 近期更新（v1.5.5）

- 移除 TKinter 旧架构，统一为纯 PyQt6，删除约 8.9K 行死代码。
- 补丁系统新增 AST 验证器与三级权限沙箱，修复任意脚本可执行漏洞。
- 检测器引擎并行化，新增 5 种检测器，F1 精度提升至 98.4%。
- 新增仪表盘实时监控、异常检测与告警管理。
- BrainCore 延迟初始化，冷启动减少 2-30s。

完整记录请查看 [CHANGELOG.md](CHANGELOG.md)。
已知问题请查看 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)。

### 版本口径说明

- 当前发布版本：以 `src/brain_system/__init__.py` 的 `__version__` 与 [CHANGELOG.md](CHANGELOG.md) 顶部条目为准。
- 历史发布记录：仅在 [CHANGELOG.md](CHANGELOG.md) 维护完整版本序列（v1.0.0 到最新）。
- 规划与模板文档：如 `ROADMAP`、`REQUIREMENTS` 中的版本可能是历史阶段或占位符，不作为当前版本声明。

---

## 构建与分发

如需打包可执行产物：

```bash
pack.bat
```

构建输出位于 `dist/`。对于超大体积产物，仓库内提供了分卷发布相关脚本思路。

---

## 常见问题（FAQ）

### Q1: 不装 AI 依赖能用吗？
可以。基础规则分析与大部分崩溃定位能力不依赖 AI 组件。

### Q2: 为什么建议先装基础依赖？
这样能先验证环境和核心功能，再按需扩展，安装速度和资源占用更可控。

### Q3: 适合哪类日志？
主要面向 Minecraft 客户端/服务端崩溃日志，尤其是复杂 Mod 环境下的多因素问题。

### Q4: 补丁系统安全吗？
v1.5.5 起新增 AST 验证器与三级权限沙箱，禁止 `exec/eval/compile` 等危险操作，默认 restricted 级别仅允许纯计算。

---

## 参与贡献

欢迎通过 Issue 或 PR 参与改进，建议优先提交以下类型：
- 新增可复现崩溃样本与最小复现说明。
- 检测规则优化与误报修复。
- 文档、测试与工具链改进。

提交前建议先运行测试并附上关键结果说明。
