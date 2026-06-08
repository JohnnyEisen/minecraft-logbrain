"""Brain System Server — FastAPI HTTP endpoints with security hardening.

VULN-006 修复: 添加 Bearer Token 认证 + 速率限制 + 安全头。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .auth import verify_auth


def create_app(brain: Any):
    """创建 HTTP 服务：health/ready/metrics。

    依赖：FastAPI + (可选) prometheus_client。
    """

    app = FastAPI(title="brain-system", docs_url=None, redoc_url=None)

    # 补丁管理 Web 控制台: 静态文件
    _static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(_static_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/patches/static", StaticFiles(directory=_static_dir), name="patch_static")

    # 补丁管理 Web 控制台: HTML 入口
    @app.get("/patches")
    @app.get("/patches/")
    def patch_console(request: Request):
        html_path = os.path.join(_static_dir, "index.html")
        if os.path.exists(html_path):
            from fastapi.responses import FileResponse
            return FileResponse(html_path, media_type="text/html")
        return {"error": "Patch console not found"}, 404

    # 补丁管理 REST API
    try:
        from .patch_api import router as patch_router
        app.include_router(patch_router)
    except Exception:
        pass  # 补丁 API 可选

    # 安全头中间件 (VULN-006)
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Server"] = ""
        return response

    @app.get("/health")
    def health(_=Depends(verify_auth)):
        return {"status": "ok"}

    @app.get("/ready")
    def ready(_=Depends(verify_auth)):
        return {"ready": True}

    @app.get("/metrics")
    def metrics(request: Request, _=Depends(verify_auth)):
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            client_host = request.client.host if request.client else "unknown"
            if client_host != "127.0.0.1":
                return JSONResponse(
                    status_code=403,
                    content={"error": "metrics endpoint 仅供本地访问"},
                )

            data = generate_latest()
            return PlainTextResponse(content=data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
        except Exception:
            return PlainTextResponse(content="# metrics disabled\n", media_type="text/plain")

    return app
