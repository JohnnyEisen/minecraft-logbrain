# 安全审计报告 — v2.1.2

**日期**: 2026-06-11 | **范围**: DLC加载, 补丁沙箱, API认证, 文件上传, 依赖注入  
**发现**: 53 | **修复**: 24 | **测试**: 32/32

---

## 修复清单

### DLC 加载 (8)

| 编号 | 漏洞 | 修复 |
|------|------|------|
| VULN-001 | AST `from os import system` 别名绕过 | 禁止 os/builtins/importlib 导入 + bare calls 黑名单 |
| VULN-002 | load_all temp_inst 资源泄漏 | finally 调用 _pre_shutdown |
| VULN-003 | builtins.exec 绕过 | builtins 加入禁止导入 |
| VULN-004 | importlib.import_module 绕过 | 禁止导入+调用 |
| VULN-005 | shutil.rmtree symlink | 移除该代码 |
| VULN-007 | reload 回滚恢复 shutdown DLC | 重新 initialize |
| VULN-008 | MappingProxyType 浅层 | 列表转 tuple |
| VULN-009 | _reverify_source 静默通过 | 拒绝无源文件 |
| VULN-011 | 签名默认未启用 | 默认 True |

### 沙箱 (8)

| 编号 | 漏洞 | 修复 |
|------|------|------|
| VULN-001 | __getattribute__ 绕过 | 阻断 dunder |
| VULN-002 | pathlib I/O 绕过 | 移除白名单 |
| VULN-003 | 超时僵尸线程 | 追踪+告警 |
| VULN-005 | inspect 标记安全 | 移除出 validator 白名单 |
| VULN-006 | io 标记安全 | 移除出 validator 白名单 |
| VULN-007 | 文件名路径遍历 | basename + 拒绝 ../ |
| VULN-011 | hasattr 绕过 | 包装 _safe_hasattr |
| VULN-012 | meta_json 注入 | 拒绝敏感字段 |

### API 认证 (5)

| 编号 | 漏洞 | 修复 |
|------|------|------|
| V-001 | Token != 时序攻击 | hmac.compare_digest |
| V-005 | CSRF Origin 缺失绕过 | 必填+拒绝 |
| V-006 | csrf_token 无生成 | /health 端点自动生成 |
| V-014 | 序列化密钥可覆盖 | set 时抛 RuntimeError |
| V-015 | pickle 静默转换 | 直接拒绝 |

### 架构加固 (3)

| 编号 | 漏洞 | 修复 |
|------|------|------|
| V-021 | 子系统静默覆盖 | 抛 ValueError |
| V-023 | 子系统信息暴露 | list_subsystems 默认隐藏 |
| V-013 | DI 注册无告警 | 覆盖时记录 warning |
| V-003 | 速率存储泄漏 | 定期清理 |
| V-009 | API 加载静默失败 | 记录错误日志 |
| V-020 | 配置文件权限 | group/other write 检测 |
| V-022 | 旧 Host 空操作 | 有效拒绝 |

### 已知限制 (29)

剩余项为需流程/架构级重构：Consul TLS(部署层)、静态文件认证(FastAPI mount限制)、DI访问控制(需新API)、DNS rebinding(网络层)、沙箱进程隔离(OS层)、配置Schema验证、深层消毒递归等，将在 v2.1.3+ 逐步推进。
