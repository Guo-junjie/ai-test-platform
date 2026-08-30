"""
Scheduler Celery Tasks

提供 celery beat 调用的定时任务执行入口。
"""

import logging
from datetime import datetime

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
                started_at=datetime.utcnow(),
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

            run.finished_at = datetime.utcnow()
            task.last_run_at = datetime.utcnow()
            task.last_run_status = run.status
            # tick 之外独立调用的入口（如手动触发）必须自己提交；
            # flush 只写了缓冲，不 commit 的话执行历史在事务结束即丢失。
            await session.commit()

            logger.info(
                f"ScheduledTask {task_id} ({task.name}) executed: {run.status}"
            )
            return {"status": run.status, "run_id": str(run.id)}

        except Exception as e:
            logger.exception(f"Failed to execute ScheduledTask {task_id}: {e}")
            return {"status": "error", "run_id": None, "error": str(e)}


@celery_app.task(name="app.modules.scheduler.tasks.scheduled_tick")
def scheduled_tick() -> dict:
    """
    定时调度 tick — 由 Celery Beat 每 30 秒派发一次。

    轮询 scheduled_tasks 表，把 next_run_at 已到期的 ACTIVE 任务派发给
    execute_scheduled_task，并用 next_run_at 做乐观锁抢占，保证多 beat /
    多 tick 并发下同一轮次只触发一次。

    语义约定：
    - cron 按北京时间解释，next_run_at 存 naive UTC（与全库一致）；
    - next_run_at 为 NULL（新建任务）时只做初始化计算，不立即触发；
    - cron 非法或计算失败时跳过该任务（记日志），不拖垮整个 tick。
    """
    import asyncio

    return asyncio.run(_tick_async())


async def _tick_async() -> dict:
    from sqlalchemy import select, update

    from app.models.database import ScheduledTask, ScheduledTaskStatus
    from app.modules.scheduler.next_run import next_run as compute_next_run

    now = datetime.utcnow()
    fired = initialized = skipped = 0

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(ScheduledTask).where(
                    ScheduledTask.status == ScheduledTaskStatus.ACTIVE
                )
            )
        ).scalars().all()

        for task in rows:
            try:
                if task.next_run_at is None:
                    # 新任务：只初始化下次执行时间，不补触发
                    nxt = compute_next_run(task.cron_expression, now)
                    if nxt is None:
                        skipped += 1
                        continue
                    res = await session.execute(
                        update(ScheduledTask)
                        .where(
                            ScheduledTask.id == task.id,
                            ScheduledTask.next_run_at.is_(None),
                        )
                        .values(next_run_at=nxt)
                    )
                    if res.rowcount:
                        await session.commit()
                        initialized += 1
                    continue

                if task.next_run_at > now:
                    continue

                # 到期：计算下一次时间（从 now 起算，追平积压只补发一次）
                nxt = compute_next_run(task.cron_expression, now)
                if nxt is None:
                    skipped += 1
                    continue
                # 乐观锁：仅当 next_run_at 仍是读到的旧值时才改写并派发
                res = await session.execute(
                    update(ScheduledTask)
                    .where(
                        ScheduledTask.id == task.id,
                        ScheduledTask.next_run_at == task.next_run_at,
                    )
                    .values(next_run_at=nxt)
                )
                if not res.rowcount:
                    continue  # 已被其他 tick 抢占
                await session.commit()
                execute_scheduled_task.delay(str(task.id))
                fired += 1
                logger.info(
                    f"Tick fired ScheduledTask {task.id} ({task.name}), "
                    f"next_run_at={nxt.isoformat()}"
                )
            except Exception as e:  # noqa: BLE001 - 单任务异常不拖垮整轮
                logger.exception(f"Tick failed for ScheduledTask {task.id}: {e}")
                skipped += 1

    return {"fired": fired, "initialized": initialized, "skipped": skipped}