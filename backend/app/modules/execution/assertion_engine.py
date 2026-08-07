"""
断言引擎 — 支持 5 种断言类型

断言类型：
- status_code: HTTP 状态码断言
- json_path: JSON 路径值断言（支持 not_null 操作符）
- contains: 响应内容包含断言
- jsonschema: JSON Schema 验证
- response_time: 响应时间断言

JSONPath 使用简单 dot notation 实现（$.data.userId → response_json["data"]["userId"]），
不依赖第三方库。
"""

import json
import re
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class AssertionEngine:
    """
    断言引擎。

    对 HTTP 响应执行多种断言，返回统一的断言结果。
    """

    def assert_response(
        self,
        response_status: int,
        response_body: Any,
        response_headers: dict[str, str],
        response_time_ms: float,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        """
        对响应执行断言。

        Args:
            response_status: HTTP 响应状态码。
            response_body: 响应体（已解析的 dict / list / str）。
            response_headers: 响应头字典。
            response_time_ms: 响应时间（毫秒）。
            expected: 预期结果，包含 status_code 和 assertions 列表。

        Returns:
            断言结果字典: {passed: bool, failures: [str], details: {...}}。
        """
        assertions = expected.get("assertions", [])
        expected_status = expected.get("status_code")

        # 如果没有显式断言但有 status_code，自动添加状态码断言
        if not assertions and expected_status is not None:
            assertions = [{"type": "status_code", "expected": expected_status}]

        failures: list[str] = []
        details: dict[str, Any] = {
            "total_assertions": len(assertions),
            "passed_assertions": 0,
            "failed_assertions": 0,
        }

        for i, assertion in enumerate(assertions):
            assertion_type = assertion.get("type", "unknown")
            passed, message = self._execute_assertion(
                assertion_type,
                assertion,
                response_status,
                response_body,
                response_headers,
                response_time_ms,
            )

            if passed:
                details["passed_assertions"] += 1
            else:
                details["failed_assertions"] += 1
                failures.append(f"[{assertion_type}#{i}] {message}")

        all_passed = len(failures) == 0
        details["all_passed"] = all_passed

        if not all_passed:
            logger.debug(
                f"Assertion failed: {len(failures)} failures out of "
                f"{len(assertions)} assertions"
            )

        return {
            "passed": all_passed,
            "failures": failures,
            "details": details,
        }

    def _execute_assertion(
        self,
        assertion_type: str,
        assertion: dict[str, Any],
        response_status: int,
        response_body: Any,
        response_headers: dict[str, str],
        response_time_ms: float,
    ) -> tuple[bool, str]:
        """执行单个断言，返回 (是否通过, 失败消息)。"""
        if assertion_type == "status_code":
            return self._assert_status_code(assertion, response_status)
        elif assertion_type == "json_path":
            return self._assert_json_path(assertion, response_body)
        elif assertion_type == "contains":
            return self._assert_contains(assertion, response_body)
        elif assertion_type == "jsonschema":
            return self._assert_jsonschema(assertion, response_body)
        elif assertion_type == "response_time":
            return self._assert_response_time(assertion, response_time_ms)
        else:
            return False, f"Unknown assertion type: {assertion_type}"

    def _assert_status_code(
        self, assertion: dict[str, Any], status: int
    ) -> tuple[bool, str]:
        """状态码断言。"""
        expected_status = assertion.get("expected")
        if expected_status is None:
            return True, ""
        if status == expected_status:
            return True, ""
        return False, f"Expected status {expected_status}, got {status}"

    def _assert_json_path(
        self, assertion: dict[str, Any], body: Any
    ) -> tuple[bool, str]:
        """JSON 路径断言（dot notation）。"""
        path = assertion.get("path", "")
        if not path:
            return False, "Missing 'path' in json_path assertion"

        value = self._resolve_json_path(body, path)
        operator = assertion.get("operator", "")

        if operator == "not_null":
            if value is not None:
                return True, ""
            return False, f"Path '{path}' is null"

        if operator == "exists":
            if value is not None:
                return True, ""
            return False, f"Path '{path}' does not exist"

        expected_value = assertion.get("expected")
        if value == expected_value:
            return True, ""
        return False, f"Path '{path}': expected {expected_value}, got {value}"

    def _assert_contains(
        self, assertion: dict[str, Any], body: Any
    ) -> tuple[bool, str]:
        """内容包含断言。"""
        expected = assertion.get("expected", "")
        body_str = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        if expected in body_str:
            return True, ""
        return False, f"Response does not contain '{expected}'"

    def _assert_jsonschema(
        self, assertion: dict[str, Any], body: Any
    ) -> tuple[bool, str]:
        """JSON Schema 验证（简化实现）。"""
        schema = assertion.get("schema", {})
        if not schema:
            return True, ""

        # 简化验证：检查 required 字段和 type
        required_fields = schema.get("required", [])
        if required_fields and isinstance(body, dict):
            for field in required_fields:
                if field not in body:
                    return False, f"Missing required field: {field}"

        # 检查 type
        expected_type = schema.get("type")
        if expected_type:
            type_map = {
                "object": dict,
                "array": list,
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
            }
            expected_python_type = type_map.get(expected_type)
            if expected_python_type and not isinstance(body, expected_python_type):
                return False, f"Expected type {expected_type}, got {type(body).__name__}"

        return True, ""

    def _assert_response_time(
        self, assertion: dict[str, Any], response_time_ms: float
    ) -> tuple[bool, str]:
        """响应时间断言。"""
        max_ms = assertion.get("max_ms", 5000)
        if response_time_ms <= max_ms:
            return True, ""
        return False, f"Response time {response_time_ms:.0f}ms exceeds {max_ms}ms"

    def _resolve_json_path(self, data: Any, path: str) -> Any:
        """
        解析 JSONPath（dot notation）。

        示例: "$.data.userId" → data["data"]["userId"]
              "$.list[0].name" → data["list"][0]["name"]

        Args:
            data: JSON 数据。
            path: JSONPath 字符串。

        Returns:
            解析到的值，路径不存在时返回 None。
        """
        if not path:
            return None

        # 去掉 $ 前缀
        if path.startswith("$"):
            path = path[1:]
        if path.startswith("."):
            path = path[1:]

        if not path:
            return data

        current = data
        # 分割路径，处理 . 和 []
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
