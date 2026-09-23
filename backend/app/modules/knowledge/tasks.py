"""知识库全量重建 Celery 任务。需加入 celery_app.py 的 include。"""
import asyncio
from datetime import datetime

from loguru import logger

from app.celery_app import celery_app
from app.utils.database import AsyncSessionLocal
from app.modules.knowledge.embedder import rebuild_kb_type
from app.modules.knowledge.retriever import get_rebuild_state, set_rebuild_state


@celery_app.task(name="app.modules.knowledge.tasks.rebuild_knowledge_base", bind=True)
def rebuild_knowledge_base(
    self, kb_type: str | None = None, force_full: bool = False
) -> dict:
    """触发指定 kb_type（或 None=全部）的重建（增量/全量）。

    force_full=False 走增量（默认），True 走全量清空重插。
    内部 asyncio.run(_rebuild(kb_type, force_full))。
    """
    return asyncio.run(_rebuild(kb_type, force_full))


@celery_app.task(name="app.modules.knowledge.tasks.process_knowledge_document", bind=True)
def process_knowledge_document(self, doc_id: str) -> dict:
    """索引单个知识文档（解析→章节切片→嵌入→入库）。

    文档上传/重新索引后由 API 派发；状态流转 parsing→indexed/failed 落在
    knowledge_documents.status，前端通过列表/详情轮询。
    """
    import uuid as _uuid

    return asyncio.run(_process_document(_uuid.UUID(doc_id)))


async def _process_document(doc_id) -> dict:
    from app.modules.knowledge.document_indexer import index_document
    from app.modules.ai.model_router import refresh_model_router_for_worker

    async with AsyncSessionLocal() as db:
        # Celery 子进程拥有独立内存，API 进程内的模型配置更新不会同步过来；
        # 同时每个 asyncio.run() 都会创建新事件循环，不能复用上次任务的异步客户端。
        # 因此文档索引必须在每次任务开始时从数据库刷新路由并重建客户端。
        await refresh_model_router_for_worker(db)
        return await index_document(db, doc_id)


@celery_app.task(name="app.modules.knowledge.tasks.auto_sync_knowledge")
def auto_sync_knowledge() -> dict:
    """知识自动同步 — Celery Beat 每日派发，增量重建 defect/case/doc/term 四类切片。

    经验闭环的最后一环：新产生的缺陷/用例/接口资产无需管理员手动点「一键重建」，
    每日凌晨自动增量入知识库（内容哈希 diff，只重算变更项，嵌入配额消耗极小）。
    知识文档（document 类）不走此任务——它们在上传/重新索引时即时索引。

    守卫：手动重建进行中（state==running 且未卡死）则跳过本轮，避免并发重建。
    """
    return asyncio.run(_auto_sync())


async def _auto_sync() -> dict:
    from datetime import datetime

    from app.modules.knowledge.retriever import get_rebuild_state

    try:
        async with AsyncSessionLocal() as s:
            state = await get_rebuild_state(s)
        if state.get("state") == "running":
            updated = state.get("updated_at")
            recent = True
            if updated:
                try:
                    upd = datetime.fromisoformat(updated)
                    # 与 API 侧一致的卡死判定（1 小时）：卡死则放行自动重建
                    recent = (datetime.utcnow() - upd).total_seconds() < 3600
                except Exception:  # noqa: BLE001
                    recent = True
            if recent:
                return {"status": "skipped", "reason": "manual rebuild in progress"}
        return await _rebuild(None, force_full=False)
    except Exception as exc:  # noqa: BLE001 - 定时任务失败不影响主流程
        logger.exception(f"KB auto sync failed: {exc}")
        return {"status": "error", "error": str(exc)}


async def _rebuild(kb_type: str | None, force_full: bool = False) -> dict:
    """全量重建逻辑（在 Celery Worker 进程内运行）。

    重活必须在 Celery 里，API 只 .delay()，避免阻塞 FastAPI 事件循环。
    """
    types = [kb_type] if kb_type else ["defect", "case", "doc", "term"]
    total = 0
    started = datetime.utcnow()

    # 标记运行中（独立 session，立即落库，前端可立即看到 state=running）
    async with AsyncSessionLocal() as s:
        await set_rebuild_state(s, "running", updated_at=started, error=None)

    try:
        async with AsyncSessionLocal() as db:
            # 模型配置和路由由 API 进程写入数据库，Celery Worker 的全局路由并不会
            # 自动更新。逐任务刷新也能避免异步 HTTP 客户端跨 event loop 复用。
            from app.modules.ai.model_router import refresh_model_router_for_worker

            await refresh_model_router_for_worker(db)
            for t in types:
                n = await rebuild_kb_type(db, t, force_full=force_full)
                total += n
            await db.commit()
        finished = datetime.utcnow()
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
