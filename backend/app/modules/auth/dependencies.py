"""
FastAPI 依赖注入 — 认证与权限校验

提供：
- get_current_user: 从请求头解析 JWT，返回当前用户
- require_role: 角色权限校验依赖工厂
"""

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import User, UserRole
from app.modules.auth.auth_service import AuthService
from app.utils.database import get_db_session

# ==================== OAuth2 方案（简化版） ====================


def _extract_token(request: Request) -> str | None:
    """
    从请求头提取 Bearer token。

    支持 Authorization: Bearer <token> 格式。
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """
    FastAPI 依赖 — 获取当前登录用户。

    从 Authorization 请求头解析 JWT，验证并返回 User 对象。

    Raises:
        HTTPException(401): 未提供 token 或 token 无效。
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = AuthService.verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: missing subject",
        )

    user = await AuthService.get_user_by_id(user_id, db)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_role(*allowed_roles: UserRole) -> Callable:
    """
    FastAPI 依赖工厂 — 角色权限校验。

    用法::

        @router.delete("/{id}")
        async def delete_resource(
            user: User = Depends(require_role(UserRole.ADMIN)):
            ...
        )

    Args:
        allowed_roles: 允许访问的角色列表。

    Returns:
        FastAPI 依赖函数。
    """

    async def _check_role(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Permission denied: role '{current_user.role.value}' "
                    f"is not allowed. Required: "
                    f"{', '.join(r.value for r in allowed_roles)}"
                ),
            )
        return current_user

    return _check_role


# ==================== 便捷别名 ====================

require_admin = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)
require_tester = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TESTER)
require_developer = require_role(
    UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TESTER, UserRole.DEVELOPER
)

# 管理类操作（用户 CRUD / 角色变更）：super_admin 立即生效，admin 需走审批
require_manager = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)

# 审批类操作（通过 / 驳回变更申请）
require_reviewer = require_role(UserRole.SUPER_ADMIN, UserRole.AUDITOR)
