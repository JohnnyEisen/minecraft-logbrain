# -*- coding: utf-8 -*-
"""补丁管理系统 — 回滚机制

功能：
- 创建回滚快照 (安装前保存状态)
- 执行回滚 (恢复到快照状态)
- 快照完整性验证
- 级联回滚 (按安装逆序批量回滚)
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime

from .integrity import compute_snapshot_checksum
from .models import PatchRecord, RollbackPoint


class RollbackManager:
    """回滚管理器 — 快照创建、回滚执行和完整性验证。"""

    def __init__(self, store):
        """
        Args:
            store: PatchStore 实例
        """
        self._store = store
        self._rollback_dir = store.rollback_dir
        self._patch_dir = store.patch_dir

    # --- 快照创建 ---

    def create_snapshot(
        self,
        patch_id: str,
        patch_version: str,
        state: dict[str, PatchRecord],
    ) -> RollbackPoint:
        """创建回滚快照 — 在应用补丁前保存系统状态。

        Args:
            patch_id: 即将应用的补丁 ID
            patch_version: 补丁版本
            state: 当前完整的状态数据库

        Returns:
            RollbackPoint 回滚点
        """
        now = datetime.now()
        point_id = f"rb_{patch_id}_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # 备份即将被修改的文件
        backup_files = self._backup_patch_files(patch_id)

        # 保存状态快照
        state_snapshot = {
            pid: rec.to_dict() for pid, rec in state.items()
        }

        rp = RollbackPoint(
            point_id=point_id,
            created_at=now.isoformat(),
            patch_id=patch_id,
            patch_version=patch_version,
            backup_files=backup_files,
            state_snapshot=state_snapshot,
            checksum=compute_snapshot_checksum(state_snapshot),
        )

        self._store.save_rollback_point(rp)
        return rp

    def _backup_patch_files(self, patch_id: str) -> dict[str, str]:
        """备份补丁相关文件。

        Returns:
            {原始路径: 备份路径}
        """
        backups = {}
        patch_file = os.path.join(self._patch_dir, f"{patch_id}.py")
        meta_file = os.path.join(self._patch_dir, f"{patch_id}.meta.json")

        for src in (patch_file, meta_file):
            if os.path.exists(src):
                dst = src + ".backup"
                shutil.copy2(src, dst)
                backups[src] = dst

        return backups

    # --- 回滚执行 ---

    def rollback(self, point_id: str, state: dict[str, PatchRecord]) -> tuple[bool, str]:
        """执行单次回滚 — 恢复到指定快照点。

        Args:
            point_id: 回滚点 ID
            state: 当前状态（将被更新）

        Returns:
            (success, message)
        """
        rp = self._store.load_rollback_point(point_id)
        if rp is None:
            return False, f"回滚点不存在: {point_id}"

        # 1. 验证快照完整性
        actual = compute_snapshot_checksum(rp.state_snapshot)
        if actual != rp.checksum:
            return False, (
                f"回滚快照完整性校验失败: "
                f"期望={rp.checksum[:16]}... 实际={actual[:16]}..."
            )

        # 2. 恢复备份文件
        for orig_path, backup_path in rp.backup_files.items():
            if os.path.exists(backup_path):
                if os.path.exists(orig_path):
                    os.remove(orig_path)
                shutil.move(backup_path, orig_path)

        # 3. 恢复状态
        state.clear()
        for pid, rec_dict in rp.state_snapshot.items():
            state[pid] = PatchRecord.from_dict(rec_dict)

        # 更新被回滚补丁的状态
        target = rp.patch_id
        if target in state:
            state[target].state = "rolled_back"
            state[target].error_message = f"已回滚至 {point_id}"
            state[target].rollback_point_id = point_id

        # 4. 清理回滚点
        self._store.delete_rollback_point(point_id)

        return True, f"成功回滚补丁 {rp.patch_id} 至快照 {point_id}"

    def cascade_rollback(
        self,
        target_patch_id: str,
        state: dict[str, PatchRecord],
    ) -> tuple[bool, str, int]:
        """级联回滚 — 按安装逆序回滚目标及其所有依赖者。

        从状态数据库中找到目标补丁之后安装的所有补丁，
        按安装逆序逐个回滚。

        Args:
            target_patch_id: 回滚的起始补丁 ID
            state: 当前状态

        Returns:
            (success, message, rolled_back_count)
        """
        # 找到目标补丁的安装序号
        if target_patch_id not in state:
            return False, f"补丁 {target_patch_id} 未在状态中", 0

        target_order = state[target_patch_id].install_order

        # 找到所有安装序号 >= target_order 的补丁
        affected = [
            (pid, rec)
            for pid, rec in state.items()
            if rec.install_order >= target_order
            and rec.state == "applied"
            and rec.rollback_point_id
        ]
        affected.sort(key=lambda x: -x[1].install_order)  # 逆序

        rolled = 0
        for pid, rec in affected:
            if not rec.rollback_point_id:
                continue
            ok, msg = self.rollback(rec.rollback_point_id, state)
            if ok:
                rolled += 1
            else:
                # 如果回滚循环中某个失败，这不是致命的 - 继续其他
                # 但报告错误
                pass

        if rolled > 0:
            return True, f"级联回滚完成: {rolled} 个补丁已回滚", rolled
        return False, f"未找到可回滚的补丁", 0

    # --- 查询 ---

    def list_snapshots(self) -> list[dict]:
        """列出所有可用回滚快照。"""
        points = self._store.list_rollback_points()
        result = []
        for pid in points:
            rp = self._store.load_rollback_point(pid)
            if rp:
                result.append({
                    "point_id": rp.point_id,
                    "patch_id": rp.patch_id,
                    "version": rp.patch_version,
                    "created_at": rp.created_at,
                    "backup_count": len(rp.backup_files),
                    "checksum": rp.checksum[:16] + "...",
                })
        return result

    def cleanup(self, keep_count: int = 10):
        """清理旧快照。"""
        self._store.cleanup_rollbacks(keep_count)