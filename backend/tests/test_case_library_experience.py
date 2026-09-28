"""用例库结构化编辑、版本和追溯能力的轻量回归。"""

from types import SimpleNamespace

import httpx
import pytest

from app.api.case_library import _case_snapshot, _normalize_tags
from app.models.database import TestCase, TestCaseAsset, TestCaseAssetVersion
from app.modules.execution.api_tester import APITester


def test_case_asset_models_expose_enterprise_metadata_and_trace_link():
    asset_columns = {column.name for column in TestCaseAsset.__table__.columns}
    version_columns = {column.name for column in TestCaseAssetVersion.__table__.columns}
    execution_columns = {column.name for column in TestCase.__table__.columns}

    assert {"folder", "tags", "version", "generation_context"}.issubset(asset_columns)
    assert {"case_asset_id", "version", "snapshot", "changed_by"}.issubset(version_columns)
    assert "case_asset_id" in execution_columns


def test_tags_are_deduplicated_trimmed_and_bounded():
    tags = _normalize_tags([" 冒烟 ", "接口", "冒烟", "", *[f"T{i}" for i in range(30)]])
    assert tags[:2] == ["冒烟", "接口"]
    assert len(tags) == 20


def test_case_version_snapshot_contains_editable_business_fields():
    item = SimpleNamespace(
        title="查询订单",
        description="订单详情",
        execution_kind="api",
        case_type="positive",
        request_data={"method": "GET", "url": "/orders/1"},
        expected_result={"status_code": 200},
        priority="P1",
        folder="订单",
        tags=["冒烟"],
    )
    snapshot = _case_snapshot(item)
    assert snapshot["request_data"]["url"] == "/orders/1"
    assert snapshot["expected_result"]["status_code"] == 200
    assert snapshot["folder"] == "订单"
    assert snapshot["tags"] == ["冒烟"]


class FakeResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    text = '{"ok": true}'

    @staticmethod
    def json():
        return {"ok": True}


@pytest.mark.asyncio
async def test_structured_bearer_auth_is_applied_to_request(monkeypatch):
    captured: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def request(self, **kwargs):
            captured.append(kwargs)
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    results = await APITester().run_tests([
        {
            "case_id": "asset-id",
            "case_name": "认证接口",
            "request": {
                "method": "GET",
                "url": "/profile",
                "auth": {"type": "bearer", "token": "{{token}}"},
            },
            "expected": {"status_code": 200},
        }
    ], "http://service", {"token": "runtime-token"})

    assert results[0]["passed"] is True
    assert captured[0]["headers"]["Authorization"] == "Bearer runtime-token"


@pytest.mark.asyncio
async def test_structured_api_key_can_be_added_to_query(monkeypatch):
    captured: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def request(self, **kwargs):
            captured.append(kwargs)
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    await APITester().run_tests([
        {
            "case_id": "asset-id",
            "case_name": "API Key",
            "request": {
                "method": "GET",
                "url": "/orders",
                "params": {"page": "1"},
                "auth": {"type": "api_key", "key": "key", "value": "{{api_key}}", "in": "query"},
            },
            "expected": {"status_code": 200},
        }
    ], "http://service", {"api_key": "secret"})

    assert captured[0]["params"] == {"page": "1", "key": "secret"}
