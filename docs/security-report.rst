安全报告
========

本报告记录项目自 v2.1.0 以来发现、修复的全部安全问题。

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
