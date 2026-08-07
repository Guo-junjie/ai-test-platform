"""
Go Gin 接口提取适配器

扫描 *.go 文件，正则匹配 r.GET( / r.POST( / router.GET( / router.POST( 等模式，
提取路径和 HTTP 方法。
"""

import re
from pathlib import Path
from typing import Any

from app.modules.code_analyzer.adapters import (
    APIExtractorAdapter,
    register_adapter,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ==================== 正则预编译 ====================

# Gin 路由：r.GET("/path", handler) / router.POST("/path", handler)
_RE_GIN_ROUTE = re.compile(
    r'\b(?:r|router|engine|api|group)\.(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*'
    r'"([^"]*)"',
)

# 函数签名：func (h *Handler) methodName(
_RE_FUNC_SIGNATURE = re.compile(
    r'func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(',
)

# 排除目录
_SKIP_DIRS = {".git", "vendor", "node_modules", "dist", "build"}


@register_adapter("go_gin")
class GoGinAdapter(APIExtractorAdapter):
    """Go Gin 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 Go 源文件，提取 Gin 路由接口。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        source_files = [
            f for f in root.rglob("*.go")
            if not any(part in _SKIP_DIRS for part in f.parts)
        ]

        logger.info(f"GoGin adapter: scanning {len(source_files)} source files")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            if not any(kw in content for kw in (".GET(", ".POST(", ".PUT(", ".DELETE(")):
                continue

            file_apis = self._extract_from_file(content, file_path, root)
            apis.extend(file_apis)

        logger.info(f"GoGin adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_file(
        self, content: str, file_path: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从单个 Go 文件中提取 Gin 路由。

        Args:
            content: 文件内容。
            file_path: 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(file_path.relative_to(root))

        for match in _RE_GIN_ROUTE.finditer(content):
            http_method = match.group(1)
            route_path = match.group(2)
            line_number = content[: match.start()].count("\n") + 1

            # 尝试查找 handler 函数名
            handler_name = "anonymous"
            sig_match = _RE_FUNC_SIGNATURE.search(content, match.end())
            if sig_match:
                handler_name = sig_match.group(1)

            # 提取注释作为描述
            description = self._extract_comment(content, match.start())

            apis.append({
                "path": route_path if route_path.startswith("/") else "/" + route_path,
                "http_method": http_method,
                "params": [],
                "return_type": "void",
                "method_name": handler_name,
                "file": rel_path,
                "line_number": line_number,
                "auth_required": False,
                "description": description,
            })

        return apis

    def _extract_comment(self, content: str, pos: int) -> str:
        """
        提取路由上方的注释作为描述。

        Args:
            content: 文件内容。
            pos: 路由位置。

        Returns:
            注释文本，无则返回空字符串。
        """
        before = content[:pos].rstrip()
        if not before.endswith("//"):
            # 查找上一行是否是注释
            lines = before.split("\n")
            if lines and lines[-1].strip().startswith("//"):
                return lines[-1].strip().lstrip("/").strip()
        else:
            return before[before.rfind("//") + 2 :].strip()
        return ""
