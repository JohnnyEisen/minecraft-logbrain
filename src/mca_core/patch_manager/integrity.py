# -*- coding: utf-8 -*-
"""补丁管理系统 — 完整性校验

功能：
- 文件哈希计算 (SHA-256)
- 补丁文件完整性校验
- 元数据一致性验证
- 快照校验和
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Optional


def compute_file_hash(filepath: str) -> str:
    """计算文件的 SHA-256 哈希值。"""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def compute_content_hash(content: bytes) -> str:
    """计算内容的 SHA-256 哈希。

    WARNING: 仅用于文件完整性校验，不适用于密码哈希。
    密码场景请使用 bcrypt / argon2。
    """
    return hashlib.sha256(content).hexdigest()


def compute_hmac_signature(filepath: str, key: bytes) -> str:
    """计算文件的 HMAC-SHA256 签名。"""
    with open(filepath, "rb") as f:
        content = f.read()
    return hmac.new(key, content, hashlib.sha256).hexdigest()


def verify_file_integrity(filepath: str, expected_hash: str) -> bool:
    """验证文件完整性 (SHA-256 比对)。"""
    if not os.path.exists(filepath):
        return False
    actual = compute_file_hash(filepath)
    return actual == expected_hash


def verify_signature(filepath: str, key: bytes, expected_signature: str) -> bool:
    """验证 HMAC-SHA256 签名。"""
    if not os.path.exists(filepath):
        return False
    actual = compute_hmac_signature(filepath, key)
    return actual == expected_signature


def verify_meta_consistency(patch_file: str, meta_file: str) -> tuple[bool, str]:
    """验证补丁文件与元数据文件的一致性。

    检查：
    1. 元数据中 file_hash 与补丁文件实际哈希一致
    2. 元数据 JSON 格式有效
    3. 元数据包含必需字段

    Returns:
        (is_valid, error_message)
    """
    if not os.path.exists(patch_file):
        return False, f"补丁文件不存在: {patch_file}"

    if not os.path.exists(meta_file):
        return False, f"元数据文件不存在: {meta_file}"

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"元数据 JSON 格式错误: {e}"

    # 必需字段检查
    required = ["patch_id", "name", "version", "description"]
    missing = [k for k in required if k not in meta]
    if missing:
        return False, f"元数据缺少必需字段: {missing}"

    # 文件哈希一致性
    expected_hash = meta.get("file_hash", "")
    if not expected_hash:
        return False, "元数据中未包含 file_hash"

    actual_hash = compute_file_hash(patch_file)
    if actual_hash != expected_hash:
        return False, (
            f"文件哈希不匹配: 期望={expected_hash[:16]}..., "
            f"实际={actual_hash[:16]}..."
        )

    return True, ""


def compute_snapshot_checksum(state: dict) -> str:
    """计算状态快照的校验和。"""
    canonical = json.dumps(state, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_project_root() -> str:
    """从当前模块向上查找项目根目录（包含 .patch_key 或 main.py）。"""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.exists(os.path.join(current, "main.py")) or \
           os.path.exists(os.path.join(current, ".patch_key")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.getcwd()


def get_patch_key() -> Optional[bytes]:
    """加载补丁签名密钥（三级优先级）。"""
    # 环境变量
    env_key = os.environ.get("MCA_PATCH_SECRET")
    if env_key:
        return env_key.encode("utf-8")

    # .patch_key 文件
    root = _find_project_root()
    key_file = os.path.join(root, ".patch_key")
    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            key = f.read().strip()
            if key:
                return key.encode("utf-8")

    return None