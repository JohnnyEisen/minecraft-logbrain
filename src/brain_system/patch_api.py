# -*- coding: utf-8 -*-
"""补丁管理 REST API — 为 Web 控制台提供数据接口。

所有端点返回 JSON，经过 Bearer Token 认证。
整合 PatchManager 的全部功能。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

# 确保项目路径正确
# VULN-011 修复: 使用 append 而非 insert(0) 降低模块劫持风险
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.append(_project_root)
_src_path = os.path.join(_project_root, "src")
if _src_path not in sys.path:
    sys.path.append(_src_path)

from .auth import verify_auth
from mca_core.patch_manager import PatchManager

router = APIRouter(
    prefix="/api/patches",
    tags=["patches"],
    dependencies=[Depends(verify_auth)],
)
"""补丁管理 REST API。

所有端点需 Bearer Token 认证，返回 JSON 格式 ``{"ok": bool, ...}``。

**端点一览**:

- ``GET /api/patches/list`` — 补丁列表（支持 state/sort/search 筛选）
- ``POST /api/patches/scan`` — 扫描补丁目录
- ``POST /api/patches/install/{id}`` — 安装补丁
- ``POST /api/patches/rollback/{id}`` — 回滚补丁
- ``POST /api/patches/upload`` — 上传新补丁（AST 验证 + 沙箱级别检查）
- ``GET /api/patches/report/full`` — 完整管理报告
"""

# PatchManager 单例
_patch_manager: Optional[PatchManager] = None
_patch_dir: str = os.path.join(_project_root, "patches")


def get_pm() -> PatchManager:
    """获取 PatchManager 实例（懒加载单例）。"""
    global _patch_manager
    if _patch_manager is None:
        _patch_manager = PatchManager(_patch_dir)
        _patch_manager.scan()
    return _patch_manager


def _ok(data=None, **extra):
    """构造成功响应。"""
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return JSONResponse(body)


def _safe_error_message(message: str) -> str:
    """VULN-012 修复: 脱敏错误消息中的内部路径。"""
    import re
    msg = str(message)
    # 移除项目绝对路径
    msg = re.sub(r'[A-Za-z]:\\(?:Users\\[^\\]+\\[^\\]+\\|)[^\\\s]*?minecraft-logbrain[^\s,;:]*', '[project_path]', msg)
    msg = re.sub(r'/(?:home/[^/]+/|)[^\s]*?minecraft-logbrain[^\s,;:]*', '[project_path]', msg)
    # 移除 Windows 用户路径
    msg = re.sub(r'[A-Za-z]:\\Users\\[^\\\s]+', '[user_path]', msg)
    return msg


def _error(message: str, status: int = 400):
    """构造错误响应。"""
    safe_msg = _safe_error_message(message)
    return JSONResponse({"ok": False, "message": safe_msg}, status_code=status)


# ═══════════════════════════════════════════════
# 查询端点
# ═══════════════════════════════════════════════

@router.get("/list")
def list_patches(
    state: str = "",
    sort: str = "",
    order: str = "asc",
    search: str = "",
):
    """获取补丁列表，支持筛选、排序、搜索。"""
    pm = get_pm()
    report = pm.generate_report()

    patches = []
    for p in report.patches:
        # 状态筛选
        if state and p["state"] != state:
            continue
        # 搜索筛选（名称/ID/描述/标签）
        if search:
            q = search.lower()
            text = (p.get("patch_id", "") + p.get("description", "") +
                    p.get("severity", "") + p.get("version", ""))
            if q not in text.lower():
                continue
        patches.append(p)

    # 排序
    sort_map = {
        "severity": lambda x: {
            "critical": 5, "high": 4, "medium": 3, "low": 2, "optional": 1
        }.get(x.get("severity", ""), 0),
        "version": lambda x: x.get("version", ""),
        "date": lambda x: x.get("installed_at", "") or x.get("created_date", ""),
        "name": lambda x: x.get("patch_id", ""),
        "state": lambda x: x.get("state", ""),
    }
    if sort in sort_map:
        reverse = order == "desc"
        patches.sort(key=sort_map[sort], reverse=reverse)

    return _ok(data=patches, total=len(patches), summary=pm.get_state_summary())


@router.get("/{patch_id}")
def get_patch(patch_id: str):
    """获取单个补丁详情。"""
    pm = get_pm()
    meta = pm.get_meta(patch_id)
    rec = pm.get_state(patch_id)

    if meta is None:
        return _error(f"补丁不存在: {patch_id}", 404)

    result = meta.to_dict()
    if rec:
        result["state"] = rec.state
        result["installed_version"] = rec.installed_version
        result["installed_at"] = rec.installed_at
        result["install_order"] = rec.install_order
        result["error_message"] = rec.error_message
        result["rollback_point_id"] = rec.rollback_point_id

    return _ok(data=result)


@router.get("/deps/graph")
def get_deps_graph():
    """获取依赖关系图数据。"""
    pm = get_pm()
    dg = pm.build_dependency_graph()
    return _ok(data={
        "nodes": sorted(dg.nodes),
        "edges": list(dg.edges),
    })


@router.get("/conflicts/list")
def get_conflicts():
    """冲突检测。"""
    pm = get_pm()
    report = pm.detect_conflicts()
    return _ok(data=report.to_dict())


@router.get("/plan/preview")
def get_install_plan():
    """安装计划预览。"""
    pm = get_pm()
    plan = pm.plan_install()
    return _ok(data=plan.to_dict())


@router.get("/report/full")
def get_report():
    """完整管理报告。"""
    pm = get_pm()
    report = pm.generate_report()
    return _ok(data=report.to_dict())


@router.get("/snapshots/list")
def get_snapshots():
    """回滚快照列表。"""
    pm = get_pm()
    return _ok(data=pm.list_snapshots())


# ═══════════════════════════════════════════════
# 操作端点
# ═══════════════════════════════════════════════

@router.post("/scan")
def scan_patches():
    """扫描并刷新补丁。"""
    pm = get_pm()
    count = pm.scan()
    summary = pm.get_state_summary()
    return _ok(message=f"扫描完成: {count} 个补丁", data={"count": count, "summary": summary})


@router.post("/install/{patch_id}")
def install_patch(patch_id: str, force: bool = False, with_deps: bool = False):
    """安装指定补丁。"""
    pm = get_pm()

    if with_deps:
        chain = pm.get_install_chain(patch_id)
        plan = pm.plan_install(chain)
        results = pm.apply_plan(plan)
        statuses = {pid: ok for pid, (ok, _) in results.items()}
        msgs = [msg for _, msg in results.values()]
        all_ok = all(statuses.values())
        return _ok(
            data={"results": statuses, "chain": chain},
            message="; ".join(msgs),
        ) if all_ok else _error("; ".join(msgs), 500)

    if not force:
        ok, missing = pm.check_dependencies(patch_id)
        if not ok:
            return _error(f"依赖不满足: {missing}", 409)

    ok, msg = pm.apply_patch(patch_id)
    if ok:
        return _ok(message=msg)
    return _error(msg, 500)


@router.post("/install-all")
def install_all():
    """安装所有可用补丁。"""
    pm = get_pm()
    results = pm.apply_all()
    statuses = {pid: ok for pid, (ok, _) in results.items()}
    msgs = [msg for _, msg in results.values()]
    return _ok(data={"results": statuses}, message="; ".join(msgs))


@router.post("/rollback/{patch_id}")
def rollback_patch(patch_id: str, cascade: bool = False):
    """回滚补丁。"""
    pm = get_pm()

    if cascade:
        ok, msg, count = pm.cascade_rollback(patch_id)
        if ok:
            return _ok(message=msg, data={"rolled_back": count})
        return _error(msg, 500)

    ok, msg = pm.rollback_patch(patch_id)
    if ok:
        return _ok(message=msg)
    return _error(msg, 500)


@router.post("/disable/{patch_id}")
def disable_patch(patch_id: str):
    """禁用补丁。"""
    pm = get_pm()
    ok, msg = pm.disable_patch(patch_id)
    if ok:
        return _ok(message=msg)
    return _error(msg)


@router.post("/enable/{patch_id}")
def enable_patch(patch_id: str):
    """启用补丁。"""
    pm = get_pm()
    ok, msg = pm.enable_patch(patch_id)
    if ok:
        return _ok(message=msg)
    return _error(msg)


@router.post("/verify/{patch_id}")
def verify_patch(patch_id: str):
    """校验补丁完整性。"""
    pm = get_pm()
    ok, msg = pm.verify_integrity(patch_id)
    return _ok(data={"passed": ok}, message=msg)


@router.post("/verify-all")
def verify_all_patches():
    """批量校验。"""
    pm = get_pm()
    results = pm.verify_all()
    statuses = {pid: ok for pid, (ok, _) in results.items()}
    msgs = {pid: msg for pid, (_, msg) in results.items()}
    return _ok(data={"results": statuses, "details": msgs})


@router.post("/upload")
async def upload_patch(
    file: UploadFile = File(...),
    meta_json: str = Form(""),
):
    """上传新补丁文件。"""
    allowed_ext = ".py"
    if not file.filename or not file.filename.lower().endswith(allowed_ext):
        return _error(f"仅支持 {allowed_ext} 文件", 400)
    # 防路径遍历: 从文件名中剥离目录路径，仅保留 basename
    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or ".." in file.filename or "/" in file.filename or "\\" in file.filename:
        return _error("文件名包含非法字符", 400)

    content = await file.read()
    if len(content) > 500_000:
        return _error("文件过大 (最大 500KB)", 400)

    pm = get_pm()

    tmp_path = os.path.join(tempfile.gettempdir(), safe_name)
    with open(tmp_path, "wb") as f:
        f.write(content)

    try:
        # 解析元数据
        if meta_json:
            meta_dict = json.loads(meta_json)
        else:
            base = os.path.splitext(file.filename)[0]
            meta_dict = {
                "patch_id": base,
                "name": base,
                "version": "1.0.0",
                "description": "",
            }

        from mca_core.patch_manager.models import PatchMeta
        meta = PatchMeta.from_dict(meta_dict)

        ok, msg = pm.upload_patch(tmp_path, meta)
        if ok:
            return _ok(message=msg)
        return _error(msg, 500)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)