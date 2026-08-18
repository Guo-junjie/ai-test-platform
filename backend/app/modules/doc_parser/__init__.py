"""
doc_parser 包 — 统一中间表示与四种格式解析器

对外暴露：
- ApiSpec / ApiEndpointSpec / ParamSpec / ResponseSpec：统一中间表示
- parse_document(format, storage_path, use_ai, raw_text, max_endpoints)：编排入口
"""

from app.modules.doc_parser.schemas import (
    ApiSpec,
    ApiEndpointSpec,
    ParamSpec,
    ResponseSpec,
)
from app.modules.doc_parser.parser_service import parse_document

__all__ = [
    "ApiSpec",
    "ApiEndpointSpec",
    "ParamSpec",
    "ResponseSpec",
    "parse_document",
]
