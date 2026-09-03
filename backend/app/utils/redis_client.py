"""
Redis 客户端封装 — 任务状态存储与缓存操作

提供：
- get_redis(): 获取 Redis 连接（连接池模式）
- get_async_redis(): 获取异步 Redis 连接
- set_task_status() / get_task_status(): 测试任务状态管理
- cache_get() / cache_set() / cache_delete(): 通用缓存操作
"""

import json
from typing import Any, Optional

import redis.asyncio as aioredis
import redis
from loguru import logger

from app.config import settings


# ==================== 连接池初始化 ====================

_redis_pool: redis.ConnectionPool | None = None
_async_redis_pool: aioredis.ConnectionPool | None = None


def _build_redis_kwargs() -> dict[str, Any]:
    """构建 Redis 连接参数。"""
    kwargs: dict[str, Any] = {
        "host": settings.REDIS_HOST,
        "port": settings.REDIS_PORT,
        "db": 0,
        "decode_responses": True,
    }
    if settings.REDIS_PASSWORD:
        kwargs["password"] = settings.REDIS_PASSWORD
    return kwargs


def get_redis() -> redis.Redis:
    """
    获取同步 Redis 客户端（连接池复用）。

    Returns:
        redis.Redis: Redis 客户端实例。
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool(**_build_redis_kwargs())
        logger.info(
            f"Redis connection pool created: {settings.REDIS_HOST}:{settings.REDIS_PORT}"
        )
    return redis.Redis(connection_pool=_redis_pool)


def get_async_redis() -> aioredis.Redis:
    """
    获取异步 Redis 客户端（连接池复用）。

    Returns:
        aioredis.Redis: 异步 Redis 客户端实例。
    """
    global _async_redis_pool
    if _async_redis_pool is None:
        _async_redis_pool = aioredis.ConnectionPool(**_build_redis_kwargs())
        logger.info(
            f"Async Redis connection pool created: "
            f"{settings.REDIS_HOST}:{settings.REDIS_PORT}"
        )
    return aioredis.Redis(connection_pool=_async_redis_pool)


async def close_redis() -> None:
    """关闭 Redis 连接池（应用关闭时调用）。"""
    global _redis_pool, _async_redis_pool
    if _async_redis_pool is not None:
        await _async_redis_pool.disconnect()
        _async_redis_pool = None
    if _redis_pool is not None:
        _redis_pool.disconnect()
        _redis_pool = None
    logger.info("Redis connection pools closed")


# ==================== 任务状态管理 ====================

# 任务状态 Redis key 前缀
TASK_STATUS_PREFIX = "task:status:"
TASK_PROGRESS_PREFIX = "task:progress:"
TASK_RESULT_PREFIX = "task:result:"

# Celery worker 模式：async helper 内部委托同步客户端。
# worker 每任务一个新事件循环，asyncio 连接池跨 loop 复用会炸
# "Event loop is closed"（与 asyncpg 连接同款问题）；同步客户端无 loop
# 绑定，本地 redis 的阻塞开销（<1ms）完全可接受。
# 由 celery_app.worker_process_init → set_worker_redis_mode() 开启。
_WORKER_MODE = False


def set_worker_redis_mode() -> None:
    global _WORKER_MODE
    _WORKER_MODE = True

# 默认过期时间（7天）
DEFAULT_TTL = 7 * 24 * 3600


class _SyncAsAsync:
    """把同步 redis 客户端的方法包装为协程，让 async helper 无感切换。"""

    def __init__(self, sync_client):
        self._c = sync_client

    def __getattr__(self, name):
        fn = getattr(self._c, name)

        async def _call(*args, **kwargs):
            return fn(*args, **kwargs)

        return _call


def _task_redis():
    """worker 模式 → 同步客户端（包装为协程接口）；API 模式 → async 客户端。"""
    if _WORKER_MODE:
        return _SyncAsAsync(get_redis())
    return get_async_redis()

async def set_task_status(
    task_id: str,
    status: str,
    extra: dict[str, Any] | None = None,
    ttl: int = DEFAULT_TTL,
) -> None:
    """
    设置任务状态到 Redis。

    Args:
        task_id: 任务 ID（通常与 test_run_id 关联）。
        status: 任务状态（pending / pulling / analyzing / ... / completed / failed）。
        extra: 额外元数据（如当前步骤、错误信息等）。
        ttl: 过期时间（秒），默认 7 天。
    """
    client = _task_redis()
    data: dict[str, Any] = {"status": status}
    if extra:
        data.update(extra)
    await client.set(
        f"{TASK_STATUS_PREFIX}{task_id}",
        json.dumps(data, ensure_ascii=False),
        ex=ttl,
    )
    logger.debug(f"Task status updated: {task_id} -> {status}")


async def get_task_status(task_id: str) -> dict[str, Any] | None:
    """
    获取任务状态。

    Args:
        task_id: 任务 ID。

    Returns:
        任务状态字典，不存在时返回 None。
    """
    client = _task_redis()
    raw = await client.get(f"{TASK_STATUS_PREFIX}{task_id}")
    if raw is None:
        return None
    return json.loads(raw)


async def set_task_progress(
    task_id: str,
    progress: int,
    current_step: str = "",
    ttl: int = DEFAULT_TTL,
) -> None:
    """
    设置任务进度。

    Args:
        task_id: 任务 ID。
        progress: 进度百分比（0-100）。
        current_step: 当前执行步骤描述。
        ttl: 过期时间（秒）。
    """
    client = _task_redis()
    await client.set(
        f"{TASK_PROGRESS_PREFIX}{task_id}",
        json.dumps({"progress": progress, "step": current_step}, ensure_ascii=False),
        ex=ttl,
    )


async def get_task_progress(task_id: str) -> dict[str, Any] | None:
    """
    获取任务进度。

    Args:
        task_id: 任务 ID。

    Returns:
        包含 progress 和 step 的字典，不存在时返回 None。
    """
    client = _task_redis()
    raw = await client.get(f"{TASK_PROGRESS_PREFIX}{task_id}")
    if raw is None:
        return None
    return json.loads(raw)


async def set_task_result(
    task_id: str,
    result: dict[str, Any],
    ttl: int = DEFAULT_TTL,
) -> None:
    """
    存储任务最终结果到 Redis。

    Args:
        task_id: 任务 ID。
        result: 任务结果数据。
        ttl: 过期时间（秒）。
    """
    client = _task_redis()
    await client.set(
        f"{TASK_RESULT_PREFIX}{task_id}",
        json.dumps(result, ensure_ascii=False),
        ex=ttl,
    )


async def get_task_result(task_id: str) -> dict[str, Any] | None:
    """
    获取任务结果。

    Args:
        task_id: 任务 ID。

    Returns:
        任务结果字典，不存在时返回 None。
    """
    client = _task_redis()
    raw = await client.get(f"{TASK_RESULT_PREFIX}{task_id}")
    if raw is None:
        return None
    return json.loads(raw)


async def delete_task_data(task_id: str) -> None:
    """
    删除任务的所有 Redis 数据（状态、进度、结果）。

    Args:
        task_id: 任务 ID。
    """
    client = _task_redis()
    await client.delete(
        f"{TASK_STATUS_PREFIX}{task_id}",
        f"{TASK_PROGRESS_PREFIX}{task_id}",
        f"{TASK_RESULT_PREFIX}{task_id}",
    )
    logger.debug(f"Task data deleted from Redis: {task_id}")


# ==================== 通用缓存操作 ====================

CACHE_PREFIX = "cache:"


async def cache_get(key: str) -> Any | None:
    """
    从缓存获取数据（自动 JSON 反序列化）。

    Args:
        key: 缓存 key（不含前缀）。

    Returns:
        缓存数据，不存在时返回 None。
    """
    client = _task_redis()
    raw = await client.get(f"{CACHE_PREFIX}{key}")
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(
    key: str,
    value: Any,
    ttl: int = 3600,
) -> None:
    """
    设置缓存数据（自动 JSON 序列化）。

    Args:
        key: 缓存 key（不含前缀）。
        value: 要缓存的数据。
        ttl: 过期时间（秒），默认 1 小时。
    """
    client = _task_redis()
    await client.set(
        f"{CACHE_PREFIX}{key}",
        json.dumps(value, ensure_ascii=False),
        ex=ttl,
    )


async def cache_delete(key: str) -> None:
    """
    删除缓存数据。

    Args:
        key: 缓存 key（不含前缀）。
    """
    client = _task_redis()
    await client.delete(f"{CACHE_PREFIX}{key}")
