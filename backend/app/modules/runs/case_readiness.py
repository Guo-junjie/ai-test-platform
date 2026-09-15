"""用例资产进入自动执行计划之前的统一校验。"""

from urllib.parse import urlsplit

from app.models.database import CaseAssetStatus, TestCaseAsset


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
ASSERTION_TYPES = {"status_code", "json_path", "contains", "jsonschema", "response_time"}


def _valid_assertion(item: object) -> bool:
    if not isinstance(item, dict) or item.get("type") not in ASSERTION_TYPES:
        return False
    kind = item["type"]
    if kind == "status_code":
        value = item.get("expected")
        return isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599
    if kind == "json_path":
        return (isinstance(item.get("path"), str) and bool(item["path"].strip())
                and (item.get("operator") in {"exists", "not_null"} or "expected" in item))
    if kind == "contains":
        return isinstance(item.get("expected"), str) and bool(item["expected"])
    if kind == "jsonschema":
        schema = item.get("schema")
        return (isinstance(schema, dict) and bool(schema)
                and (schema.get("type") in {"object", "array", "string", "integer", "number", "boolean"}
                     or isinstance(schema.get("required"), list) and bool(schema["required"])))
    value = item.get("max_ms")
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def api_case_errors(request: dict | None, expected: dict | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(request, dict):
        return ["请求必须是对象"]
    method = request.get("method")
    if not isinstance(method, str) or method.upper() not in HTTP_METHODS:
        errors.append("缺少有效 HTTP 方法")
    url = request.get("url")
    if not isinstance(url, str) or not url.startswith("/") or url.startswith("//"):
        errors.append("请求路径必须是以 / 开头的相对路径")
    elif urlsplit(url).scheme or urlsplit(url).netloc or any(ord(c) < 32 for c in url):
        errors.append("请求路径不能包含主机、协议或控制字符")
    if not isinstance(expected, dict):
        return errors + ["缺少预期结果"]
    status = expected.get("status_code")
    valid_status = isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599
    assertions = expected.get("assertions")
    valid_assertions = isinstance(assertions, list) and bool(assertions) and all(
        _valid_assertion(item) for item in assertions)
    if status is not None and not valid_status:
        errors.append("HTTP 状态码断言必须在 100–599 之间")
    if assertions is not None and (not isinstance(assertions, list) or
                                   any(not _valid_assertion(item) for item in assertions)):
        errors.append("断言列表格式或类型无效")
    if not valid_status and not valid_assertions:
        errors.append("至少配置一个有效断言")
    return errors


def case_plan_errors(asset: TestCaseAsset) -> list[str]:
    errors: list[str] = []
    if asset.status != CaseAssetStatus.ADOPTED:
        errors.append("用例尚未评审采纳")
    if asset.execution_kind == "manual":
        errors.append("手工用例不能进入自动执行计划")
    elif asset.execution_kind == "api":
        errors.extend(api_case_errors(asset.request_data, asset.expected_result))
    elif asset.execution_kind not in {"performance", "integration"}:
        errors.append("不支持的执行类型")
    return errors
