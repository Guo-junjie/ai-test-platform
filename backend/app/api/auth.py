"""
用户认证 API 路由

提供：
- POST /login — 用户登录（返回 JWT token）
- POST /register — 用户注册（仅管理员可调用）
- GET /me — 获取当前用户信息
- GET /users — 用户列表（仅管理员）
- PUT /users/{user_id}/role — 更新用户角色（仅管理员）
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import User, UserRole
from app.modules.auth.auth_service import AuthService
from app.modules.auth.dependencies import get_current_user, require_admin
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
    role: str = "viewer"  # admin / tester / developer / viewer


class UpdateRoleRequest(BaseModel):
    """更新角色请求"""
    role: str  # admin / tester / developer / viewer


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
async def register(
    req: RegisterRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    注册新用户（仅管理员可调用）。

    Args:
        req: 注册请求（用户名、邮箱、密码、角色）。
    """
    # 解析角色
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"无效的角色: {req.role}。可选: admin/tester/developer/viewer")

    try:
        user = await AuthService.create_user(
            username=req.username,
            email=req.email,
            password=req.password,
            role=role,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="register_user",
        resource_type="user",
        resource_id=str(user.id),
        details={"username": req.username, "role": req.role},
        ip_address=ip,
    )

    logger.info(f"User registered: {req.username} by {current_user.username}")

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


@router.get("/users")
async def list_users(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """获取用户列表（仅管理员）。"""
    result = await AuthService.list_users(page, page_size, db)

    return {
        "code": 0,
        "data": result,
        "message": "success",
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    req: UpdateRoleRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """更新用户角色（仅管理员）。"""
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"无效的角色: {req.role}")

    user = await AuthService.update_user_role(user_id, role, db)
    if user is None:
        raise HTTPException(404, f"用户不存在: {user_id}")

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_user_role",
        resource_type="user",
        resource_id=user_id,
        details={"username": user.username, "new_role": req.role},
        ip_address=ip,
    )

    logger.info(f"User role updated: {user.username} -> {req.role} by {current_user.username}")

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
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    启用 / 禁用用户（仅管理员）。

    更新用户的 is_active 标志，并写入审计日志。
    """
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, f"Invalid user_id: {user_id}")

    user = await AuthService.get_user_by_id(user_id, db)
    if user is None:
        raise HTTPException(404, f"用户不存在: {user_id}")

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
