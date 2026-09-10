"""
接口测试执行器

使用 httpx.AsyncClient 异步发送 HTTP 请求，支持变量替换和断言。
"""

import asyncio
import time
import uuid
from typing import Any

import httpx

from app.modules.execution.assertion_engine import AssertionEngine
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 最大并发请求数
_MAX_CONCURRENT_REQUESTS = 10


class APITester:
    """
    接口测试执行器。

    异步执行接口测试用例，支持 {{variable}} 变量替换，
    使用 AssertionEngine 判断通过/失败。
    """

    def __init__(self) -> None:
        self.assertion_engine = AssertionEngine()

    async def run_tests(
        self,
        test_cases: list[dict[str, Any]],
        service_url: str,
        context: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        执行接口测试用例。

        Args:
            test_cases: 测试用例列表。
            service_url: 被测服务的基础 URL。
            context: 变量上下文字典（如 {"token": "xxx", "user_id": "123"}）。

        Returns:
            测试结果列表，每个结果包含：
                case_id, case_name, passed, actual_status_code,
                actual_response, response_time_ms, error_message。
        """
        context = context or {}
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            base_url=service_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            verify=False,
        ) as client:
            tasks = [
                self._run_single_test(client, case, context, semaphore)
                for case in test_cases
            ]
            results = await asyncio.gather(*tasks)

        passed_count = sum(1 for r in results if r["passed"])
        logger.info(
            f"API tests completed: {passed_count}/{len(results)} passed"
        )

        return list(results)

    async def _run_single_test(
        self,
        client: httpx.AsyncClient,
        case: dict[str, Any],
        context: dict[str, str],
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        """执行单个测试用例。"""
        async with semaphore:
            case_id = case.get("case_id", str(uuid.uuid4())) if isinstance(case, dict) else str(uuid.uuid4())
            case_name = case.get("case_name", "unknown") if isinstance(case, dict) else "unknown"
            start_time = time.time()

            try:
                request_data = case.get("request", {}) if isinstance(case, dict) else {}
                if not isinstance(request_data, dict):
                    request_data = {}
                expected = case.get("expected", {}) if isinstance(case, dict) else {}
                if not isinstance(expected, dict):
                    expected = {}

                # 变量替换
                method = self._replace_variables(
                    request_data.get("method", "GET"), context
                )
                url = self._replace_variables(
                    request_data.get("url", "/"), context
                )
                raw_headers = request_data.get("headers")
                headers = self._replace_variables_in_dict(raw_headers, context) if isinstance(raw_headers, dict) else {}

                raw_params = request_data.get("params")
                params = self._replace_variables_in_dict(raw_params, context) if isinstance(raw_params, dict) else {}

                raw_body = request_data.get("body")
                if isinstance(raw_body, dict):
                    body = self._replace_variables_in_dict(raw_body, context)
                elif isinstance(raw_body, str):
                    body = self._replace_variables(raw_body, context)
                else:
                    body = raw_body

                req_kwargs: dict[str, Any] = {
                    "method": str(method or "GET").upper(),
                    "url": str(url or "/"),
                }
                if headers:
                    req_kwargs["headers"] = headers
                if params:
                    req_kwargs["params"] = params
                if body is not None and body != {}:
                    if isinstance(body, (dict, list)):
                        req_kwargs["json"] = body
                    else:
                        req_kwargs["content"] = str(body)

                response = await client.request(**req_kwargs)
                response_time_ms = (time.time() - start_time) * 1000

                # 解析响应体
                try:
                    response_body = response.json()
                except Exception:
                    response_body = response.text

                # 执行断言
                assertion_result = self.assertion_engine.assert_response(
                    response_status=response.status_code,
                    response_body=response_body,
                    response_headers=dict(response.headers),
                    response_time_ms=response_time_ms,
                    expected=expected,
                )

                return {
                    "case_id": case_id,
                    "case_name": case_name,
                    "passed": assertion_result["passed"],
                    "actual_status_code": response.status_code,
                    "actual_response": response_body,
                    "response_time_ms": round(response_time_ms, 2),
                    "error_message": (
                        "; ".join(assertion_result["failures"])
                        if assertion_result["failures"] else None
                    ),
                }

            except httpx.TimeoutException:
                response_time_ms = (time.time() - start_time) * 1000
                return {
                    "case_id": case_id,
                    "case_name": case_name,
                    "passed": False,
                    "actual_status_code": None,
                    "actual_response": None,
                    "response_time_ms": round(response_time_ms, 2),
                    "error_message": "Request timeout",
                }
            except Exception as e:
                response_time_ms = (time.time() - start_time) * 1000
                return {
                    "case_id": case_id,
                    "case_name": case_name,
                    "passed": False,
                    "actual_status_code": None,
                    "actual_response": None,
                    "response_time_ms": round(response_time_ms, 2),
                    "error_message": str(e),
                }

    def _replace_variables(
        self, text: str, context: dict[str, str]
    ) -> str:
        """替换字符串中的 {{variable}} 占位符。"""
        if not isinstance(text, str):
            return text
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text

    def _replace_variables_in_dict(
        self, data: Any, context: dict[str, str]
    ) -> dict[str, Any]:
        """递归替换字典中的变量占位符。"""
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._replace_variables(value, context)
            elif isinstance(value, dict):
                result[key] = self._replace_variables_in_dict(value, context)
            elif isinstance(value, list):
                result[key] = [
                    self._replace_variables(item, context) if isinstance(item, str)
                    else self._replace_variables_in_dict(item, context) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
