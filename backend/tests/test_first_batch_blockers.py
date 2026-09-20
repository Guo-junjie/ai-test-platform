"""第一批阻断问题的回归测试。"""

import uuid

import pytest

from app.api.requirement_doc import _complete_case, _rule_case
from app.modules.ai.model_router import ModelNotConfiguredError
from app.modules.script_gen.script_generator import ScriptGenerator
from app.schemas.script import GenerateScriptRequest


@pytest.mark.asyncio
async def test_script_generator_awaits_validation_and_returns_serializable_result(monkeypatch):
    generator = ScriptGenerator()

    class Router:
        async def call(self, **_kwargs):
            return "```python\ndef main():\n    return {'ready': True}\n```"

    generator.router = Router()
    result = await generator.generate(
        "pre_script",
        {"api_info": {"http_method": "GET", "path": "/health"}},
    )

    assert isinstance(result, dict)
    assert result["valid"] is True
    assert result["generation_engine"] == "ai"
    assert result["degraded"] is False


@pytest.mark.asyncio
async def test_script_generator_falls_back_when_model_is_unavailable():
    generator = ScriptGenerator()

    class MissingRouter:
        async def call(self, **_kwargs):
            raise ModelNotConfiguredError("未配置脚本生成模型")

    generator.router = MissingRouter()
    result = await generator.generate(
        "post_script",
        {"api_info": {"http_method": "GET", "path": "/health"}},
    )

    assert result["valid"] is True
    assert result["generation_engine"] == "rule_degraded"
    assert result["degraded"] is True
    assert "未配置" in result["degraded_reason"]


def test_script_request_accepts_uuid_project_id():
    project_id = uuid.uuid4()
    request = GenerateScriptRequest(script_type="pre_script", project_id=str(project_id))
    assert request.project_id == project_id


def test_rule_requirement_case_is_ready_for_manual_review():
    requirement = {
        "rid": "FR-4",
        "title": "订单创建",
        "description": "库存不足时拒绝下单",
        "priority": "P1",
        "acceptance_criteria": ["库存不足返回 409", "库存不得为负数"],
        "test_points": ["准备库存为 0 的商品", "提交下单请求"],
    }
    case = _rule_case(requirement)
    assert case["steps"]
    assert case["expected"] == "库存不足返回 409；库存不得为负数"
    assert case["related_requirement"] == "FR-4"


def test_ai_requirement_case_missing_content_is_completed_from_source():
    requirement = {
        "rid": "FR-1",
        "title": "用户登录",
        "description": "正确凭据可以登录",
        "acceptance_criteria": ["成功返回令牌"],
        "test_points": ["输入正确账号密码"],
    }
    case = _complete_case(
        {"title": "登录验证", "related_requirement": "FR-1", "steps": [], "expected": ""},
        requirement,
    )
    assert case["steps"] == ["输入正确账号密码"]
    assert case["expected"] == "成功返回令牌"
