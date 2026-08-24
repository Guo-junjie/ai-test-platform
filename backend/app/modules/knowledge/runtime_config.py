"""知识库运行时配置（KB_RAG_ENABLED 等可被前端实时切换的开关）。

设计要点：
    - env（KB_RAG_ENABLED）作为首次 fallback；前端切换写入 kb_runtime_config 表后，
      模块级缓存立即失效，最坏 5s 延迟内对所有进程可见。
    - 每个 Python 进程独立缓存（Worker 多进程不需要跨进程失效：env 是兜底，
      切换发生在前端与 API，前端是 Browser 单一连接、API 是 uvicorn 单进程，
      celery-worker 侧读次缓存不命中时查 DB 拿新值）。
    - 异常（全 DB 不可用）时 fallback 到 env，绝不阻塞主流程。

性能：
    - 默认 5s 缓存；缺陷分析 3 分支 + 用例生成 + 文档解析 2 分支共 6 调用点，
      缓存期间零额外 DB 开销；5s 过期后一次 DB 查（<5ms）。
"""
import time
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import KBRuntimeConfig


# 同步内存缓存（key -> (monotonic_ts, value_bool)）
_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 5.0  # 秒


# 已知 key 集中管理，避免散落字符串硬编码
KEY_KB_RAG_ENABLED = "kb_rag_enabled"


async def get_kb_rag_enabled(db: AsyncSession) -> bool:
    """读运行时开关（带 5s 缓存）。env 是首次 fallback。"""
    now = time.monotonic()
    cached = _CACHE.get(KEY_KB_RAG_ENABLED)
    if cached is not None and now - cached[0] < _CACHE_TTL:
        return bool(cached[1])

    value: bool
    try:
        row = (
            await db.execute(
                select(KBRuntimeConfig).where(KBRuntimeConfig.key == KEY_KB_RAG_ENABLED)
            )
        ).scalar_one_or_none()
        if row is None or row.value is None:
            value = bool(settings.KB_RAG_ENABLED)
        else:
            value = bool(row.value)
    except Exception as exc:  # noqa: BLE001
        value = bool(settings.KB_RAG_ENABLED)
        logger.warning(
            f"KB runtime config 读取失败，fallback 到 env: value={value}, err={exc}"
        )

    _CACHE[KEY_KB_RAG_ENABLED] = (now, value)
    return value


async def set_kb_rag_enabled(db: AsyncSession, value: bool) -> None:
    """写入运行时开关（前端切换调用）。立即失效缓存。"""
    row = (
        await db.execute(
            select(KBRuntimeConfig).where(KBRuntimeConfig.key == KEY_KB_RAG_ENABLED)
        )
    ).scalar_one_or_none()
    if row is None:
        row = KBRuntimeConfig(key=KEY_KB_RAG_ENABLED, value=value)
        db.add(row)
    else:
        row.value = value
    await db.commit()
    # 立即失效缓存（最多 5s 延迟对其他进程生效）
    _CACHE.pop(KEY_KB_RAG_ENABLED, None)


def clear_cache_for_tests() -> None:
    """清缓存：测试 / 紧急运维用。"""
    _CACHE.clear()