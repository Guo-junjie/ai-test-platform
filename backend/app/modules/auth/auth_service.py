"""
用户认证服务 — JWT 签发/验证、密码哈希、用户 CRUD

使用 python-jose 签发 JWT，passlib[bcrypt] 哈希密码。
支持四种角色：admin / tester / developer / viewer。
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import User, UserRole
from app.utils.database import AsyncSessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ==================== 常量 ====================

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# 密码哈希上下文
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """
    用户认证服务。

    提供 JWT 签发/验证、密码哈希/校验、用户创建/查询等核心功能。
    所有方法均为 async，使用 AsyncSession 操作数据库。
    """

    # ==================== JWT 操作 ====================

    @staticmethod
    def create_access_token(
        user_id: str,
        username: str,
        role: str,
        expires_hours: int = JWT_EXPIRE_HOURS,
    ) -> str:
        """
        签发 JWT access token。

        Args:
            user_id: 用户 ID。
            username: 用户名。
            role: 用户角色。
            expires_hours: 过期时间（小时），默认 24 小时。

        Returns:
            编码后的 JWT 字符串。
        """
        payload: dict[str, Any] = {
            "sub": user_id,
            "username": username,
            "role": role,
            "exp": datetime.utcnow() + timedelta(hours=expires_hours),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> dict[str, Any] | None:
        """
        验证 JWT token 并返回 payload。

        Args:
            token: JWT 字符串。

        Returns:
            解码后的 payload 字典，验证失败返回 None。
        """
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except JWTError as e:
            logger.warning(f"JWT verification failed: {e}")
            return None

    # ==================== 密码操作 ====================

    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码（bcrypt）。"""
        return _pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证明文密码与哈希密码是否匹配。"""
        return _pwd_context.verify(plain_password, hashed_password)

    # ==================== 用户 CRUD ====================

    @staticmethod
    async def create_user(
        username: str,
        email: str,
        password: str,
        role: UserRole = UserRole.VIEWER,
        db: AsyncSession | None = None,
    ) -> User:
        """
        创建新用户。

        Args:
            username: 用户名（唯一）。
            email: 邮箱（唯一）。
            password: 明文密码（将自动哈希）。
            role: 用户角色，默认 viewer。
            db: 数据库会话，为 None 时自动创建。

        Returns:
            创建的 User 对象。

        Raises:
            ValueError: 用户名或邮箱已存在。
        """
        async def _create(session: AsyncSession) -> User:
            # 检查用户名是否已存在
            existing = await session.execute(
                select(User).where(User.username == username)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Username '{username}' already exists")

            # 检查邮箱是否已存在
            existing = await session.execute(
                select(User).where(User.email == email)
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Email '{email}' already exists")

            user = User(
                id=uuid.uuid4(),
                username=username,
                email=email,
                hashed_password=AuthService.hash_password(password),
                role=role,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"User created: {username} ({role.value})")
            return user

        if db is not None:
            return await _create(db)
        async with AsyncSessionLocal() as session:
            return await _create(session)

    @staticmethod
    async def authenticate_user(
        username: str,
        password: str,
        db: AsyncSession,
    ) -> User | None:
        """
        验证用户凭据。

        Args:
            username: 用户名。
            password: 明文密码。
            db: 数据库会话。

        Returns:
            验证成功返回 User 对象，失败返回 None。
        """
        result = await db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()

        if user is None or not user.is_active:
            return None

        if not AuthService.verify_password(password, user.hashed_password):
            return None

        return user

    @staticmethod
    async def get_user_by_id(user_id: str, db: AsyncSession) -> User | None:
        """根据 ID 查询用户。"""
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return None

        result = await db.execute(select(User).where(User.id == uid))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(username: str, db: AsyncSession) -> User | None:
        """根据用户名查询用户。"""
        result = await db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_users(
        page: int = 1,
        page_size: int = 20,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        分页查询用户列表。

        Returns:
            {"list": [...], "total": int, "page": int, "page_size": int}
        """
        async def _list(session: AsyncSession) -> dict[str, Any]:
            offset = (page - 1) * page_size
            result = await session.execute(
                select(User)
                .order_by(User.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            users = result.scalars().all()

            count_result = await session.execute(select(User))
            total = len(count_result.scalars().all())

            return {
                "list": [
                    {
                        "id": str(u.id),
                        "username": u.username,
                        "email": u.email,
                        "role": u.role.value if u.role else "viewer",
                        "is_active": u.is_active,
                        "created_at": u.created_at.isoformat() if u.created_at else None,
                    }
                    for u in users
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        if db is not None:
            return await _list(db)
        async with AsyncSessionLocal() as session:
            return await _list(session)

    @staticmethod
    async def update_user_role(
        user_id: str,
        role: UserRole,
        db: AsyncSession,
    ) -> User | None:
        """更新用户角色。"""
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            return None

        result = await db.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if user is None:
            return None

        user.role = role
        await db.commit()
        await db.refresh(user)
        logger.info(f"User role updated: {user.username} -> {role.value}")
        return user

    # ==================== 初始化默认管理员 ====================

    @staticmethod
    async def init_default_admin() -> None:
        """
        初始化默认管理员账户。

        在应用启动时调用，如果 users 表为空则创建默认 admin 账户。
        默认凭据: admin / admin123
        """
        async with AsyncSessionLocal() as session:
            # 检查是否已有用户
            result = await session.execute(select(User).limit(1))
            if result.scalar_one_or_none() is not None:
                return

            admin = User(
                id=uuid.uuid4(),
                username="admin",
                email="admin@ai-test-platform.local",
                hashed_password=AuthService.hash_password("admin123"),
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            logger.info("Default admin user created (admin / admin123)")

    @staticmethod
    def user_to_dict(user: User) -> dict[str, Any]:
        """将 User 对象序列化为字典（不含密码）。"""
        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role.value if user.role else "viewer",
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
