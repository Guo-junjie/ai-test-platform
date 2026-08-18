"""
rules — 无 AI 时的确定性规则评审兜底（engine=rule）

对接口列表算确定性比率 → score = round(1 + 4 * ratio, 1)（clamp 1~5）。
各维度比率定义见各 _ratio_* 函数。issues 由固定模板生成。
"""

import json
import re
from typing import Any


# 维度权重（与 review_service 保持一致，后端复算总分）
DIMENSION_WEIGHTS: dict[str, float] = {
    "basic_info": 0.2,
    "request_params": 0.3,
    "response_definition": 0.3,
    "security_auth": 0.2,
}

_SENSITIVE_RE = re.compile(
    r"(password|passwd|pwd|token|secret|身份证|手机号|手机|phone|mobile|idcard|id_card)",
    re.IGNORECASE,
)


def _score(ratio: float) -> float:
    r = max(0.0, min(1.0, ratio))
    return round(1 + 4 * r, 1)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_sensitive_example(example: Any) -> bool:
    text = ""
    try:
        text = json.dumps(example, ensure_ascii=False) if not isinstance(example, str) else example
    except Exception:
        text = str(example)
    return bool(_SENSITIVE_RE.search(text))


def _ratio_basic_info(eps: list) -> float:
    if not eps:
        return 0.0
    summary_rate = sum(1 for e in eps if _get(e, "summary")) / len(eps)
    desc_rate = sum(1 for e in eps if _get(e, "description")) / len(eps)
    return summary_rate * 0.6 + desc_rate * 0.4


def _ratio_request_params(eps: list) -> float:
    params = [(p for p in (_get(e, "params") or [])) for e in eps]
    flat: list = []
    for e in eps:
        flat.extend(_get(e, "params") or [])
    if not flat:
        return 0.5  # 无参数接口（如纯 GET 查询）不扣请求参数分
    desc_rate = sum(1 for p in flat if _get(p, "description")) / len(flat)
    req_rate = sum(1 for p in flat if _get(p, "required")) / len(flat)
    ex_rate = sum(1 for p in flat if _get(p, "example") is not None) / len(flat)
    return desc_rate * 0.4 + req_rate * 0.3 + ex_rate * 0.3


def _ratio_response_definition(eps: list) -> float:
    if not eps:
        return 0.0
    has_2xx = 0
    has_err = 0
    has_schema = 0
    for e in eps:
        responses = _get(e, "responses") or []
        codes = [int(r.get("status_code", 200)) for r in responses if str(r.get("status_code", "")).isdigit()]
        if any(200 <= c < 300 for c in codes):
            has_2xx += 1
        if any(c >= 400 for c in codes):
            has_err += 1
        if any(_get(r, "schema") for r in responses):
            has_schema += 1
    r1 = has_2xx / len(eps)
    r2 = has_err / len(eps)
    r3 = has_schema / len(eps)
    return r1 * 0.4 + r2 * 0.4 + r3 * 0.2


def _ratio_security_auth(eps: list) -> float:
    if not eps:
        return 0.0
    auth_rate = sum(1 for e in eps if _get(e, "auth_required")) / len(eps)
    err_rate = 0.0
    sensitive_rate = 0.0
    for e in eps:
        responses = _get(e, "responses") or []
        codes = [int(r.get("status_code", 200)) for r in responses if str(r.get("status_code", "")).isdigit()]
        if any(c in (401, 403) for c in codes):
            err_rate += 1
        rb = _get(e, "request_body") or {}
        ex = _get(rb, "example")
        if ex and _is_sensitive_example(ex):
            sensitive_rate += 1
    err_rate = err_rate / len(eps)
    sensitive_rate = sensitive_rate / len(eps)
    return auth_rate * 0.5 + err_rate * 0.3 + (1 - sensitive_rate) * 0.2


def _overall(dimension_scores: dict) -> float:
    total = 0.0
    for name, w in DIMENSION_WEIGHTS.items():
        total += w * float(dimension_scores.get(name, 1.0))
    return round(total, 2)


def rule_review(endpoints: list) -> dict:
    """对接口列表做确定性比率评分（engine=rule）。返回与 AI 评审同构的 dict。"""
    eps = [e for e in endpoints if e]
    if not eps:
        dims = {k: 1.0 for k in DIMENSION_WEIGHTS}
        return {
            "engine": "rule",
            "overall_score": 1.0,
            "dimension_scores": dims,
            "dimensions": [
                {"dimension": k, "score": 1.0, "comment": "无接口可评审"} for k in DIMENSION_WEIGHTS
            ],
            "issues": [
                {
                    "dimension": "basic_info",
                    "target": "__document__",
                    "severity": "medium",
                    "issue": "未解析出任何接口，无法评审",
                    "root_cause": "文档未包含可识别的接口定义",
                    "suggestion": "检查文档格式是否正确，或补充接口描述",
                    "example": None,
                }
            ],
            "summary": "文档未解析出任何接口，规则评审给出最低分。",
        }

    dimension_scores = {
        "basic_info": _ratio_basic_info(eps),
        "request_params": _ratio_request_params(eps),
        "response_definition": _ratio_response_definition(eps),
        "security_auth": _ratio_security_auth(eps),
    }
    dims = {k: _score(v) for k, v in dimension_scores.items()}
    overall = _overall(dims)

    issues: list[dict] = []
    low_basic = [e for e in eps if not _get(e, "summary")]
    if len(low_basic) >= max(1, int(len(eps) * 0.5)):
        issues.append(
            {
                "dimension": "basic_info",
                "target": "__document__",
                "severity": "medium",
                "issue": f"{len(low_basic)} 个接口缺少 summary 描述",
                "root_cause": "文档编写者未为接口补充说明",
                "suggestion": "为每个接口补充 summary / description，提升可读性",
                "example": None,
            }
        )
    no_err = [e for e in eps if not any(str(r.get("status_code", "")).isdigit() and int(r.get("status_code")) >= 400 for r in (_get(e, "responses") or []))]
    if no_err:
        issues.append(
            {
                "dimension": "response_definition",
                "target": "__document__",
                "severity": "medium",
                "issue": f"{len(no_err)} 个接口未定义 4xx/5xx 错误响应",
                "root_cause": "文档缺少错误码规范",
                "suggestion": "为每个接口补充 400/401/403/404/500 等错误响应定义",
                "example": None,
            }
        )
    sensitive = [
        e
        for e in eps
        if _is_sensitive_example(_get(_get(e, "request_body") or {}, "example"))
    ]
    if sensitive:
        issues.append(
            {
                "dimension": "security_auth",
                "target": "__document__",
                "severity": "high",
                "issue": f"{len(sensitive)} 个接口的请求示例包含明文敏感字段（密码/token 等）",
                "root_cause": "文档模板直接罗列业务明文凭据",
                "suggestion": "示例中对敏感字段使用占位符（如 <sha256(pwd+salt)>），并补充 401/403 响应",
                "example": None,
            }
        )

    return {
        "engine": "rule",
        "overall_score": overall,
        "dimension_scores": dims,
        "dimensions": [
            {"dimension": k, "score": dims[k], "comment": _comment(k, dims[k])}
            for k in DIMENSION_WEIGHTS
        ],
        "issues": issues,
        "summary": (
            f"规则评审（未配置 AI 模型）：综合得分 {overall}，"
            f"基本信息 {dims['basic_info']}，请求参数 {dims['request_params']}，"
            f"响应定义 {dims['response_definition']}，安全认证 {dims['security_auth']}。"
        ),
    }


def _comment(dimension: str, score: float) -> str:
    if score >= 4:
        return "较好"
    if score >= 3:
        return "一般，存在可改进项"
    if score >= 2:
        return "偏弱，需补充规范"
    return "严重不足"
