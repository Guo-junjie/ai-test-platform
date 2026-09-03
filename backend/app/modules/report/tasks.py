"""报告自动生成 Celery 任务 — 测试完成后无需手动点「重新生成」。

由 aggregate_results 在测试结果落库后派发（total_tests>0 时）。
守卫：已有报告跳过（避免覆盖手动重新生成的版本）、无测试结果跳过。
"""
import asyncio

from loguru import logger

from app.celery_app import celery_app
from app.utils.database import AsyncSessionLocal


@celery_app.task(name="app.modules.report.tasks.auto_generate_report")
def auto_generate_report(test_run_id: str) -> dict:
    """测试完成后自动生成报告（含项目归属上下文）。"""
    return asyncio.run(_auto_generate(test_run_id))


async def _auto_generate(test_run_id: str) -> dict:
    from sqlalchemy import select

    from app.models.database import TestReport

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(TestReport).where(TestReport.test_run_id == test_run_id)
            )
        ).scalar_one_or_none()
    if existing is not None:
        logger.info(f"[{test_run_id}] auto report skipped: report already exists")
        return {"status": "skipped", "reason": "report exists"}

    # 复用 API 层的结果加载与生成流程（含缺陷分析 + 项目上下文 + 双格式渲染）
    from app.api.report import _generate_report_async, _load_test_results

    async with AsyncSessionLocal() as db:
        test_results = await _load_test_results(test_run_id, db)
    if test_results is None:
        logger.info(f"[{test_run_id}] auto report skipped: no test results")
        return {"status": "skipped", "reason": "no test results"}

    try:
        await _generate_report_async(test_run_id, test_results)
        logger.info(f"[{test_run_id}] auto report generated")
        return {"status": "success"}
    except Exception as exc:  # noqa: BLE001 - 自动生成失败不影响测试结果
        logger.exception(f"[{test_run_id}] auto report generation failed: {exc}")
        return {"status": "failed", "error": str(exc)[:300]}
