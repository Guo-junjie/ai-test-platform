"""
代码覆盖率 API（能力11：行/分支覆盖率采集与展示）

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/coverage" 注册。

提供：
- POST /upload   上传覆盖率报告 XML（coverage.py / jacoco / istanbul / cobertura），解析并入库
- GET  /         按项目 / 测试任务列出覆盖率报告
- GET  /{id}     报告详情（含文件级明细）
- DELETE /{id}   删除报告
"""

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

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
):
    """上传覆盖率报告 XML 并解析入库。"""
    async with get_db_session() as db:
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
            files_json=result["files"][:2000],
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
):
    """按项目 / 测试任务列出覆盖率报告。"""
    async with get_db_session() as db:
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
):
    """覆盖率报告详情（含文件级明细）。"""
    async with get_db_session() as db:
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
):
    """删除覆盖率报告。"""
    async with get_db_session() as db:
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
