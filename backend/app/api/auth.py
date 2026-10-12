"""
用户认证 API 路由

提供：
- POST /login — 用户登录（返回 JWT token）
- POST /register、POST /users — 新建用户（管理员直接创建普通业务账号）
- GET /me — 获取当前用户信息
- GET /users — 用户列表（管理员）
- PUT /users/{user_id}/role — 更新用户角色（特权角色仅超级管理员可授予）
- DELETE /users/{user_id} — 删除用户（有关联运行时自动软删除）
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import PersonalAccessToken, TestRun, User, UserRole
from app.modules.auth.auth_service import AuthService
from app.modules.auth.dependencies import get_current_user, require_manager
from app.modules.audit.audit_service import AuditService
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 请求模型 ====================


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    email: str
    password: str
    # super_admin / admin / test_manager / tester / developer / viewer
    role: str = "viewer"


class UpdateRoleRequest(BaseModel):
    """更新角色请求"""
    # super_admin / admin / test_manager / tester / developer / viewer
    role: str


class UpdateProfileRequest(BaseModel):
    """更新个人资料请求 — 字段为 None 表示不修改"""
    email: str | None = None
    username: str | None = None


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


class UpdateStatusRequest(BaseModel):
    """更新用户启用/禁用状态请求"""
    is_active: bool


class CreatePersonalTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)
    scopes: list[str] = Field(default_factory=lambda: ["api"])


# ==================== 共享助手 ====================

VALID_ROLE_HINT = (
    "super_admin/admin/test_manager/tester/developer/viewer"
)
STANDARD_ROLES = {
    UserRole.TEST_MANAGER,
    UserRole.TESTER,
    UserRole.DEVELOPER,
    UserRole.VIEWER,
}
PRIVILEGED_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.AUDITOR}


def _validate_managed_role(actor: User, role: UserRole) -> None:
    """管理员只能授予普通业务角色；审核员仅作为历史兼容角色保留。"""
    if role == UserRole.AUDITOR:
        raise HTTPException(400, "审核员已退出默认角色体系，不能再新建或授予")
    if actor.role == UserRole.ADMIN and role not in STANDARD_ROLES:
        raise HTTPException(403, "管理员只能授予测试经理、测试人员、开发人员或只读用户角色")


def _validate_managed_target(actor: User, target: User) -> None:
    """普通管理员不能管理管理员、超级管理员或历史合规审计账号。"""
    if actor.role == UserRole.ADMIN and target.role in PRIVILEGED_ROLES:
        raise HTTPException(403, "管理员不能管理特权账号")


async def apply_delete_user(session: AsyncSession, uid: uuid.UUID) -> dict[str, Any]:
    """
    落地删除用户操作。

    有运行或其他业务历史引用时仅停用账号，保留缺陷责任人与审计历史。

    Args:
        session: 数据库会话。
        uid: 目标用户 ID。

    Returns:
        {"id": str, "username": str, "deleted": bool, "soft": bool}

    Raises:
        HTTPException(404): 用户不存在。
    """
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(404, f"用户不存在: {uid}")

    username = user.username

    run_result = await session.execute(
        select(TestRun.id).where(TestRun.user_id == uid).limit(1)
    )
    has_runs = run_result.scalar_one_or_none() is not None

    if has_runs:
        user.is_active = False
        await session.flush()
        logger.info(f"User soft-deleted (has test runs): {username}")
        return {"id": str(uid), "username": username, "deleted": True, "soft": True}

    try:
        async with session.begin_nested():
            await session.delete(user)
            await session.flush()
    except IntegrityError as failure:
        if getattr(failure.orig, "sqlstate", None) != "23503" and getattr(failure.orig, "sqlite_errorcode", None) != 787:
            raise
        user = (await session.execute(select(User).where(User.id == uid))).scalar_one()
        user.is_active = False
        await session.flush()
        logger.info(f"User deactivated (business history retained): {username}")
        return {"id": str(uid), "username": username, "deleted": True, "soft": True}
    logger.info(f"User hard-deleted: {username}")
    return {"id": str(uid), "username": username, "deleted": True, "soft": False}


# ==================== API 路由 ====================


@router.post("/login")
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """
    用户登录。

    验证用户名和密码，返回 JWT access token。

    Returns:
        {"token": str, "token_type": "bearer", "user": {...}}
    """
    user = await AuthService.authenticate_user(req.username, req.password, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = AuthService.create_access_token(
        user_id=str(user.id),
        username=user.username,
        role=user.role.value if user.role else "viewer",
    )

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(user.id),
        action="login",
        resource_type="auth",
        resource_id=str(user.id),
        details={"username": user.username},
        ip_address=ip,
    )

    logger.info(f"User logged in: {user.username}")

    return {
        "code": 0,
        "data": {
            "token": token,
            "token_type": "bearer",
            "user": AuthService.user_to_dict(user),
        },
        "message": "登录成功",
    }


@router.post("/register")
@router.post("/users")
async def register(
    req: RegisterRequest,
    request: Request,
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """
    新建用户。

    管理员创建普通业务账号立即生效；特权角色只能由超级管理员授予。

    Args:
        req: 注册请求（用户名、邮箱、密码、角色）。
    """
    # 解析角色
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"无效的角色: {req.role}。可选: {VALID_ROLE_HINT}")
    _validate_managed_role(current_user, role)

    if len(req.password.encode("utf-8")) > 72:
        raise HTTPException(400, "密码过长，bcrypt 限制明文不超过 72 字节")

    ip = request.client.host if request.client else None

    try:
        user = await AuthService.create_user(
            username=req.username, email=req.email, password=req.password, role=role, db=db,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    await AuditService.log_action(
        user_id=str(current_user.id),
        action="register_user",
        resource_type="user",
        resource_id=str(user.id),
        details={"username": req.username, "role": req.role},
        ip_address=ip,
    )

    logger.info(
        f"User registered: {req.username} by {current_user.username}"
    )

    return {
        "code": 0,
        "data": AuthService.user_to_dict(user),
        "message": "用户创建成功",
    }


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """获取当前登录用户信息。"""
    return {
        "code": 0,
        "data": AuthService.user_to_dict(current_user),
        "message": "success",
    }


@router.put("/me")
async def update_me(
    req: UpdateProfileRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    更新当前登录用户的个人资料（用户名 / 邮箱）。

    仅更新请求中非 None 的字段，并校验用户名、邮箱的唯一性。
    """
    changed: dict[str, Any] = {}

    if req.username is not None:
        new_username = req.username.strip()
        if not new_username:
            raise HTTPException(400, "用户名不能为空")
        if new_username != current_user.username:
            existing = await db.execute(
                select(User).where(User.username == new_username)
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(400, f"用户名已存在: {new_username}")
            current_user.username = new_username
            changed["username"] = new_username

    if req.email is not None:
        new_email = req.email.strip()
        if not new_email or "@" not in new_email:
            raise HTTPException(400, f"无效的邮箱地址: {req.email}")
        if new_email != current_user.email:
            existing = await db.execute(
                select(User).where(User.email == new_email)
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(400, f"邮箱已被占用: {new_email}")
            current_user.email = new_email
            changed["email"] = new_email

    await db.flush()
    await db.refresh(current_user)

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_profile",
        resource_type="user",
        resource_id=str(current_user.id),
        details=changed,
        ip_address=ip,
    )

    logger.info(f"User profile updated: {current_user.username} changed={list(changed)}")

    return {
        "code": 0,
        "data": AuthService.user_to_dict(current_user),
        "message": "个人资料更新成功",
    }


@router.put("/me/password")
async def change_my_password(
    req: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    修改当前登录用户的密码。

    校验旧密码后写入新密码哈希。bcrypt 限制明文最长 72 字节，超长直接拒绝。
    """
    if not AuthService.verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(400, "原密码不正确")

    new_password = req.new_password
    if len(new_password) < 6:
        raise HTTPException(400, "新密码长度不能少于 6 位")
    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(400, "新密码过长，bcrypt 限制明文不超过 72 字节")
    if new_password == req.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")

    current_user.hashed_password = AuthService.hash_password(new_password)
    await db.flush()

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="change_password",
        resource_type="user",
        resource_id=str(current_user.id),
        details={"username": current_user.username},
        ip_address=ip,
    )

    logger.info(f"User password changed: {current_user.username}")

    return {
        "code": 0,
        "data": {"id": str(current_user.id)},
        "message": "密码修改成功，请重新登录",
    }


@router.get("/me/tokens")
async def list_personal_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    rows = (await db.execute(select(PersonalAccessToken).where(
        PersonalAccessToken.user_id == current_user.id,
    ).order_by(PersonalAccessToken.created_at.desc()))).scalars().all()
    return {"code": 0, "data": {"items": [{
        "id": str(row.id), "name": row.name, "prefix": row.prefix, "scopes": row.scopes or [],
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]}, "message": "success"}


@router.post("/me/tokens")
async def create_personal_token(
    req: CreatePersonalTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    raw_token = f"atp_{secrets.token_urlsafe(32)}"
    item = PersonalAccessToken(
        user_id=current_user.id, name=req.name.strip(), prefix=raw_token[:12],
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(), scopes=req.scopes,
        expires_at=datetime.utcnow() + timedelta(days=req.expires_in_days) if req.expires_in_days else None,
    )
    db.add(item)
    await db.flush()
    return {"code": 0, "data": {"id": str(item.id), "name": item.name, "token": raw_token,
        "prefix": item.prefix, "expires_at": item.expires_at.isoformat() if item.expires_at else None},
        "message": "Token 已生成，请立即复制；关闭后无法再次查看明文"}


@router.delete("/me/tokens/{token_id}")
async def revoke_personal_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        tid = uuid.UUID(token_id)
    except ValueError as exc:
        raise HTTPException(422, "Token ID 格式错误") from exc
    item = (await db.execute(select(PersonalAccessToken).where(
        PersonalAccessToken.id == tid, PersonalAccessToken.user_id == current_user.id,
    ))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Token 不存在")
    item.revoked_at = datetime.utcnow()
    await db.flush()
    return {"code": 0, "data": {"id": token_id}, "message": "Token 已吊销"}


@router.get("/users")
async def list_users(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """获取用户列表（管理员 / 超级管理员）。"""
    result = await AuthService.list_users(page, page_size, db)

    return {
        "code": 0,
        "data": result,
        "message": "success",
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """
    删除用户。

    管理员可直接删除普通业务账号；有关联测试任务时自动软删除。

    禁止删除自己，禁止删除超级管理员。
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, f"Invalid user_id: {user_id}")

    if uid == current_user.id:
        raise HTTPException(400, "不能删除自己")

    target = await AuthService.get_user_by_id(user_id, db)
    if target is None:
        raise HTTPException(404, f"用户不存在: {user_id}")
    _validate_managed_target(current_user, target)
    if target.role == UserRole.SUPER_ADMIN:
        raise HTTPException(400, "不能删除超级管理员")

    ip = request.client.host if request.client else None

    result = await apply_delete_user(db, uid)

    await AuditService.log_action(
        user_id=str(current_user.id),
        action="delete_user",
        resource_type="user",
        resource_id=user_id,
        details=result,
        ip_address=ip,
    )

    logger.info(
        f"User deleted: {result['username']} by {current_user.username}"
    )

    return {
        "code": 0,
        "data": result,
        "message": "用户已删除",
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    req: UpdateRoleRequest,
    request: Request,
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """
    更新用户角色。

    角色变更立即生效；普通管理员不能管理或授予特权角色。
    """
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"无效的角色: {req.role}。可选: {VALID_ROLE_HINT}")
    _validate_managed_role(current_user, role)

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, f"Invalid user_id: {user_id}")

    ip = request.client.host if request.client else None

    target = await AuthService.get_user_by_id(user_id, db)
    if target is None:
        raise HTTPException(404, f"用户不存在: {user_id}")
    if uid == current_user.id:
        raise HTTPException(400, "不能修改自己的角色")
    _validate_managed_target(current_user, target)
    user = await AuthService.update_user_role(user_id, role, db)

    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_user_role",
        resource_type="user",
        resource_id=user_id,
        details={"target_user_id": user_id, "new_role": req.role},
        ip_address=ip,
    )

    logger.info(
        f"User role updated: {target.username} -> {req.role} "
        f"by {current_user.username}"
    )

    return {
        "code": 0,
        "data": AuthService.user_to_dict(user),
        "message": "角色更新成功",
    }


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    req: UpdateStatusRequest,
    request: Request,
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """
    启用 / 禁用用户（管理员 / 超级管理员）。

    状态切换可逆、风险低，不走审批流，立即生效。
    更新用户的 is_active 标志，并写入审计日志。
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, f"Invalid user_id: {user_id}")

    user = await AuthService.get_user_by_id(user_id, db)
    if user is None:
        raise HTTPException(404, f"用户不存在: {user_id}")
    if uid == current_user.id:
        raise HTTPException(400, "不能启用或禁用自己")
    _validate_managed_target(current_user, user)

    user.is_active = req.is_active
    await db.flush()
    await db.refresh(user)

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_user_status",
        resource_type="user",
        resource_id=user_id,
        details={"is_active": req.is_active},
        ip_address=ip,
    )

    logger.info(
        f"User status updated: {user.username} -> is_active={req.is_active} "
        f"by {current_user.username}"
    )

    return {
        "code": 0,
        "data": AuthService.user_to_dict(user),
        "message": "用户状态更新成功",
    }


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
):
    """
    用户登出。

    JWT 是无状态的，客户端删除 token 即可。
    服务端记录审计日志。
    """
    logger.info(f"User logged out: {current_user.username}")

    return {
        "code": 0,
        "data": {},
        "message": "登出成功",
    }
