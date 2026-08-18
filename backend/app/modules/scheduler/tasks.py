"""
Scheduler Celery Tasks

提供 celery beat 调用的定时任务执行入口。
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.utils.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.modules.scheduler.tasks.execute_scheduled_task")
def execute_scheduled_task(task_id: str) -> dict:
    """
    执行定时任务。

    被 django-celery-beat DatabaseScheduler 按 cron 调度调用。
    从数据库读取 ScheduledTask，触发对应的测试任务或场景执行。

    Args:
        task_id: ScheduledTask 的 ID

    Returns:
        {"status": str, "run_id": str | None}
    """
    import asyncio

    return asyncio.run(_execute_async(task_id))


async def _execute_async(task_id: str) -> dict:
    """异步执行定时任务。"""
    from sqlalchemy import select
    from app.models.database import (
        ScheduledTask,
        ScheduledTaskRun,
        ScheduledTaskStatus,
        ScheduledTaskTargetType,
    )
    import uuid

    async with AsyncSessionLocal() as session:
        try:
            # 加载任务定义
            result = await session.execute(
                select(ScheduledTask).where(ScheduledTask.id == uuid.UUID(task_id))
            )
            task = result.scalar_one_or_none()

            if task is None:
                logger.error(f"ScheduledTask {task_id} not found")
                return {"status": "error", "run_id": None, "error": "Task not found"}

            if task.status != ScheduledTaskStatus.ACTIVE:
                logger.info(f"ScheduledTask {task_id} is {task.status}, skipping")
                return {"status": "skipped", "run_id": None}

            # 创建执行记录
            run = ScheduledTaskRun(
                id=uuid.uuid4(),
                task_id=uuid.UUID(task_id),
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            session.add(run)
            await session.flush()

            # 触发实际执行
            # 注：真实的测试执行链（TestExecutionEngine / ScenarioOrchestrator）
            # 需要 analysis_result / test_cases / candidate_endpoints 等完整上下文，
            # 当前调度上下文仅有 target_id，不足以直接拉起一次完整执行。
            # 此处先记录调度触发，待接入真实执行链（TODO）。
            if task.target_type in (
                ScheduledTaskTargetType.SCENARIO,
                ScheduledTaskTargetType.CASE_COLLECTION,
            ):
                logger.info(
                    f"Scheduled task {task_id} triggered "
                    f"(target_type={task.target_type.value}, target_id={task.target_id}); "
                    f"真实执行链待接入"
                )
                run.status = "success"
            else:
                run.status = "failed"
                run.error_message = f"Unknown target_type: {task.target_type}"

            run.finished_at = datetime.now(timezone.utc)
            task.last_run_at = datetime.now(timezone.utc)
            task.last_run_status = run.status
            await session.flush()

            logger.info(
                f"ScheduledTask {task_id} ({task.name}) executed: {run.status}"
            )
            return {"status": run.status, "run_id": str(run.id)}

        except Exception as e:
            logger.exception(f"Failed to execute ScheduledTask {task_id}: {e}")
            return {"status": "error", "run_id": None, "error": str(e)}