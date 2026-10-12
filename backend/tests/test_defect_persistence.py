"""报告持久化契约：稳定检测身份、不吞掉同事务中的数据库失败。"""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.modules.defects.pipeline import detection_signature
from app.modules.report.generator import persist_defects_to_db, CATEGORY_TO_DEFECT_TYPE


@pytest.mark.asyncio
async def test_report_defects_share_caller_transaction(monkeypatch):
    run_id, project_id, case_id = uuid4(), uuid4(), uuid4()
    session = AsyncMock()
    persist = AsyncMock(return_value=1)
    monkeypatch.setattr("app.modules.defects.pipeline.persist_run_defects", persist)
    items = [{"case_id": str(case_id), "title": "AI 分析标题", "category": "program_bug", "severity": "P1"}]
    count = await persist_defects_to_db(run_id, {"defects": items}, project_id, session)
    assert count == 1
    persist.assert_awaited_once_with(session, run_id, items, CATEGORY_TO_DEFECT_TYPE, project_id)
    session.commit.assert_not_awaited()
    session.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_error_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr("app.modules.defects.pipeline.persist_run_defects", AsyncMock(side_effect=RuntimeError("database failure")))
    with pytest.raises(RuntimeError, match="database failure"):
        await persist_defects_to_db(uuid4(), {"defects": []}, uuid4(), AsyncMock())


def test_detection_signature_uses_execution_identity():
    identifier = uuid4()
    assert detection_signature(identifier) == detection_signature(str(identifier))
    assert detection_signature(identifier) != detection_signature(uuid4())


@pytest.mark.asyncio
async def test_invalid_run_id_is_safely_rejected():
    session = AsyncMock()
    assert await persist_defects_to_db("invalid", {"defects": []}, session=session) == 0
    session.execute.assert_not_awaited()
