"""
数据库会话管理 — 异步 SQLAlchemy 引擎与会话工厂

提供：
- async_engine: 异步数据库引擎
- AsyncSessionLocal: 异步会话工厂（**proxy 对象**，始终从当前 engine 创建）
- get_db_session(): FastAPI 依赖注入函数
- get_sync_engine(): 同步引擎（用于 Alembic 迁移等场景）
- reset_async_engine(): 重建 async_engine + AsyncSessionLocal（Celery worker_process_init 用）
"""
import asyncio
from typing import AsyncGenerator, Optional

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from loguru import logger

from app.config import settings


# ==================== 异步引擎与会话工厂 ====================

async_engine: Optional[AsyncEngine] = create_async_engine(
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


# ==================== AsyncSessionLocal proxy ====================
# 关键设计：AsyncSessionLocal 是一个 module-level **proxy 对象**，
# 17 处 `from app.utils.database import AsyncSessionLocal` 拿到的都是**同一个 proxy**。
# proxy 内部始终从 `_current_async_engine` + `_current_session_maker` 拿最新值。
#
# 触发时机：
# 1. Celery worker_process_init signal：fork 子进程后，调用 reset_async_engine()
#    重建 engine + 替换 module attr；后续所有 `AsyncSessionLocal()` 自动用新 engine
# 2. FastAPI 启动：保持原状（无 fork，无需 reset）
# 3. 普通 `import`：拿到 proxy，不创建 session（懒加载）

_current_async_engine: Optional[AsyncEngine] = async_engine
_current_session_maker: Optional[async_sessionmaker] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class _AsyncSessionLocalProxy:
    """代理对象：始终从最新 module attr 创建 session。

    解决 Celery prefork + asyncpg "Future attached to a different loop" Bug：
    - 17 处 `from app.utils.database import AsyncSessionLocal` 拿到的都是**这个 proxy**
    - proxy 在调用时从 `_current_session_maker` 拿 sessionmaker；sessionmaker 内部
      bind 的 engine 是最新 reset 过的
    - worker_process_init 调用 reset_async_engine() 后，proxy 自动用新 engine
    - 不需要改任何 import 位置
    """

    def __call__(self, *args, **kwargs):
        """支持 `AsyncSessionLocal()` 调用，返回 session 实例（支持 `async with`）。"""
        if _current_session_maker is None:
            raise RuntimeError("AsyncSessionLocal not initialized — call reset_async_engine() first")
        return _current_session_maker(*args, **kwargs)

    def __getattr__(self, name):
        """透传 sessionmaker 的方法/属性（如 configure、kw 等）。"""
        if _current_session_maker is None:
            raise RuntimeError("AsyncSessionLocal not initialized — call reset_async_engine() first")
        return getattr(_current_session_maker, name)


# module-level 单一 proxy 对象；17 处 import 都拿到**同一个引用**
AsyncSessionLocal = _AsyncSessionLocalProxy()


# ==================== 引擎管理 ====================


async def dispose_engine() -> None:
    """关闭异步引擎连接池（应用关闭时调用）。"""
    global _current_async_engine, _current_session_maker
    if _current_async_engine is not None:
        await _current_async_engine.dispose()
    if sync_engine is not None:
        sync_engine.dispose()
    _current_async_engine = None
    _current_session_maker = None
    logger.info("Database engine connection pools disposed")


def reset_async_engine() -> None:
    """重建 async_engine + 同步替换 module attr（Celery worker_process_init 用）。

    关键
    ----
    Celery prefork 模式下，主进程创建 `async_engine` 单例 → fork → 子进程继承。
    子进程 `asyncio.run(...)` 创建新 event loop，但 asyncpg connection 内部的
    ``_loop`` 引用仍指向主进程 loop → "Future attached to a different loop"。

    ``dispose()`` 只关 connection pool，但 **engine 内部仍持有其他状态**。
    最稳的修法：**完全重建 engine** + **通过 proxy 让所有 import 自动拿新值**。

    子进程调用流程：
    1. worker_process_init 触发 reset_async_engine()
    2. 旧 engine 关闭（同步 dispose，因为没有可用 loop）
    3. 新 engine 创建（worker 子进程内全新的 engine + 全新的 pool）
    4. 新 sessionmaker 绑定新 engine
    5. module attr 替换完成；所有 `AsyncSessionLocal()` 自动用新值

    API 进程（FastAPI）无需调用本函数——主进程一次 fork 不存在此问题。
    """
    global _current_async_engine, _current_session_maker, async_engine, AsyncSessionLocal

    # 1) 关闭旧 engine（同步 dispose，兼容子进程内无 event loop 场景）
    if _current_async_engine is not None:
        try:
            _current_async_engine.sync_engine.dispose()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"reset_async_engine: dispose old engine failed (non-fatal): {exc}")

    # 2) 重建 engine。
    # 【必须用 NullPool】Celery 每个任务都是 asyncio.run() 新建 event loop，
    # QueuePool 会把上一个 loop 创建的 asyncpg 连接复用到下一个 loop，
    # 触发 "Future attached to a different loop"（pool_pre_ping 对 asyncpg 的
    # RuntimeError 不归类为断连，无法稳定自愈——部署机 2026-08-30 实锤：
    # scheduled_tick 与 process_knowledge_document 反复失败）。
    # NullPool 完全不复用连接，每个 loop 内新建/关闭，从根上消除该问题；
    # worker 任务频率低（30s tick + 偶发任务），无连接复用收益，性能无感。
    new_engine = create_async_engine(
        settings.async_database_url,
        echo=settings.APP_DEBUG,
        poolclass=NullPool,
    )

    # 3) 重建 sessionmaker 绑定新 engine
    new_session_maker = async_sessionmaker(
        bind=new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    # 4) 替换 module attr（**关键**：17 处 import 拿的 proxy 内部会自动用新值）
    _current_async_engine = new_engine
    _current_session_maker = new_session_maker
    async_engine = new_engine
    # AsyncSessionLocal 是 proxy 对象本身不变，**proxy 内部引用已变**

    logger.info(
        "reset_async_engine: 子进程已重建 async engine + sessionmaker，"
        "所有 AsyncSessionLocal() 调用将用新 engine。"
    )


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
