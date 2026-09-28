# -*- coding: utf-8 -*-
"""Brain System — 认证与速率限制

供 server.py 和 patch_api.py 共享使用。
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Optional

from fastapi import Header, HTTPException, Request


# 速率限制器 — M-001 修复: 添加锁保护并发访问
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_rate_limit_store: dict[str, tuple[float, int]] = {}
_rate_lock = threading.Lock()


def _check_rate_limit(client_ip: str) -> None:
    """M-001 修复: 所有对 _rate_limit_store 的访问都在锁保护下进行。"""
    now = time.time()
    with _rate_lock:
        if client_ip in _rate_limit_store:
            start_time, count = _rate_limit_store[client_ip]
            if now - start_time > _RATE_LIMIT_WINDOW:
                _rate_limit_store[client_ip] = (now, 1)
            elif count >= _RATE_LIMIT_MAX:
                raise HTTPException(429, "Too Many Requests")
            else:
                _rate_limit_store[client_ip] = (start_time, count + 1)
        else:
            _rate_limit_store[client_ip] = (now, 1)
            # Periodic cleanup: every 100th new IP entry
            if len(_rate_limit_store) % 100 == 0:
                expired = [ip for ip, (t, _) in _rate_limit_store.items() if now - t > _RATE_LIMIT_WINDOW]
                for ip in expired:
                    del _rate_limit_store[ip]


def _get_trusted_proxies() -> set[str]:
    """V-005 修复: 反向代理白名单来自环境变量，默认为空（不信任任何 XFF）。"""
    raw = os.environ.get("MCA_TRUSTED_PROXIES", "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def _resolve_client_ip(request: Request) -> str:
    """解析真实客户端 IP。

    V-005 修复: 仅当直连对端（request.client.host）位于 MCA_TRUSTED_PROXIES
    白名单时才采信 X-Forwarded-For；默认不信任任何 XFF——攻击者伪造
    ``X-Forwarded-For: 127.0.0.1`` 无法再冒充本机。
    """
    client_ip = request.client.host if request.client else "unknown"
    trusted = _get_trusted_proxies()
    if trusted and client_ip in trusted:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
    return client_ip


def verify_auth(request: Request, authorization: Optional[str] = Header(None)) -> None:
    """验证 API 认证令牌。

    VULN-004 修复: expected 在使用前赋值（原实现 UnboundLocalError 导致全部
    API 500）；认证层内部异常兜底返回 401 而非 500。
    VULN-005 修复: XFF 仅信任 MCA_TRUSTED_PROXIES 白名单中的直连代理。
    VULN-007 修复: 未配置 token 时校验 Host 头防 DNS rebinding。
    """
    try:
        _verify_auth_impl(request, authorization)
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger("brain_system.auth").exception("认证层内部异常")
        raise HTTPException(401, "Authentication failed")


def _verify_auth_impl(request: Request, authorization: Optional[str]) -> None:
    # 直调/DI 边界: FastAPI 的 Header(None) 标记对象在未注入时可能原样传入，
    # 统一归一化为 None（视为未提供凭据）。
    if not isinstance(authorization, str):
        authorization = None

    client_ip = _resolve_client_ip(request)
    _check_rate_limit(client_ip)

    # VULN-004 修复: expected 必须先赋值再使用（原实现在赋值前引用 → 必崩）
    expected = os.environ.get("MCA_API_TOKEN", "")

    # Host header 验证（VULN-007）——仅用于"未配置 token"的本机限流模式
    host = request.headers.get("Host", "")
    expected_hosts = {"127.0.0.1", "localhost", "::1"}
    if host and ":" in host:
        expected_hosts.add(f"localhost:{host.split(':')[1]}")

    if not expected:
        # 未配置 token: 仅接受本机请求（按真实客户端 IP 判定，不信任伪造 XFF）
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(403, "API authentication not configured; localhost only")
        if host and host.split(":")[0] not in expected_hosts:
            raise HTTPException(403, "API authentication not configured; localhost only")
        # VULN-007: 打印警告说明 token 未配置
        import logging
        logging.getLogger("brain_system.auth").warning(
            "MCA_API_TOKEN 未配置。API 仅接受 localhost 请求。"
            "生产环境请设置 MCA_API_TOKEN 环境变量。"
        )
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = authorization[len("Bearer "):]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(403, "Invalid API token")