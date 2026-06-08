# -*- coding: utf-8 -*-
"""MCA 补丁管理子系统 — MCA Brain System 内建子系统

补丁管理系统是 MCA Brain System 的子系统，非独立 Web 应用。
作为 `mca_core.patch_manager` 包运行于 MCA 进程空间中。

PatchSubsystem 提供标准化子系统生命周期管理 (initialize → startup → shutdown)，
PatchManager 提供底层补丁操作 API。

功能覆盖:
- 补丁上传与存储
- 版本控制
- 依赖关系管理（DAG + 拓扑排序）
- 冲突检测与解决
- 补丁应用状态监控
- 回滚机制（快照 + 级联回滚）
- 补丁元数据管理
- 完整性校验（SHA-256 + HMAC-SHA256）
- REST API 管理接口（可选）

用法 — 子系统模式（推荐）:
    from mca_core.patch_manager import PatchSubsystem

    sub = PatchSubsystem("patches")
    sub.initialize()
    sub.startup()
    sub.install_patch("hotfix_001")
    sub.shutdown()

用法 — 直接 API 模式:
    from mca_core.patch_manager import PatchManager

    pm = PatchManager("patches")
    pm.scan()
    report = pm.generate_report()
    print(report.summary)
"""

from .core import PatchManager
from .models import (
    ConflictReport,
    ConflictType,
    InstallPlan,
    PatchMeta,
    PatchRecord,
    PatchReport,
    PatchSeverity,
    PatchState,
    RollbackPoint,
)
from .dependency import DependencyGraph, detect_conflicts
from .integrity import (
    compute_file_hash,
    verify_file_integrity,
    verify_meta_consistency,
    verify_signature,
    get_patch_key,
)
from .patch_cache import PatchCache
from .patch_downloader import PatchDownloader
from .patch_monitor import PatchMonitor
from .patch_sandbox import (
    PermissionLevel,
    SandboxResult,
    create_sandbox_globals,
    execute_patch_sandboxed,
)
from .patch_validator import (
    PatchValidator,
    RiskLevel,
    ValidationResult,
    validate_patch_code,
    validate_patch_file,
)
from .rollback import RollbackManager
from .storage import PatchStore
from .subsystem import PatchSubsystem, SubsystemState, SubsystemStatus

__all__ = [
    # 子系统接口（推荐入口）
    "PatchSubsystem",
    "SubsystemState",
    "SubsystemStatus",
    # 核心管理器
    "PatchManager",
    # 数据模型
    "PatchMeta",
    "PatchRecord",
    "PatchReport",
    "InstallPlan",
    "RollbackPoint",
    "ConflictReport",
    "PatchState",
    "PatchSeverity",
    "ConflictType",
    # 内部模块
    "PatchStore",
    "DependencyGraph",
    "RollbackManager",
    "detect_conflicts",
    # 完整性
    "compute_file_hash",
    "verify_file_integrity",
    "verify_meta_consistency",
    "verify_signature",
    "get_patch_key",
    # 安全验证
    "PatchValidator",
    "ValidationResult",
    "RiskLevel",
    "validate_patch_code",
    "validate_patch_file",
    # 沙箱执行
    "PermissionLevel",
    "SandboxResult",
    "create_sandbox_globals",
    "execute_patch_sandboxed",
    # 新增组件
    "PatchCache",
    "PatchDownloader",
    "PatchMonitor",
]