"""
parser_service — 编排四种格式解析，产出统一 ApiSpec（文档级）

- openapi / har：规则解析器直接出 ApiSpec（parse_engine=rule），零 AI 依赖
- docx / pdf：先抽取 raw_text →（可选）AI 结构化；AI 不可用则 rule_degraded（正则仅抽 method+path）
- 返回结构统一为 dict，供 api/doc.py 落库与预览
"""

import os
import re
from typing import Any, Optional

from loguru import logger

from app.modules.doc_parser.schemas import ApiSpec
from app.modules.doc_parser.swagger_parser import parse_swagger
from app.modules.doc_parser.har_parser import parse_har
from app.modules.doc_parser.docx_parser import extract_text_docx
from app.modules.doc_parser.pdf_parser import extract_text_pdf
from app.modules.doc_parser.ai_enhancer import enhance_with_ai


_METHOD_RE = re.compile(
    r"(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+(/[^\s,，、)）]+)",
    re.IGNORECASE,
)


def _regex_fallback(raw_text: str) -> list[dict]:
    """无 AI 时的正则兜底：仅抽取 method + path 骨架（confidence=0.3）。"""
    specs: list[dict] = []
    seen: set[str] = set()
    for m in _METHOD_RE.finditer(raw_text or ""):
        method = m.group(1).upper()
        path = m.group(2).strip().rstrip(".,;").split("?")[0]
        if not path.startswith("/"):
            path = "/" + path
        key = f"{method} {path}"
        if key in seen:
            continue
        seen.add(key)
        specs.append(
            {
                "path": path,
                "method": method,
                "summary": "",
                "description": "",
                "params": [],
                "request_body": None,
                "responses": [
                    {
                        "status_code": 200,
                        "description": "",
                        "content_type": "application/json",
                        "schema": None,
                        "example": None,
                    }
                ],
                "auth_required": False,
                "auth_type": None,
                "confidence": 0.3,
                "evidence": "",
            }
        )
    return specs


def _empty_spec() -> ApiSpec:
    return ApiSpec(title="", version="", servers=[], base_path="", endpoints=[])


async def parse_document(
    format: str,
    storage_path: str,
    use_ai: bool = True,
    raw_text: Optional[str] = None,
    max_endpoints: int = 200,
) -> dict:
    """
    解析文档，返回：
    {
      "parse_engine": "rule" | "ai" | "rule_degraded",
      "api_spec": ApiSpec | None,
      "raw_text": str,
      "unparsed_notes": list[str],
      "meta": dict,
      "degraded": bool,
      "error": str | None,         # 仅抽取失败时
      "scanned": bool,             # 仅扫描版 PDF
    }
    """
    fmt = (format or "").lower()
    unparsed_notes: list[str] = []
    meta: dict[str, Any] = {}

    # ---- 规则型格式（openapi / har / txt）----
    if fmt in ("openapi", "har", "txt"):
        if raw_text is None:
            try:
                with open(storage_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw_text = f.read()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Read {storage_path} failed: {e}")
                raw_text = ""
        if fmt == "openapi":
            api_spec = parse_swagger(raw_text)
            return _ok("rule", api_spec, raw_text or "", unparsed_notes, meta)
        if fmt == "har":
            api_spec = parse_har(raw_text)
            return _ok("rule", api_spec, raw_text or "", unparsed_notes, meta)
        # txt：非结构文本，走 AI 或降级
        return await _parse_unstructured(raw_text or "", use_ai, unparsed_notes, meta, max_endpoints)

    # ---- 文档型格式（docx / pdf）：先抽取文本，再 AI 结构化 ----
    try:
        raw_text = extract_text_docx(storage_path) if fmt == "docx" else extract_text_pdf(storage_path)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Extract text failed for {storage_path}: {e}", exc_info=True)
        return {
            "parse_engine": "rule_degraded",
            "api_spec": _empty_spec(),
            "raw_text": "",
            "unparsed_notes": [f"文本抽取失败: {e}"],
            "meta": meta,
            "degraded": True,
            "error": str(e),
            "scanned": False,
        }

    if not raw_text or not raw_text.strip():
        # 扫描版（无文本层）
        return {
            "parse_engine": "rule_degraded",
            "api_spec": _empty_spec(),
            "raw_text": "",
            "unparsed_notes": ["疑似扫描版文档，无可提取文本（本版本不支持 OCR）"],
            "meta": meta,
            "degraded": True,
            "error": None,
            "scanned": True,
        }

    return await _parse_unstructured(raw_text, use_ai, unparsed_notes, meta, max_endpoints)


async def _parse_unstructured(
    raw_text: str,
    use_ai: bool,
    unparsed_notes: list[str],
    meta: dict,
    max_endpoints: int,
) -> dict:
    if use_ai:
        specs = await enhance_with_ai(raw_text, use_case="doc_parse", max_endpoints=max_endpoints)
        if specs:
            return _ok("ai", ApiSpec(title="", version="", servers=[], base_path="", endpoints=specs), raw_text, unparsed_notes, meta)
        unparsed_notes.append("未配置 AI 模型或 AI 解析失败，仅抽取到接口骨架")
    fb = _regex_fallback(raw_text)
    return _ok("rule_degraded", ApiSpec(title="", version="", servers=[], base_path="", endpoints=fb), raw_text, unparsed_notes, meta, degraded=True)


def _ok(
    engine: str,
    api_spec: ApiSpec,
    raw_text: str,
    unparsed_notes: list[str],
    meta: dict,
    degraded: bool = False,
) -> dict:
    return {
        "parse_engine": engine,
        "api_spec": api_spec,
        "raw_text": raw_text,
        "unparsed_notes": unparsed_notes,
        "meta": meta,
        "degraded": degraded,
        "error": None,
        "scanned": False,
    }
