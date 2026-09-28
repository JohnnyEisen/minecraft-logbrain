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
| **补丁系统** | AST 验证 + 三级沙箱 + HMAC 签名强制（fail-closed） |
| **仪表盘** | 实时指标、异常检测、告警管理、历史持久化 |
| **DLC 生态** | 可热加载扩展包（硬件加速、NN 算子、CodeBERT、分布式计算） |

---

## 安装与启动

```bash
# 桌面应用安装（纯规则分析，无需 GPU）
pip install -e .[desktop]

# AI 增强安装
pip install -e .[desktop,ai]

# 兼容旧安装流程
pip install -r requirements.txt

# 启动桌面应用
python main.py

# 或启动 Web 服务端（健康检查 + 补丁管理 API，默认仅本机访问）
python -m brain_system serve --host 127.0.0.1 --port 8000
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

两轮安全审计：

1. **全仓审计**：修复 **14 项漏洞**（3 CRITICAL / 5 HIGH），详见 `docs/security/`。
2. **红队实弹演练**：修复 **7 项漏洞**——沙箱帧攀爬逃逸、补丁签名 fail-open、DLC 签名 fail-open、认证层崩溃、XFF 身份伪造、模型路径劫持、schema 泄露与上传竞态；并重构密钥管理。

- 补丁：AST 禁止 `exec/eval/compile` 与帧对象属性访问，三级权限沙箱；签名缺失/密钥未配置一律拒绝（fail-closed）
- DLC：签名强制校验，未配置公钥时拒绝加载
- API：Bearer Token + CSRF 保护 + 速率限制；`X-Forwarded-For` 仅信任显式白名单代理；生产默认关闭 `/openapi.json` 与 `/docs`
- 密钥：优先 `MCA_PATCH_SECRET` 环境变量 → 用户私有密钥 `~/.config/logbrain/patch.key`（首次运行自动生成，0600）→ 遗留 `.patch_key` 仅作兼容（权限检查 + 迁移告警，不做向上扫描）

### 环境变量

| 变量 | 说明 |
|------|------|
| `MCA_API_TOKEN` | Web API Bearer Token；未设置时仅接受 localhost 请求 |
| `MCA_TRUSTED_PROXIES` | 可信反向代理 IP 白名单（逗号分隔）；默认不信任任何 `X-Forwarded-For` |
| `MCA_PATCH_SECRET` | 补丁签名密钥，部署级注入，优先级最高 |
| `MCA_PATCH_SIGNATURE_REQUIRED` | 设为 `0` 降级为仅哈希校验（默认强制签名） |
| `MCA_ALLOWED_MODEL_ROOTS` | 允许加载本地模型目录的白名单（路径分隔符分隔） |
| `MCA_ENV` | 设为 `dev` 时开启 `/openapi.json` 与 `/docs`（默认关闭） |

---

## 近期更新（v2.1.3）

- 红队实弹演练：修复 7 项漏洞并完成三状态验证（有密钥 / 无密钥 / 劫持）
- 密钥管理重构：密钥迁出项目目录，用户私有目录自动生成，废除向上扫描防劫持
- 架构迁移：补丁加载器归位 `mca_core.launcher`，BrainCore 执行逻辑抽取为 `execution_service`
- v2.1.1 全仓审计：14 项漏洞修复（DLC 代码执行、SSRF、沙箱逃逸、ReDoS 等）

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
