# -*- coding: utf-8 -*-
"""补丁管理系统 — 存储层

负责补丁文件的存储、检索和组织。
目录结构:
  patches/
    ├── hotfix_*.py          # 补丁文件
    ├── hotfix_*.meta.json   # 补丁元数据
    ├── .state.json          # 运行时状态数据库
    ├── .rollback/           # 回滚快照
    └── .archive/            # 归档旧版本
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .models import PatchMeta, PatchRecord, RollbackPoint


class PatchStore:
    """补丁文件存储管理器。

    封装 patches/ 目录的所有文件操作，
    提供上传、检索、归档和状态持久化功能。
    """

    def __init__(self, patch_dir: str):
        self.patch_dir = os.path.abspath(patch_dir)
        self.rollback_dir = os.path.join(self.patch_dir, ".rollback")
        self.archive_dir = os.path.join(self.patch_dir, ".archive")
        self.state_file = os.path.join(self.patch_dir, ".state.json")

        self._ensure_dirs()

    # --- 目录管理 ---

    def _ensure_dirs(self):
        """确保所有子目录存在。"""
        for d in (self.patch_dir, self.rollback_dir, self.archive_dir):
            os.makedirs(d, exist_ok=True)

    # --- 补丁文件操作 ---

    def list_patch_files(self) -> list[str]:
        """列出所有补丁 (.py) 文件路径。"""
        result = []
        if not os.path.isdir(self.patch_dir):
            return result
        for fname in sorted(os.listdir(self.patch_dir)):
            if fname.endswith(".py") and not fname.startswith("."):
                result.append(os.path.join(self.patch_dir, fname))
        return result

    def list_meta_files(self) -> list[str]:
        """列出所有元数据 (.meta.json) 文件路径。"""
        result = []
        if not os.path.isdir(self.patch_dir):
            return result
        for fname in sorted(os.listdir(self.patch_dir)):
            if fname.endswith(".meta.json"):
                result.append(os.path.join(self.patch_dir, fname))
        return result

    def get_meta_path(self, patch_path: str) -> str:
        """根据补丁文件路径推导元数据文件路径。"""
        base = os.path.basename(patch_path)
        name, _ = os.path.splitext(base)
        return os.path.join(self.patch_dir, f"{name}.meta.json")

    def patch_exists(self, patch_id: str) -> bool:
        """检查指定 ID 的补丁是否存在。"""
        patch_path = os.path.join(self.patch_dir, f"{patch_id}.py")
        return os.path.isfile(patch_path)

    def read_patch_content(self, patch_id: str) -> str:
        """读取补丁文件内容。"""
        patch_path = os.path.join(self.patch_dir, f"{patch_id}.py")
        with open(patch_path, "r", encoding="utf-8") as f:
            return f.read()

    # --- 元数据操作 ---

    def read_meta(self, patch_id: str) -> PatchMeta | None:
        """读取补丁元数据。"""
        meta_path = os.path.join(self.patch_dir, f"{patch_id}.meta.json")
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PatchMeta.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return None

    def write_meta(self, meta: PatchMeta):
        """写入补丁元数据。"""
        meta_path = os.path.join(self.patch_dir, f"{meta.patch_id}.meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta.to_dict(), f, indent=2, ensure_ascii=False)

    def delete_meta(self, patch_id: str):
        """删除补丁元数据。"""
        meta_path = os.path.join(self.patch_dir, f"{patch_id}.meta.json")
        if os.path.exists(meta_path):
            os.remove(meta_path)

    def _get_state_path(self) -> str:
        return self.state_file

    def load_all_meta(self, cache=None) -> dict[str, PatchMeta]:
        """加载所有补丁的元数据（支持 mtime 缓存）。

        Args:
            cache: 可选 PatchCache 实例

        Returns:
            {patch_id: PatchMeta} 字典
        """
        meta_files = self.list_meta_files()
        result = {}
        for meta_path in meta_files:
            if cache is not None:
                cached = cache.get_meta(meta_path)
                if cached is not None:
                    _, data = cached
                    if isinstance(data, dict):
                        try:
                            meta = PatchMeta.from_dict(data)
                            result[meta.patch_id] = meta
                            continue
                        except Exception:
                            pass

            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = PatchMeta.from_dict(data)
                result[meta.patch_id] = meta
                if cache is not None:
                    cache.put_meta(meta_path, data)
            except (json.JSONDecodeError, TypeError):
                continue
        return result

    def load_state(self, cache=None) -> dict[str, PatchRecord]:
        """加载运行时状态数据库（支持 mtime 缓存）。

        Args:
            cache: 可选 PatchCache 实例

        Returns:
            {patch_id: PatchRecord} 字典
        """
        if not os.path.exists(self.state_file):
            return {}

        if cache is not None:
            cached = cache.get_state(self.state_file)
            if cached is not None:
                _, data = cached
                if isinstance(data, dict):
                    return {
                        pid: PatchRecord.from_dict(rec)
                        for pid, rec in data.items()
                    }

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = {
                pid: PatchRecord.from_dict(rec)
                for pid, rec in data.items()
            }
            if cache is not None:
                cache.put_state(self.state_file, data)
            return result
        except (json.JSONDecodeError, TypeError):
            return {}

    def save_state(self, state: dict[str, PatchRecord]):
        """保存运行时状态数据库。"""
        # 确保原子写入
        tmp = self.state_file + ".tmp"
        data = {pid: rec.to_dict() for pid, rec in state.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_file)

    def upload_patch(self, source_path: str, patch_id: str) -> str:
        dest_path = os.path.join(self.patch_dir, f"{patch_id}.py")
        shutil.copy2(source_path, dest_path)
        return dest_path

    def archive_patch(self, patch_id: str):
        src = os.path.join(self.patch_dir, f"{patch_id}.py")
        if not os.path.exists(src):
            return
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        dst = os.path.join(self.archive_dir, f"{patch_id}_{ts}.py")
        shutil.move(src, dst)

        meta_src = os.path.join(self.patch_dir, f"{patch_id}.meta.json")
        if os.path.exists(meta_src):
            meta_dst = os.path.join(self.archive_dir, f"{patch_id}_{ts}.meta.json")
            shutil.move(meta_src, meta_dst)

    # --- 回滚快照 ---

    def save_rollback_point(self, rp: RollbackPoint):
        """保存回滚快照。"""
        rp_path = os.path.join(self.rollback_dir, f"{rp.point_id}.json")
        with open(rp_path, "w", encoding="utf-8") as f:
            json.dump(rp.to_dict(), f, indent=2, ensure_ascii=False)

    def load_rollback_point(self, point_id: str) -> RollbackPoint | None:
        """加载回滚快照。"""
        rp_path = os.path.join(self.rollback_dir, f"{point_id}.json")
        if not os.path.exists(rp_path):
            return None
        try:
            with open(rp_path, "r", encoding="utf-8") as f:
                return RollbackPoint.from_dict(json.load(f))
        except (json.JSONDecodeError, TypeError):
            return None

    def list_rollback_points(self) -> list[str]:
        """列出所有回滚点 ID。"""
        result = []
        if not os.path.isdir(self.rollback_dir):
            return result
        for fname in sorted(os.listdir(self.rollback_dir), reverse=True):
            if fname.endswith(".json"):
                result.append(fname[:-5])
        return result

    def delete_rollback_point(self, point_id: str):
        """删除回滚快照。"""
        rp_path = os.path.join(self.rollback_dir, f"{point_id}.json")
        if os.path.exists(rp_path):
            os.remove(rp_path)

    def cleanup_rollbacks(self, keep_count: int = 10):
        """清理旧回滚点，仅保留最近的 N 个。"""
        points = self.list_rollback_points()
        for pid in points[keep_count:]:
            self.delete_rollback_point(pid)