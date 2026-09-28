API 参考 — v2.1.3
====================

.. contents::
   :depth: 2

----

核心引擎
--------

.. automodule:: mca_core.diagnostic_engine
   :members: analyze, shutdown, set_progress_callback, get_cache_stats
   :undoc-members:

.. automodule:: mca_core.detectors.base
   :members: Detector
   :undoc-members:

Brain AI
--------

.. automodule:: brain_system.core
   :members: BrainCore, load_dlc_file, load_all_dlcs, reload_dlc_file
   :undoc-members:

.. automodule:: brain_system.dlc
   :members: BrainDLC, enable, disable, shutdown, inject
   :undoc-members:

补丁管理
--------

.. automodule:: mca_core.patch_manager.core
   :members: PatchManager, upload_patch, apply_patch, rollback_patch, verify_integrity
   :undoc-members:

.. automodule:: mca_core.patch_manager.patch_sandbox
   :members: execute_patch_sandboxed, create_sandbox_globals, PermissionLevel
   :undoc-members:

.. automodule:: mca_core.patch_manager.integrity
   :members: compute_file_hash, verify_file_integrity, verify_signature, get_patch_key
   :undoc-members:

REST API
--------

.. automodule:: brain_system.server
   :members: create_app
   :undoc-members:

.. automodule:: brain_system.patch_api
   :members:
   :undoc-members:

认证
----

.. automodule:: brain_system.auth
   :members: verify_auth
   :undoc-members:

集成总线
--------

.. automodule:: mca_core.integration.bus
   :members: IntegrationBus, register, list_subsystems, health_check_all
   :undoc-members:

----

v2.1.2 API 变更
---------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - 模块
     - 类型
     - 说明
   * - ``server.py``
     - CSRF 强化
     - POST/PUT/DELETE 必须带 Origin header；``/health`` 自动设置 csrf_token cookie
   * - ``server.py``
     - 错误处理
     - 补丁 API 加载失败时记录错误日志（不再静默 pass）
   * - ``auth.py``
     - 时序安全
     - Token 比较从 ``!=`` 改为 ``hmac.compare_digest``
   * - ``auth.py``
     - Host 验证
     - 非 localhost 且无 token 时返回 403
   * - ``auth.py``
     - 内存管理
     - 速率限制 store 每 100 条新 IP 触发过期清理
   * - ``patch_api.py``
     - 输入校验
     - 上传文件名路径遍历防护（basename + 拒绝 ../）
   * - ``patch_api.py``
     - 字段保护
     - 拒绝 meta_json 覆盖敏感字段（permission_level/risk_level/signature）
   * - ``patch_sandbox.py``
     - 沙箱加固
     - 移除 pathlib 白名单；hasattr/getattr 双守卫；__getattribute__/__dict__ 阻断
   * - ``patch_sandbox.py``
     - 超时控制
     - 30s 执行超时 + 僵尸线程追踪告警
   * - ``patch_sandbox.py``
     - 防御补全
     - ADMIN_DENIED 新增 breakpoint
   * - ``patch_validator.py``
     - 白名单对齐
     - 移除 inspect/io（与沙箱白名单对齐）
   * - ``discovery.py``
     - AST 增强
     - 禁止 os/builtins/importlib 导入；拦截 from X import Y 别名绕过
   * - ``discovery.py``
     - 安全加固
     - 移除 shutil.rmtree(__pycache__) 符号链接风险
   * - ``core.py``
     - 配置保护
     - MappingProxyType 深只读（列表值转 tuple）
   * - ``core.py``
     - 默认安全
     - dlc_signature_required 默认 True
   * - ``core.py``
     - 完整性
     - 上传时自动生成 integrity_token
   * - ``dlc.py``
     - 生命周期
     - _reverify_source 拒绝无源文件 DLC；set_serialization_secret 防覆盖
   * - ``dlc_manager.py``
     - 资源管理
     - temp_inst finally 调用 _pre_shutdown；回滚时重新初始化
   * - ``integration/bus.py``
     - 访问控制
     - 重复注册抛 ValueError；list_subsystems 默认隐藏敏感信息
   * - ``config.py``
     - 权限检查
     - 配置文件 group/other write 权限检测
   * - ``di.py``
     - 审计
     - 服务覆盖注册时记录 warning
   * - ``security/__init__.py``
     - 序列化
     - pickle 格式直接拒绝；set_serialization_secret 仅允许一次

----

v2.1.3 架构加固
-----------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - 模块
     - 类型
     - 说明
   * - ``auth.py``
     - 反向代理
     - ``verify_auth`` 从 ``X-Forwarded-For`` 取真实客户端 IP
   * - ``di.py``
     - 容器锁定
     - ``DIContainer.seal()`` 锁定后拒绝新注册；字符串键限制 ``system./config.`` 前缀
   * - ``config.py``
     - TLS/验证
     - ``ConsulConfigSource`` 新增 ``token``/``scheme`` 参数；``_validate_config_schema`` 18 项类型检查
   * - ``config.py``
     - 权限
     - 配置文件 group/other write 权限检测
   * - ``dlc_manager.py``
     - 完整性
     - ``load_all`` 文件签名验证后 + exec_module 前后 SHA-256 比对
   * - ``patch_downloader.py``
     - 网络
     - 连接后从 socket 获取实际 IP 重新验证内网 (DNS rebinding)
   * - ``patch_sandbox.py``
     - 消毒
     - ``_sanitize_imported_module`` 递归 depth=3 + 下划线前缀检查
   * - ``patch_sandbox.py``
     - 超时
     - 僵尸线程追踪告警 (>10 个) + 线程命名 sandbox-{id}
   * - ``integration/bus.py``
     - 访问控制
     - 重复子系统注册抛 ValueError；``list_subsystems`` 默认隐藏敏感信息
   * - ``integration/bus.py``
     - 监控
     - 超时请求记录活跃线程数
   * - ``security/__init__.py``
     - 序列化
     - ``set_serialization_secret`` 仅允许一次调用
   * - ``server.py``
     - 错误处理
     - 补丁 API 加载失败记录 error 日志
