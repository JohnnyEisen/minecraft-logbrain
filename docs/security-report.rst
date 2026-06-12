安全报告
========

本报告记录项目自 v2.1.0 以来发现、修复的全部安全问题。

**最新更新**: v2.1.2 — 三轮全仓审计发现 53 项漏洞，修复 24 项。

.. contents::
   :depth: 1

----

漏洞目录
--------

.. list-table::
   :header-rows: 1
   :widths: 12 8 30 50

   * - 编号
     - 严重性
     - 问题
     - 修复策略
   * - **VULN-001**
     - CRITICAL
     - DLC 加载 ``exec_module`` 无安全验证
     - 新增 ``_validate_dlc_source()`` AST 分析 + 危险调用/导入拦截
   * - **VULN-002**
     - CRITICAL
     - PatchDownloader SSRF（``file://`` 等协议未过滤）
     - URL scheme 白名单（仅 http/https）+ ``ipaddress`` 精确内网判断
   * - **VULN-003**
     - CRITICAL
     - Admin 沙箱 ``__import__`` 未拦截 → 任意命令执行
     - ``_ADMIN_DENIED`` 加入 ``__import__`` + 全局 ``_safe_import`` 白名单
   * - **VULN-004**
     - HIGH
     - BYPASS_PATTERNS 正则回溯 ReDoS
     - ``.*`` → ``.{0,200}?`` 非贪婪限制，参数加长度上限
   * - **VULN-005**
     - HIGH
     - 补丁上传 TOCTOU 竞态
     - 上传前 hash 内容 → 写入后交叉比对，不匹配则回滚
   * - **VULN-006**
     - HIGH
     - REST API 无 CSRF 保护
     - Origin 验证 + ``X-CSRF-Token`` 中间件
   * - **VULN-007**
     - HIGH
     - Auth localhost 过度宽松
     - Host header 验证 + 未配置 token 时打印警告
   * - **VULN-008**
     - HIGH
     - 下载路径 ``../`` 遍历注入
     - ``os.path.basename`` + ``os.path.realpath`` 边界检查
   * - **VULN-009**
     - MEDIUM
     - 路径脱敏不完整（仅 ``C:\Users`` 和 ``/home``）
     - 扩展盘符、``%APPDATA%``、``/opt``、``/var/lib`` 模式
   * - **VULN-010**
     - MEDIUM
     - SQLite ``read_uncommitted=ON`` 脏读
     - 改为 ``OFF``，WAL 模式本身支持读写并发
   * - **VULN-011**
     - MEDIUM
     - ``sys.path.insert(0)`` 模块劫持
     - 改为 ``sys.path.append``
   * - **VULN-012**
     - MEDIUM
     - API 错误消息泄露内部路径
     - 新增 ``_safe_error_message()`` 脱敏
   * - **VULN-013**
     - LOW
     - ``compute_content_hash`` 用途不明（可能被误用于密码）
     - 添加注释："仅用于文件校验，不适用于密码"
   * - **VULN-014**
     - LOW
     - 日志无限增长
     - 已有 10MB×5 轮转，无需额外修复

----

威胁模型驱动修复
----------------

基于攻击者视角威胁建模发现并修复的深层漏洞：

.. list-table::
   :header-rows: 1
   :widths: 15 30 55

   * - 编号
     - 问题
     - 修复策略
   * - **THREAT-001**
     - 沙箱 ``__subclasses__()`` 内省逃逸
     - 源码编译前拦截 12 个内省模式（``__subclasses__``, ``__bases__``,
       ``__globals__``, ``__code__``, ``__builtins__`` 等）
   * - **THREAT-002**
     - ``load_dlc_classes_from_module`` 无 AST 验证
     - 导入后对模块源文件执行 ``_validate_dlc_source()``
   * - **THREAT-003**
     - ``iter_dlc_files`` 不防隐藏文件/符号链接
     - 过滤 ``.xxx.py``、拒绝符号链接、resolve 后路径边界验证
   * - **THREAT-004**
     - ``self.config`` 可变 dict，DLC 可运行时关闭签名
     - ``MappingProxyType`` 只读代理
   * - **THREAT-005**
     - ``inject()`` 可被恶意 DLC 重复调用覆盖配置
     - 增加 ``_injected`` 标记，仅允许初始化前调用一次

----

算力与逻辑 Bug
---------------

.. list-table::
   :header-rows: 1
   :widths: 12 8 30 50

   * - 编号
     - 严重性
     - 问题
     - 修复策略
   * - **BUG-001**
     - HIGH
     - SSRF 修复中 ``startswith("127.")`` 误杀合法域名
     - 改用 ``ipaddress`` 模块精确判断
   * - **BUG-002**
     - HIGH
     - ``publish_async`` 每次创建+销毁线程池
     - 改为复用单一后台 ``_async_executor``
   * - **BUG-003**
     - MEDIUM
     - ``unsubscribe`` 分发期间不安全
     - 改为 ``_remove_handler`` 延迟移除
   * - **BUG-004**
     - MEDIUM
     - 检测器路径不生成 AI prompt
     - ``_convert_context_to_results`` 统一生成
   * - **BUG-C01**
     - HIGH
     - 注意力池化参数留 CPU（``.to()`` 非原地）
     - ``torch.randn(..., device=self.device)`` 直接初始化
   * - **BUG-C05**
     - HIGH
     - 鲁棒聚合缓冲区每调用清零 → 永不激活
     - 移除 ``clear()``，提供显式 ``reset_robust_buffer()``
   * - **BUG-C07**
     - MEDIUM
     - ``"warn"`` 子串匹配所有 WARN 行
     - 改为 ``"mod conflict"`` 精确词汇

----

攻击链验证
----------

.. list-table::
   :header-rows: 1
   :widths: 25 25 25 25

   * - 攻击链
     - 步骤 1
     - 阻断点
     - 结果
   * - **A**: ZipSlip→PubKey→Token→Admin
     - ZipSlip 文件写入
     - ``archive_utils.py`` 四重防护
     - ❌ 失败
   * - **B**: TOCTOU→DLC 持久化
     - TOCTOU 替换
     - VULN-005 hash 比对
     - ❌ 失败
   * - **C**: Metrics→Token→Config→外传
     - ``/metrics`` 无认证
     - THREAT-004/005 加固
     - ✅ 解除

----

统计
----

+------------------+------+
| 类别             | 数量 |
+==================+======+
| CRITICAL 漏洞    | 3    |
+------------------+------+
| HIGH 漏洞        | 5    |
+------------------+------+
| MEDIUM 漏洞      | 4    |
+------------------+------+
| LOW 漏洞         | 2    |
+------------------+------+
| 威胁模型修复     | 5    |
+------------------+------+
| 算力 Bug         | 7    |
+------------------+------+
| **合计**         | 26   |
+------------------+------+

----

v2.1.2 审计 — DLC 加载修复
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 12 8 30 50

   * - 编号
     - 严重性
     - 问题
     - 修复策略
   * - **VULN-D01**
     - CRITICAL
     - AST ``from os import system`` 别名绕过
     - 禁止 os/builtins/importlib 导入 + ``from X import Y`` 别名追踪
   * - **VULN-D02**
     - CRITICAL
     - ``load_all`` temp_inst 资源泄漏
     - finally 调用 ``_pre_shutdown()``
   * - **VULN-D03**
     - CRITICAL
     - ``builtins.exec`` 绕过 AST
     - builtins 加入禁止导入列表
   * - **VULN-D04**
     - CRITICAL
     - ``importlib.import_module`` 动态导入绕过
     - importlib 加入禁止导入 + 禁止调用
   * - **VULN-D05**
     - HIGH
     - ``shutil.rmtree(__pycache__)`` 符号链接风险
     - 移除该代码块（exec_module 不读 pycache）
   * - **VULN-D06**
     - HIGH
     - MappingProxyType 浅层只读
     - 列表值转 tuple 后包装
   * - **VULN-D07**
     - HIGH
     - reload 回滚恢复已 shutdown 的 DLC
     - 回滚前检查状态，UNLOADED 则重新 initialize
   * - **VULN-D08**
     - MEDIUM
     - ``_reverify_source`` 无法确定源文件时静默通过
     - 改为拒绝，返回 False
   * - **VULN-D09**
     - MEDIUM
     - 签名验证默认不启用
     - ``dlc_signature_required`` 默认改为 True

----

v2.1.2 审计 — 沙箱修复
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 12 8 30 50

   * - 编号
     - 严重性
     - 问题
     - 修复策略
   * - **VULN-S01**
     - CRITICAL
     - ``type.__getattribute__`` 完全绕过 getattr 守卫
     - ``__getattribute__`` 加入阻断 dunder 列表
   * - **VULN-S02**
     - CRITICAL
     - ``pathlib`` 白名单导致 I/O 限制失效
     - 移除 pathlib 出白名单
   * - **VULN-S03**
     - HIGH
     - 超时后台线程无法终止（僵尸线程）
     - 僵尸线程追踪 + 超过 10 个告警
   * - **VULN-S04**
     - HIGH
     - ``hasattr`` C 级调用绕过 getattr 守卫
     - 包装 ``_safe_hasattr``
   * - **VULN-S05**
     - HIGH
     - validator ``inspect``/``io`` 标记安全
     - 移除出 validator 白名单对齐沙箱
   * - **VULN-S06**
     - HIGH
     - 上传文件名路径遍历
     - ``os.path.basename`` + 拒绝 ``../``
   * - **VULN-S07**
     - MEDIUM
     - ``meta_json`` 注入覆盖安全字段
     - 拒绝 permission_level/risk_level/signature 等字段
   * - **VULN-S08**
     - LOW
     - ``ADMIN_DENIED`` 缺少 ``breakpoint``
     - 补全 breakpoint 进入黑名单
   * - **VULN-S09**
     - HIGH
     - 源码文本拦截可字符串构造绕过
     - getattr 运行时守卫作为第二道防线

----

v2.1.2 审计 — API 认证修复
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 12 8 30 50

   * - 编号
     - 严重性
     - 问题
     - 修复策略
   * - **VULN-A01**
     - CRITICAL
     - Token ``!=`` 比较存在时序攻击
     - 改用 ``hmac.compare_digest`` 恒定时间比较
   * - **VULN-A02**
     - CRITICAL
     - CSRF 可省略 Origin 绕过
     - 无 Origin 的 POST 请求直接拒绝
   * - **VULN-A03**
     - CRITICAL
     - CSRF token cookie 从未设置
     - ``/health`` 端点自动生成 ``csrf_token``
   * - **VULN-A04**
     - HIGH
     - Host header 验证为空操作
     - 非 localhost 且无 token 时返回 403
   * - **VULN-A05**
     - CRITICAL
     - 序列化密钥全局可写
     - ``set_serialization_secret`` 第二次调用抛 RuntimeError
   * - **VULN-A06**
     - MEDIUM
     - pickle 格式被接受为参数
     - 直接拒绝抛 ValueError

----

v2.1.2 审计 — 架构加固
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 12 8 30 50

   * - 编号
     - 严重性
     - 问题
     - 修复策略
   * - **VULN-X01**
     - CRITICAL
     - 集成总线重复注册静默覆盖
     - 抛 ValueError，需显式 unregister 或 force=True
   * - **VULN-X02**
     - MEDIUM
     - 子系统列表暴露内部信息
     - ``list_subsystems`` 默认 ``verbose=False``
   * - **VULN-X03**
     - LOW
     - DI 服务覆盖无警告
     - 覆盖时记录 warning 日志
   * - **VULN-X04**
     - LOW
     - 配置文件权限未检查
     - group/other write 检测 + 告警
   * - **VULN-X05**
     - LOW
     - 补丁 API 加载失败静默 pass
     - 记录 error 日志

----

最终统计
--------

+------------------+------+------+
| 类别             | 发现 | 修复 |
+==================+======+======+
| v2.1.0 初始审计  | 14   | 14   |
+------------------+------+------+
| 威胁模型修复     | 5    | 5    |
+------------------+------+------+
| 算力 Bug         | 7    | 7    |
+------------------+------+------+
| v2.1.2 DLC 加载  | 14   | 9    |
+------------------+------+------+
| v2.1.2 沙箱      | 15   | 9    |
+------------------+------+------+
| v2.1.2 API 认证  | 24   | 6    |
+------------------+------+------+
| **合计**         | 79   | 50   |
+------------------+------+------+
