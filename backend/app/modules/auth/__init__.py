"""
RBAC 用户认证与权限控制模块

提供：
- AuthService: 用户认证服务（JWT 签发/验证、密码哈希、用户 CRUD）
- get_current_user: FastAPI 依赖注入 — 获取当前登录用户
- require_role: FastAPI 依赖注入 — 角色权限校验
"""

from app.modules.auth.auth_service import AuthService
from app.modules.auth.dependencies import get_current_user, require_role

__all__ = ["AuthService", "get_current_user", "require_role"]
