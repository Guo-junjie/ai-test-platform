"""
Node.js Express 接口提取适配器

扫描 *.js / *.ts 文件，匹配 app.get( / app.post( / router.get( / router.post( 模式，
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

# Express 路由：app.get("/path", handler) / router.post("/path", handler)
_RE_EXPRESS_ROUTE = re.compile(
    r'\b(?:app|router|route)\.(get|post|put|delete|patch)\s*\(\s*'
    r'["\']([^"\']+)["\']',
)

# 函数签名：function handlerName( / const handlerName = (
_RE_FUNC_NAME = re.compile(
    r'(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\(?|(\w+)\s*=>)',
)

# 排除目录
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build",
    ".idea", ".vscode", "coverage",
}


@register_adapter("node_express")
class NodeExpressAdapter(APIExtractorAdapter):
    """Node.js Express 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 JavaScript/TypeScript 源文件，提取 Express 路由接口。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        source_files: list[Path] = []
        for ext in ("*.js", "*.ts", "*.mjs"):
            source_files.extend(
                f for f in root.rglob(ext)
                if not any(part in _SKIP_DIRS for part in f.parts)
            )

        logger.info(f"NodeExpress adapter: scanning {len(source_files)} source files")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            if ".get(" not in content and ".post(" not in content and ".put(" not in content and ".delete(" not in content:
                continue

            file_apis = self._extract_from_file(content, file_path, root)
            apis.extend(file_apis)

        logger.info(f"NodeExpress adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_file(
        self, content: str, file_path: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从单个 JS/TS 文件中提取 Express 路由。

        Args:
            content: 文件内容。
            file_path: 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(file_path.relative_to(root))

        for match in _RE_EXPRESS_ROUTE.finditer(content):
            http_method = match.group(1).upper()
            route_path = match.group(2)
            line_number = content[: match.start()].count("\n") + 1

            # 尝试提取 handler 名称
            handler_name = "anonymous"
            sig_match = _RE_FUNC_NAME.search(content, match.end())
            if sig_match:
                handler_name = sig_match.group(1) or sig_match.group(2) or sig_match.group(3) or "anonymous"

            # 提取注释
            description = self._extract_comment(content, match.start())

            apis.append({
                "path": route_path,
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
        """提取路由上方的注释。"""
        before = content[:pos]
        lines = before.split("\n")
        # 查找上方最近的注释行
        for line in reversed(lines[-5:]):
            stripped = line.strip()
            if stripped.startswith("//"):
                return stripped.lstrip("/").strip()
            if stripped.startswith("/*"):
                return stripped.lstrip("/*").rstrip("*/").strip()
        return ""
