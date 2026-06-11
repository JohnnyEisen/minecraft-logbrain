# Minecraft LogBrain — 崩溃日志智能诊断

面向复杂 Mod 环境的 Minecraft 崩溃诊断平台 —— 高并发解析 + AI 语义分析 + 可扩展检测器。

MCA 回答三件事：**哪个组件触发崩溃、哪个根因最可疑、下一步怎么修。**

---

## 核心能力

- **并行诊断引擎 v3.0** — 21 种检测器并发执行，15s 超时，F1 精度 98.4%
- **AI 语义分析** — MiniLM + 7 项优化（注意力池化、Int8 量化、CrossEncoder 重排序等）
- **补丁系统** — AST 静态验证 + 三级权限沙箱 + HMAC 签名，14 项安全漏洞全量修复
- **仪表盘** — 实时指标、异常检测、告警管理、历史持久化
- **DLC 生态** — 可热加载的扩展包（硬件加速、神经网络算子、CodeBERT 语义、分布式计算）
- **启动加速** — BrainCore 延迟初始化，冷启动缩短 2-30s

---

## 安装

```bash
# 基础安装（纯规则分析，无需 GPU）
pip install -r requirements.txt

# AI 增强安装（语义分析组件）
pip install -e .[ai]
```

辅助脚本：
- Windows 一键安装（含 CUDA）：`scripts/setup/install_env.bat`
- GPU 状态检测：`python scripts/setup/check_gpu.py`

---

## 快速开始

```bash
python -m venv venv
venv\Scripts\activate     # Windows
source venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
python main.py            # 启动 PyQt6 客户端
```

基本流程：导入崩溃日志 → 执行分析 → 查看结论与建议 → 按需开启 AI 增强。

---

## 项目结构

| 目录 | 用途 |
|------|------|
| `src/mca_core/` | 核心引擎、21 种检测器、补丁管理、仪表盘、服务层 |
| `src/brain_system/` | AI 语义分析（BrainCore/DLC 框架） |
| `src/dlcs/` | DLC 扩展包（硬件加速、NN 算子、CodeBERT、分布式） |
| `plugins/` | 可插拔检查器与扩展 |
| `data/` | 规则库、崩溃样本、历史数据 |
| `tests/` | 单元测试、集成测试、安全测试 |
| `scripts/` | 开发辅助、基准测试、构建脚本 |
| `docs/` | 架构文档、安全报告、更新日志 |

---

## 质量与安全

- **测试**：823+ 项，覆盖核心链路
- **安全**：最近一次全仓渗透测试发现并修复 14 项漏洞（含 3 个 CRITICAL）→ `docs/security/`
- **补丁**：AST 禁止 `exec/eval/compile`，三级沙箱，HMAC 签名验证
- **服务端**：`/ready` 已脱敏，`/metrics` 仅本地访问，CSRF 保护
- **依赖**：Python Optional Dependencies 标准，不劫持安装流程

---

## 近期更新（v2.1.1）

- **安全纵深加固**：DLC 加载增加 AST 验证、PatchDownloader SSRF 修复（ipaddress 精确白名单）、Admin 沙箱 `__import__` 拦截、14 项漏洞全量修复
- **算力 Bug 修复**：注意力池化参数 GPU 停留修复、鲁棒聚合死代码激活、"warn" 过匹配修正
- **工程卫生**：根目录文件归位、死目录清理、依赖修复（PySide6→PyQt6）

完整记录：[CHANGELOG.md](CHANGELOG.md) | 已知问题：[KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)

---

## 构建

```bash
scripts/build/pack.bat    # PyInstaller 打包
```

输出：`dist/MCA_Brain_System_vX.Y.Z/`

---

## FAQ

**不装 AI 依赖能用吗？** 可以。基础规则分析不依赖 AI 组件。

**补丁系统安全吗？** v2.0.0 起 AST 验证 + 三级沙箱。v2.1.1 新增 DLC 验证 + Admin 沙箱加固 + SSRF 防护。

**适合什么日志？** Minecraft 客户端/服务端崩溃日志，尤其是复杂 Mod 环境的整合包。

---

## 参与贡献

欢迎提交 Issue/PR。优先接收：可复现崩溃样本、检测规则优化、测试与文档改进。提交前请运行测试。
