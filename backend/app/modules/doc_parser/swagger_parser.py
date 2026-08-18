"""
swagger_parser — OpenAPI 2.0 / 3.x 规则解析（不依赖 AI，parse_engine=rule）

支持：
- YAML 或 JSON（pyyaml.safe_load / json.loads）
- $ref 递归解引用（components/schemas、definitions），深度上限 10 防循环
- swagger2 的 body parameter 转 request_body；consumes/produces 转 content_type
- security + securitySchemes → auth_required / auth_type
- basePath / servers[].url 计入 meta 的 base_path（不污染 path）
"""

import json
from typing import Any
from urllib.parse import urlparse

import yaml

from app.modules.doc_parser.schemas import (
    ApiSpec,
    ApiEndpointSpec,
    ParamSpec,
    ResponseSpec,
    ApiRequestBody,
)

HTTP_METHODS = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "head",
    "options",
    "trace",
}


def _load_doc(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    if text[0] in ("{", "["):
        return json.loads(text)
    return yaml.safe_load(text) or {}


def _deref(node: Any, root: dict, depth: int = 0) -> Any:
    """递归解引用 $ref。深度上限 10 防止循环引用。"""
    if depth > 10:
        return node
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            parts = [p for p in ref.lstrip("#/").split("/") if p]
            cur: Any = root
            for p in parts:
                if not isinstance(cur, dict) or p not in cur:
                    return None
                cur = cur[p]
            return _deref(cur, root, depth + 1)
        return {k: _deref(v, root, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_deref(v, root, depth + 1) for v in node]
    return node


def _json_type(t: Any) -> str:
    if not t:
        return "string"
    return str(t).lower()


def _infer_params(operation: dict, path_level_params: list, root: dict) -> list[ParamSpec]:
    params: list[ParamSpec] = []
    for p in (path_level_params or []) + (operation.get("parameters", []) or []):
        p = _deref(p, root)
        if not isinstance(p, dict):
            continue
        # swagger2 body 参数在 _build_request_body 单独处理
        if p.get("in") == "body":
            continue
        params.append(
            ParamSpec(
                name=p.get("name", ""),
                in_=p.get("in", "query"),
                type=_json_type(p.get("type", "string")),
                required=bool(p.get("required", False)),
                description=p.get("description", "") or "",
                example=p.get("x-example", p.get("example")),
            )
        )
    return params


def _build_request_body(operation: dict, root: dict) -> ApiRequestBody | None:
    rb = operation.get("requestBody")
    if rb:
        rb = _deref(rb, root)
        content = rb.get("content", {}) if isinstance(rb, dict) else {}
        ct = next(iter(content), "application/json")
        media = content.get(ct, {}) if isinstance(content, dict) else {}
        return ApiRequestBody(
            content_type=ct,
            required=bool(rb.get("required", False)),
            schema=_deref(media.get("schema"), root) if isinstance(media, dict) else None,
            example=media.get("example") if isinstance(media, dict) else None,
        )
    # swagger2 body parameter
    for p in operation.get("parameters", []) or []:
        p = _deref(p, root)
        if isinstance(p, dict) and p.get("in") == "body":
            consumes = operation.get("consumes") or []
            ct = consumes[0] if consumes else "application/json"
            return ApiRequestBody(
                content_type=ct,
                required=bool(p.get("required", False)),
                schema=_deref(p.get("schema"), root) if p.get("schema") else {},
                example=None,
            )
    return None


def _build_responses(operation: dict, root: dict) -> list[ResponseSpec]:
    out: list[ResponseSpec] = []
    responses = operation.get("responses", {}) or {}
    for status_code, resp in responses.items():
        resp = _deref(resp, root)
        if not isinstance(resp, dict):
            continue
        content = resp.get("content", {}) if isinstance(resp, dict) else {}
        ct = next(iter(content), "application/json") if content else "application/json"
        media = content.get(ct, {}) if isinstance(content, dict) else {}
        try:
            sc = int(status_code)
        except (ValueError, TypeError):
            sc = 200
        out.append(
            ResponseSpec(
                status_code=sc,
                description=resp.get("description", "") or "",
                content_type=ct,
                schema=_deref(media.get("schema"), root) if isinstance(media, dict) else None,
                example=media.get("example") if isinstance(media, dict) else None,
            )
        )
    return out


def _detect_auth(operation: dict, root: dict) -> tuple[bool, str | None]:
    security = operation.get("security", None)
    if security is None:
        security = root.get("security", None)
    if not security:
        return False, None
    schemes = root.get("securityDefinitions") or root.get("components", {}).get(
        "securitySchemes", {}
    )
    first = security[0] if isinstance(security, list) and security else None
    if not isinstance(first, dict):
        return True, None
    scheme_name = next(iter(first), None)
    if not scheme_name or scheme_name not in schemes:
        return True, None
    sdef = _deref(schemes[scheme_name], root)
    if not isinstance(sdef, dict):
        return True, None
    t = sdef.get("type")
    if t == "http":
        return True, (sdef.get("scheme") or "http").lower()
    if t == "apiKey":
        return True, "apikey"
    if t == "oauth2":
        return True, "oauth2"
    return True, "bearer"


def parse_swagger(text: str) -> ApiSpec:
    """解析 OpenAPI/Swagger 文本 → 文档级 ApiSpec（规则解析）。"""
    root = _load_doc(text)
    if not isinstance(root, dict):
        return ApiSpec(title="", version="", servers=[], base_path="", endpoints=[])

    info = root.get("info", {}) if isinstance(root.get("info"), dict) else {}
    title = info.get("title", "") if isinstance(info, dict) else ""
    version = info.get("version", "") if isinstance(info, dict) else ""

    base_path = root.get("basePath", "") if isinstance(root.get("basePath"), str) else ""
    servers = root.get("servers", []) or []
    server_urls = (
        [s.get("url", "") for s in servers if isinstance(s, dict)]
        if servers
        else []
    )
    if not base_path and server_urls:
        base_path = urlparse(server_urls[0]).path if server_urls else ""

    endpoints: list[ApiEndpointSpec] = []
    paths = root.get("paths", {}) or {}
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        path_level_params = item.get("parameters", []) or []
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            auth_required, auth_type = _detect_auth(operation, root)
            endpoints.append(
                ApiEndpointSpec(
                    path=path,
                    method=method.upper(),
                    summary=operation.get("summary", "") or "",
                    description=operation.get("description", "") or "",
                    params=_infer_params(operation, path_level_params, root),
                    request_body=_build_request_body(operation, root),
                    responses=_build_responses(operation, root),
                    auth_required=auth_required,
                    auth_type=auth_type,
                    confidence=1.0,
                )
            )

    return ApiSpec(
        title=title,
        version=version,
        servers=server_urls,
        base_path=base_path,
        endpoints=endpoints,
    )
