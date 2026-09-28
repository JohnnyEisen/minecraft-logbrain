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


_ERR_PREFIX = "文件哈希不匹配: 期望="

# VULN-002 修复: 全局签名强制开关，默认 True（fail-closed）。
# 仅在显式设置 MCA_PATCH_SIGNATURE_REQUIRED=0 时降级为兼容模式（仅哈希校验）。
PATCH_SIGNATURE_REQUIRED: bool = os.environ.get("MCA_PATCH_SIGNATURE_REQUIRED", "1") != "0"


def _format_err(expected: str, actual: str, label: str = "文件哈希不匹配") -> str:
    """构造不匹配错误消息。

    label 默认为文件哈希语义（verify_meta_consistency 的哈希比对路径
    自行内联同款文案）；integrity_token 校验路径必须传入专属 label，
    避免"实为 token 不匹配却报文件哈希不匹配"的误导。
    """
    return f"{label}: 期望={expected[:16]}..., 实际={actual[:16]}..."


# 构成 integrity_token 的核心元数据字段（稳定字段，不受模型升级影响）
_META_CORE_FIELDS = (
    "patch_id", "name", "version", "description", "author",
    "created_date", "severity", "target_version",
    "dependencies", "conflicts", "replaces", "affected_modules", "tags",
)


def _compute_auth_token(filepath: str, meta: dict, key: bytes) -> str:
    """计算补丁完整性认证 token。

    仅使用核心稳定字段 + 文件哈希 + 签名，
    不受 PatchMeta 新增非核心字段（如 permission_level、risk_level）的影响。
    """
    import json as _json
    file_hash = compute_file_hash(filepath)
    meta_sig = {k: meta.get(k, "") for k in _META_CORE_FIELDS}
    meta_hash = compute_content_hash(_json.dumps(meta_sig, sort_keys=True, ensure_ascii=False).encode())
    signature = meta.get("signature", "")
    patch_id = meta.get("patch_id", "")
    version = meta.get("version", "")
    msg = f"{file_hash}|{meta_hash}|{signature}|{patch_id}|{version}"
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_auth_token(filepath: str, meta: dict, key: bytes) -> tuple[bool, str]:
    expected = meta.get("integrity_token", "")
    if not expected:
        # VULN-002 修复: 缺失 integrity_token 一律拒绝（原实现返回 True → fail-open）
        return False, "元数据缺少 integrity_token，完整性校验拒绝"
    actual = _compute_auth_token(filepath, meta, key)
    if not hmac.compare_digest(actual, expected):
        return False, _format_err(expected, actual, label="integrity_token 不匹配")
    return True, ""


def compute_snapshot_checksum(state: dict) -> str:
    """计算状态快照的校验和。"""
    canonical = json.dumps(state, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_project_root() -> str:
    """返回遗留 .patch_key 的查找根。

    VULN-密钥修复: 原实现从模块位置向上扫描 6 层找 .patch_key / main.py，
    攻击者可在任一上层目录放置伪造 .patch_key 劫持签名密钥（红队三状态
    矩阵第 3 行）。现固定返回当前工作目录——遗留密钥仅在显式工作目录下
    查找，不做任何向上扫描。
    """
    return os.getcwd()


def _user_key_file() -> str:
    """用户私有密钥文件固定路径（项目目录之外）。"""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "logbrain", "patch.key")


def _load_legacy_key_file(key_file: str) -> Optional[bytes]:
    """读取遗留 .patch_key：保留兼容，但做权限检查并输出弃用告警。"""
    if not os.path.exists(key_file):
        return None
    import logging
    try:
        st = os.stat(key_file)
        if getattr(st, "st_mode", 0) & 0o077:
            logging.getLogger(__name__).warning(
                "遗留密钥文件 %s 权限过宽（group/other 可读），建议迁移至用户私有密钥目录",
                key_file,
            )
        with open(key_file, "r") as f:
            key = f.read().strip()
        if key:
            logging.getLogger(__name__).warning(
                "检测到遗留 .patch_key（%s）。项目目录明文密钥已弃用，"
                "请迁移至用户私有密钥文件: %s（MCA_PATCH_SECRET 环境变量优先）",
                key_file, _user_key_file(),
            )
            return key.encode("utf-8")
    except OSError as e:
        logging.getLogger(__name__).error("读取遗留密钥文件失败: %s (%s)", key_file, e)
    return None


def _ensure_user_key() -> Optional[bytes]:
    """首次运行生成用户私有密钥（secrets.token_bytes(32)，0o600 独占创建）。

    生成失败（不可恢复）时返回 None，调用方必须 fail-closed。
    """
    import secrets
    key_file = _user_key_file()
    import logging
    try:
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
    except OSError as e:
        logging.getLogger(__name__).error("用户密钥目录创建失败: %s (%s)", key_file, e)
        return None
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, secrets.token_bytes(32).hex().encode("ascii") + b"\n")
        finally:
            os.close(fd)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass  # Windows 上 chmod 语义受限，创建时 0o600 已尽力
    except FileExistsError:
        pass  # 已有密钥，走读取路径
    except OSError as e:
        logging.getLogger(__name__).error("用户密钥文件生成失败: %s (%s)", key_file, e)
        return None
    try:
        with open(key_file, "r") as f:
            key = f.read().strip()
        return key.encode("utf-8") if key else None
    except OSError as e:
        logging.getLogger(__name__).error("用户密钥文件读取失败: %s (%s)", key_file, e)
        return None


def get_patch_key() -> Optional[bytes]:
    """加载补丁签名密钥（VULN-密钥修复后的三级优先级）。

    1. ``MCA_PATCH_SECRET`` 环境变量（部署级注入，最高优先）
    2. 用户私有密钥文件 ``~/.config/logbrain/patch.key``
       （首次运行自动生成：``secrets.token_bytes(32)``，0o600 独占创建，
       不落项目目录）
    3. 遗留 ``.patch_key``（仅固定路径 = 当前工作目录，权限检查 + 弃用告警，
       **不做向上扫描**——上层目录劫持无效）

    返回 None 时所有调用方必须 fail-closed（拒绝签名相关操作）。
    """
    env_key = os.environ.get("MCA_PATCH_SECRET")
    if env_key:
        return env_key.encode("utf-8")

    key = _load_legacy_key_file(os.path.join(_find_project_root(), ".patch_key"))
    if key:
        return key

    return _ensure_user_key()