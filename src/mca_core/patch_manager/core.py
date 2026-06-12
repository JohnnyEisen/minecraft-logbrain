# -*- coding: utf-8 -*-
"""补丁管理系统 — 核心管理器

PatchManager 是整个补丁生命周期管理的中央编排器。
它协调存储、依赖、完整性、回滚等子系统，
提供统一的 API 给 CLI 和程序化调用。
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime
from typing import Any

from .dependency import DependencyGraph, detect_conflicts
from .integrity import (
    compute_file_hash,
    compute_hmac_signature,
    get_patch_key,
    verify_file_integrity,
    verify_meta_consistency,
    verify_signature,
)
from .models import (
    ConflictReport,
    InstallPlan, PatchMeta, PatchRecord,
    PatchReport, PatchState, RollbackPoint,
)
from .patch_cache import PatchCache
from .patch_downloader import PatchDownloader
from .patch_monitor import PatchMonitor
from .patch_sandbox import (
    PermissionLevel,
    execute_patch_sandboxed,
)
from .patch_validator import (
    PatchValidator,
    RiskLevel,
    validate_patch_code,
)
from .rollback import RollbackManager
from .storage import PatchStore


class PatchManager:
    """补丁生命周期中央管理器（线程安全 + 缓存 + 安全验证）。

    协调补丁的扫描、上传、安装、回滚、监控全生命周期。
    所有写操作受 ``threading.RLock()`` 保护，读操作使用 mtime 缓存。

    :param patch_dir: 补丁存储目录路径。
    :param config: DI 注入的配置管理器（可选）。
    :param audit: DI 注入的审计追踪器（可选）。

    **用法**::

        pm = PatchManager("patches")
        pm.scan()
        pm.apply_patch("hotfix_001")           # 单补丁安装
        pm.apply_all()                         # 批量安装
        report = pm.generate_report()
        print(report.summary)
    """

    def __init__(
        self,
        patch_dir: str,
        *,
        config: Any = None,
        audit: Any = None,
    ) -> None:
        self._store = PatchStore(patch_dir)
        self._rollback = RollbackManager(self._store)
        self._state: dict[str, PatchRecord] = {}
        self._metas: dict[str, PatchMeta] = {}
        self._initialized = False
        self._lock = threading.RLock()
        self._cache = PatchCache()
        self._downloader = PatchDownloader()
        self._monitor: PatchMonitor | None = None
        self._validator = PatchValidator()
        self._sandbox_level = PermissionLevel.RESTRICTED

        self._config = config
        self._audit = audit
        self._max_retries = 3
        self._monitor_interval = 30.0

        if config is not None:
            self._max_retries = config.get_int("patch.max_retries", 3)
            self._monitor_interval = config.get_float("monitor.interval_seconds", 30.0)

    # --- 初始化 ---

    def scan(self) -> int:
        """扫描 patches 目录，加载所有元数据和状态。

        使用 mtime 缓存：首次读取磁盘，后续命中缓存则跳过。

        Returns:
            发现的补丁数量
        """
        with self._lock:
            self._metas = self._store.load_all_meta(cache=self._cache)
            self._state = self._store.load_state(cache=self._cache)
            self._initialized = True

            for pid in self._metas:
                if pid not in self._state:
                    self._state[pid] = PatchRecord(patch_id=pid, state="available")

            count = len(self._metas)

        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PATCH_SCAN,
                    detail=f"扫描完成，发现 {count} 个补丁",
                    component="patch_manager",
                    metadata={"patch_count": count},
                )
            except Exception:
                pass

        return count

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # --- 补丁上传 ---

    def upload_patch(
        self,
        source_path: str,
        meta: PatchMeta,
        key: bytes | None = None,
    ) -> tuple[bool, str]:
        with self._lock:
            return self._upload_patch_locked(source_path, meta, key)

    def _upload_patch_locked(
        self,
        source_path: str,
        meta: PatchMeta,
        key: bytes | None = None,
    ) -> tuple[bool, str]:
        if not os.path.isfile(source_path):
            return False, f"源文件不存在: {source_path}"

        basename = os.path.basename(source_path)
        if not basename.endswith(".py"):
            return False, "补丁文件必须是 .py 文件"

        # ── VULN-003 修复: API 上传的补丁最高只能为 standard 权限 ──
        # admin 权限补丁仅允许通过本地手动部署（签名的补丁）
        if meta.permission_level == "admin":
            return False, (
                "admin 权限级别的补丁不允许通过 Web API 上传。"
                "请使用本地部署方式安装 admin 权限补丁。"
            )

        # ── VULN-005 修复: 先 hash 再读取，防止 TOCTOU ──
        import hashlib
        try:
            with open(source_path, "rb") as f:
                raw_bytes = f.read()
            pre_hash = hashlib.sha256(raw_bytes).hexdigest()
            patch_code = raw_bytes.decode("utf-8")
        except Exception as e:
            return False, f"无法读取补丁文件: {e}"

        validation = validate_patch_code(patch_code, basename)
        if not validation.is_valid:
            return False, f"补丁代码验证失败:\n{validation.summary}"

        # 风险等级过高则拒绝
        if validation.risk_level in (RiskLevel.CRITICAL.value, RiskLevel.REJECTED.value):
            return False, (
                f"补丁风险等级为 {validation.risk_level}，拒绝上传。\n"
                f"{validation.summary}"
            )

        # 根据风险等级自动设置权限
        if meta.permission_level == "restricted":
            if validation.risk_level in (RiskLevel.HIGH.value, RiskLevel.MEDIUM.value):
                return False, (
                    f"补丁风险等级为 {validation.risk_level}，"
                    f"但权限级别为 restricted。\n"
                    f"请将 permission_level 设置为 'standard'。\n"
                    f"{validation.summary}"
                )

        # VULN-003 修复: standard 级别也拒绝 HIGH 风险（含 os.system/subprocess 等）
        if validation.risk_level == RiskLevel.HIGH.value:
            return False, (
                f"补丁风险等级为 HIGH，包含系统调用。\n"
                f"该补丁无法通过 Web API 安装。\n"
                f"{validation.summary}"
            )

        # 回填风险等级到元数据
        meta.risk_level = validation.risk_level
        # ── 安全验证结束 ──

        pid = meta.patch_id

        if self._store.patch_exists(pid):
            self._store.archive_patch(pid)

        dest = self._store.upload_patch(source_path, pid)

        # ── VULN-005: 验证写入文件与验证时一致 ──
        meta.file_hash = compute_file_hash(dest)
        if meta.file_hash != pre_hash:
            # 文件在上传过程中被替换！回滚
            if os.path.exists(dest):
                os.remove(dest)
            return False, "安全错误: 补丁文件在验证后发生变更，已拒绝"

        if key is None:
            key = get_patch_key()
        if key:
            meta.signature = compute_hmac_signature(dest, key)
            # 生成元数据认证 token
            from .integrity import _compute_auth_token
            meta_dict = meta.to_dict()
            meta_dict["file_hash"] = meta.file_hash
            meta_dict["signature"] = meta.signature
            meta.integrity_token = _compute_auth_token(dest, meta_dict, key)

        if not meta.created_date:
            meta.created_date = datetime.now().isoformat()

        self._store.write_meta(meta)

        self._metas = self._store.load_all_meta(cache=self._cache)
        self._state = self._store.load_state(cache=self._cache)

        for pid_existing in self._metas:
            if pid_existing not in self._state:
                self._state[pid_existing] = PatchRecord(patch_id=pid_existing, state="available")

        return True, f"补丁 {pid} v{meta.version} 上传成功"

    # --- 元数据管理 ---

    def get_meta(self, patch_id: str) -> PatchMeta | None:
        return self._metas.get(patch_id)

    def update_meta(self, patch_id: str, updates: dict) -> tuple[bool, str]:
        """更新补丁元数据。"""
        meta = self._metas.get(patch_id)
        if meta is None:
            return False, f"补丁不存在: {patch_id}"

        for key, value in updates.items():
            if hasattr(meta, key) and key != "patch_id":
                setattr(meta, key, value)

        self._store.write_meta(meta)
        return True, f"元数据已更新: {patch_id}"

    def list_metas(self, filter_state: str | None = None) -> list[PatchMeta]:
        """列出所有补丁元数据，可按状态筛选。"""
        if filter_state is None:
            return list(self._metas.values())

        result = []
        for pid, meta in self._metas.items():
            rec = self._state.get(pid)
            if rec and rec.state == filter_state:
                result.append(meta)
        return result

    # --- 完整性校验 ---

    def verify_integrity(self, patch_id: str) -> tuple[bool, str]:
        """校验补丁完整性：文件哈希 + 签名 + 元数据一致性。
        
        Returns:
            (pass, details)
        """
        meta = self._metas.get(patch_id)
        if meta is None:
            return False, "元数据不存在"

        patch_file = os.path.join(self._store.patch_dir, f"{patch_id}.py")
        meta_file = self._store.get_meta_path(patch_file)

        # 1. 元数据一致性
        ok, err = verify_meta_consistency(patch_file, meta_file)
        if not ok:
            return False, f"元数据一致性失败: {err}"

        # 2. 文件哈希
        if not verify_file_integrity(patch_file, meta.file_hash):
            return False, "文件哈希不匹配"

        # 3. 签名验证
        key = get_patch_key()
        if key and meta.signature:
            if not verify_signature(patch_file, key, meta.signature):
                return False, "签名验证失败"

        # 4. 元数据认证 token 校验
        if key:
            from .integrity import _verify_auth_token
            meta_dict = meta.to_dict() if hasattr(meta, "to_dict") else {
                "patch_id": meta.patch_id, "version": meta.version,
                "signature": meta.signature, "file_hash": meta.file_hash,
                "integrity_token": meta.integrity_token if hasattr(meta, "integrity_token") else "",
            }
            ok, err = _verify_auth_token(patch_file, meta_dict, key)
            if not ok:
                return False, err

        return True, "完整性校验通过"

    def verify_all(self) -> dict[str, tuple[bool, str]]:
        """批量校验所有补丁完整性。"""
        return {pid: self.verify_integrity(pid) for pid in self._metas}

    # --- 依赖性管理 ---

    def build_dependency_graph(self) -> DependencyGraph:
        """构建当前所有补丁的依赖图。"""
        dg = DependencyGraph()
        dg.build(list(self._metas.values()))
        return dg

    def check_dependencies(self, patch_id: str) -> tuple[bool, list[str]]:
        """检查补丁依赖是否满足。"""
        installed = {
            pid for pid, rec in self._state.items()
            if rec.state == "applied"
        }
        dg = self.build_dependency_graph()
        return dg.check_dependencies_satisfied(patch_id, installed)

    # --- 冲突检测 ---

    def detect_conflicts(self, patch_ids: list[str] | None = None) -> ConflictReport:
        """检测补丁间冲突。

        Args:
            patch_ids: 要检查的补丁 ID 列表（None = 所有）

        Returns:
            ConflictReport
        """
        if patch_ids is None:
            metas = list(self._metas.values())
        else:
            metas = [self._metas[pid] for pid in patch_ids if pid in self._metas]
        return detect_conflicts(metas, self._state)

    # --- 安装计划 ---

    def plan_install(self, patch_ids: list[str] | None = None) -> InstallPlan:
        """生成安装计划 — 拓扑排序确定安装顺序。

        Args:
            patch_ids: 要安装的补丁 ID（None = 所有未安装的）

        Returns:
            InstallPlan 包含排序后的补丁列表
        """
        if patch_ids is None:
            # 默认：所有非 applied/failed/disabled 的补丁
            patch_ids = [
                pid for pid, rec in self._state.items()
                if rec.state in ("available", "pending", "rolled_back", "superseded")
            ]

        metas = [self._metas[pid] for pid in patch_ids if pid in self._metas]

        dg = DependencyGraph()
        dg.build(metas)

        # 检测循环依赖
        cycles = dg.detect_cycles()
        warnings = []
        if cycles:
            for c in cycles:
                warnings.append(f"循环依赖: {' → '.join(c)}")

        # 冲突检测
        conflict_report = detect_conflicts(metas, self._state)
        if conflict_report.has_conflicts:
            for c in conflict_report.conflicts:
                warnings.append(c["detail"])

        # 拓扑排序
        try:
            order = dg.topological_sort()
        except ValueError as e:
            order = list(dg.nodes)
            warnings.append(str(e))

        # 筛选有元数据的补丁
        ordered_metas = [self._metas[pid] for pid in order if pid in self._metas]

        plan = InstallPlan(
            plan_id=f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            created_at=datetime.now().isoformat(),
            patches=ordered_metas,
            total_count=len(ordered_metas),
            estimated_steps=len(ordered_metas),
            warnings=warnings,
        )

        # 生成备注
        if ordered_metas:
            plan.notes.append(
                f"安装顺序: {' → '.join(m.patch_id for m in ordered_metas)}"
            )
            plan.notes.append(
                "可运行 apply_plan() 执行安装"
            )

        return plan

    def get_install_chain(self, patch_id: str) -> list[str]:
        """获取安装指定补丁所需的完整依赖链。"""
        dg = self.build_dependency_graph()
        return dg.get_install_chain(patch_id)

    # --- 安装执行 ---

    def apply_patch(self, patch_id: str) -> tuple[bool, str]:
        with self._lock:
            return self._apply_patch_locked(patch_id)

    def _apply_patch_locked(self, patch_id: str) -> tuple[bool, str]:
        if patch_id not in self._metas:
            return False, f"补丁不存在: {patch_id}"

        rec = self._state.get(patch_id)
        if rec is None:
            return False, f"补丁未在状态中: {patch_id}"

        meta = self._metas[patch_id]

        if rec.state == "applied":
            return False, f"补丁已安装: {patch_id}"

        ok, msg = self.verify_integrity(patch_id)
        if not ok:
            rec.state = "failed"
            rec.error_message = msg
            rec.last_checked_at = datetime.now().isoformat()
            self._persist_state()
            return False, f"完整性校验失败: {msg}"

        try:
            rp = self._rollback.create_snapshot(
                patch_id, meta.version, self._state
            )
            rec.rollback_point_id = rp.point_id
        except Exception as e:
            return False, f"创建回滚快照失败: {e}"

        rec.state = "installing"
        rec.last_checked_at = datetime.now().isoformat()
        self._persist_state()

        try:
            # ── 沙箱安全执行 ──
            patch_path = os.path.join(self._store.patch_dir, f"{patch_id}.py")
            with open(patch_path, "r", encoding="utf-8") as f:
                patch_code = f.read()

            # 根据元数据中的权限级别确定沙箱等级
            sandbox_level = PermissionLevel.RESTRICTED
            if meta.permission_level == "admin":
                sandbox_level = PermissionLevel.ADMIN
            elif meta.permission_level == "standard":
                sandbox_level = PermissionLevel.STANDARD

            # 在沙箱中执行补丁
            sandbox_result = execute_patch_sandboxed(
                code=patch_code,
                patch_id=patch_id,
                level=sandbox_level,
                entry_point="apply",
            )

            if not sandbox_result.success:
                raise RuntimeError(sandbox_result.message)

            if self._audit is not None:
                try:
                    from mca_core.audit import OperationType as OpT
                    self._audit.record(
                        op_type=OpT.PATCH_INSTALL,
                        detail=(
                            f"补丁 {patch_id} v{meta.version} 沙箱执行成功 "
                            f"(权限: {sandbox_level.value}, "
                            f"耗时: {sandbox_result.execution_time_ms:.1f}ms)"
                        ),
                        component="patch_manager",
                        metadata={
                            "patch_id": patch_id,
                            "version": meta.version,
                            "permission_level": sandbox_level.value,
                            "execution_time_ms": sandbox_result.execution_time_ms,
                        },
                    )
                except Exception:
                    pass
            # ── 沙箱执行结束 ──
        except Exception as e:
            rec.state = "failed"
            rec.error_message = str(e)
            rec.last_checked_at = datetime.now().isoformat()
            self._persist_state()
            return False, f"模块加载失败: {e}"

        now = datetime.now().isoformat()
        rec.state = "applied"
        rec.installed_version = meta.version
        rec.installed_at = now
        rec.last_checked_at = now
        rec.error_message = ""
        rec.metadata_snapshot = meta.to_dict()

        max_order = max(
            (r.install_order for r in self._state.values() if r.install_order > 0),
            default=0,
        )
        rec.install_order = max_order + 1

        for old_id in meta.replaces:
            if old_id in self._state:
                self._state[old_id].state = "superseded"

        self._persist_state()

        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PATCH_INSTALL,
                    detail=f"补丁 {patch_id} v{meta.version} 安装成功",
                    component="patch_manager",
                    metadata={"patch_id": patch_id, "version": meta.version},
                )
            except Exception:
                pass

        return True, f"补丁 {patch_id} v{meta.version} 安装成功"

    def apply_plan(self, plan: InstallPlan) -> dict[str, tuple[bool, str]]:
        """按安装计划顺序执行所有补丁。

        Returns:
            {patch_id: (success, message)} 结果字典
        """
        results = {}
        for meta in plan.patches:
            ok, msg = self.apply_patch(meta.patch_id)
            results[meta.patch_id] = (ok, msg)
            if not ok:
                # 严重补丁失败则停止
                if meta.severity in ("critical", "high"):
                    break
        return results

    def apply_all(self) -> dict[str, tuple[bool, str]]:
        """应用所有可用补丁。"""
        plan = self.plan_install()
        return self.apply_plan(plan)

    # --- 回滚 ---

    def rollback_patch(self, patch_id: str) -> tuple[bool, str]:
        """回滚指定补丁。"""
        rec = self._state.get(patch_id)
        if rec is None:
            return False, f"补丁未在状态中: {patch_id}"
        if not rec.rollback_point_id:
            return False, f"补丁 {patch_id} 没有回滚点"

        ok, msg = self._rollback.rollback(rec.rollback_point_id, self._state)
        self._persist_state()

        if ok and self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PATCH_ROLLBACK,
                    detail=f"补丁 {patch_id} 已回滚",
                    component="patch_manager",
                    metadata={"patch_id": patch_id},
                )
            except Exception:
                pass

        return ok, msg

    def cascade_rollback(self, patch_id: str) -> tuple[bool, str, int]:
        """级联回滚。"""
        ok, msg, count = self._rollback.cascade_rollback(patch_id, self._state)
        self._persist_state()
        return ok, msg, count

    def list_snapshots(self) -> list[dict]:
        """列出所有回滚快照。"""
        return self._rollback.list_snapshots()

    # --- 状态管理 ---

    def get_state(self, patch_id: str) -> PatchRecord | None:
        return self._state.get(patch_id)

    def get_state_summary(self) -> dict[str, int]:
        """获取状态汇总统计。"""
        counts = {s.value: 0 for s in PatchState}
        for rec in self._state.values():
            counts[rec.state] = counts.get(rec.state, 0) + 1
        return counts

    def disable_patch(self, patch_id: str) -> tuple[bool, str]:
        """禁用一个补丁（不卸载，仅标记）。"""
        if patch_id not in self._state:
            return False, f"补丁不存在: {patch_id}"
        self._state[patch_id].state = "disabled"
        self._persist_state()

        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PATCH_REMOVE,
                    detail=f"补丁 {patch_id} 已禁用",
                    component="patch_manager",
                    metadata={"patch_id": patch_id},
                )
            except Exception:
                pass

        return True, f"补丁已禁用: {patch_id}"

    def enable_patch(self, patch_id: str) -> tuple[bool, str]:
        """启用一个已禁用的补丁。"""
        if patch_id not in self._state:
            return False, f"补丁不存在: {patch_id}"
        if self._state[patch_id].state != "disabled":
            return False, f"补丁 {patch_id} 不是禁用状态"
        self._state[patch_id].state = "available"
        self._persist_state()

        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.PATCH_VERIFY,
                    detail=f"补丁 {patch_id} 已启用",
                    component="patch_manager",
                    metadata={"patch_id": patch_id},
                )
            except Exception:
                pass

        return True, f"补丁已启用: {patch_id}"

    # --- 报告生成 ---

    def generate_report(self) -> PatchReport:
        """生成补丁管理报告。"""
        now = datetime.now().isoformat()
        summary = self.get_state_summary()

        patches_detail = []
        for pid in sorted(self._state.keys()):
            rec = self._state[pid]
            meta = self._metas.get(pid)
            detail = {
                "patch_id": pid,
                "state": rec.state,
                "version": rec.installed_version or (meta.version if meta else ""),
                "installed_at": rec.installed_at,
                "error": rec.error_message,
                "install_order": rec.install_order,
                "severity": meta.severity if meta else "",
                "description": meta.description if meta else "",
            }
            patches_detail.append(detail)

        report = PatchReport(
            generated_at=now,
            total_patches=len(self._state),
            applied=summary.get("applied", 0),
            available=summary.get("available", 0),
            pending=summary.get("pending", 0),
            failed=summary.get("failed", 0),
            rolled_back=summary.get("rolled_back", 0),
            disabled=summary.get("disabled", 0),
            superseded=summary.get("superseded", 0),
            patches=patches_detail,
        )

        # 生成摘要
        parts = [f"总数={report.total_patches}"]
        if report.applied:
            parts.append(f"已应用={report.applied}")
        if report.available:
            parts.append(f"可用={report.available}")
        if report.failed:
            parts.append(f"失败={report.failed}")
        if report.disabled:
            parts.append(f"已禁用={report.disabled}")
        report.summary = ", ".join(parts)

        return report

    # --- 远程下载 ---

    def download_patch(
        self,
        url: str,
        patch_id: str,
        meta: PatchMeta,
        expected_sha256: str | None = None,
        progress_callback=None,
    ) -> tuple[bool, str]:
        """从远程 URL 下载补丁并注册。

        Args:
            url: 补丁文件下载 URL
            patch_id: 补丁 ID
            meta: 补丁元数据
            expected_sha256: 期望的 SHA-256（可选）
            progress_callback: 进度回调 fn(done_bytes, total_bytes)

        Returns:
            (success, message)
        """
        # VULN-008 修复: 防止路径遍历 + 验证目标在 patch_dir 内
        safe_pid = os.path.basename(patch_id)
        if safe_pid != patch_id or ".." in patch_id or "/" in patch_id or "\\" in patch_id:
            return False, f"无效的 patch_id: {patch_id}"
        dest = os.path.join(self._store.patch_dir, f"{safe_pid}.py")
        if not os.path.realpath(dest).startswith(os.path.realpath(self._store.patch_dir)):
            return False, "路径遍历攻击被阻止"
        ok, msg = self._downloader.download(url, dest, expected_sha256, progress_callback)
        if not ok:
            return False, msg

        with self._lock:
            meta.file_hash = compute_file_hash(dest)
            if not meta.created_date:
                meta.created_date = datetime.now().isoformat()
            self._store.write_meta(meta)
            self._metas[patch_id] = meta
            self._state[patch_id] = PatchRecord(patch_id=patch_id, state="available")

        return True, f"补丁 {patch_id} 下载并注册成功"

    def cancel_download(self) -> None:
        self._downloader.cancel()

    # --- 后台监控 ---

    def start_monitor(self, interval: float = 30.0) -> None:
        if self._monitor is None:
            self._monitor = PatchMonitor(self, interval)
        self._monitor.start()

        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.SYSTEM_START,
                    detail=f"补丁监控已启动 (间隔 {interval}s)",
                    component="patch_manager",
                )
            except Exception:
                pass

    def stop_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.SYSTEM_STOP,
                    detail="补丁监控已停止",
                    component="patch_manager",
                )
            except Exception:
                pass

    def get_monitor_stats(self) -> dict:
        if self._monitor is None:
            return {"error": "监控未启动"}
        return self._monitor.get_stats()

    # --- 缓存管理 ---

    def get_cache_stats(self) -> dict[str, float]:
        return {
            "size": self._cache.size,
            "hit_rate": round(self._cache.hit_rate, 4),
        }

    def invalidate_cache(self) -> None:
        self._cache.clear()

    # --- 内部辅助 ---

    def _persist_state(self):
        """持久化当前状态。"""
        self._store.save_state(self._state)
        serialized = {pid: rec.to_dict() for pid, rec in self._state.items()}
        self._cache.put_state(self._store._get_state_path(), serialized)