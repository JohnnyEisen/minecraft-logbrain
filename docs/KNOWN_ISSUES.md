# 已知问题 — Bug 与修复记录

> 本文档面向终端用户，只记录实际使用中遇到的 Bug 以及开发过程中发现并修复的问题。
> 每条问题都标注了「来源」：🔴 实际用户遇到 / 🔵 开发中发现。

---

## v2.1.0 — Bug 修复汇总

| # | 来源 | 问题 | 影响版本 | 说明 | 修复方案 |
|---|------|------|----------|------|----------|
| 1 | 🔵 | BrainCore 巨型类 | v1.5.0 ~ v2.0.0 | 1302 行难以维护，职责混乱 | 提取 DLCManager 子模块（303 行），DLC 方法改为委托桩 |
| 2 | 🔵 | EventBus 排序开销 | v1.5.0 ~ v2.0.0 | 每次 subscribe 立即 O(n log n) 排序 | 改为惰性排序，publish 时才触发 |
| 3 | 🔵 | Registry 导入级联 | v1.5.0 ~ v2.0.0 | 导入 registry 时立即 load_builtins | 改为懒加载，首次调用时触发 |
| 4 | 🔵 | 插件系统静默放行 | v2.0.0 | `_validate_imports` 返回 True 放行违禁模块 | 返回值改为 `list[str]` 违规列表 |
| 5 | 🔵 | 插件重复 hash 计算 | v2.0.0 | `_validate_plugin_code` 和调用方各读一次文件 | 返回 hash，调用方复用 |
| 6 | 🔵 | DistributedComputing 竞态 | v2.0.0 | stop_workers 先设 is_running=False 再发毒丸，worker 阻塞 | 先发毒丸再设标志 |
| 7 | 🔵 | DLC disable 不释放 GPU | v2.0.0 | disable() 未调用 shutdown 钩子 | 改为调用 _pre_shutdown/_post_shutdown |
| 8 | 🔵 | CodeBertDLC 绕过基类 | v2.0.0 | shutdown() 直接清理 GPU，未调用 super() | 清理移入 _pre_shutdown |
| 9 | 🔵 | Discovery sys.modules 泄漏 | v2.0.0 | load_dlc_classes_from_file 临时模块未清理 | try/finally 中 pop |
| 10 | 🔵 | 沙箱 __import__ 漏洞 | v2.0.0 | RESTRICTED 级别允许 __import__ | 从 RESTRICTED_BUILTINS 移除 |
| 11 | 🔵 | 沙箱 open() 分配脆弱 | v2.0.0 | elif 分支重复，顺序依赖 | 用 pop 明确禁止，消除重复 |

---

## v2.0.0 — Bug 修复汇总

| # | 来源 | 问题 | 影响版本 | 说明 | 修复方案 |
|---|------|------|----------|------|----------|
| 1 | 🔴 | 启动慢 | v1.5.0 ~ v1.5.2 | 冷启动 30s+，期间界面无响应 | 延迟加载 BrainCore，点击"启用语义分析"时才初始化 |
| 2 | 🔴 | AI 状态不可见 | v1.5.0 ~ v1.5.2 | 无法知道 AI 是加载中还是已就绪 | 5 色 AI 状态标签 + 120s 超时 + 分阶段进度报告 |
| 3 | 🔴 | GPU 检测不准 | v1.5.0 ~ v1.5.2 | 装了 PyTorch + CUDA 但识别不到 GPU | 新增 PyTorch 回退检测 |
| 4 | 🔴 | 检测结果不准确 | v1.5.0 ~ v1.5.2 | 重复模组/版本冲突/OGL 漏检，依赖误报 | 新增 5 种检测器 + 正则优化，F1 从 71.8% → 98.4% |
| 5 | 🔴 | 检测结果翻倍 | v1.5.2 | 同一问题出现两次，检测器被执行两遍 | 移除冗余调用 |
| 6 | 🔴 | 大量 unknown 标签 | v1.5.0 ~ v1.5.2 | 原因显示 "unknown" 而非检测器名称 | 使用 detector 作为回退名 |
| 7 | 🔴 | 模型不可用误报 | v1.5.0 ~ v1.5.2 | AI 可用却提示不可用 | 移除无效硬编码兜底提示 |
| 8 | 🔴 | 渲染建议太笼统 | v1.5.0 ~ v1.5.2 | 不同根因的渲染问题给出相同建议 | 差异化建议 |
| 9 | 🔴 | JAR 伪命名误判 | v1.5.0 ~ v1.5.2 | 带数字前缀的文件名被当成 mod 名 | 增加无效名称过滤 |
| 10 | 🔴 | 自动测试结果无区分 | v1.5.1 ~ v1.5.2 | 只显示"检出(N项)"，不知来源 | 改为"规则: x \| 检测: y" |
| 11 |  | 渲染候选误导诊断 | v1.5.0 | InvalidInjectionException 场景被渲染候选误导 | 强规则优先输出 |
| 12 | 🔴 | 仪表盘指标全为 "--" | 未发布 | DashboardDLC 未实例化 | 创建独立 DashboardController |
| 13 | 🔵 | 告警刷屏 (1296条/min) | 未发布 | AnomalyDetector 无冷却期 | 新增 60s 冷却期 |
| 14 | 🔵 | 补丁可执行任意代码 | 未发布 | 默认 admin 无限制 | AST 验证 + 三级权限沙箱 |
| 15 | 🔵 | 补丁面板启动崩溃 | 未发布 | QTimer 未导入 | 补全导入 |
| 16 | 🔵 | 补丁反序列化失败 | 未发布 | `_persist_state()` 直接存对象导致反序列化崩溃 | 改为序列化 dict 格式 |
| 17 | 🔵 | 仪表盘检测率/误报率为 0 | 未发布 | `_dashboard_controller` 从未被设置 | 正确连接引擎 + 追踪检测前后变化 |
| 18 | 🔵 | Alert ID 碰撞 | 未发布 | 同一毫秒内 ID 冲突导致确认/解决操作作用错误目标 | 改用 UUID |
| 19 | 🔵 | LruTtlCache 缓存污染 | 未发布 | 对象被 GC 后新对象复用同一 `id()` 返回错误大小估算 | 添加活跃集合追踪 |

---

## v1.5.3 及更早版本 — 历史 Bug 修复

| # | 来源 | 问题 | 影响版本 | 说明 | 修复方案 |
|---|------|------|----------|------|----------|
| 1 | 🔴 | RegexCache 内存泄漏 | v1.0 ~ v1.1 | 缓存无限膨胀导致内存溢出 | 挂载到主管道生命周期，定期 `.clear()` |
| 2 | 🔴 | 数据库多线程 locked 崩溃 | v1.0 ~ v1.1 | 多线程解析日志时 `database is locked` | 单写多读架构 + 独立 DB-Writer-Thread |
| 3 | 🔴 | 静默吞错 | v1.0 ~ v1.1 | 5 处 `except: pass` 不记录任何错误信息 | 改为有意义的日志记录 |
| 4 | 🔴 | 内存监控永远返回 0 | v1.0 ~ v1.1 | `ResourceLimiter._get_memory_usage()` 未接入 psutil | 接上 psutil 实现真正监控 |
| 5 | 🔴 | URL 特殊字符崩溃 | v1.0 ~ v1.1 | `replace(' ', '+')` 遇到特殊字符就炸 | 改用 `urllib.parse.quote_plus` |
| 6 | 🔴 | 日志缓存形同虚设 | v1.0 ~ v1.1 | `LogService` 缓存比较用 `is` 而非 `==` | 改为按值比较 |
| 7 | 🔵 | generate_batch 参数顺序错误 | v1.3 | 函数调用参数顺序不对 | 修正参数顺序 |
| 8 | 🔵 | 阴影效果导入位置错误 | v1.4 | `QGraphicsDropShadowEffect` 从错误模块导入 | 改为从 QtWidgets 导入 |

---

## 已知限制

| 限制 | 影响 | 解决方案 |
|------|------|----------|
| 只装 PyTorch 未装 cupy | GPU 被检测到但 `device_objects` 无 GPU 条目 | 同时安装 cupy |
| `/metrics` 仅允许 localhost | Prometheus 在外部机器时无法访问 | 通过反向代理转发 |

---

## 反馈

遇到未列出的问题？欢迎提交 [GitHub Issues](https://github.com/JohnnyEisen/MCA-Brain-System/issues)，请附上完整崩溃日志。
