# Security Audit Results — Automated Multi-Round

**Start**: 2026-06-11 | **Scope**: DLC加载, 补丁沙箱, API认证, 文件上传, 依赖注入

---


## Round 1 — DLC 加载 (Agent 1)

| ID | Severity | File | Line | Description |
|------|----------|------|------|------|
| VULN-001 | CRITICAL | discovery.py | 38-89 | AST bypass: `from os import system` renames forbidden calls |
| VULN-002 | CRITICAL | dlc_manager.py | 315-330 | `load_all` instantiates DLC twice, first not shutdown |
| VULN-003 | CRITICAL | discovery.py | 19-68 | `builtins.exec` bypasses AST blacklist |
| VULN-004 | CRITICAL | discovery.py | 19-31 | `importlib.import_module` not forbidden |
| VULN-005 | HIGH | discovery.py | 152-158 | `shutil.rmtree(__pycache__)` symlink attack |
| VULN-006 | HIGH | dlc_manager.py | 300-304 | TOCTOU between file check and load |
| VULN-007 | HIGH | dlc_manager.py | 214-266 | Reload rollback restores shutdown DLC |
| VULN-008 | HIGH | core.py | 84 | MappingProxyType shallow-only, lists mutable |
| VULN-009 | MEDIUM | dlc.py | 70-108 | _reverify_source passes silently on missing file |
| VULN-010 | MEDIUM | discovery.py | 169-227 | Package discovery lacks signature verification |
| VULN-011 | MEDIUM | core.py | 277-294 | Signature verification not enabled by default |
| VULN-012 | MEDIUM | discovery.py | 126-166 | load_dlc_classes_from_file is public, no sig check |
| VULN-013 | LOW | core.py | 269-275 | Hot-reload clears public keys |
| VULN-014 | LOW | dlc.py | 163,189 | Audit import inside function, silent fail |

## Round 2 — API 认证 + 依赖注入 (Agent 2)

| ID | Severity | File | Line | Description |
|------|----------|------|------|------|
| V-001 | CRITICAL | auth.py | 72 | Token comparison uses != not hmac.compare_digest |
| V-005 | CRITICAL | server.py | 71 | CSRF bypassable by omitting Origin header |
| V-006 | CRITICAL | server.py | 73-80 | CSRF token cookie never set, defense non-functional |
| V-010 | CRITICAL | di.py | 93-210 | DI container no access control, services hijackable |
| V-014 | CRITICAL | security/__init__.py | 39-43 | Serialization secret globally writable |
| V-018 | CRITICAL | config.py | 107 | Consul connection without auth or TLS |
| V-021 | CRITICAL | integration/bus.py | 141-325 | Integration bus no authentication |
| V-002 | HIGH | auth.py | 51-54 | Host header check is no-op |
| V-007 | HIGH | server.py | 75 | CSRF compare uses != not hmac |
| V-008 | HIGH | server.py | 38-39 | Static files mount lacks explicit auth |
| V-011 | HIGH | di.py | 212-239 | String key registration bypasses type checking |
| V-012 | HIGH | di.py | 328-358 | Auto-injection amplifies service hijack |
| V-015 | MEDIUM | security/__init__.py | 122-130 | Pickle format still accepted as parameter |
| V-016 | MEDIUM | security/__init__.py | 54 | Secret via env var readable by same process |
| V-019 | MEDIUM | config.py | 55-130 | Config values lack schema validation |
| V-022 | MEDIUM | integration/bus.py | 154-165 | Subsystem registration silently overwrites |
| V-023 | MEDIUM | integration/bus.py | 198-501 | Integration architecture info overexposed |
| V-003 | LOW | auth.py | 37-39 | Rate limit store potential memory leak |
| V-004 | LOW | auth.py | 57-59 | localhost check fails behind reverse proxy |
| V-009 | LOW | server.py | 52-56 | Patch API silent degradation |
| V-013 | LOW | di.py | 110-163 | Service overwrite without warning |
| V-017 | LOW | security/__init__.py | 228-231 | Overly broad exception catch |
| V-020 | LOW | config.py | 64-89 | File watcher no permission check |
| V-024 | LOW | integration/bus.py | 352-355 | Timeout threads continue running |

