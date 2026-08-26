"""
能力9（报告分析）API 路由

提供：
- POST /reports/{id}/ai-analysis:  报告级 AI 分析
- POST /results/{id}/ai-analysis:  结果级 AI 失败分析
- POST /results/{id}/compare:       结果对比分析
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TestCase, TestResult, TestRun
from app.modules.ai.model_router import ModelNotConfiguredError
from app.modules.report_analysis.analyzer import ReportAnalyzer
from app.schemas.report_analysis import (
    ReportAnalysisRequest,
    ResultAnalysisRequest,
    CompareRequest,
)
from app.utils.database import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/results")
async def list_results(
    project_id: str | None = Query(None, description="按项目ID过滤"),
    test_run_id: str | None = Query(None, description="按测试任务ID过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    列出测试结果（供前端下拉框选择已有结果）。

    支持按 project_id 或 test_run_id 过滤，分页返回。
    返回字段含关联的用例名，便于下拉框展示可读 label。
    """
    query = (
        select(TestResult, TestCase, TestRun)
        .join(TestCase, TestCase.id == TestResult.test_case_id)
        .join(TestRun, TestRun.id == TestResult.test_run_id)
    )

    if test_run_id:
        try:
            query = query.where(TestResult.test_run_id == uuid.UUID(test_run_id))
        except ValueError:
            raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")

    if project_id:
        try:
            pid = uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(400, f"Invalid project_id: {project_id}")
        run_ids = (
            await db.execute(select(TestRun.id).where(TestRun.project_id == pid))
        ).fetchall()
        run_id_list = [row[0] for row in run_ids]
        if run_id_list:
            query = query.where(TestResult.test_run_id.in_(run_id_list))
        else:
            return {
                "code": 0,
                "data": {"list": [], "total": 0, "page": page, "page_size": page_size},
                "message": "success",
            }

    query = query.order_by(desc(TestResult.executed_at))
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.fetchall()

    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "id": str(res.id),
                    "test_run_id": str(res.test_run_id),
                    "test_case_id": str(res.test_case_id),
                    "case_name": case.case_name if case else "unknown",
                    "case_type": case.case_type if case else None,
                    "is_passed": res.is_passed,
                    "status_code": res.status_code,
                    "response_time_ms": res.response_time_ms,
                    "error_message": (res.error_message or "")[:200],
                    "executed_at": res.executed_at.isoformat() if res.executed_at else None,
                }
                for res, case, run in rows
            ],
            "total": len(rows),
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.post("/reports/{report_id}/ai-analysis")
async def analyze_report(
    report_id: str,
    req: ReportAnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    报告级 AI 分析（仅支持报告摘要 / 质量评估）。

    报告资源只做摘要，单用例失败分析请走 /results/{id}/ai-analysis。
    此前该端点默认走 failure_analysis 分支、拿报告 ID 去查 test_results
    表导致 404，现统一为摘要分析。
    """
    if not req.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    analyzer = ReportAnalyzer()

    try:
        result = await analyzer.analyze_summary(
            report_id=report_id,
            project_id=req.project_id,
            db_session=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotConfiguredError:
        raise
    except Exception as e:
        logger.exception(f"Report analysis failed for {report_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    return {"code": 0, "data": result, "message": "ok"}


@router.post("/results/{result_id}/ai-analysis")
async def analyze_result(
    result_id: str,
    req: ResultAnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    结果级 AI 失败分析。

    分析单个测试结果的失败原因。
    """
    if not req.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    analyzer = ReportAnalyzer()

    try:
        result = await analyzer.analyze_failure(
            result_id=result_id,
            project_id=req.project_id,
            db_session=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotConfiguredError:
        raise
    except Exception as e:
        logger.exception(f"Result analysis failed for {result_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    return {"code": 0, "data": result, "message": "ok"}


@router.post("/results/{result_id}/compare")
async def compare_results(
    result_id: str,
    req: CompareRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    结果对比分析。

    对比当前测试结果与对比 run 的对应结果，分析质量趋势。
    """
    if not req.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    analyzer = ReportAnalyzer()

    try:
        result = await analyzer.analyze_compare(
            result_id=result_id,
            compare_run_id=req.compare_run_id,
            project_id=req.project_id,
            db_session=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotConfiguredError:
        raise
    except Exception as e:
        logger.exception(f"Compare analysis failed for {result_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    return {"code": 0, "data": result, "message": "ok"}