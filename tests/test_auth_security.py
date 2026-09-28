# -*- coding: utf-8 -*-
"""VULN-004 / VULN-005 回归: 认证层行为契约。"""
import pytest
from fastapi import HTTPException
from fastapi import Request

from brain_system.auth import verify_auth


def _make_request(client_host="127.0.0.1", headers=None):
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http", "method": "GET", "path": "/", "client": (client_host, 54321),
        "headers": hdrs, "query_string": b"",
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """限流表是模块级状态，跨用例累积会触发 429 干扰断言。"""
    import brain_system.auth as auth_mod
    auth_mod._rate_limit_store.clear()
    yield
    auth_mod._rate_limit_store.clear()


def test_verify_auth_does_not_crash_without_token(monkeypatch):
    """VULN-004: 原实现 expected 先用后赋值 → 全部请求 500。"""
    monkeypatch.delenv("MCA_API_TOKEN", raising=False)
    monkeypatch.delenv("MCA_TRUSTED_PROXIES", raising=False)
    verify_auth(_make_request())  # 不应抛 UnboundLocalError


def test_verify_auth_rejects_spoofed_xff_from_remote(monkeypatch):
    """VULN-005: 远端主机伪造 X-Forwarded-For: 127.0.0.1 必须被 403。"""
    monkeypatch.delenv("MCA_API_TOKEN", raising=False)
    monkeypatch.delenv("MCA_TRUSTED_PROXIES", raising=False)
    with pytest.raises(HTTPException) as ei:
        verify_auth(_make_request(
            client_host="203.0.113.5",
            headers={"X-Forwarded-For": "127.0.0.1"},
        ))
    assert ei.value.status_code == 403


def test_verify_auth_trusts_xff_only_from_trusted_proxy(monkeypatch):
    """VULN-005: 仅 MCA_TRUSTED_PROXIES 白名单中的直连代理可携带 XFF。"""
    monkeypatch.delenv("MCA_API_TOKEN", raising=False)
    monkeypatch.setenv("MCA_TRUSTED_PROXIES", "10.0.0.9, 10.0.0.10")
    # 可信代理 + XFF 指向本机 → 放行
    verify_auth(_make_request(
        client_host="10.0.0.9",
        headers={"X-Forwarded-For": "127.0.0.1"},
    ))
    # 白名单清空后，同一请求（XFF 伪造本机）→ 403
    monkeypatch.setenv("MCA_TRUSTED_PROXIES", "")
    with pytest.raises(HTTPException):
        verify_auth(_make_request(
            client_host="10.0.0.9",
            headers={"X-Forwarded-For": "127.0.0.1"},
        ))


def test_verify_auth_token_paths(monkeypatch):
    monkeypatch.setenv("MCA_API_TOKEN", "s3cret")
    # 直调时 FastAPI DI 不注入 Header 参数，需显式传第二参
    with pytest.raises(HTTPException) as ei:
        verify_auth(_make_request())
    assert ei.value.status_code == 401  # 缺少 Authorization
    with pytest.raises(HTTPException) as ei:
        verify_auth(_make_request(), authorization="Bearer wrong")
    assert ei.value.status_code == 403  # 令牌错误
    verify_auth(_make_request(), authorization="Bearer s3cret")  # 通过


def test_verify_auth_internal_error_returns_401(monkeypatch):
    """VULN-004 兜底: 认证层内部异常必须 401，不得 500。"""
    import brain_system.auth as auth_mod
    monkeypatch.delenv("MCA_API_TOKEN", raising=False)
    monkeypatch.setattr(auth_mod, "_check_rate_limit", lambda ip: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(HTTPException) as ei:
        verify_auth(_make_request())
    assert ei.value.status_code == 401
