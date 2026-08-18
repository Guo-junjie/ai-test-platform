"""
能力8：定时任务调度服务

提供定时任务的 CRUD 操作，以及 Celery beat 集成。
当前实现仅做 CRUD 管理，不实现 beat 同步细节。
"""

import uuid
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    ScheduledTask,
    ScheduledTaskRun,
    ScheduledTaskStatus,
    ScheduledTaskTargetType,
)
from app.utils.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    定时任务调度服务。

    提供定时任务的 CRUD 操作和执行历史查询。
    """

    # ==================== CRUD ====================

    @staticmethod
    async def create_task(
        project_id: str,
        name: str,
        cron_expression: str,
        target_type: str,
        target_id: str | None = None,
        description: str | None = None,
        nl_schedule: str | None = None,
        target_config: dict[str, Any] | None = None,
        env_config: dict[str, Any] | None = None,
        created_by: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """创建定时任务。"""
        async def _create(session: AsyncSession) -> dict[str, Any]:
            try:
                tt = ScheduledTaskTargetType(target_type)
            except ValueError:
                raise ValueError(f"Invalid target_type: {target_type}")

            tgt_id = uuid.UUID(target_id) if target_id else None
            cby = uuid.UUID(created_by) if created_by else None

            task = ScheduledTask(
                id=uuid.uuid4(),
                project_id=uuid.UUID(project_id),
                name=name,
                description=description,
                nl_schedule=nl_schedule,
                cron_expression=cron_expression,
                target_type=tt,
                target_id=tgt_id,
                target_config=target_config or {},
                env_config=env_config or {},
                status=ScheduledTaskStatus.ACTIVE,
                created_by=cby,
            )
            session.add(task)
            await session.flush()
            await session.refresh(task)

            return {
                "id": str(task.id),
                "project_id": str(task.project_id),
                "name": task.name,
                "description": task.description,
                "nl_schedule": task.nl_schedule,
                "cron_expression": task.cron_expression,
                "target_type": task.target_type.value if task.target_type else "",
                "target_id": str(task.target_id) if task.target_id else None,
                "target_config": task.target_config or {},
                "env_config": task.env_config or {},
                "status": task.status.value if task.status else "active",
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }

        if db is not None:
            return await _create(db)
        async with AsyncSessionLocal() as session:
            return await _create(session)

    @staticmethod
    async def update_task(
        task_id: str,
        name: str | None = None,
        description: str | None = None,
        cron_expression: str | None = None,
        nl_schedule: str | None = None,
        target_config: dict[str, Any] | None = None,
        env_config: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """更新定时任务。"""
        async def _update(session: AsyncSession) -> dict[str, Any] | None:
            tid = uuid.UUID(task_id)
            task = (
                await session.execute(
                    select(ScheduledTask).where(ScheduledTask.id == tid)
                )
            ).scalar_one_or_none()
            if task is None:
                return None

            if name is not None:
                task.name = name
            if description is not None:
                task.description = description
            if cron_expression is not None:
                task.cron_expression = cron_expression
            if nl_schedule is not None:
                task.nl_schedule = nl_schedule
            if target_config is not None:
                task.target_config = target_config
            if env_config is not None:
                task.env_config = env_config

            await session.flush()
            await session.refresh(task)

            return {
                "id": str(task.id),
                "name": task.name,
                "cron_expression": task.cron_expression,
                "status": task.status.value if task.status else "active",
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }

        if db is not None:
            return await _update(db)
        async with AsyncSessionLocal() as session:
            return await _update(session)

    @staticmethod
    async def delete_task(
        task_id: str,
        db: AsyncSession | None = None,
    ) -> bool:
        """删除定时任务（软删除）。"""
        async def _delete(session: AsyncSession) -> bool:
            tid = uuid.UUID(task_id)
            task = (
                await session.execute(
                    select(ScheduledTask).where(ScheduledTask.id == tid)
                )
            ).scalar_one_or_none()
            if task is None:
                return False

            task.status = ScheduledTaskStatus.DELETED
            await session.flush()
            return True

        if db is not None:
            return await _delete(db)
        async with AsyncSessionLocal() as session:
            return await _delete(session)

    @staticmethod
    async def toggle_task(
        task_id: str,
        db: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """切换定时任务启用/暂停状态。"""
        async def _toggle(session: AsyncSession) -> dict[str, Any] | None:
            tid = uuid.UUID(task_id)
            task = (
                await session.execute(
                    select(ScheduledTask).where(ScheduledTask.id == tid)
                )
            ).scalar_one_or_none()
            if task is None:
                return None

            if task.status == ScheduledTaskStatus.ACTIVE:
                task.status = ScheduledTaskStatus.PAUSED
            elif task.status == ScheduledTaskStatus.PAUSED:
                task.status = ScheduledTaskStatus.ACTIVE
            else:
                return None

            await session.flush()
            await session.refresh(task)

            return {
                "id": str(task.id),
                "status": task.status.value if task.status else "",
            }

        if db is not None:
            return await _toggle(db)
        async with AsyncSessionLocal() as session:
            return await _toggle(session)

    # ==================== 列表 / 详情 ====================

    @staticmethod
    async def list_tasks(
        project_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """查询定时任务列表（按创建时间倒序）。"""
        async def _query(session: AsyncSession) -> dict[str, Any]:
            q = select(ScheduledTask).order_by(desc(ScheduledTask.created_at))
            if project_id:
                try:
                    pid = uuid.UUID(project_id)
                    q = q.where(ScheduledTask.project_id == pid)
                except ValueError:
                    pass
            if status:
                try:
                    st = ScheduledTaskStatus(status)
                    q = q.where(ScheduledTask.status == st)
                except ValueError:
                    pass

            all_rows = (await session.execute(q)).scalars().all()
            total = len(all_rows)
            page_val = max(1, page)
            page_size_val = max(1, min(page_size, 200))
            start = (page_val - 1) * page_size_val
            items = all_rows[start : start + page_size_val]

            return {
                "items": [
                    {
                        "id": str(t.id),
                        "project_id": str(t.project_id),
                        "name": t.name,
                        "description": t.description,
                        "nl_schedule": t.nl_schedule,
                        "cron_expression": t.cron_expression,
                        "target_type": t.target_type.value if t.target_type else "",
                        "target_id": str(t.target_id) if t.target_id else None,
                        "target_config": t.target_config or {},
                        "env_config": t.env_config or {},
                        "status": t.status.value if t.status else "active",
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                    }
                    for t in items
                ],
                "total": total,
            }

        if db is not None:
            return await _query(db)
        async with AsyncSessionLocal() as session:
            return await _query(session)

    @staticmethod
    async def get_task(
        task_id: str,
        db: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """按 ID 查询单条定时任务。"""
        async def _query(session: AsyncSession) -> dict[str, Any] | None:
            tid = uuid.UUID(task_id)
            task = (
                await session.execute(
                    select(ScheduledTask).where(ScheduledTask.id == tid)
                )
            ).scalar_one_or_none()
            if task is None:
                return None
            return {
                "id": str(task.id),
                "project_id": str(task.project_id),
                "name": task.name,
                "description": task.description,
                "nl_schedule": task.nl_schedule,
                "cron_expression": task.cron_expression,
                "target_type": task.target_type.value if task.target_type else "",
                "target_id": str(task.target_id) if task.target_id else None,
                "target_config": task.target_config or {},
                "env_config": task.env_config or {},
                "status": task.status.value if task.status else "active",
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }

        if db is not None:
            return await _query(db)
        async with AsyncSessionLocal() as session:
            return await _query(session)

    @staticmethod
    async def get_history(
        task_id: str,
        page: int = 1,
        page_size: int = 20,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """查询执行历史 — 委托 get_execution_history。"""
        return await SchedulerService.get_execution_history(
            task_id=task_id,
            page=page,
            page_size=page_size,
            db=db,
        )

    # ==================== 执行历史 ====================

    @staticmethod
    async def get_execution_history(
        task_id: str,
        page: int = 1,
        page_size: int = 20,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """查询定时任务执行历史。"""
        async def _query(session: AsyncSession) -> dict[str, Any]:
            tid = uuid.UUID(task_id)
            q = (
                select(ScheduledTaskRun)
                .where(ScheduledTaskRun.task_id == tid)
                .order_by(desc(ScheduledTaskRun.started_at))
            )
            all_rows = (await session.execute(q)).scalars().all()
            total = len(all_rows)
            page_val = max(1, page)
            page_size_val = max(1, min(page_size, 200))
            start = (page_val - 1) * page_size_val
            items = all_rows[start : start + page_size_val]

            return {
                "total": total,
                "page": page_val,
                "page_size": page_size_val,
                "items": [
                    {
                        "id": str(r.id),
                        "task_id": str(r.task_id),
                        "status": r.status,
                        "test_run_id": str(r.test_run_id) if r.test_run_id else None,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                        "error_message": r.error_message,
                    }
                    for r in items
                ],
            }

        if db is not None:
            return await _query(db)
        async with AsyncSessionLocal() as session:
            return await _query(session)

    @staticmethod
    async def record_run(
        task_id: str,
        status: str,
        test_run_id: str | None = None,
        error_message: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """记录一次任务执行。"""
        async def _record(session: AsyncSession) -> dict[str, Any]:
            run = ScheduledTaskRun(
                id=uuid.uuid4(),
                task_id=uuid.UUID(task_id),
                status=status,
                test_run_id=uuid.UUID(test_run_id) if test_run_id else None,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow() if status != "running" else None,
                error_message=error_message,
            )
            session.add(run)

            # 更新任务的 last_run 信息
            task = (
                await session.execute(
                    select(ScheduledTask).where(ScheduledTask.id == uuid.UUID(task_id))
                )
            ).scalar_one_or_none()
            if task:
                task.last_run_at = datetime.utcnow()
                task.last_run_status = status

            await session.flush()
            await session.refresh(run)

            return {
                "id": str(run.id),
                "task_id": str(run.task_id),
                "status": r.status,
                "test_run_id": str(r.test_run_id) if r.test_run_id else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "error_message": r.error_message,
            }

        if db is not None:
            return await _record(db)
        async with AsyncSessionLocal() as session:
            return await _record(session)