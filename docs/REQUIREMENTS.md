# 需求清单

历史开发维护文档，非发布说明。当前版本见 `CHANGELOG.md` 顶部。

---

## 架构与代码质量

| 需求 | 状态 | 优先级 |
|------|------|--------|
| 配置集中管理 | ✅ `config/constants.py` | — |
| 魔法数字消除 | ✅ I/O 缓冲区/截断阈值已常量化 | — |
| app.py 拆分 View/Controller/Service | 待办 | 高 |
| 类型注解补齐 + mypy | 进行中 | 中 |
| 核心算法注释 | 待补充 | 中 |

## 安全性

| 需求 | 状态 |
|------|------|
| 路径遍历防护 (`..`) | ✅ `security.py` |
| URL 注入清洗 | ✅ `InputSanitizer.sanitize_url()` |
| 补丁 AST 验证 + 沙箱 | ✅ `patch_validator.py` + `patch_sandbox.py` |
| DLC 加载安全验证 | ✅ `discovery.py` (v2.1.1) |
| SSRF 防护 | ✅ `patch_downloader.py` (v2.1.1) |

## 性能优化

| 需求 | 状态 | 优先级 |
|------|------|--------|
| I/O 异步化 | ✅ 流式读取 + Head-only | — |
| 正则预编译 | ✅ `RegexCache` + 模块级 `re.compile` | — |
| 资源限制 | ✅ `ResourceLimiter` 接入 psutil | — |
| 主线程 I/O → Worker Thread | 待办 | 高 |

## 历史修复 (v1.1.1)

- 5 处 `except: pass` 静默吞错 → 有意义的日志
- URL 拼接 `replace(' ', '+')` → `urllib.parse.quote_plus`
- `LogService` 缓存 `is` → `==`
- 日志截断 2000 → 常量 `MAX_LOG_LINE_LENGTH`
- 配置加载失败无日志 → 已加日志

## 待办

- 拆分 `app.py` (View/Controller/Service) — 高优先级，~2-4 周
- `crash_patterns.py` 单元与基准测试
- 补齐类型注解并通过 mypy

## 远期愿景

- 微内核化 (`mca_lib` SDK / CLI / Asyncio)
- 语义分析（小模型 + 专家系统 DLC）
- 可视化升级（Webview / ECharts）
