"""
审计日志 API 路由

提供：
- GET / — 分页查询审计日志（支持过滤）
- GET /statistics — 审计日志统计
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import User
from app.modules.auth.dependencies import get_current_user
from app.modules.audit.audit_service import AuditService
from app.utils.database import get_db_session

router = APIRouter()


@router.get("/")
async def list_audit_logs(
    user_id: str | None = Query(None, description="按用户ID过滤"),
    action: str | None = Query(None, description="按操作类型过滤"),
    resource_type: str | None = Query(None, description="按资源类型过滤"),
    start_date: str | None = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="结束日期 (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    查询审计日志列表。

    支持按用户、操作类型、资源类型、时间范围过滤。
    """
    # 解析日期
    start_dt: datetime | None = None
    end_dt: datetime | None = None
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
        except ValueError:
            pass

    result = await AuditService.list_logs(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        page_size=page_size,
        db=db,
    )

    return {
        "code": 0,
        "data": result,
        "message": "success",
    }


@router.get("/statistics")
async def get_audit_statistics(
    days: int = Query(30, ge=1, le=365, description="统计时间范围（天）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """获取审计日志统计信息。"""
    result = await AuditService.get_statistics(days=days, db=db)

    return {
        "code": 0,
        "data": result,
        "message": "success",
    }
