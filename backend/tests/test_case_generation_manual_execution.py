"""接口生成熔断与手工执行请求契约。"""

import pytest
from pydantic import ValidationError

from app.modules.case_generator.case_generator import TestCaseGenerator as CaseGenerator
from app.schemas.case_library import CompleteManualExecutionRequest


@pytest.mark.asyncio
async def test_generation_batch_circuit_breaks_after_provider_failure():
    generator = CaseGenerator()

    class InsufficientBalanceRouter:
        def __init__(self):
            self.calls = 0

        async def call(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("Error code: 402 - Insufficient Balance")

    router = InsufficientBalanceRouter()
    generator.router = router
    endpoints = [{"endpoint_id": f"00000000-0000-0000-0000-{index:012d}",
                  "path": f"/orders/{index}", "http_method": "GET"}
                 for index in range(1, 9)]

    result = await generator.generate_all(endpoints, {})

    assert router.calls == 1  # 首个接口探测失败后，本批次不再重复请求模型
    assert generator.ai_circuit_open is True
    assert generator.degraded_reasons == ["AI 模型余额不足，已使用规则模板完成本批次生成"]
    assert len(result["api"]) == 8 * 15
    assert all(case["endpoint_id"] for case in result["api"])


@pytest.mark.asyncio
async def test_generation_continues_after_successful_probe():
    generator = CaseGenerator()

    class JsonRouter:
        def __init__(self):
            self.calls = 0

        async def call(self, **_kwargs):
            self.calls += 1
            return '{"cases": []}'

    router = JsonRouter()
    generator.router = router
    endpoints = [
        {"endpoint_id": f"00000000-0000-0000-0000-{index:012d}",
         "path": f"/orders/{index}", "http_method": "GET"}
        for index in range(1, 4)
    ]

    result = await generator.generate_all(endpoints, {})

    assert router.calls == 3
    assert generator.ai_circuit_open is False
    assert generator.degraded_reasons == []
    assert len(result["api"]) == 3 * 15


def test_manual_execution_requires_valid_step_results():
    request = CompleteManualExecutionRequest(
        status="failed",
        step_results=[{"step": "提交订单", "status": "failed", "actual": "返回 500"}],
        actual_result="接口返回 500",
    )
    assert request.step_results[0] == {
        "index": 1, "step": "提交订单", "status": "failed", "actual": "返回 500",
    }
    with pytest.raises(ValidationError, match="有效执行结果"):
        CompleteManualExecutionRequest(
            status="passed", step_results=[{"step": "提交订单", "status": "pending"}],
        )
