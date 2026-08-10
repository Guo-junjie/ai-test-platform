"""
测试流水线 Celery 任务

将完整测试流水线（代码拉取 → 代码解析 → 用例生成 → 执行调度）从 API 进程
迁移到 Celery worker 进程执行。

原实现放在 `app/api/test_run.py::_execute_full_pipeline`，使用
`asyncio.create_task` 在 API 事件循环里跑，但其中的 `SourceAdapterFactory.fetch_code()`
是同步阻塞调用，`AICodeAnalyzer.analyze_project` / `TestCaseGenerator.generate_all`
也在同一事件循环里 `await`，会把整个事件循环卡死，导致列表刷新、进度轮询等
后续 API 全部无响应（前端表现为"页面卡死"）。

迁入 Celery 后：API 只负责建 TestRun 记录并 `delay()` 派发，立刻返回；
所有重活在 worker 进程里以同步方式执行，互不干扰。
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text  # noqa: F401  (text 供后续扩展/排错使用)

from app.celery_app import celery_app as app
from app.models.database import TestRun, TestStatus
from app.modules.execution.engine import (
    _set_task_progress_sync,
    _set_task_status_sync,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 内部助手 ====================


def _mark_run_failed(test_run_id: str, error: str) -> None:
    """
    将 TestRun 行状态置为 FAILED（在 worker 进程中通过独立事件循环执行）。

    Args:
        test_run_id: 测试任务 ID。
        error: 错误描述，截取前 500 字符写入 error_message。
    """

    async def _update() -> None:
        from app.utils.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
            )
            run = result.scalar_one_or_none()
            if run:
                run.status = TestStatus.FAILED
                run.error_message = error[:500]
                run.completed_at = datetime.utcnow()
                await session.commit()

    try:
        asyncio.run(_update())
    except Exception as db_err:  # pragma: no cover - 兜底日志
        logger.error(f"[{test_run_id}] Failed to update DB status: {db_err}")


# ==================== Celery 任务 ====================


@app.task(bind=True, max_retries=2)
def run_test_pipeline(self, test_run_id: str, req_dict: dict[str, Any]) -> dict[str, Any]:
    """
    执行完整测试流水线（Celery 同步任务）。

    流程：代码拉取（10%）→ 代码解析（25%）→ 用例生成（40%）→ 执行调度（50%）

    Args:
        test_run_id: 测试任务 ID（字符串 UUID）。
        req_dict: `CreateTestRunRequest.model_dump()` 的结果。

    Returns:
        {"test_run_id": str, "status": str} —— 派发结果概要。
    """
    try:
        # Step 1: 代码拉取
        _set_task_status_sync(test_run_id, "pulling", {"step": "fetching_code"})
        _set_task_progress_sync(test_run_id, 10, "拉取代码")

        from app.modules.source import SourceAdapterFactory, SourceConfig, SourceType

        source_config = SourceConfig(
            source_type=SourceType(req_dict.get("source_type") or "github"),
            github_token=req_dict.get("github_token"),
            repo_url=req_dict.get("repo_url"),
            branch=req_dict.get("branch") or "main",
            commit_sha=req_dict.get("commit_sha"),
            svn_url=req_dict.get("svn_url"),
            svn_username=req_dict.get("svn_username"),
            svn_password=req_dict.get("svn_password"),
            upload_file_path=req_dict.get("upload_file_path"),
        )

        fetch_result = SourceAdapterFactory.fetch_code(source_config)
        local_path = fetch_result.get("local_path", "")
        snapshot_id = fetch_result.get("snapshot_id")

        logger.info(f"[{test_run_id}] Code fetched: {local_path}")

        # Step 2: 代码解析
        _set_task_status_sync(test_run_id, "analyzing", {"step": "code_analysis"})
        _set_task_progress_sync(test_run_id, 25, "代码解析")

        from app.modules.code_analyzer import AICodeAnalyzer, APIExtractor, StackDetector

        detector = StackDetector()
        stack_info = detector.detect(local_path)

        extractor = APIExtractor()
        apis = extractor.extract(local_path, stack_info)

        ai_analyzer = AICodeAnalyzer()
        try:
            ai_analysis = asyncio.run(
                ai_analyzer.analyze_project(local_path, apis, stack_info)
            )
        except Exception as e:
            logger.error(f"[{test_run_id}] AI analysis failed: {e}")
            ai_analysis = {
                "business_modules": [],
                "data_flow": {},
                "risk_areas": [],
                "api_analyses": [],
            }

        analysis_result: dict[str, Any] = {
            "tech_stack": stack_info,
            "apis": apis,
            "ai_analysis": ai_analysis,
            "total_apis": len(apis),
            "repo_path": local_path,
            "snapshot_id": snapshot_id,
        }

        logger.info(
            f"[{test_run_id}] Analysis completed: stack={stack_info.get('stack')}, "
            f"apis={len(apis)}"
        )

        # Step 3: 用例生成
        _set_task_status_sync(test_run_id, "generating", {"step": "case_generation"})
        _set_task_progress_sync(test_run_id, 40, "生成测试用例")

        from app.modules.case_generator import TestCaseGenerator

        generator = TestCaseGenerator()
        test_cases = asyncio.run(generator.generate_all(apis, ai_analysis))

        logger.info(
            f"[{test_run_id}] Cases generated: "
            f"api={len(test_cases.get('api', []))}, "
            f"perf={len(test_cases.get('performance', []))}, "
            f"integ={len(test_cases.get('integration', []))}"
        )

        # Step 4: 测试执行（内部为 Celery chain 的 apply_async，非阻塞）
        _set_task_status_sync(test_run_id, "executing", {"step": "test_execution"})
        _set_task_progress_sync(test_run_id, 50, "调度测试执行")

        from app.modules.execution.engine import TestExecutionEngine

        engine = TestExecutionEngine()
        engine.execute_all(test_run_id, analysis_result, test_cases)

        logger.info(f"[{test_run_id}] Pipeline dispatched, waiting for execution...")

        return {"test_run_id": test_run_id, "status": "executing"}

    except Exception as e:
        logger.error(f"[{test_run_id}] Pipeline failed: {e}", exc_info=True)

        _set_task_status_sync(test_run_id, "failed", {"error": str(e)})
        _set_task_progress_sync(test_run_id, 0, f"失败: {str(e)[:100]}")

        _mark_run_failed(test_run_id, str(e))

        return {"test_run_id": test_run_id, "status": "failed", "error": str(e)[:500]}
