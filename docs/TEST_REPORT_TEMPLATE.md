# 测试报告模板

> 版本字段为占位符，填写时替换为当前发布版本。

| 项目 | 内容 |
|------|------|
| 项目名称 | Minecraft LogBrain |
| 版本 | {{release_version}} |
| 测试日期 | YYYY-MM-DD |
| 测试环境 | Python 3.x / Windows 11 |

---

## 1. 测试执行汇总

| 指标 | 数值 | 百分比 |
|------|------|--------|
| 总测试数 | {{total}} | 100% |
| 通过 | {{passed}} | {{passed_pct}}% |
| 失败 | {{failed}} | {{failed_pct}}% |
| 跳过 | {{skipped}} | {{skipped_pct}}% |

### 代码覆盖率

| 模块 | 行 | 分支 | 状态 |
|------|-----|------|------|
| mca_core | {{coverage}}% | {{branch}}% | ✅ (>80%) |
| brain_system | {{coverage}}% | {{branch}}% | ✅/⚠️/❌ |
| 总计 | {{total}}% | {{total}}% | — |

---

## 2. 单元测试详情

### 核心模块

| 测试文件 | 用例数 | 通过 | 备注 |
|----------|--------|------|------|
| test_detectors.py | {{n}} | {{p}} | 21 种检测器全覆盖 |
| test_diagnostic_engine.py | {{n}} | {{p}} | 并行执行 + 缓存 |
| test_patch_security.py | {{n}} | {{p}} | 沙箱 + AST 验证 |
| test_security.py | {{n}} | {{p}} | 输入净化、路径验证 |
| test_database.py | {{n}} | {{p}} | 连接池、WAL 模式 |
| test_services.py | {{n}} | {{p}} | 配置、日志服务 |

### 安全测试

| 测试文件 | 用例数 | 覆盖范围 |
|----------|--------|----------|
| test_patch_security.py | — | 沙箱执行、AST 验证 |
| test_dlc_security_validation.py | — | DLC 加载安全检查 |
| test_input_sanitizer_paths.py | — | 路径遍历防护 |
| test_core_security.py | — | 签名验证 |

---

## 3. 性能基准

| 测试场景 | 文件大小 | 耗时 | 内存 | 备注 |
|----------|----------|------|------|------|
| 小日志 (100KB) | 100KB | {{time}} | {{mem}} | — |
| 中日志 (10MB) | 10MB | {{time}} | {{mem}} | — |
| 大日志 (100MB) | 100MB | {{time}} | {{mem}} | 头尾截断 |

---

## 4. 兼容性

| 平台 | Python | 状态 | 备注 |
|------|--------|------|------|
| Windows 11 | 3.13 | ✅ | 主开发平台 |
| Windows 10 | 3.10+ | {{status}} | — |
| Linux | 3.10+ | {{status}} | — |
| macOS | 3.10+ | {{status}} | — |

---

## 5. 已知问题

| 问题 | 影响 | 计划修复 |
|------|------|----------|
| {{issue}} | {{impact}} | {{version}} |

---

- [README.md](README.md) — 项目说明
- [CHANGELOG.md](../CHANGELOG.md) — 变更日志
- [REQUIREMENTS.md](REQUIREMENTS.md) — 需求说明
