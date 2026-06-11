Minecraft LogBrain
==================

面向复杂 Mod 环境的 Minecraft 崩溃日志智能诊断平台。

**核心定位**：高并发解析 + AI 语义分析 + 可扩展检测器。
回答三件事：哪个组件触发崩溃、哪个根因最可疑、下一步怎么修。

----

快速开始
--------

.. code-block:: bash

   # 基础安装
   pip install -r requirements.txt

   # AI 增强安装
   pip install -e .[ai]

   # 启动 GUI
   python main.py

   # 启动 API 服务
   logbrain-cli serve --host 0.0.0.0 --port 8000

----

模块概览
--------

.. list-table::
   :header-rows: 1

   * - 模块
     - 说明
   * - :doc:`api`
     - 核心 API 参考（诊断引擎 / 检测器 / BrainCore / DLC / 补丁管理 / REST API）
   * - :doc:`ops`
     - 运维手册（启动方式、健康检查、安全配置）
   * - :doc:`security-report`
     - 安全报告（漏洞目录 + 修复策略 + 攻击链验证）

核心包：

* **mca_core** — 核心引擎：21 种崩溃检测器、并行诊断引擎 v3.0、补丁管理（AST 验证 + 三级沙箱）、仪表盘
* **brain_system** — AI 语义分析：BrainCore 调度器、DLC 插件框架、REST API 服务端
* **dlcs** — DLC 扩展包：CodeBERT 语义引擎、硬件加速器、神经网络算子、分布式计算

----

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

.. toctree::
   :maxdepth: 2
   :hidden:

   api
   ops
   security-report
