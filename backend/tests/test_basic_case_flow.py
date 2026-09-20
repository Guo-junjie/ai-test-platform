"""需求草稿、可执行计划和断言的关键边界。"""

import uuid

import pytest

from app.models.database import CaseAssetStatus, TestCaseAsset as CaseAsset
from app.modules.ai.model_router import ModelNotConfiguredError
from app.modules.doc_parser import requirement_parser
from app.modules.execution.assertion_engine import AssertionEngine
from app.modules.runs.case_readiness import api_case_errors, case_plan_errors


def _asset(*, kind="api", request=None, expected=None, status=CaseAssetStatus.ADOPTED):
    return CaseAsset(
        id=uuid.uuid4(), project_id=uuid.uuid4(), title="订单查询",
        case_type="positive", execution_kind=kind, status=status,
        request_data=request or {}, expected_result=expected or {},
    )


def test_requirement_draft_cannot_be_published_as_api_case():
    draft = _asset(kind="manual", request={"steps": ["查询订单"]},
                   expected={"text": "返回订单"}, status=CaseAssetStatus.DRAFT)
    assert "手工用例不能进入自动执行计划" in case_plan_errors(draft)
    assert "用例尚未评审采纳" in case_plan_errors(draft)


def test_api_plan_requires_relative_path_and_real_assertion():
    assert api_case_errors({"method": "GET", "url": "//other-host/orders"}, {})
    assert api_case_errors({"method": "GET", "url": "/orders"}, {}) == ["至少配置一个有效断言"]
    assert "断言列表格式或类型无效" in api_case_errors(
        {"method": "GET", "url": "/orders"},
        {"assertions": [{"type": "contains", "expected": ""}]})
    assert api_case_errors({"method": "GET", "url": "/orders"},
                           {"status_code": 200, "assertions": []}) == []
    ready = _asset(request={"method": "GET", "url": "/orders/1"},
                   expected={"status_code": 200})
    assert case_plan_errors(ready) == []


def test_missing_assertion_never_passes_and_status_is_always_checked():
    engine = AssertionEngine()
    result = engine.assert_response(200, {"ok": True}, {}, 12, {})
    assert result["passed"] is False
    result = engine.assert_response(500, {"ok": True}, {}, 12,
                                    {"status_code": 200,
                                     "assertions": [{"type": "contains", "expected": "ok"}]})
    assert result["passed"] is False
    assert any("status_code" in failure for failure in result["failures"])


@pytest.mark.asyncio
async def test_ai_requirement_parse_falls_back_to_reviewable_rule_result(monkeypatch):
    class MissingModel:
        async def call(self, **_kwargs):
            raise ModelNotConfiguredError("未配置模型")

    monkeypatch.setattr(requirement_parser, "get_model_router", lambda: MissingModel())
    text = ("订单中心需求文档\nFR-1: 查询订单\n系统应按订单编号返回订单详情，"
            "并在订单不存在时返回明确错误。\n验收标准：已存在订单返回编号、金额和状态。\n"
            "验收标准：不存在的订单返回可识别错误。\n测试需要覆盖正常订单、异常编号和空编号。\n"
            "非功能要求：接口返回内容应保持字段类型稳定，状态码应与接口契约一致，错误响应需要包含可排查的信息。")
    items, engine, reason = await requirement_parser.parse_requirements(text, use_ai=True)
    assert engine == "rule_degraded" and items
    assert "未配置模型" in reason
    assert items[0].acceptance_criteria
    assert items[0].test_points

    items, engine, reason = await requirement_parser.parse_requirements(text, use_ai=False)
    assert engine == "rule_degraded" and items and reason is None
