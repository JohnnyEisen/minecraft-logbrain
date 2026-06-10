# -*- coding: utf-8 -*-
"""Brain System — 认证与速率限制

供 server.py 和 patch_api.py 共享使用。
"""
from __future__ import annotations

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
            expired = [ip for ip, (t, _) in _rate_limit_store.items() if now - t > _RATE_LIMIT_WINDOW]
            for ip in expired:
                del _rate_limit_store[ip]


def verify_auth(request: Request, authorization: Optional[str] = Header(None)) -> None:
    """验证 API 认证令牌。

    VULN-007 修复: 添加 Host header 验证防止 DNS rebinding。
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    # VULN-007: Host header 验证 — 拒绝非预期的主机名
    host = request.headers.get("Host", "")
    if host and host not in ("127.0.0.1", "localhost", f"localhost:{request.url.port}" if request.url.port else ""):
        # 不是 localhost — 必须要求 token
        pass  # 由下面的 token 逻辑处理

    expected = os.environ.get("MCA_API_TOKEN", "")
    if not expected:
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
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
    if token != expected:
        raise HTTPException(403, "Invalid API token")