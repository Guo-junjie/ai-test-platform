"""计划发布后编辑资产或计划时，运行仍须消费发布时的用例。"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.api.plan import _plan_state
from app.models.database import TestCaseAsset as CaseAsset, TestPlanRevisionCase as RevisionCase
from app.modules.runs.case_snapshot import (
    case_content_hash,
    cases_from_run_snapshot,
    executable_case_payload,
    resolve_revision_case_payload,
)


def _asset() -> CaseAsset:
    return CaseAsset(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        case_type="positive",
        execution_kind="api",
        title="发布时的用例",
        request_data={"method": "GET", "url": "/before"},
        expected_result={"status_code": 200},
        priority="P2",
    )


def _revision_case(asset: CaseAsset, *, frozen: bool) -> RevisionCase:
    return RevisionCase(
        case_asset_id=asset.id,
        title=asset.title,
        execution_kind=asset.execution_kind,
        content_hash=case_content_hash(asset),
        case_payload=executable_case_payload(asset) if frozen else None,
    )


def test_published_payload_survives_asset_edit_and_plan_edit():
    asset = _asset()
    revision_case = _revision_case(asset, frozen=True)
    other = _asset()

    # 发布后修改原用例，并在计划编辑态加入另一条用例。
    asset.title = "编辑后的用例"
    asset.request_data = {"method": "DELETE", "url": "/after"}
    current_plan_cases = [asset, other]

    payload = resolve_revision_case_payload(revision_case, asset)
    snapshot = {
        "plan_id": "plan-1",
        "plan_revision_id": "revision-1",
        "cases": [{
            "case_asset_id": str(revision_case.case_asset_id),
            "execution_kind": revision_case.execution_kind,
            "payload": payload,
        }],
    }
    buckets = cases_from_run_snapshot(
        snapshot, "plan-1", "revision-1", [str(revision_case.case_asset_id)]
    )

    assert len(current_plan_cases) == 2
    assert len(buckets["api"]) == 1
    assert buckets["api"][0]["case_name"] == "发布时的用例"
    assert buckets["api"][0]["request"]["url"] == "/before"
    assert buckets["api"][0]["request_data"]["url"] == "/before"
    with pytest.raises(ValueError, match="集合与派发参数不匹配"):
        cases_from_run_snapshot(snapshot, "plan-1", "revision-1", [str(other.id)])


def test_legacy_revision_only_uses_unchanged_asset():
    asset = _asset()
    revision_case = _revision_case(asset, frozen=False)
    assert resolve_revision_case_payload(revision_case, asset)["request"]["url"] == "/before"

    asset.request_data = {"method": "DELETE", "url": "/after"}
    with pytest.raises(ValueError, match="内容已变更"):
        resolve_revision_case_payload(revision_case, asset)
    with pytest.raises(ValueError, match="内容已变更"):
        resolve_revision_case_payload(revision_case, None)


def test_republish_detects_case_content_change():
    asset = _asset()
    plan_case = SimpleNamespace(case_asset_id=asset.id, enabled=True)

    class _Session:
        async def execute(self, _query):
            return SimpleNamespace(all=lambda: [(plan_case, asset)])

    before, _ = asyncio.run(_plan_state(uuid.uuid4(), _Session()))
    asset.expected_result = {"status_code": 201}
    after, _ = asyncio.run(_plan_state(uuid.uuid4(), _Session()))
    assert before != after


def test_run_snapshot_rejects_missing_payload():
    with pytest.raises(ValueError, match="载荷不完整"):
        cases_from_run_snapshot(
            {"plan_id": "p", "plan_revision_id": "r", "cases": [{"case_asset_id": "a"}]},
            "p", "r",
        )
