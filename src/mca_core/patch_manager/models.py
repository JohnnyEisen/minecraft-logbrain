# -*- coding: utf-8 -*-
"""补丁管理系统 — 数据模型

定义补丁生命周期中所有核心数据结构：
- PatchMeta      : 补丁元数据
- PatchState     : 补丁应用状态枚举
- PatchRecord    : 补丁运行时记录
- InstallPlan    : 安装计划
- RollbackPoint  : 回滚快照
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict, fields
from typing import Optional


# ============================================================
# 枚举
# ============================================================

class PatchState(enum.Enum):
    """补丁应用状态"""
    AVAILABLE   = "available"     # 可用，尚未安装
    PENDING     = "pending"       # 等待依赖满足后安装
    INSTALLING  = "installing"    # 正在安装中
    APPLIED     = "applied"       # 已成功应用
    FAILED      = "failed"        # 应用失败
    ROLLED_BACK = "rolled_back"   # 已回滚
    DISABLED    = "disabled"      # 已禁用
    SUPERSEDED  = "superseded"    # 被新版本替代


class PatchSeverity(enum.Enum):
    """补丁严重级别"""
    CRITICAL = "critical"   # 安全漏洞，需立即应用
    HIGH     = "high"       # 重要功能修复
    MEDIUM   = "medium"     # 一般修复
    LOW      = "low"        # 次要改进
    OPTIONAL = "optional"   # 可选增强


class ConflictType(enum.Enum):
    """冲突类型"""
    FILE_OVERLAP   = "file_overlap"    # 修改相同文件
    LOGIC_CONFLICT = "logic_conflict"   # 逻辑冲突（互斥声明）
    VERSION_CLASH  = "version_clash"   # 版本不兼容
    DEPENDENCY     = "dependency"       # 依赖冲突


# ============================================================
# 数据类
# ============================================================

@dataclass
class PatchMeta:
    """补丁元数据 — 描述补丁的身份和属性。
    
    每个补丁 (.py) 对应一个 PatchMeta，可存储为 .meta.json。
    """
    patch_id: str                              # 唯一标识，如 "hotfix_secure_ops"
    name: str                                  # 人类可读名称
    version: str                               # 语义化版本 "1.0.0"
    description: str                           # 修复描述
    author: str = "MCA Security Team"          # 作者
    created_date: str = ""                     # ISO 格式日期
    severity: str = "medium"                   # critical/high/medium/low/optional
    target_version: str = ">=1.0.0"            # 适用系统版本范围
    dependencies: list[str] = field(default_factory=list)   # 依赖的 patch_id 列表
    conflicts: list[str] = field(default_factory=list)       # 冲突的 patch_id 列表
    replaces: list[str] = field(default_factory=list)        # 替代的旧 patch_id
    affected_modules: list[str] = field(default_factory=list) # 影响的模块列表
    file_hash: str = ""                        # 补丁文件 SHA-256
    signature: str = ""                        # HMAC-SHA256 签名
    tags: list[str] = field(default_factory=list)            # 标签
    permission_level: str = "restricted"                     # 权限级别: restricted/standard/admin
    required_entry_points: list[str] = field(default_factory=lambda: ["apply"])  # 必需入口函数
    risk_level: str = ""                                     # 代码风险等级: safe/low/medium/high
    integrity_token: str = ""                                # Layer 7 盲态完整性 token

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PatchMeta":
        return cls(**{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}})
    

@dataclass
class PatchRecord:
    """补丁运行时状态记录 — 追踪单个补丁的安装历程。"""
    patch_id: str
    state: str = "available"                    # PatchState 值
    installed_version: str = ""                 # 当前安装版本
    installed_at: str = ""                      # 安装时间 ISO
    last_checked_at: str = ""                   # 最后检查时间
    error_message: str = ""                     # 失败原因
    install_order: int = 0                      # 安装序号
    rollback_point_id: str = ""                 # 关联的回滚点
    metadata_snapshot: Optional[dict] = None    # 安装时的元数据快照

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PatchRecord":
        return cls(**{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}})
    

@dataclass
class InstallPlan:
    """安装计划 — 拓扑排序后的补丁安装序列。"""
    plan_id: str                                # 计划 ID
    created_at: str                             # 创建时间
    patches: list[PatchMeta] = field(default_factory=list)  # 按安装顺序排列的补丁列表
    total_count: int = 0
    estimated_steps: int = 0
    warnings: list[str] = field(default_factory=list)      # 依赖警告
    notes: list[str] = field(default_factory=list)         # 备注

    def to_dict(self) -> dict:
        result = asdict(self)
        result["patches"] = [p.to_dict() for p in self.patches]
        return result


@dataclass
class RollbackPoint:
    """回滚快照 — 记录补丁应用前的系统状态。"""
    point_id: str
    created_at: str
    patch_id: str
    patch_version: str
    backup_files: dict[str, str] = field(default_factory=dict)  # {原始路径: 备份路径}
    state_snapshot: dict = field(default_factory=dict)           # 应用前的状态快照
    checksum: str = ""                                           # 快照完整性校验

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RollbackPoint":
        return cls(**{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}})
    

@dataclass
class ConflictReport:
    """冲突检测报告。"""
    has_conflicts: bool = False
    conflicts: list[dict] = field(default_factory=list)
    resolution: str = ""                        # 解决建议

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PatchReport:
    """补丁管理报告 — 汇总所有补丁的状态。"""
    generated_at: str = ""
    total_patches: int = 0
    applied: int = 0
    available: int = 0
    pending: int = 0
    failed: int = 0
    rolled_back: int = 0
    disabled: int = 0
    superseded: int = 0
    patches: list[dict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)