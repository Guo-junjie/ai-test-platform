"""
代码覆盖率 API（能力11：行/分支覆盖率采集与展示）

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/coverage" 注册。

提供：
- POST /upload   上传覆盖率报告 XML（coverage.py / jacoco / istanbul / cobertura），解析并入库
- GET  /         按项目 / 测试任务列出覆盖率报告
- GET  /{id}     报告详情（含文件级明细）
- DELETE /{id}   删除报告

⚠ 历史 Bug：4 个端点原本误用 ``async with get_db_session() as db:``，
``get_db_session`` 是 FastAPI Depends 注入函数（AsyncGenerator）不是
async-context-manager，会抛 ``TypeError: 'async_generator' object does
not support the asynchronous context manager protocol``。全部改为：
``db: AsyncSession = Depends(get_db_session)``。
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AuditLog,
    CoverageReport,
    CoverageSource,
    CoverageTool,
    Project,
    User,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.coverage.parser import parse_coverage_report
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

COV_DIR = os.path.join("/app", "data", "uploads", "coverage")
os.makedirs(COV_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_EXT = {".xml"}


class DeleteResponse(BaseModel):
    pass


# ==================== 接口 ====================


@router.post("")
async def upload_coverage(
    project_id: str = Form(...),
    tool: str = Form(...),  # coverage.py / jacoco / istanbul / cobertura
    language: str = Form(None),  # python / java / javascript ...
    test_run_id: str = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """上传覆盖率报告 XML 并解析入库。"""
    proj = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "项目不存在")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "仅支持 .xml 覆盖率报告")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "文件超过 20MB 限制")
    raw_xml = content.decode("utf-8", errors="ignore")

    # 解析
    try:
        result = parse_coverage_report(tool, raw_xml)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 落盘原始报告
    stored_name = f"{uuid.uuid4()}.xml"
    storage_path = os.path.join(COV_DIR, stored_name)
    with open(storage_path, "wb") as f:
        f.write(content)

    # 工具枚举
    try:
        tool_enum = CoverageTool(tool)
    except ValueError:
        tool_enum = CoverageTool.COBERTURA

    run_uuid = None
    if test_run_id:
        try:
            run_uuid = uuid.UUID(test_run_id)
        except ValueError:
            raise HTTPException(400, "test_run_id 格式错误")

    report = CoverageReport(
        project_id=uuid.UUID(project_id),
        test_run_id=run_uuid,
        uploader_id=current_user.id,
        tool=tool_enum,
        language=language,
        source=CoverageSource.UPLOAD,
        line_rate=result["line_rate"],
        branch_rate=result["branch_rate"],
        total_lines=result["total_lines"],
        covered_lines=result["covered_lines"],
        total_branches=result["total_branches"],
        covered_branches=result["covered_branches"],
        # P1：files_json 只存文件级汇总（去掉 lines 字段，减小体积）；行级明细放 line_json
        files_json=[
            {k: v for k, v in f.items() if k != "lines"}
            for f in result["files"][:2000]
        ],
        # P1：line_json = {path: {lines: [...]}}，供前端源码高亮按需加载
        line_json={
            f["path"]: {"lines": f.get("lines", [])}
            for f in result["files"][:2000]
        },
        storage_key=storage_path,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {
        "code": 0,
        "data": {
            "id": str(report.id),
            "tool": report.tool.value,
            "line_rate": report.line_rate,
            "branch_rate": report.branch_rate,
            "total_lines": report.total_lines,
            "covered_lines": report.covered_lines,
            "total_branches": report.total_branches,
            "covered_branches": report.covered_branches,
            "file_count": len(result["files"]),
        },
        "message": "覆盖率报告已解析入库",
    }


@router.get("")
async def list_coverage(
    project_id: str,
    test_run_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """按项目 / 测试任务列出覆盖率报告。"""
    stmt = select(CoverageReport).where(CoverageReport.project_id == project_id)
    if test_run_id:
        stmt = stmt.where(CoverageReport.test_run_id == uuid.UUID(test_run_id))
    stmt = stmt.order_by(CoverageReport.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "code": 0,
        "data": [
            {
                "id": str(r.id),
                "tool": r.tool.value,
                "language": r.language,
                "source": r.source.value,
                "line_rate": r.line_rate,
                "branch_rate": r.branch_rate,
                "total_lines": r.total_lines,
                "covered_lines": r.covered_lines,
                "total_branches": r.total_branches,
                "covered_branches": r.covered_branches,
                "test_run_id": str(r.test_run_id) if r.test_run_id else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "message": "success",
    }


@router.get("/{report_id}")
async def get_coverage(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """覆盖率报告详情（含文件级明细）。"""
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")
    return {
        "code": 0,
        "data": {
            "id": str(r.id),
            "tool": r.tool.value,
            "language": r.language,
            "source": r.source.value,
            "line_rate": r.line_rate,
            "branch_rate": r.branch_rate,
            "total_lines": r.total_lines,
            "covered_lines": r.covered_lines,
            "total_branches": r.total_branches,
            "covered_branches": r.covered_branches,
            "files": r.files_json or [],
            "test_run_id": str(r.test_run_id) if r.test_run_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        },
        "message": "success",
    }


@router.delete("/{report_id}")
async def delete_coverage(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """删除覆盖率报告。"""
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")
    await db.delete(r)
    await db.commit()
    try:
        if r.storage_key and os.path.exists(r.storage_key):
            os.remove(r.storage_key)
    except Exception:  # noqa: BLE001
        pass
    return {"code": 0, "data": None, "message": "已删除"}


# ==================== P1：覆盖率看板端点 ====================


@router.get("/dashboard/{project_id}")
async def coverage_dashboard(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：项目级聚合 —— 最新报告 + 较上次差值 + 文件数 / 报告数。"""
    # 最近两份报告（最新 + 上次），用于计算「较上次差值」
    stmt = (
        select(CoverageReport)
        .where(CoverageReport.project_id == project_id)
        .order_by(CoverageReport.created_at.desc())
        .limit(2)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return {
            "code": 0,
            "data": {
                "latest": None,
                "diff_line_rate": 0.0,
                "diff_branch_rate": 0.0,
                "report_count": 0,
                "file_count": 0,
            },
            "message": "暂无覆盖率报告",
        }
    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    files = latest.files_json or []
    return {
        "code": 0,
        "data": {
            "latest": {
                "id": str(latest.id),
                "tool": latest.tool.value,
                "language": latest.language,
                "source": latest.source.value,
                "line_rate": latest.line_rate or 0.0,
                "branch_rate": latest.branch_rate or 0.0,
                "total_lines": latest.total_lines or 0,
                "covered_lines": latest.covered_lines or 0,
                "total_branches": latest.total_branches or 0,
                "covered_branches": latest.covered_branches or 0,
                "created_at": latest.created_at.isoformat() if latest.created_at else None,
            },
            "diff_line_rate": round(
                (latest.line_rate or 0.0) - (prev.line_rate or 0.0), 2
            ) if prev else 0.0,
            "diff_branch_rate": round(
                (latest.branch_rate or 0.0) - (prev.branch_rate or 0.0), 2
            ) if prev else 0.0,
            "report_count": len(rows),
            "file_count": len(files),
        },
        "message": "success",
    }


@router.get("/trend/{project_id}")
async def coverage_trend(
    project_id: str,
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：项目覆盖率趋势（最近 N 天，按 created_at 升序）。"""
    days = max(1, min(int(days), 365))
    cutoff = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(CoverageReport)
        .where(
            CoverageReport.project_id == project_id,
            CoverageReport.created_at >= cutoff,
        )
        .order_by(CoverageReport.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "code": 0,
        "data": {
            "labels": [
                r.created_at.strftime("%m-%d %H:%M") if r.created_at else ""
                for r in rows
            ],
            "line_rate": [float(r.line_rate or 0.0) for r in rows],
            "branch_rate": [float(r.branch_rate or 0.0) for r in rows],
        },
        "message": "success",
    }


@router.get("/files/{report_id}")
async def coverage_files(
    report_id: str,
    sort: str = "rate",  # rate | path | total_lines
    order: str = "asc",  # asc | desc
    page: int = 1,
    page_size: int = 50,
    q: str | None = None,  # 文件名模糊搜索
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：报告的文件清单（支持搜索 / 排序 / 分页）。"""
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")

    files = list(r.files_json or [])
    # 模糊搜索
    if q:
        ql = q.lower()
        files = [f for f in files if ql in (f.get("path") or "").lower()]
    # 排序
    key_map = {
        "rate": lambda f: float(f.get("line_rate") or 0.0),
        "path": lambda f: f.get("path") or "",
        "total_lines": lambda f: int(f.get("total_lines") or 0),
    }
    key_fn = key_map.get(sort, key_map["rate"])
    files.sort(key=key_fn, reverse=(order == "desc"))

    # 分页
    total = len(files)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))
    start = (page - 1) * page_size
    page_files = files[start : start + page_size]
    return {
        "code": 0,
        "data": {
            "files": page_files,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.get("/source/{report_id}")
async def coverage_source(
    report_id: str,
    file: str,  # 文件路径
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：单文件的行级覆盖率明细（供源码高亮用）。

    Args:
        file: 文件路径（URL ?file=xxx 传入，路径含 / 需前端 encodeURIComponent）
    """
    from urllib.parse import unquote
    file_path = unquote(file)
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")

    line_data = (r.line_json or {}).get(file_path) or {}
    files_list = r.files_json or []
    file_summary = next(
        (f for f in files_list if f.get("path") == file_path), None
    )
    if not file_summary:
        raise HTTPException(404, f"该报告不含此文件: {file_path}")
    return {
        "code": 0,
        "data": {
            "path": file_path,
            "line_rate": file_summary.get("line_rate"),
            "branch_rate": file_summary.get("branch_rate"),
            "total_lines": file_summary.get("total_lines"),
            "covered_lines": file_summary.get("covered_lines"),
            "lines": line_data.get("lines", []),
        },
        "message": "success",
    }
