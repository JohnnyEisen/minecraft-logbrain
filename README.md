# Minecraft LogBrain — 崩溃日志智能诊断

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

面向复杂 Mod 环境的 Minecraft 崩溃诊断平台。回答三件事：**哪个组件触发崩溃、哪个根因最可疑、下一步怎么修。**

---

## 核心能力

| 模块 | 能力 |
|------|------|
| **诊断引擎** | 21 种检测器并行执行，15s 超时，F1 精度 98.4% |
| **AI 语义** | MiniLM + 7 项优化（注意力池化、Int8 量化、CrossEncoder 重排序） |
| **补丁系统** | AST 验证 + 三级沙箱 + HMAC 签名，全仓渗透测试零未修复漏洞 |
| **仪表盘** | 实时指标、异常检测、告警管理、历史持久化 |
| **DLC 生态** | 可热加载扩展包（硬件加速、NN 算子、CodeBERT、分布式计算） |

---

## 安装与启动

```bash
# 基础安装（纯规则分析，无需 GPU）
pip install -r requirements.txt

# AI 增强安装
pip install -e .[ai]

# 启动
python main.py
```

辅助：`scripts/setup/install_env.bat`（Windows 一键安装）| `python scripts/setup/check_gpu.py`（GPU 检测）

---

## 项目结构

```
src/
├── mca_core/         核心引擎、检测器、补丁管理、仪表盘
├── brain_system/     AI 语义分析（BrainCore / DLC 框架）
├── dlcs/             DLC 扩展包
├── config/           配置管理
plugins/              可插拔扩展
tests/                 823+ 测试
data/                  规则库、崩溃样本
docs/                  架构文档、安全报告、更新日志
assets/                应用图标等静态资源
scripts/               构建、基准测试、辅助脚本
```

---

## 安全

最近全仓渗透测试发现并修复 **14 项漏洞**（3 CRITICAL / 5 HIGH），详见 `docs/security/`。

- 补丁：AST 禁止 `exec/eval/compile`，三级权限沙箱，HMAC 签名
- DLC：加载前 AST 验证，拦截危险系统调用
- API：Bearer Token 认证 + CSRF 保护 + 速率限制
- 服务端：`/ready` 已脱敏，`/metrics` 仅本地访问

---

## 近期更新（v2.1.1）

- 全仓安全审计：14 项漏洞修复（DLC 代码执行、SSRF、沙箱逃逸、ReDoS 等）
- 核心算力修复：注意力池化 GPU 参数、鲁棒聚合死代码激活、严重度误判修正
- 工程整理：根目录归位、死目录清理、PySide6→PyQt6

[完整更新日志](CHANGELOG.md) | [已知问题](docs/KNOWN_ISSUES.md)

---

## 构建

```bash
scripts/build/pack.bat
```

输出 `dist/minecraft-logbrain/`

---

## FAQ

**AI 依赖必要吗？** 不必要。基础规则分析不依赖 AI 组件。

**安全性如何？** AST 验证 + 沙箱 + 签名三重防护，全仓审计零未修复漏洞。

**适合什么日志？** Minecraft 客户端/服务端崩溃日志，尤其是复杂 Mod 整合包。

---

## 参与贡献

欢迎 Issue/PR。优先：可复现崩溃样本、检测规则优化、测试与文档改进。
