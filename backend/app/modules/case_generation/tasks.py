"""接口用例生成 Celery 任务。"""

import asyncio

from app.celery_app import celery_app
from app.modules.case_generation.service import run_generation_task


@celery_app.task(name="app.modules.case_generation.tasks.generate_api_cases")
def generate_api_cases(task_id: str) -> None:
    from uuid import UUID
    asyncio.run(run_generation_task(UUID(task_id)))
