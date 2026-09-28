"""前端原型新增交互所依赖的后端契约。"""

import pytest

from app.api.case_library import _normalize_import_row
from app.api.scenario import _scenario_assertion_to_expected
from app.api.scheduled_tasks import SchedulePreviewRequest, preview_schedule
from app.modules.execution.assertion_engine import AssertionEngine
from app.modules.quality_gate import QualityGateEvaluator
from app.modules.script_gen.script_generator import ScriptGenerator


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


def test_quality_rule_operator_and_plan_scope_are_effective():
    config = QualityGateEvaluator.get_default_config()
    config["rule_meta"] = {
        key: {"enabled": False} for key in config["rules"]
    }
    config["rule_meta"]["min_quality_score"] = {
        "enabled": True, "operator": ">", "plan_ids": ["plan-a"],
    }
    evaluator = QualityGateEvaluator(config)
    scoped = evaluator.evaluate(quality_score=70, defects={}, test_summary={}, plan_id="plan-a")
    outside_scope = evaluator.evaluate(quality_score=70, defects={}, test_summary={}, plan_id="plan-b")
    assert scoped["passed"] is False
    assert scoped["violations"][0]["expected"] == "> 70"
    assert outside_scope["passed"] is True


def test_scenario_assertion_is_preserved_when_adopted_as_case():
    assert _scenario_assertion_to_expected({
        "field": "$.data.status", "operator": "contains", "expected": "paid",
    }) == {"assertions": [{
        "type": "json_path", "path": "$.data.status",
        "operator": "contains", "expected": "paid",
    }]}
    assert _scenario_assertion_to_expected({
        "field": "$status", "operator": "eq", "expected": "201",
    }) == {"status_code": 201}


def test_structured_assertion_operators_execute_against_real_body():
    result = AssertionEngine().assert_response(
        response_status=200,
        response_body={"data": {"name": "enterprise-order", "amount": 1200}},
        response_headers={},
        response_time_ms=30,
        expected={"assertions": [
            {"type": "json_path", "path": "$.data.name", "operator": "contains", "expected": "order"},
            {"type": "json_path", "path": "$.data.amount", "operator": "gt", "expected": 1000},
            {"type": "json_path", "path": "$.data.missing", "operator": "not_exists"},
        ]},
    )
    assert result["passed"] is True
    assert result["details"]["passed_assertions"] == 3


@pytest.mark.asyncio
async def test_script_generation_returns_the_exact_persisted_record_id(monkeypatch):
    generator = ScriptGenerator()

    class Router:
        async def call(self, **_kwargs):
            return "```python\ndef main():\n    return {}\n```"

    async def fake_log_record(**_kwargs):
        return "record-123"

    generator.router = Router()
    monkeypatch.setattr(generator, "_log_record", fake_log_record)
    result = await generator.generate("pre_script", {"nl_input": "准备数据"})
    assert result["id"] == "record-123"
