"""
har_parser — HAR 规则解析（不依赖 AI，parse_engine=rule）

HAR 是浏览器/抓包导出的 HTTP 归档（log.entries[]）。
- request.url 去 host、query 拆为 in=query 参数
- 同 (method, path) 多条 entry 聚合：参数取并集，required=出现率 100% 才 True
- postData.text 尝试 json 解析 → request_body.example，反推 schema
- response.status → responses（多状态码合并）
- 纯数字 / UUID 路径段参数化为 {id}，避免资产爆炸
- 过滤静态资源（.js/.css/.png...）
"""

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse, parse_qs

from app.modules.doc_parser.schemas import (
    ApiSpec,
    ApiEndpointSpec,
    ParamSpec,
    ResponseSpec,
    ApiRequestBody,
)

HTTP_METHODS = {
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "HEAD",
    "OPTIONS",
}

STATIC_EXT = {
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
    ".html",
    ".htm",
}


def _looks_like_uuid(s: str) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            s,
        )
    )


def _parameterize(path: str) -> str:
    """纯数字 / UUID 路径段参数化。/users/12345 → /users/{id}"""
    parts = [p for p in path.split("/") if p]
    out = []
    for part in parts:
        if re.fullmatch(r"\d+", part) or _looks_like_uuid(part):
            out.append("{id}")
        else:
            out.append(part)
    return "/" + "/".join(out)


def _is_static(path: str) -> bool:
    ext = urlparse(path).path.rsplit(".", 1)[-1].lower() if "." in urlparse(path).path else ""
    return f".{ext}" in STATIC_EXT


def _infer_schema(sample: Any) -> dict:
    if isinstance(sample, dict):
        return {"type": "object", "properties": {k: _infer_schema(v) for k, v in sample.items()}}
    if isinstance(sample, list):
        return {"type": "array", "items": _infer_schema(sample[0]) if sample else {}}
    if isinstance(sample, bool):
        return {"type": "boolean"}
    if isinstance(sample, int):
        return {"type": "integer"}
    if isinstance(sample, float):
        return {"type": "number"}
    return {"type": "string"}


def _merge_examples(samples: list) -> Any:
    """合并多个请求体样本：对象取字段并集，数组取首个。"""
    merged: dict = {}
    for s in samples:
        if isinstance(s, dict):
            for k, v in s.items():
                if k not in merged:
                    merged[k] = v
    return merged


def parse_har(text: str) -> ApiSpec:
    """解析 HAR 文本 → 文档级 ApiSpec（规则解析）。"""
    try:
        root = json.loads(text)
    except Exception:
        return ApiSpec(title="HAR Import", version="", servers=[], base_path="", endpoints=[])

    log = root.get("log", {}) if isinstance(root, dict) else {}
    entries = log.get("entries", []) if isinstance(log, dict) else []

    agg: dict = defaultdict(
        lambda: {
            "count": 0,
            "param_names": defaultdict(int),
            "req_examples": [],
            "status_codes": defaultdict(int),
            "auth": False,
        }
    )

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        req = entry.get("request", {}) or {}
        method = (req.get("method") or "GET").upper()
        if method not in HTTP_METHODS:
            continue
        url = req.get("url", "") or ""
        parsed = urlparse(url)
        path = parsed.path or "/"
        if _is_static(path):
            continue
        path = _parameterize(path)
        key = (method, path)
        bucket = agg[key]
        bucket["count"] += 1

        for qname in parse_qs(parsed.query).keys():
            bucket["param_names"][qname] += 1

        post = req.get("postData", {}) or {}
        body_text = post.get("text")
        if body_text:
            try:
                bucket["req_examples"].append(json.loads(body_text))
            except Exception:
                pass

        for h in req.get("headers", []) or []:
            if isinstance(h, dict) and h.get("name", "").lower() in ("authorization", "cookie"):
                bucket["auth"] = True

        resp = entry.get("response", {}) or {}
        sc = resp.get("status")
        if sc:
            bucket["status_codes"][sc] += 1

    endpoints: list[ApiEndpointSpec] = []
    for (method, path), bucket in agg.items():
        total = bucket["count"]
        params = [
            ParamSpec(
                name=name,
                in_="query",
                type="string",
                required=(cnt == total),
                description="",
                example=None,
            )
            for name, cnt in bucket["param_names"].items()
        ]

        request_body = None
        if bucket["req_examples"]:
            merged = _merge_examples(bucket["req_examples"])
            request_body = ApiRequestBody(
                content_type="application/json",
                required=True,
                schema=_infer_schema(merged) if isinstance(merged, (dict, list)) else {},
                example=merged,
            )

        responses = [
            ResponseSpec(
                status_code=int(sc) if str(sc).isdigit() else 200,
                description="",
                content_type="application/json",
                schema=None,
                example=None,
            )
            for sc, _ in bucket["status_codes"].items()
        ]

        endpoints.append(
            ApiEndpointSpec(
                path=path,
                method=method,
                summary="",
                description="",
                params=params,
                request_body=request_body,
                responses=responses,
                auth_required=bucket["auth"],
                auth_type="bearer" if bucket["auth"] else None,
                confidence=1.0,
            )
        )

    return ApiSpec(
        title="HAR Import",
        version="",
        servers=[],
        base_path="",
        endpoints=endpoints,
    )
