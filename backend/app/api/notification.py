"""
站内通知 API 路由

提供：
- GET / — 当前用户通知列表（支持 ?unread_only=true 过滤）
- POST /{notification_id}/read — 标记单条已读
- POST /read-all — 全部标记已读
- DELETE /{notification_id} — 删除单条通知

注意：router 本身不带 prefix，统一由 main.py 以 ``prefix="/api/notifications"``
注册，与其它路由保持一致的注册风格。
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Notification, User, UserPreference
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class NotificationPreferenceRequest(BaseModel):
    enabled: bool = True
    channels: list[str] = Field(default_factory=lambda: ["in_app"])
    quiet_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"


# ==================== 内部工具 ====================


def _notification_to_dict(item: Notification) -> dict:
    """将 Notification ORM 对象序列化为字典。"""
    return {
        "id": str(item.id),
        "user_id": str(item.user_id) if item.user_id else None,
        "title": item.title,
        "content": item.content,
        "type": item.type or "system",
        "is_read": bool(item.is_read),
        "related_url": item.related_url,
        "resource_type": item.resource_type,
        "resource_id": str(item.resource_id) if item.resource_id else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


async def _get_owned_notification(
    notification_id: str,
    current_user: User,
    db: AsyncSession,
) -> Notification:
    """
    查询归属于当前用户的通知，找不到时抛 404。

    Raises:
        HTTPException(400): notification_id 不是合法 UUID。
        HTTPException(404): 通知不存在或不属于当前用户。
    """
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        raise HTTPException(400, f"Invalid notification_id: {notification_id}")

    result = await db.execute(
        select(Notification).where(
            Notification.id == nid,
            Notification.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(404, f"Notification not found: {notification_id}")
    return item


# ==================== 公共服务函数 ====================


async def create_notification(
    user_id: uuid.UUID,
    title: str,
    content: str = "",
    type: str = "system",
    related_url: str | None = None,
    db: AsyncSession | None = None,
) -> Notification:
    """
    创建一条站内通知（供其它模块复用，例如门禁失败、任务完成推送）。

    Args:
        user_id: 接收者用户 ID。
        title: 通知标题。
        content: 通知正文。
        type: 通知类型（system / test / defect / gate）。
        related_url: 点击跳转地址。
        db: 数据库会话，为 None 时自动创建独立会话并提交。

    Returns:
        创建的 Notification 对象。
    """
    from app.utils.database import AsyncSessionLocal

    async def _create(session: AsyncSession) -> Notification:
        item = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
            content=content,
            type=type,
            is_read=False,
            related_url=related_url,
            created_at=datetime.utcnow(),
        )
        session.add(item)
        await session.flush()
        return item

    if db is not None:
        return await _create(db)

    async with AsyncSessionLocal() as session:
        item = await _create(session)
        await session.commit()
        return item


# ==================== API 路由 ====================


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False, description="仅返回未读通知"),
    limit: int = Query(100, ge=1, le=500),
    is_read: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取当前用户的通知列表，按 created_at 倒序。

    Returns:
        {"items": [...], "total": int, "unread_count": int}
    """
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only or is_read is False:
        stmt = stmt.where(Notification.is_read.is_(False))
    elif is_read is True:
        stmt = stmt.where(Notification.is_read.is_(True))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    size = page_size or limit
    stmt = stmt.order_by(Notification.created_at.desc()).offset((page - 1) * size).limit(size)

    result = await db.execute(stmt)
    items = [_notification_to_dict(n) for n in result.scalars().all()]

    # 未读总数（不受 unread_only / limit 影响）
    unread_result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )
    unread_count = int(unread_result.scalar() or 0)

    return {
        "code": 0,
        "data": {
            "items": items,
            "list": items,
            "total": total, "page": page, "page_size": size,
            "unread_count": unread_count,
        },
        "message": "success",
    }


@router.get("/preferences")
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    row = (await db.execute(select(UserPreference).where(UserPreference.user_id == current_user.id))).scalar_one_or_none()
    data = row.notification_config if row else {
        "enabled": True, "channels": ["in_app"], "quiet_enabled": False,
        "quiet_start": "22:00", "quiet_end": "08:00",
    }
    return {"code": 0, "data": data, "message": "success"}


@router.put("/preferences")
async def update_notification_preferences(
    req: NotificationPreferenceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    allowed = {"in_app", "email", "webhook", "dingtalk"}
    if any(channel not in allowed for channel in req.channels):
        raise HTTPException(422, "通知渠道不受支持")
    row = (await db.execute(select(UserPreference).where(UserPreference.user_id == current_user.id))).scalar_one_or_none()
    if row is None:
        row = UserPreference(user_id=current_user.id)
        db.add(row)
    row.notification_config = req.model_dump()
    row.updated_at = datetime.utcnow()
    await db.flush()
    return {"code": 0, "data": row.notification_config, "message": "通知偏好已保存"}


@router.post("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """将当前用户的全部未读通知标记为已读。"""
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )
    items = result.scalars().all()
    for item in items:
        item.is_read = True

    logger.info(
        f"Marked {len(items)} notification(s) as read for {current_user.username}"
    )

    return {
        "code": 0,
        "data": {"updated": len(items)},
        "message": "全部已读",
    }


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """标记单条通知为已读。"""
    item = await _get_owned_notification(notification_id, current_user, db)
    item.is_read = True

    return {
        "code": 0,
        "data": _notification_to_dict(item),
        "message": "已标记为已读",
    }


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """删除单条通知。"""
    item = await _get_owned_notification(notification_id, current_user, db)
    await db.delete(item)

    logger.info(
        f"Notification deleted: {notification_id} by {current_user.username}"
    )

    return {
        "code": 0,
        "data": {"id": notification_id},
        "message": "删除成功",
    }
