"""
变更审批 API 路由

管理类操作（新建用户 / 删除用户 / 修改角色）由 ADMIN 发起后落为 pending 的
ChangeRequest，需 AUDITOR 或 SUPER_ADMIN 审批：

- GET / — 审批列表（可按 status 过滤）
- POST /{cr_id}/approve — 通过并落地变更
- POST /{cr_id}/reject — 驳回
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import apply_delete_user
from app.models.database import ChangeRequest, Notification, User, UserRole
from app.modules.audit.audit_service import AuditService
from app.modules.auth.auth_service import AuthService
from app.modules.auth.dependencies import require_reviewer
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 注意：路径前缀统一在 main.py 注册时给出（prefix="/api/change-requests"），
# 此处不再重复声明 prefix，避免出现 /api/change-requests/change-requests。
router = APIRouter(tags=["审批"])


# ==================== 常量 ====================

TYPE_LABELS: dict[str, str] = {
    "create_user": "新建用户",
    "delete_user": "删除用户",
    "change_role": "修改角色",
}


# ==================== 请求模型 ====================


class RejectRequest(BaseModel):
    """驳回请求"""
    note: str | None = None


# ==================== 序列化 ====================


def cr_to_dict(
    cr: ChangeRequest,
    requested_by_username: str | None = None,
) -> dict[str, Any]:
    """
    将 ChangeRequest 序列化为字典。

    Args:
        cr: 变更申请对象。
        requested_by_username: 申请人用户名（可选，列表接口预查后传入）。

    Returns:
        前端契约要求的字段字典。
    """
    return {
        "id": str(cr.id),
        "type": cr.type,
        "type_label": TYPE_LABELS.get(cr.type, cr.type),
        "payload": cr.payload or {},
        "requested_by": str(cr.requested_by) if cr.requested_by else None,
        "requested_by_username": requested_by_username,
        "target_user_id": str(cr.target_user_id) if cr.target_user_id else None,
        "status": cr.status,
        "review_note": cr.review_note,
        "created_at": cr.created_at.isoformat() if cr.created_at else None,
        "reviewed_at": cr.reviewed_at.isoformat() if cr.reviewed_at else None,
    }


async def _get_username(db: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    """根据用户 ID 查询用户名，查不到返回 None。"""
    if user_id is None:
        return None
    result = await db.execute(select(User.username).where(User.id == user_id))
    return result.scalar_one_or_none()


async def _load_cr(db: AsyncSession, cr_id: str) -> ChangeRequest:
    """
    加载 pending 状态的变更申请。

    Raises:
        HTTPException(400): ID 非法或申请已被处理。
        HTTPException(404): 申请不存在。
    """
    try:
        rid = uuid.UUID(cr_id)
    except ValueError:
        raise HTTPException(400, f"Invalid change_request_id: {cr_id}")

    result = await db.execute(select(ChangeRequest).where(ChangeRequest.id == rid))
    cr = result.scalar_one_or_none()
    if cr is None:
        raise HTTPException(404, f"申请不存在: {cr_id}")
    if cr.status != "pending":
        raise HTTPException(400, f"该申请已处理: {cr.status}")
    return cr


# ==================== API 路由 ====================


@router.get("")
async def list_change_requests(
    status: str | None = None,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db_session),
):
    """
    列出变更申请（审核员 / 超级管理员）。

    Args:
        status: 可选状态过滤，pending / approved / rejected。
    """
    stmt = select(ChangeRequest).order_by(ChangeRequest.created_at.desc())
    if status:
        stmt = stmt.where(ChangeRequest.status == status)

    result = await db.execute(stmt)
    items = result.scalars().all()

    data: list[dict[str, Any]] = []
    username_cache: dict[uuid.UUID, str | None] = {}
    for cr in items:
        if cr.requested_by is not None and cr.requested_by not in username_cache:
            username_cache[cr.requested_by] = await _get_username(db, cr.requested_by)
        data.append(cr_to_dict(cr, username_cache.get(cr.requested_by)))

    return {
        "code": 0,
        "data": {"list": data, "total": len(data)},
        "message": "success",
    }


@router.post("/{cr_id}/approve")
async def approve_change_request(
    cr_id: str,
    request: Request,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db_session),
):
    """审批通过并落地变更（审核员 / 超级管理员）。"""
    cr = await _load_cr(db, cr_id)
    payload: dict[str, Any] = cr.payload or {}
    type_label = TYPE_LABELS.get(cr.type, cr.type)

    if cr.type == "create_user":
        # 校验唯一性，避免申请期间被抢注
        existing = await db.execute(
            select(User).where(User.username == payload.get("username"))
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(400, f"用户名已存在: {payload.get('username')}")
        existing = await db.execute(
            select(User).where(User.email == payload.get("email"))
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(400, f"邮箱已被占用: {payload.get('email')}")

        # 密码在提交申请时已哈希，此处直接落库，切勿二次哈希
        new_user = User(
            id=uuid.uuid4(),
            username=payload["username"],
            email=payload["email"],
            hashed_password=payload["hashed_password"],
            role=UserRole(payload["role"]),
            is_active=True,
        )
        db.add(new_user)
        await db.flush()

    elif cr.type == "delete_user":
        if cr.target_user_id is None:
            raise HTTPException(400, "申请缺少 target_user_id")
        await apply_delete_user(db, cr.target_user_id)

    elif cr.type == "change_role":
        if cr.target_user_id is None:
            raise HTTPException(400, "申请缺少 target_user_id")
        user = await AuthService.update_user_role(
            str(cr.target_user_id), UserRole(payload["role"]), db
        )
        if user is None:
            raise HTTPException(404, f"目标用户不存在: {cr.target_user_id}")

    else:
        raise HTTPException(400, f"未知的申请类型: {cr.type}")

    cr.status = "approved"
    cr.reviewed_by = current_user.id
    cr.reviewed_at = datetime.utcnow()

    if cr.requested_by is not None:
        db.add(
            Notification(
                id=uuid.uuid4(),
                user_id=cr.requested_by,
                title="审批通过",
                content=f"您的{type_label}申请已通过",
                type="system",
            )
        )

    await db.flush()

    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="approve_change_request",
        resource_type="change_request",
        resource_id=str(cr.id),
        details={"type": cr.type},
        ip_address=ip,
    )

    logger.info(f"ChangeRequest approved: {cr.id} ({cr.type}) by {current_user.username}")

    requested_by_username = await _get_username(db, cr.requested_by)
    return {
        "code": 0,
        "data": cr_to_dict(cr, requested_by_username),
        "message": "已通过",
    }


@router.post("/{cr_id}/reject")
async def reject_change_request(
    cr_id: str,
    req: RejectRequest,
    request: Request,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db_session),
):
    """驳回变更申请（审核员 / 超级管理员）。"""
    cr = await _load_cr(db, cr_id)
    type_label = TYPE_LABELS.get(cr.type, cr.type)

    cr.status = "rejected"
    cr.review_note = req.note
    cr.reviewed_by = current_user.id
    cr.reviewed_at = datetime.utcnow()

    if cr.requested_by is not None:
        db.add(
            Notification(
                id=uuid.uuid4(),
                user_id=cr.requested_by,
                title="申请被驳回",
                content=f"您的{type_label}申请被驳回：{req.note or '无'}",
                type="system",
            )
        )

    await db.flush()

    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="reject_change_request",
        resource_type="change_request",
        resource_id=str(cr.id),
        details={"type": cr.type, "note": req.note},
        ip_address=ip,
    )

    logger.info(f"ChangeRequest rejected: {cr.id} ({cr.type}) by {current_user.username}")

    requested_by_username = await _get_username(db, cr.requested_by)
    return {
        "code": 0,
        "data": cr_to_dict(cr, requested_by_username),
        "message": "已驳回",
    }
