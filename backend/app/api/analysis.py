"""
代码解析 API 路由

提供代码分析接口：
- POST /run — 执行代码解析（技术栈识别 → 接口提取 → AI 语义分析）
- GET /{analysis_id} — 查询历史解析结果（从 TestRun 表查）
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TestRun
from app.modules.code_analyzer import AICodeAnalyzer, APIExtractor, StackDetector
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 请求模型 ====================


class AnalysisRequest(BaseModel):
    """代码解析请求"""

    local_path: str
    test_run_id: str | None = None  # 可选，关联测试任务


# ==================== API 路由 ====================


@router.post("/run")
async def run_analysis(
    req: AnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    执行代码解析。

    流程：
    1. 技术栈识别 — StackDetector.detect()
    2. API 接口提取 — APIExtractor.extract()
    3. AI 语义分析增强 — AICodeAnalyzer.analyze_project()
    4. 组装完整 analysis_result
    5. 如果有 test_run_id，更新 TestRun 记录

    Args:
        req: 解析请求，包含 local_path 和可选的 test_run_id。

    Returns:
        完整的 analysis_result 对象。
    """
    logger.info(
        f"Analysis request: path={req.local_path}, test_run_id={req.test_run_id}"
    )

    # 1. 技术栈识别
    detector = StackDetector()
    stack_info = detector.detect(req.local_path)

    # 2. API 接口提取
    extractor = APIExtractor()
    apis = extractor.extract(req.local_path, stack_info)

    # 3. AI 语义分析增强
    ai_analyzer = AICodeAnalyzer()
    try:
        ai_analysis = await ai_analyzer.analyze_project(
            req.local_path, apis, stack_info
        )
    except Exception as e:
        logger.error(f"AI analysis failed (non-blocking): {e}", exc_info=True)
        ai_analysis = {
            "business_modules": [],
            "data_flow": {},
            "risk_areas": [],
            "api_analyses": [],
            "error": str(e),
        }

    # 4. 组装完整结果
    analysis_result: dict[str, Any] = {
        "tech_stack": stack_info,
        "apis": apis,
        "ai_analysis": ai_analysis,
        "total_apis": len(apis),
    }

    # 5. 如果有 test_run_id，更新 TestRun 记录
    if req.test_run_id:
        try:
            result = await db.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(req.test_run_id))
            )
            test_run = result.scalar_one_or_none()
            if test_run is not None:
                test_run.analysis_result = analysis_result
                await db.flush()
                logger.info(
                    f"Analysis result saved to TestRun: {req.test_run_id}"
                )
            else:
                logger.warning(
                    f"TestRun not found: {req.test_run_id}, "
                    f"analysis result will not be persisted"
                )
        except Exception as e:
            logger.error(
                f"Failed to update TestRun {req.test_run_id}: {e}",
                exc_info=True,
            )

    logger.info(
        f"Analysis completed: stack={stack_info.get('stack')}, "
        f"apis={len(apis)}, "
        f"modules={len(ai_analysis.get('business_modules', []))}, "
        f"risks={len(ai_analysis.get('risk_areas', []))}"
    )

    return {
        "code": 0,
        "data": analysis_result,
        "message": "Analysis completed successfully",
    }


@router.get("/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    查询历史解析结果。

    从 TestRun 表的 analysis_result 字段获取。

    Args:
        analysis_id: TestRun ID（UUID 字符串）。

    Returns:
        analysis_result 对象。
    """
    try:
        run_id = uuid.UUID(analysis_id)
    except ValueError:
        raise HTTPException(400, f"Invalid analysis_id format: {analysis_id}")

    result = await db.execute(select(TestRun).where(TestRun.id == run_id))
    test_run = result.scalar_one_or_none()

    if test_run is None:
        raise HTTPException(404, f"Analysis not found: {analysis_id}")

    analysis_result = test_run.analysis_result or {}

    return {
        "code": 0,
        "data": {
            "test_run_id": str(test_run.id),
            "status": test_run.status.value if test_run.status else None,
            "analysis_result": analysis_result,
        },
        "message": "success",
    }
