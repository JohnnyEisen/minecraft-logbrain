# -*- coding: utf-8 -*-
"""VULN-006 / VULN-007 回归: 模型来源校验 + schema 关闭 + 上传临时文件。"""
import hashlib
import json
import os

import pytest

from dlcs.model_guard import validate_model_dir


@pytest.fixture(autouse=True)
def _allow_tmp_roots(tmp_path, monkeypatch):
    """测试目录不在项目 models/ 下，显式加入白名单。"""
    monkeypatch.setenv("MCA_ALLOWED_MODEL_ROOTS", str(tmp_path))
    yield


def test_model_guard_accepts_safetensors_dir(tmp_path):
    d = tmp_path / "m1"
    d.mkdir()
    (d / "model.safetensors").write_bytes(b"x")
    ok, reason = validate_model_dir(str(d))
    assert ok and reason == "safetensors", reason


def test_model_guard_rejects_bin_without_manifest(tmp_path):
    d = tmp_path / "m2"
    d.mkdir()
    (d / "pytorch_model.bin").write_bytes(b"pickle-ish")
    ok, reason = validate_model_dir(str(d))
    assert not ok and "model_manifest.json" in reason, reason


def test_model_guard_accepts_bin_with_matching_manifest(tmp_path):
    d = tmp_path / "m3"
    d.mkdir()
    data = b"real weights"
    (d / "pytorch_model.bin").write_bytes(data)
    (d / "model_manifest.json").write_text(json.dumps({
        "files": {"pytorch_model.bin": hashlib.sha256(data).hexdigest()}
    }), encoding="utf-8")
    ok, reason = validate_model_dir(str(d))
    assert ok and reason == "manifest-verified", reason


def test_model_guard_rejects_bin_with_tampered_manifest(tmp_path):
    d = tmp_path / "m4"
    d.mkdir()
    (d / "pytorch_model.bin").write_bytes(b"tampered")
    (d / "model_manifest.json").write_text(json.dumps({
        "files": {"pytorch_model.bin": "0" * 64}
    }), encoding="utf-8")
    ok, reason = validate_model_dir(str(d))
    assert not ok and "哈希校验失败" in reason, reason


def test_model_guard_rejects_path_outside_allowed_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("MCA_ALLOWED_MODEL_ROOTS", str(tmp_path / "nowhere"))
    d = tmp_path / "m5"
    d.mkdir()
    (d / "model.safetensors").write_bytes(b"x")
    ok, reason = validate_model_dir(str(d))
    assert not ok and "来源" in reason, reason


def test_openapi_disabled_by_default(monkeypatch):
    """VULN-007: 生产模式（默认）必须关闭 /openapi.json 与 /docs。

    直接断言应用配置契约（httpx 0.28 与旧 starlette TestClient 不兼容，
    无法走 HTTP 客户端；openapi_url=None 时 FastAPI 不注册 schema 路由，
    断言等价于 404）。
    """
    monkeypatch.delenv("MCA_ENV", raising=False)
    from brain_system.server import create_app
    app = create_app(None)
    assert app.openapi_url is None
    assert app.docs_url is None


def test_openapi_enabled_in_dev(monkeypatch):
    """MCA_ENV=dev 显式开启 schema。"""
    monkeypatch.setenv("MCA_ENV", "dev")
    from brain_system.server import create_app
    app = create_app(None)
    assert app.openapi_url == "/openapi.json"
    assert app.docs_url == "/docs"
