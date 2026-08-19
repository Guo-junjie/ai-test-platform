"""
review_service — AI 多维评审（use_case=doc_review）+ 后端按权重复算总分

四维度权重（后端常量，AI 只打分不算总分）：
- basic_info: 0.20
- request_params: 0.30
- response_definition: 0.30
- security_auth: 0.20

总分恒由后端复算：overall = round(Σ score_i * weight_i, 2)，与 AI 返回值无关。
无 AI / 失败 → 转 rules.rule_review 确定性兜底。
"""

import json
import re
from typing import Any, Optional

from loguru import logger

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.modules.doc_review.rules import DIMENSION_WEIGHTS, rule_review


_DIMENSION_PROMPT = """你是一名资深的 API 文档质检专家。请对以下接口定义做四维评审，输出严格 JSON。

四维（权重固定，你只需对每项打 1-5 整数分）：
- basic_info（基本信息）：接口名/描述是否可懂、path 与 method 语义是否相符、命名风格是否统一
- request_params（请求参数）：类型是否明确、必填是否标注、取值范围/枚举/示例、分页是否规范
- response_definition（响应定义）：是否定义 2xx、是否定义 4xx/5xx 错误码、字段是否有类型与示例、是否有统一包装
- security_auth（安全认证）：认证方式是否明确、是否定义 401/403、敏感字段是否明文示例、是否有权限/限流说明

输出格式（仅 JSON，不要 markdown 代码块）：
{
  "summary": "整体结论",
  "dimensions": [
    {"dimension":"basic_info","score":4,"comment":"..."},
    {"dimension":"request_params","score":3,"comment":"..."},
    {"dimension":"response_definition","score":2,"comment":"..."},
    {"dimension":"security_auth","score":2,"comment":"..."}
  ],
  "issues": [
    {"dimension":"security_auth","target":"POST /api/v1/login","severity":"high",
     "issue":"...","root_cause":"...","suggestion":"...","example":"..."}
  ]
}
severity 取值 high/medium/low；target 为 "METHOD /path" 或 "__document__"。"""

_TEMPLATE = """请评审以下接口定义（已裁剪，去掉大示例，仅保留结构）：

===== 接口列表开始 =====
{specs}
===== 接口列表结束 =====

按系统要求输出 JSON。"""


def _endpoint_to_dict(e: Any) -> dict:
    if isinstance(e, dict):
        return e
    try:
        return e.model_dump(by_alias=True, exclude_none=True)
    except Exception:
        return {}


def _build_specs_json(endpoints: list) -> str:
    """裁剪接口列表：去掉 example，schema 只留一层 properties keys，控制输入长度。"""
    slim: list[dict] = []
    for e in endpoints:
        d = _endpoint_to_dict(e)
        slim.append(
            {
                "method": d.get("method"),
                "path": d.get("path"),
                "summary": d.get("summary"),
                "auth_required": d.get("auth_required"),
                "auth_type": d.get("auth_type"),
                "params": [
                    {
                        "name": p.get("name"),
                        "in": p.get("in"),
                        "type": p.get("type"),
                        "required": p.get("required"),
                    }
                    for p in (d.get("params") or [])
                ],
                "responses": [
                    {"status_code": r.get("status_code")} for r in (d.get("responses") or [])
                ],
            }
        )
    return json.dumps(slim, ensure_ascii=False)


def _parse_json_response(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break
    return None


def _recompute_overall(dimensions: list) -> float:
    total = 0.0
    for d in dimensions:
        name = d.get("dimension")
        w = DIMENSION_WEIGHTS.get(name)
        if w is not None:
            try:
                total += w * float(d.get("score", 0))
            except (ValueError, TypeError):
                pass
    return round(total, 2)


async def review(endpoints: list, use_ai: bool = True) -> dict:
    """
    评审接口列表，返回与 rules 同构的 dict：
    { engine, overall_score, dimension_scores, dimensions, issues, summary }
    """
    if not use_ai:
        return rule_review(endpoints)

    router = get_model_router()
    specs_json = _build_specs_json(endpoints)
    prompt = _TEMPLATE.format(specs=specs_json[:30000])
    try:
        resp = await router.call(
            use_case="doc_review",
            messages=[{"role": "user", "content": prompt}],
            response_format_json=True,
            temperature=0.3,
        )
    except ModelNotConfiguredError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AI doc review failed (fallback to rule): {e}")
        return rule_review(endpoints)

    data = _parse_json_response(resp)
    if not data or "dimensions" not in data:
        return rule_review(endpoints)

    dims: list[dict] = []
    for d in data.get("dimensions", []):
        try:
            sc = int(round(float(d.get("score", 0))))
        except (ValueError, TypeError):
            sc = 0
        sc = max(1, min(5, sc))
        dims.append(
            {"dimension": d.get("dimension"), "score": sc, "comment": d.get("comment", "")}
        )
    # 补全缺失维度（防止权重计算缺项）
    present = {d["dimension"] for d in dims}
    for name in DIMENSION_WEIGHTS:
        if name not in present:
            dims.append({"dimension": name, "score": 1, "comment": "AI 未给出该维度评分"})

    overall = _recompute_overall(dims)

    issues: list[dict] = []
    for it in data.get("issues", []) or []:
        issues.append(
            {
                "dimension": it.get("dimension"),
                "target": it.get("target", "__document__"),
                "severity": it.get("severity", "medium"),
                "issue": it.get("issue", ""),
                "root_cause": it.get("root_cause", ""),
                "suggestion": it.get("suggestion", ""),
                "example": it.get("example"),
            }
        )

    return {
        "engine": "ai",
        "overall_score": overall,
        "dimension_scores": {d["dimension"]: d["score"] for d in dims},
        "dimensions": dims,
        "issues": issues,
        "summary": data.get("summary", ""),
    }
