"""
能力8（定时任务）API 路由

提供：
- GET  /:                列表
- POST /:                创建
- POST /parse-cron:      NL→Cron 解析
- GET  /{id}:            详情
- PUT  /{id}:            更新
- DELETE /{id}:          删除
- POST /{id}/toggle:     启用/禁用切换
- GET  /{id}/history:    执行历史
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scheduler.cron_parser import CronParser
from app.modules.scheduler.scheduler_service import SchedulerService
from app.schemas.scheduled_task import (
    ScheduledTaskRequest,
    ScheduledTaskUpdate,
    ParseCronRequest,
)
from app.utils.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.scheduler.next_run import next_run

router = APIRouter()


class SchedulePreviewRequest(BaseModel):
    cron_expression: str | None = None
    mode: str = "daily"
    hour: int = Field(default=9, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    weekday: int = Field(default=1, ge=0, le=6)
    month_day: int = Field(default=1, ge=1, le=31)
    interval_hours: int = Field(default=1, ge=1, le=23)
    timezone: str = "Asia/Shanghai"
    count: int = Field(default=5, ge=1, le=20)


@router.get("")
async def list_tasks(
    project_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取定时任务列表。"""
    result = await SchedulerService.list_tasks(
        project_id=project_id,
        status=status,
        page=page,
        page_size=page_size,
        db=db,
    )
    return {"code": 0, "data": result, "message": "ok"}


@router.post("")
async def create_task(
    req: ScheduledTaskRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """创建定时任务。"""
    if not req.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    # 若未显式提供 cron 表达式，则用自然语言描述解析得到
    cron_expression = req.cron_expression
    if (not cron_expression or cron_expression == "0 0 * * *") and req.nl_schedule:
        parser = CronParser()
        cron_expression = await parser.parse(req.nl_schedule)

    result = await SchedulerService.create_task(
        project_id=req.project_id,
        name=req.name,
        cron_expression=cron_expression,
        target_type=req.target_type,
        target_id=req.target_id,
        description=req.description,
        nl_schedule=req.nl_schedule,
        target_config=req.target_config,
        env_config=req.env_config,
        status=req.status,
        created_by=str(current_user.id),
        db=db,
    )
    return {"code": 0, "data": result, "message": "ok"}


@router.post("/parse-cron")
async def parse_cron(
    req: ParseCronRequest,
) -> dict[str, Any]:
    """NL→Cron 表达式解析。"""
    parser = CronParser()
    cron = await parser.parse(req.nl_schedule)
    return {
        "code": 0,
        "data": {
            "cron_expression": cron,
            "description": parser.describe(cron),
        },
        "message": "ok",
    }


@router.post("/preview")
async def preview_schedule(
    req: SchedulePreviewRequest,
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """将表单化调度转换为 Cron，并预览后续触发时间。"""
    if req.timezone != "Asia/Shanghai":
        raise HTTPException(422, "当前调度器仅支持 Asia/Shanghai 时区")
    if req.cron_expression:
        cron = req.cron_expression.strip()
    elif req.mode == "daily":
        cron = f"{req.minute} {req.hour} * * *"
    elif req.mode == "weekly":
        cron = f"{req.minute} {req.hour} * * {req.weekday}"
    elif req.mode == "monthly":
        cron = f"{req.minute} {req.hour} {req.month_day} * *"
    elif req.mode == "interval":
        cron = f"{req.minute} */{req.interval_hours} * * *"
    else:
        raise HTTPException(422, "不支持的调度模式")
    cursor = datetime.utcnow()
    values: list[str] = []
    try:
        from zoneinfo import ZoneInfo
        display_tz = ZoneInfo(req.timezone)
    except Exception:
        display_tz = timezone.utc
    for _ in range(req.count):
        value = next_run(cron, cursor)
        if value is None:
            raise HTTPException(422, "Cron 表达式无效或无法计算下次时间")
        values.append(value.replace(tzinfo=timezone.utc).astimezone(display_tz).isoformat())
        cursor = value
    return {"code": 0, "data": {"cron_expression": cron, "timezone": req.timezone, "next_runs": values}, "message": "ok"}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取定时任务详情。"""
    result = await SchedulerService.get_task(task_id=task_id, db=db)
    if result is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"code": 0, "data": result, "message": "ok"}


@router.put("/{task_id}")
async def update_task(
    task_id: str,
    req: ScheduledTaskUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """更新定时任务。"""
    data = {k: v for k, v in req.model_dump().items() if v is not None}
    # service 的 update_task 仅接受可安全原地修改的字段。
    allowed = {
        "name", "description", "cron_expression", "nl_schedule",
        "target_config", "env_config", "status",
    }
    filtered = {k: v for k, v in data.items() if k in allowed}
    result = await SchedulerService.update_task(task_id=task_id, db=db, **filtered)
    if result is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"code": 0, "data": result, "message": "ok"}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """删除定时任务。"""
    success = await SchedulerService.delete_task(task_id=task_id, db=db)
    if not success:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{task_id}/toggle")
async def toggle_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """切换定时任务启用/禁用状态。"""
    result = await SchedulerService.toggle_task(task_id=task_id, db=db)
    if result is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"code": 0, "data": result, "message": "ok"}


@router.get("/{task_id}/history")
async def get_task_history(
    task_id: str,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取定时任务执行历史。"""
    result = await SchedulerService.get_history(
        task_id=task_id, page=page, page_size=page_size, db=db
    )
    return {"code": 0, "data": result, "message": "ok"}
