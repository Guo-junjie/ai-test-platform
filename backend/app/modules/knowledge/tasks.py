"""知识库全量重建 Celery 任务。需加入 celery_app.py 的 include。"""
import asyncio
from datetime import datetime, timezone

from loguru import logger

from app.celery_app import celery_app
from app.utils.database import AsyncSessionLocal
from app.modules.knowledge.embedder import rebuild_kb_type
from app.modules.knowledge.retriever import get_rebuild_state, set_rebuild_state


@celery_app.task(name="app.modules.knowledge.tasks.rebuild_knowledge_base", bind=True)
def rebuild_knowledge_base(self, kb_type: str | None = None) -> dict:
    """触发指定 kb_type（或 None=全部）的全量重建。

    内部 asyncio.run(_rebuild(kb_type))。
    """
    return asyncio.run(_rebuild(kb_type))


async def _rebuild(kb_type: str | None) -> dict:
    """全量重建逻辑（在 Celery Worker 进程内运行）。

    重活必须在 Celery 里，API 只 .delay()，避免阻塞 FastAPI 事件循环。
    """
    types = [kb_type] if kb_type else ["defect", "case", "doc", "term"]
    total = 0
    started = datetime.now(timezone.utc)

    # 标记运行中（独立 session，立即落库，前端可立即看到 state=running）
    async with AsyncSessionLocal() as s:
        await set_rebuild_state(s, "running", updated_at=started, error=None)

    try:
        async with AsyncSessionLocal() as db:
            for t in types:
                n = await rebuild_kb_type(db, t)
                total += n
            await db.commit()
        finished = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as s:
            await set_rebuild_state(
                s,
                "idle",
                last_rebuild=finished,
                last_rebuild_chunks=total,
                error=None,
            )
        logger.info(f"KB rebuild finished: types={types} chunks={total}")
        return {"kb_type": kb_type or "all", "chunks": total, "state": "idle"}
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"KB rebuild failed: {exc}")
        async with AsyncSessionLocal() as s:
            await set_rebuild_state(s, "failed", error=str(exc)[:500])
        return {
            "kb_type": kb_type or "all",
            "chunks": total,
            "state": "failed",
            "error": str(exc),
        }
