"""前端原型新增交互所依赖的后端契约。"""

import pytest

from app.api.case_library import _normalize_import_row
from app.api.scheduled_tasks import SchedulePreviewRequest, preview_schedule
from app.modules.quality_gate import QualityGateEvaluator


def test_case_import_preview_normalizes_structured_fields():
    row = _normalize_import_row({
        "用例名称": "查询商品",
        "请求方法": "get",
        "请求地址": "/api/products",
        "查询参数": '{"page": 1}',
        "预期结果": '{"status_code": 200}',
        "标签": "冒烟,回归",
    }, 2)
    assert row["valid"] is True
    assert row["data"]["request_data"]["method"] == "GET"
    assert row["data"]["request_data"]["params"] == {"page": 1}
    assert row["data"]["tags"] == ["冒烟", "回归"]


def test_case_import_preview_rejects_api_without_url():
    row = _normalize_import_row({"用例名称": "缺少地址", "执行类型": "api"}, 3)
    assert row["valid"] is False
    assert "API 用例必须填写请求地址" in row["errors"]


@pytest.mark.asyncio
async def test_schedule_preview_returns_five_readable_occurrences():
    result = await preview_schedule(
        SchedulePreviewRequest(cron_expression="0 9 * * *", count=5),
        current_user=object(),
    )
    assert result["data"]["cron_expression"] == "0 9 * * *"
    assert len(result["data"]["next_runs"]) == 5
    assert all("+08:00" in item for item in result["data"]["next_runs"])


def test_disabled_quality_rule_is_not_evaluated():
    config = QualityGateEvaluator.get_default_config()
    config["rule_meta"] = {"max_p0_defects": {"name": "P0 缺陷数", "enabled": False}}
    result = QualityGateEvaluator(config).evaluate(
        quality_score=100,
        defects={"summary": {"by_severity": {"P0": 5, "P1": 0}}},
        test_summary={},
    )
    assert result["passed"] is True
