"""
报告 API 路由

提供测试报告的完整生命周期管理：
- GET /{run_id} — 获取报告数据 JSON
- GET /{run_id}/html — 返回在线 HTML 报告内容
- GET /{run_id}/pdf — 下载 PDF 报告
- GET /{run_id}/share — 生成分享链接
- GET /history — 查询历史报告列表
- POST /{run_id}/generate — 手动触发报告生成
"""

import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TestReport, TestRun
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== API 路由 ====================


@router.get("/history")
async def get_report_history(
    test_run_id: str | None = Query(None, description="按测试任务ID过滤"),
    project_id: str | None = Query(None, description="按项目ID过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    查询历史报告列表。

    支持按 test_run_id 或 project_id 过滤，分页返回。
    """
    query = select(TestReport).order_by(desc(TestReport.created_at))

    if test_run_id:
        try:
            run_uuid = uuid.UUID(test_run_id)
            query = query.where(TestReport.test_run_id == run_uuid)
        except ValueError:
            raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")

    if project_id:
        # 通过 TestRun 关联查询 project_id
        run_query = select(TestRun.id).where(TestRun.project_id == uuid.UUID(project_id))
        run_result = await db.execute(run_query)
        run_ids = [row[0] for row in run_result.fetchall()]
        if run_ids:
            query = query.where(TestReport.test_run_id.in_(run_ids))
        else:
            return {"code": 0, "data": {"list": [], "total": 0}, "message": "success"}

    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    reports = result.scalars().all()

    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "id": str(r.id),
                    "test_run_id": str(r.test_run_id),
                    "quality_score": r.quality_score,
                    "gate_passed": r.gate_passed,
                    "html_path": r.html_path,
                    "pdf_path": r.pdf_path,
                    "share_token": r.share_token,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in reports
            ],
            "total": len(reports),
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.get("/{run_id}")
async def get_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取报告数据 JSON。

    从 TestReport 表查询完整 report_data。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(404, f"Report not found for run: {run_id}")

    return {
        "code": 0,
        "data": {
            "id": str(report.id),
            "test_run_id": str(report.test_run_id),
            "report_data": report.report_data,
            "quality_score": report.quality_score,
            "gate_passed": report.gate_passed,
            "gate_details": report.gate_details,
            "html_path": report.html_path,
            "pdf_path": report.pdf_path,
            "share_token": report.share_token,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        },
        "message": "success",
    }


@router.get("/{run_id}/html")
async def get_html_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    返回在线 HTML 报告内容。

    优先从 MinIO 下载，失败时从本地路径读取。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(404, f"Report not found for run: {run_id}")

    html_object_name = report.html_path
    if not html_object_name:
        raise HTTPException(404, "HTML report path not available")

    # 尝试从 MinIO 下载
    try:
        from app.utils.storage import download_file
        import tempfile
        import os

        temp_path = os.path.join(tempfile.gettempdir(), f"report_{run_id}.html")
        download_file(html_object_name, temp_path)

        with open(temp_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        return {"code": 0, "data": {"html": html_content}, "message": "success"}
    except Exception as e:
        logger.warning(f"Failed to download HTML from MinIO: {e}")

        # 尝试从本地路径读取
        try:
            from app.config import settings
            local_path = os.path.join(settings.REPORT_DIR, html_object_name.split("/")[-1])
            with open(local_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            return {"code": 0, "data": {"html": html_content}, "message": "success"}
        except Exception as e2:
            raise HTTPException(500, f"Failed to read HTML report: {e2}")


@router.get("/{run_id}/pdf")
async def download_pdf_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    下载 PDF 报告。

    返回 StreamingResponse，media_type=application/pdf。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(404, f"Report not found for run: {run_id}")

    pdf_object_name = report.pdf_path
    if not pdf_object_name:
        raise HTTPException(404, "PDF report not available (may not have been generated)")

    # 从 MinIO 下载
    try:
        from app.utils.storage import download_file
        import tempfile
        import os

        temp_path = os.path.join(tempfile.gettempdir(), f"report_{run_id}.pdf")
        download_file(pdf_object_name, temp_path)

        with open(temp_path, "rb") as f:
            pdf_bytes = f.read()

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=test_report_{run_id[:8]}.pdf"
            },
        )
    except Exception as e:
        logger.error(f"Failed to download PDF: {e}")
        raise HTTPException(500, f"Failed to download PDF report: {e}")


@router.get("/{run_id}/share")
async def get_share_link(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    生成报告分享链接。

    返回 presigned URL（7 天有效期）。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(404, f"Report not found for run: {run_id}")

    html_object_name = report.html_path
    if not html_object_name:
        raise HTTPException(404, "HTML report path not available")

    try:
        from app.utils.storage import get_presigned_url

        # 生成 7 天有效的 presigned URL
        share_url = get_presigned_url(html_object_name, expires_hours=7 * 24)

        return {
            "code": 0,
            "data": {
                "share_url": share_url,
                "share_token": report.share_token,
                "expires_hours": 7 * 24,
            },
            "message": "success",
        }
    except Exception as e:
        logger.error(f"Failed to generate share link: {e}")
        raise HTTPException(500, f"Failed to generate share link: {e}")


@router.post("/{run_id}/generate")
async def generate_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    手动触发报告生成。

    从 Redis 读取测试结果，调用 DefectAnalyzer + ReportGenerator 生成报告。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    # 查询 TestRun
    result = await db.execute(select(TestRun).where(TestRun.id == run_uuid))
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(404, f"Test run not found: {run_id}")

    # 从 Redis 读取测试结果
    from app.utils.redis_client import get_task_result

    test_results = await get_task_result(run_id)
    if test_results is None:
        raise HTTPException(400, "Test results not found in Redis. Has the test completed?")

    # 异步执行报告生成
    import asyncio

    asyncio.create_task(
        _generate_report_async(run_id, test_results)
    )

    return {
        "code": 0,
        "data": {
            "test_run_id": run_id,
            "status": "generating",
            "message": "Report generation started",
        },
        "message": "success",
    }


# ==================== 内部函数 ====================


async def _generate_report_async(
    test_run_id: str,
    test_results: dict[str, Any],
) -> None:
    """异步执行报告生成流程。"""
    from app.utils.redis_client import set_task_status, set_task_progress

    try:
        await set_task_status(test_run_id, "analyzing_defects", {"step": "defect_analysis"})
        await set_task_progress(test_run_id, 90, "缺陷分析")

        # 1. 缺陷分析
        from app.modules.defect_analyzer import DefectAnalyzer

        analyzer = DefectAnalyzer()
        defects = await analyzer.analyze(test_results)

        logger.info(f"[{test_run_id}] Defect analysis completed: {defects['summary']['total']} defects")

        # 2. 报告生成
        await set_task_status(test_run_id, "reporting", {"step": "report_generation"})
        await set_task_progress(test_run_id, 95, "生成报告")

        from app.modules.report import ReportGenerator

        generator = ReportGenerator()
        report_result = await generator.generate(test_run_id, test_results, defects)

        logger.info(
            f"[{test_run_id}] Report generated: score={report_result['quality_score']}, "
            f"pass={report_result['overall_pass']}"
        )

        await set_task_status(test_run_id, "completed", {
            "quality_score": report_result["quality_score"],
            "overall_pass": report_result["overall_pass"],
        })
        await set_task_progress(test_run_id, 100, "报告生成完成")

    except Exception as e:
        logger.error(f"[{test_run_id}] Report generation failed: {e}", exc_info=True)
        await set_task_status(test_run_id, "failed", {"error": str(e)})
        await set_task_progress(test_run_id, 0, f"报告生成失败: {str(e)[:100]}")
