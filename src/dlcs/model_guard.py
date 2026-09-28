# -*- coding: utf-8 -*-
"""VULN-006 修复: 本地模型目录来源校验 + 权重清单哈希校验。

防御可写配置（data/config.json 的 model_path 等）被指向攻击者目录后，
transformers/torch 反序列化恶意 pickle 执行任意代码（红队链C原语已实证：
torch.load 在 weights_only=True 下仍可能执行 reduce 载荷）。

策略（fail-closed）:
1. 来源校验: resolved 路径必须位于允许根（项目 models/、HF 缓存、
   MCA_ALLOWED_MODEL_ROOTS 显式白名单）之下；
2. 目录含 torch 可反序列化权重（.bin/.pt/.pth）时，必须提供
   model_manifest.json 且逐文件 sha256 匹配，否则拒绝；
3. safetensors 目录直接放行（格式本身不可执行 pickle）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

_MANIFEST_NAME = "model_manifest.json"
_RISKY_WEIGHT_EXTS = (".bin", ".pt", ".pth")


def _project_root() -> str:
    # src/dlcs/model_guard.py → 项目根为上溯两级
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _allowed_roots() -> list[str]:
    roots = [
        os.path.realpath(os.path.join(_project_root(), "models")),
        os.path.realpath(os.environ.get("HF_HOME")
                         or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")),
    ]
    extra = os.environ.get("MCA_ALLOWED_MODEL_ROOTS", "")
    roots += [os.path.realpath(r) for r in extra.split(os.pathsep) if r.strip()]
    return roots


def validate_model_dir(path: str) -> tuple[bool, str]:
    """校验本地模型目录是否可安全加载。返回 (ok, 说明)。"""
    if not path or not os.path.isdir(path):
        return False, "模型目录不存在"

    real = os.path.realpath(path)
    if not any(real == r or real.startswith(r + os.sep) for r in _allowed_roots()):
        return False, f"模型路径不在允许的来源内: {real}"

    try:
        names = os.listdir(real)
    except OSError as e:
        return False, f"模型目录不可读: {e}"

    has_safetensors = any(n.endswith(".safetensors") for n in names)
    risky = sorted(n for n in names if n.endswith(_RISKY_WEIGHT_EXTS))

    if risky:
        manifest_path = os.path.join(real, _MANIFEST_NAME)
        if not os.path.exists(manifest_path):
            return False, (
                "目录含 torch 反序列化权重(.bin/.pt/.pth)但缺少 "
                f"{_MANIFEST_NAME}，拒绝加载（pickle 反序列化风险）"
            )
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return False, f"模型清单不可读: {e}"
        hashes = manifest.get("files", manifest)
        for name in risky:
            want = hashes.get(name)
            if not want or _sha256(os.path.join(real, name)) != want:
                return False, f"权重文件哈希校验失败: {name}"
        return True, "manifest-verified"

    if has_safetensors:
        return True, "safetensors"

    return True, "no-weight-files"
