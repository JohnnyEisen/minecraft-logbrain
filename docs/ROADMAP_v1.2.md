# Roadmap — v1.2（历史规划，仅供参考）

> 当前发布版本以 `CHANGELOG.md` 顶部为准。

## v1.2 目标（2026 Q2）

- 性能：大日志 (200MB+) GUI 卡顿降至 <500ms
- 正则模块基准性能 2x
- CI 覆盖关键单元测试，mypy 通过率 >95%

## 里程碑

| 版本 | 目标 | 估时 |
|------|------|------|
| v1.2.1 | 拆分 app.py + 主线程 I/O 异步化 | 3-6 周 |
| v1.2.2 | 基准测试 + CI 集成 | 2-3 周 |
| v1.2.3 | 类型注解 + mypy >95% | 1-2 周 |
| v1.2.4 | Prometheus + OpenTelemetry | 2 周 |
| v1.2.5 | 全盘扫描 / 多源取证 / 环境上下文 | 2 周 |

## v1.3 探索方向

- **差分诊断 (Diff Doctor)**: 众包基准库，对比正常/异常日志
- **Mixin 解构 (De-obfuscator)**: 名称映射，反解 Mixin 混淆
- **Watchdog 时序图**: 解析时间戳，画出心跳停止前最后 60s 热力图

## 参考

- [REQUIREMENTS.md](REQUIREMENTS.md)
- [CHANGELOG.md](../CHANGELOG.md)
