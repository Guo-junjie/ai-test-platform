"""
集成测试执行器

执行全链路串联测试：按业务场景编排多接口调用序列。
上下文传递：前一步响应字段自动注入后续步骤。
"""

import asyncio
import json
import re
import time
import uuid
from typing import Any

import httpx

from app.modules.execution.assertion_engine import AssertionEngine
from app.utils.logger import get_logger

logger = get_logger(__name__)


class IntegrationTester:
    """
    集成测试执行器。

    按步骤序列执行多接口调用，支持上下文传递和逐步断言。
    """

    def __init__(self) -> None:
        self.assertion_engine = AssertionEngine()

    async def run_tests(
        self,
        test_scenarios: list[dict[str, Any]],
        service_url: str,
    ) -> list[dict[str, Any]]:
        """
        执行集成测试场景。

        Args:
            test_scenarios: 集成测试场景列表，每个场景包含 steps 序列。
            service_url: 被测服务的基础 URL。

        Returns:
            集成测试结果列表，每个结果包含场景执行详情。
        """
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            base_url=service_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            verify=False,
        ) as client:
            for scenario in test_scenarios:
                result = await self._run_scenario(client, scenario)
                results.append(result)

        passed = sum(1 for r in results if r["passed"])
        logger.info(
            f"Integration tests completed: {passed}/{len(results)} scenarios passed"
        )

        return results

    async def _run_scenario(
        self, client: httpx.AsyncClient, scenario: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行单个集成测试场景。

        按步骤序列依次调用接口，前一步的响应字段自动注入后续步骤。

        Args:
            client: httpx 异步客户端。
            scenario: 集成测试场景。

        Returns:
            场景执行结果。
        """
        case_id = scenario.get("case_id", str(uuid.uuid4()))
        case_name = scenario.get("case_name", "integration_test")
        steps = scenario.get("steps", [])

        # 上下文字典：存储前一步提取的变量
        context: dict[str, Any] = {}
        step_results: list[dict[str, Any]] = []
        scenario_passed = True
        failure_step = None
        failure_reason = None

        logger.info(f"Integration scenario starting: {case_name} ({len(steps)} steps)")

        for step in steps:
            step_num = step.get("step", 0)
            step_result = await self._run_step(client, step, context)

            step_results.append(step_result)

            if not step_result["passed"]:
                scenario_passed = False
                failure_step = step_num
                failure_reason = step_result.get("error_message", "Step assertion failed")
                logger.warning(
                    f"  Step {step_num} failed: {failure_reason}, "
                    f"stopping scenario"
                )
                break

            # 提取上下文变量
            extract_rules = step.get("extract", {})
            if extract_rules and step_result.get("actual_response"):
                for var_name, json_path in extract_rules.items():
                    value = self._extract_value(
                        step_result["actual_response"], json_path
                    )
                    if value is not None:
                        context[var_name] = value
                        logger.debug(f"  Extracted: {var_name} = {value}")

        result = {
            "case_id": case_id,
            "case_name": case_name,
            "passed": scenario_passed,
            "total_steps": len(steps),
            "executed_steps": len(step_results),
            "failure_step": failure_step,
            "failure_reason": failure_reason,
            "step_results": step_results,
            "context": context,
        }

        logger.info(
            f"Integration scenario completed: {case_name}, "
            f"passed={scenario_passed}, steps={len(step_results)}/{len(steps)}"
        )

        return result

    async def _run_step(
        self,
        client: httpx.AsyncClient,
        step: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行单个步骤。"""
        step_num = step.get("step", 0)
        method = self._replace_vars(step.get("method", "GET"), context)
        url = self._replace_vars(step.get("url", "/"), context)
        headers = self._replace_vars_in_dict(step.get("headers", {}), context)
        body = self._replace_vars_in_dict(step.get("body", {}), context)

        start_time = time.time()
        try:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=body if body else None,
            )
            response_time_ms = (time.time() - start_time) * 1000

            try:
                response_body = response.json()
            except Exception:
                response_body = response.text

            assertion = step.get("assertion") or {"field": "$status", "operator": "between_2xx_3xx"}
            passed, assertion_error = self._check_rule(assertion, response.status_code, response_body)
            condition = step.get("condition") or {}
            if passed and condition.get("field"):
                passed, assertion_error = self._check_rule({
                    "field": condition.get("field"), "operator": condition.get("operator", "eq"),
                    "expected": condition.get("value"),
                }, response.status_code, response_body)

            return {
                "step": step_num,
                "method": method,
                "url": url,
                "passed": passed,
                "status_code": response.status_code,
                "actual_response": response_body,
                "response_time_ms": round(response_time_ms, 2),
                "error_message": None if passed else assertion_error,
            }

        except httpx.TimeoutException:
            response_time_ms = (time.time() - start_time) * 1000
            return {
                "step": step_num,
                "method": method,
                "url": url,
                "passed": False,
                "status_code": None,
                "actual_response": None,
                "response_time_ms": round(response_time_ms, 2),
                "error_message": "Request timeout",
            }
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return {
                "step": step_num,
                "method": method,
                "url": url,
                "passed": False,
                "status_code": None,
                "actual_response": None,
                "response_time_ms": round(response_time_ms, 2),
                "error_message": str(e),
            }

    def _check_rule(self, rule: dict[str, Any], status_code: int, body: Any) -> tuple[bool, str | None]:
        field = rule.get("field", "$status")
        operator = rule.get("operator", "eq")
        actual = status_code if field == "$status" else self._extract_value(body, field)
        expected = rule.get("expected")
        if isinstance(expected, str):
            if expected.lower() in {"true", "false"}:
                expected = expected.lower() == "true"
            elif expected.replace(".", "", 1).isdigit():
                expected = float(expected) if "." in expected else int(expected)
        if operator == "between_2xx_3xx":
            passed = 200 <= status_code < 400
        elif operator == "exists":
            passed = actual is not None
        elif operator == "contains":
            passed = expected in actual if isinstance(actual, (str, list, dict)) else False
        elif operator == "neq":
            passed = actual != expected
        else:
            passed = actual == expected
        return passed, None if passed else f"断言失败：{field} 实际为 {actual!r}，期望 {operator} {expected!r}"

    def _extract_value(self, data: Any, json_path: str) -> Any:
        """
        从响应中提取值（JSONPath dot notation）。

        Args:
            data: 响应数据。
            json_path: JSONPath（如 $.data.token 或 data.token）。

        Returns:
            提取到的值，不存在时返回 None。
        """
        if not json_path:
            return None

        # 去掉 $ 前缀
        path = json_path.lstrip("$").lstrip(".")
        if not path:
            return data

        current = data
        parts = re.split(r'\.|\[(\d+)\]', path)
        for part in parts:
            if part == "" or part is None:
                continue
            if isinstance(current, list):
                try:
                    idx = int(part)
                    if 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
                except ValueError:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return None
            else:
                return None

        return current

    def _replace_vars(self, text: str, context: dict[str, Any]) -> str:
        """替换字符串中的 {{variable}} 占位符。"""
        if not isinstance(text, str):
            return text
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text

    def _replace_vars_in_dict(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """递归替换字典中的变量占位符。"""
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._replace_vars(value, context)
            elif isinstance(value, dict):
                result[key] = self._replace_vars_in_dict(value, context)
            else:
                result[key] = value
        return result
