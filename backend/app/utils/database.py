"""
数据库会话管理 — 异步 SQLAlchemy 引擎与会话工厂

提供：
- async_engine: 异步数据库引擎
- AsyncSessionLocal: 异步会话工厂
- get_db_session(): FastAPI 依赖注入函数
- get_sync_engine(): 同步引擎（用于 Alembic 迁移等场景）
"""

from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from loguru import logger

from app.config import settings


# ==================== 异步引擎与会话工厂 ====================

async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.APP_DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# ==================== 同步引擎（Alembic 迁移 / 脚本用） ====================

sync_engine = create_engine(
    settings.database_url,
    echo=settings.APP_DEBUG,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ==================== 同步引擎（Alembic 迁移 / 脚本用） ====================
# 已在上方统一创建


# ==================== FastAPI 依赖注入 ====================

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入 — 提供异步数据库会话。

    使用方式::

        from fastapi import Depends
        from app.utils.database import get_db_session

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db_session)):
            result = await db.execute(select(Item))
            return result.scalars().all()

    Yields:
        AsyncSession: 异步数据库会话，请求结束后自动关闭。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ==================== 引擎管理 ====================

async def dispose_engine() -> None:
    """关闭异步引擎连接池（应用关闭时调用）。"""
    await async_engine.dispose()
    sync_engine.dispose()
    logger.info("Database engine connection pools disposed")
