"""
能力9（报告分析）API 路由

提供：
- POST /reports/{id}/ai-analysis:  报告级 AI 分析
- POST /results/{id}/ai-analysis:  结果级 AI 失败分析
- POST /results/{id}/compare:       结果对比分析
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.report_analysis.analyzer import ReportAnalyzer
from app.schemas.report_analysis import (
    ReportAnalysisRequest,
    ResultAnalysisRequest,
    CompareRequest,
)
from app.utils.database import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/reports/{report_id}/ai-analysis")
async def analyze_report(
    report_id: str,
    req: ReportAnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    报告级 AI 分析。

    根据 analysis_type 执行不同分析：
    - failure_analysis: 失败原因分析
    - summary: 测试摘要生成
    """
    if not req.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    analyzer = ReportAnalyzer()

    try:
        if req.analysis_type == "summary":
            result = await analyzer.analyze_summary(
                report_id=report_id,
                project_id=req.project_id,
                db_session=db,
            )
        else:
            result = await analyzer.analyze_failure(
                result_id=req.result_id or report_id,
                project_id=req.project_id,
                db_session=db,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    except Exception as e:
        logger.exception(f"Compare analysis failed for {result_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    return {"code": 0, "data": result, "message": "ok"}