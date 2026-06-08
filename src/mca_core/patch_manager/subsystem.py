# -*- coding: utf-8 -*-
"""补丁管理子系统 — MCA 子系统接口

PatchSubsystem 是补丁管理系统在 MCA Brain System 中的正式子系统封装。
它包装 PatchManager，提供标准化的子系统生命周期管理，
以便与 BrainCore 调度器和 DLC 框架集成。

设计原则 (遵循 PRD & TECHNICAL_ARCHITECTURE):
- 子系统优先: 运行于 MCA 进程空间，非独立服务
- 库优先于服务: 程序化 API 为第一公民
- 生命周期管理: initialize → startup → shutdown
- 健康监控: status() 提供子系统运行状态

用法:
    from mca_core.patch_manager import PatchSubsystem

    sub = PatchSubsystem(patch_dir="patches")
    sub.initialize()
    sub.startup()
    # ... patch operations ...
    sub.shutdown()
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .core import PatchManager


class SubsystemState(Enum):
    """子系统生命周期状态"""
    UNINITIALIZED = "uninitialized"
    INITIALIZED   = "initialized"
    RUNNING       = "running"
    DEGRADED      = "degraded"
    STOPPING      = "stopping"
    STOPPED       = "stopped"
    ERROR         = "error"


@dataclass
class SubsystemStatus:
    """子系统状态快照"""
    name: str = "patch_management"
    version: str = "1.0.0"
    state: str = "uninitialized"
    patch_dir: str = ""
    total_patches: int = 0
    applied: int = 0
    available: int = 0
    failed: int = 0
    disabled: int = 0
    healthy: bool = False
    last_scan: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "state": self.state,
            "patch_dir": self.patch_dir,
            "total_patches": self.total_patches,
            "applied": self.applied,
            "available": self.available,
            "failed": self.failed,
            "disabled": self.disabled,
            "healthy": self.healthy,
            "last_scan": self.last_scan,
            "errors": self.errors,
        }


class PatchSubsystem:
    """MCA 补丁管理子系统 — 标准化子系统接口。

    包装 PatchManager，提供生命周期管理和 BrainCore 集成接口。

    Attributes:
        name: 子系统名称
        version: 子系统版本
        _state: 当前生命周期状态
        _pm: 内部 PatchManager 实例
        _patch_dir: 补丁存储目录

    Lifecycle:
        uninitialized → initialized → running → stopping → stopped
                                    ↓
                                 degraded / error
    """

    name: str = "patch_management"
    version: str = "1.0.0"

    def __init__(self, patch_dir: str = "patches"):
        """
        Args:
            patch_dir: 补丁存储目录路径（相对于项目根或绝对路径）
        """
        self._patch_dir = os.path.abspath(patch_dir)
        self._pm: Optional[PatchManager] = None
        self._state = SubsystemState.UNINITIALIZED
        self._errors: list[str] = []
        self._initialized_at: Optional[str] = None
        self._started_at: Optional[str] = None
        self._last_scan_at: Optional[str] = None

    # ── 生命周期管理 ──────────────────────────────────────

    def initialize(self) -> bool:
        """初始化子系统: 创建 PatchManager 实例并扫描补丁。

        此方法幂等——重复调用不会重新初始化。

        Returns:
            True 表示初始化成功
        """
        if self._state in (SubsystemState.INITIALIZED, SubsystemState.RUNNING):
            return True

        try:
            self._pm = PatchManager(self._patch_dir)
            self._pm.scan()
            self._state = SubsystemState.INITIALIZED
            self._initialized_at = datetime.now().isoformat()
            self._last_scan_at = self._initialized_at
            self._errors.clear()
            return True
        except Exception as e:
            self._state = SubsystemState.ERROR
            self._errors.append(f"初始化失败: {e}")
            return False

    def startup(self) -> bool:
        """启动子系统: 从 initialized 过渡到 running。

        执行启动后检查:
        - 验证 patches 目录可访问
        - 验证状态数据库可读写
        - 记录启动时间

        Returns:
            True 表示启动成功
        """
        if self._state == SubsystemState.RUNNING:
            return True

        if self._state != SubsystemState.INITIALIZED:
            if not self.initialize():
                return False

        try:
            if self._pm is None:
                raise RuntimeError("PatchManager 未初始化")

            # 启动检查: 目录可访问性
            if not os.path.isdir(self._patch_dir):
                os.makedirs(self._patch_dir, exist_ok=True)

            # 刷新扫描
            self._pm.scan()
            self._last_scan_at = datetime.now().isoformat()

            self._state = SubsystemState.RUNNING
            self._started_at = datetime.now().isoformat()
            return True
        except Exception as e:
            self._state = SubsystemState.DEGRADED
            self._errors.append(f"启动失败: {e}")
            return False

    def shutdown(self) -> bool:
        """关闭子系统: 持久化状态并释放资源。

        此方法幂等——重复调用安全。

        Returns:
            True 表示关闭成功
        """
        if self._state in (SubsystemState.STOPPED, SubsystemState.UNINITIALIZED):
            return True

        self._state = SubsystemState.STOPPING

        try:
            if self._pm is not None:
                self._pm._persist_state()
            self._state = SubsystemState.STOPPED
            return True
        except Exception as e:
            self._errors.append(f"关闭异常: {e}")
            self._state = SubsystemState.STOPPED
            return False

    # ── 状态查询 ──────────────────────────────────────────

    def status(self) -> SubsystemStatus:
        """获取子系统当前状态快照。

        Returns:
            SubsystemStatus 包含完整的运行时状态
        """
        summary: dict[str, int] = {}
        if self._pm is not None and self._pm.is_initialized:
            try:
                summary = self._pm.get_state_summary()
            except Exception:
                pass

        return SubsystemStatus(
            name=self.name,
            version=self.version,
            state=self._state.value,
            patch_dir=self._patch_dir,
            total_patches=sum(summary.values()),
            applied=summary.get("applied", 0),
            available=summary.get("available", 0),
            failed=summary.get("failed", 0),
            disabled=summary.get("disabled", 0),
            healthy=self.is_healthy(),
            last_scan=self._last_scan_at,
            errors=list(self._errors),
        )

    def is_healthy(self) -> bool:
        """检查子系统是否健康运行。

        健康条件:
        - 状态为 RUNNING
        - patches 目录存在且可访问
        - 无未恢复的错误
        """
        if self._state != SubsystemState.RUNNING:
            return False
        if not os.path.isdir(self._patch_dir):
            return False
        if self._pm is None or not self._pm.is_initialized:
            return False
        return True

    @property
    def state(self) -> SubsystemState:
        """当前生命周期状态"""
        return self._state

    @property
    def manager(self) -> Optional[PatchManager]:
        """获取内部 PatchManager 实例（高级操作用）。"""
        return self._pm

    # ── 委托方法 — 核心补丁操作 ──────────────────────────

    def _ensure_running(self):
        """确保子系统处于运行状态，否则抛出异常。"""
        if not self.is_healthy():
            raise RuntimeError(
                f"补丁子系统未就绪 (状态: {self._state.value})。"
                f"请先调用 initialize() + startup()"
            )
        if self._pm is None:
            raise RuntimeError("PatchManager 未初始化")

    def scan(self) -> int:
        """扫描补丁目录，刷新元数据和状态。"""
        self._ensure_running()
        count = self._pm.scan()
        self._last_scan_at = datetime.now().isoformat()
        return count

    def install_patch(self, patch_id: str, with_deps: bool = False, force: bool = False) -> tuple[bool, str]:
        """安装指定补丁。"""
        self._ensure_running()

        if with_deps:
            chain = self._pm.get_install_chain(patch_id)
            plan = self._pm.plan_install(chain)
            results = self._pm.apply_plan(plan)
            msgs = [msg for _, msg in results.values()]
            all_ok = all(ok for ok, _ in results.values())
            return all_ok, "; ".join(msgs)

        if not force:
            ok, missing = self._pm.check_dependencies(patch_id)
            if not ok:
                return False, f"依赖不满足: {missing}"

        return self._pm.apply_patch(patch_id)

    def rollback_patch(self, patch_id: str, cascade: bool = False) -> tuple[bool, str]:
        """回滚指定补丁。"""
        self._ensure_running()

        if cascade:
            ok, msg, _count = self._pm.cascade_rollback(patch_id)
            return ok, msg

        return self._pm.rollback_patch(patch_id)

    def verify_integrity(self, patch_id: str) -> tuple[bool, str]:
        """校验补丁完整性。"""
        self._ensure_running()
        return self._pm.verify_integrity(patch_id)

    def verify_all(self) -> dict[str, tuple[bool, str]]:
        """批量校验所有补丁完整性。"""
        self._ensure_running()
        return self._pm.verify_all()

    def generate_report(self):
        """生成补丁管理报告。"""
        self._ensure_running()
        return self._pm.generate_report()

    def get_install_plan(self):
        """生成安装计划。"""
        self._ensure_running()
        return self._pm.plan_install()

    def detect_conflicts(self, patch_ids: Optional[list[str]] = None):
        """检测补丁冲突。"""
        self._ensure_running()
        return self._pm.detect_conflicts(patch_ids)

    def disable_patch(self, patch_id: str) -> tuple[bool, str]:
        """禁用补丁。"""
        self._ensure_running()
        return self._pm.disable_patch(patch_id)

    def enable_patch(self, patch_id: str) -> tuple[bool, str]:
        """启用补丁。"""
        self._ensure_running()
        return self._pm.enable_patch(patch_id)

    def list_snapshots(self) -> list[dict]:
        """列出回滚快照。"""
        self._ensure_running()
        return self._pm.list_snapshots()

    def upload_patch(self, source_path: str, meta) -> tuple[bool, str]:
        """上传新补丁。"""
        self._ensure_running()
        return self._pm.upload_patch(source_path, meta)

    def download_patch(self, url: str, patch_id: str, meta, expected_sha256=None, progress_callback=None) -> tuple[bool, str]:
        self._ensure_running()
        return self._pm.download_patch(url, patch_id, meta, expected_sha256, progress_callback)

    def cancel_download(self) -> None:
        if self._pm is not None:
            self._pm.cancel_download()

    def start_monitor(self, interval: float = 30.0) -> None:
        self._ensure_running()
        self._pm.start_monitor(interval)

    def stop_monitor(self) -> None:
        if self._pm is not None:
            self._pm.stop_monitor()

    def get_monitor_stats(self) -> dict:
        if self._pm is not None:
            return self._pm.get_monitor_stats()
        return {"error": "管理器未初始化"}

    def get_cache_stats(self) -> dict:
        if self._pm is not None:
            return self._pm.get_cache_stats()
        return {"error": "管理器未初始化"}

    def invalidate_cache(self) -> None:
        if self._pm is not None:
            self._pm.invalidate_cache()

    # ── Dunder ────────────────────────────────────────────

    def __repr__(self) -> str:
        return (f"PatchSubsystem(name={self.name!r}, version={self.version!r}, "
                f"state={self._state.value}, dir={self._patch_dir!r})")

    def __enter__(self):
        """上下文管理器: 自动 initialize + startup。"""
        self.initialize()
        self.startup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器: 自动 shutdown。"""
        self.shutdown()
        return False