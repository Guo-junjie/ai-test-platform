"""第二批基础链路缺陷的回归测试。"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.api.case_library import _ep_to_dict
from app.api.report import generate_report
from app.models.database import ScheduledTaskStatus
from app.modules.ai.model_router import ModelNotConfiguredError, ModelRouter
from app.modules.case_generator.case_generator import TestCaseGenerator as CaseGenerator
from app.modules.scheduler.scheduler_service import SchedulerService
from app.schemas.scheduled_task import ScheduledTaskRequest


def test_scheduled_task_request_accepts_paused_and_rejects_unknown_status():
    request = ScheduledTaskRequest(
        name="夜间回归",
        project_id=str(uuid.uuid4()),
        status="paused",
    )
    assert request.status == "paused"
    with pytest.raises(ValidationError):
        ScheduledTaskRequest(name="非法状态", status="disabled")


@pytest.mark.asyncio
async def test_scheduler_service_preserves_initial_paused_status():
    session = AsyncMock()
    captured = []
    session.add = captured.append

    result = await SchedulerService.create_task(
        project_id=str(uuid.uuid4()),
        name="暂停创建",
        cron_expression="0 2 * * *",
        target_type="plan",
        status="paused",
        db=session,
    )

    assert captured[0].status == ScheduledTaskStatus.PAUSED
    assert result["status"] == "paused"


def test_endpoint_mapping_keeps_source_id():
    endpoint_id = uuid.uuid4()
    endpoint = SimpleNamespace(
        id=endpoint_id,
        path="/users",
        method="GET",
        params=[],
        auth_required=True,
        summary="用户列表",
    )
    assert _ep_to_dict(endpoint)["endpoint_id"] == str(endpoint_id)


@pytest.mark.asyncio
async def test_batch_generation_propagates_endpoint_id(monkeypatch):
    endpoint_id = str(uuid.uuid4())
    generator = CaseGenerator()
    monkeypatch.setattr(
        generator,
        "generate_api_cases",
        AsyncMock(return_value=[{"case_name": "正常查询"}]),
    )
    monkeypatch.setattr(generator, "_generate_performance_cases", lambda cases: [])
    monkeypatch.setattr(generator, "_generate_integration_cases", lambda cases, analysis: [])

    result = await generator.generate_all(
        [{"endpoint_id": endpoint_id, "path": "/users", "http_method": "GET"}],
        {},
    )

    assert result["api"][0]["endpoint_id"] == endpoint_id


def test_embedding_route_requires_explicit_model():
    router = ModelRouter()
    with pytest.raises(ModelNotConfiguredError, match="嵌入模型"):
        router.get_client("embedding")


@pytest.mark.asyncio
async def test_manual_report_generation_waits_until_completed(monkeypatch):
    run_id = str(uuid.uuid4())
    db = AsyncMock()
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = SimpleNamespace(id=run_id)
    db.execute.return_value = query_result

    monkeypatch.setattr(
        "app.api.report._load_test_results",
        AsyncMock(return_value={"summary": {"source": "db_fallback"}}),
    )
    generate = AsyncMock(return_value={"quality_score": 88, "overall_pass": True})
    monkeypatch.setattr("app.api.report._generate_report_async", generate)

    response = await generate_report(run_id, db)

    generate.assert_awaited_once()
    assert response["data"]["status"] == "completed"
    assert response["data"]["quality_score"] == 88
