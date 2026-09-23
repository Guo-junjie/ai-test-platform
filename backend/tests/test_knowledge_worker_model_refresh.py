"""知识任务在 Celery 子进程中刷新模型路由的回归测试。"""

from unittest.mock import AsyncMock

import pytest

from app.modules.knowledge import tasks


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_rebuild_refreshes_worker_model_route_before_embedding(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: _SessionContext(session))
    monkeypatch.setattr(tasks, "set_rebuild_state", AsyncMock())

    events = []

    async def refresh(db):
        assert db is session
        events.append("refresh")

    async def rebuild(db, kb_type, *, force_full):
        assert db is session
        events.append(f"rebuild:{kb_type}:{force_full}")
        return 1

    monkeypatch.setattr("app.modules.ai.model_router.refresh_model_router_for_worker", refresh)
    monkeypatch.setattr(tasks, "rebuild_kb_type", rebuild)

    result = await tasks._rebuild("term", force_full=True)

    assert result["state"] == "idle"
    assert events == ["refresh", "rebuild:term:True"]


@pytest.mark.asyncio
async def test_document_index_refreshes_worker_model_route_first(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: _SessionContext(session))
    events = []

    async def refresh(db):
        assert db is session
        events.append("refresh")

    async def index_document(db, doc_id):
        assert db is session
        events.append(f"index:{doc_id}")
        return {"status": "indexed"}

    monkeypatch.setattr("app.modules.ai.model_router.refresh_model_router_for_worker", refresh)
    monkeypatch.setattr("app.modules.knowledge.document_indexer.index_document", index_document)

    result = await tasks._process_document("doc-1")

    assert result == {"status": "indexed"}
    assert events == ["refresh", "index:doc-1"]
