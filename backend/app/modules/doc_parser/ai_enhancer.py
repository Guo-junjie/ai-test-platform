"""
ai_enhancer — 用 AI 把非结构化文本结构化为接口定义（use_case=doc_parse）

- 长文本分块（≤12000 字符，优先在空行切），Semaphore(3) 并发调模型
- JSON 三重容错：裸 JSON / ```json 块 / 抽取首个 {...}
- 失败 / 无模型 → 返回 None（由 parser_service 降级为 rule_degraded）
"""

import asyncio
import json
import re
from typing import Any, Optional

from loguru import logger

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.modules.knowledge.retriever import retrieve_and_inject
from app.modules.doc_parser.schemas import ApiEndpointSpec


_SYSTEM_PROMPT = """你是一名资深 API 文档解析引擎。任务：从给定文本中抽取 HTTP 接口，输出严格 JSON。

铁律：
1. 只允许从文本中抽取真实存在的接口/参数，禁止推测、补全不存在的内容。
2. 文本未写明的 type 一律填 "string"，description 留空，不要臆造。
3. 无法判定的整段放入 unparsed_notes，不要硬凑成接口。
4. confidence 自评：明确参数表 >=0.8；散落描述 0.4~0.7；仅出现 URL 0.3。

输出格式（仅 JSON，不要 markdown 代码块，不要解释文字）：
{
  "endpoints": [
    {"path":"","method":"","summary":"","description":"","auth_required":false,"auth_type":null,
     "params":[{"name":"","in":"query","type":"string","required":false,"description":"","example":null}],
     "request_body":{"content_type":"application/json","required":false,"schema":{},"example":null},
     "responses":[{"status_code":200,"description":"","content_type":"application/json","schema":{},"example":null}],
     "confidence":0.8,"evidence":""}
  ],
  "unparsed_notes": []
}
"""

_PROMPT_TEMPLATE = """请解析以下接口文档文本：

===== 文档开始 =====
{text}
===== 文档结束 =====

{glossary}按系统要求输出 JSON。"""


def _parse_json_response(text: str) -> Optional[dict]:
    """三重容错解析 LLM 返回的 JSON。"""
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


def _split_chunks(text: str, max_chars: int = 12000) -> list[str]:
    """优先在空行处切分，避免切断参数表。"""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    buf = ""
    for line in text.splitlines():
        if len(buf) + len(line) > max_chars and buf:
            chunks.append(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        chunks.append(buf)
    return chunks


def _coerce_endpoint(item: dict) -> dict:
    """把 AI 返回的 dict 规整为 ApiEndpointSpec 兼容的字段字典。"""
    params = []
    for p in item.get("params", []) or []:
        if not isinstance(p, dict):
            continue
        params.append(
            {
                "name": p.get("name", ""),
                "in_": p.get("in", "query"),
                "type": p.get("type", "string"),
                "required": bool(p.get("required", False)),
                "description": p.get("description", "") or "",
                "example": p.get("example"),
            }
        )
    rb = item.get("request_body") or {}
    request_body = None
    if rb:
        request_body = {
            "content_type": rb.get("content_type", "application/json"),
            "required": bool(rb.get("required", False)),
            "schema_": rb.get("schema") if isinstance(rb, dict) else None,
            "example": rb.get("example"),
        }
    responses = []
    for r in item.get("responses", []) or []:
        if not isinstance(r, dict):
            continue
        try:
            sc = int(r.get("status_code", 200))
        except (ValueError, TypeError):
            sc = 200
        responses.append(
            {
                "status_code": sc,
                "description": r.get("description", "") or "",
                "content_type": r.get("content_type", "application/json"),
                "schema_": r.get("schema") if isinstance(r, dict) else None,
                "example": r.get("example"),
            }
        )
    path = item.get("path") or "/"
    if not path.startswith("/"):
        path = "/" + path
    return {
        "path": path,
        "method": (item.get("method") or "GET").upper(),
        "summary": item.get("summary", "") or "",
        "description": item.get("description", "") or "",
        "params": params,
        "request_body": request_body,
        "responses": responses,
        "auth_required": bool(item.get("auth_required", False)),
        "auth_type": item.get("auth_type"),
        "confidence": float(item.get("confidence", 0.8)) if item.get("confidence") else 0.8,
        "evidence": item.get("evidence", "") or "",
    }


async def enhance_with_ai(
    raw_text: str, use_case: str = "doc_parse", max_endpoints: int = 200
) -> Optional[list[ApiEndpointSpec]]:
    """
    把非结构化文本结构化为 ApiEndpointSpec 列表。
    无 AI 模型 / 调用失败 → 返回 None（由调用方降级）。
    """
    if not raw_text or not raw_text.strip():
        return None

    router = get_model_router()
    glossary = ""
    try:
        glossary = await retrieve_and_inject(None, raw_text[:500], "term", top_k=10)
    except Exception:
        glossary = ""
    glossary_block = f"{glossary}\n\n" if glossary else ""
    chunks = _split_chunks(raw_text, max_chars=12000)
    sem = asyncio.Semaphore(3)

    async def _one(chunk: str) -> Optional[dict]:
        async with sem:
            prompt = _PROMPT_TEMPLATE.format(text=chunk, glossary=glossary_block)
            try:
                resp = await router.call(
                    use_case=use_case,
                    messages=[{"role": "user", "content": prompt}],
                    response_format_json=True,
                    temperature=0.1,
                )
            except ModelNotConfiguredError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"AI doc parse chunk failed (degrade): {e}")
                return None
            return _parse_json_response(resp)

    results = await asyncio.gather(*[_one(c) for c in chunks])

    merged: dict[str, ApiEndpointSpec] = {}
    for data in results:
        if not data or "endpoints" not in data:
            continue
        for item in data.get("endpoints", []):
            try:
                spec = ApiEndpointSpec(**_coerce_endpoint(item))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skip invalid AI endpoint: {e}")
                continue
            key = f"{spec.method} {spec.path}"
            # 冲突时保留字段更完整的（params 多者优先）
            if key not in merged or len(spec.params) > len(merged[key].params):
                merged[key] = spec

    specs = list(merged.values())[:max_endpoints]
    return specs or None
