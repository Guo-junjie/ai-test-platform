"""
Python Flask 接口提取适配器

扫描 *.py 文件，匹配 @app.route / @blueprint.route / @bp.route 装饰器，
解析 methods 参数获取 HTTP 方法（默认 GET）。
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

# Flask 路由装饰器：@app.route("/path", methods=["GET", "POST"])
_RE_FLASK_ROUTE = re.compile(
    r'@(?:app|blueprint|bp)\.route\s*\(\s*["\']([^"\']+)["\']'
    r'(?:.*?methods\s*=\s*\[([^\]]*)\])?',
    re.MULTILINE | re.DOTALL,
)

# 函数签名
_RE_FUNC_SIGNATURE = re.compile(
    r'(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)',
    re.MULTILINE,
)

# 排除目录
_SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "env", ".git",
    "node_modules", ".idea", ".vscode", "dist", "build",
}


@register_adapter("python_flask")
class PythonFlaskAdapter(APIExtractorAdapter):
    """Python Flask 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 Python 源文件，提取 Flask 路由接口。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        source_files = [
            f for f in root.rglob("*.py")
            if not any(part in _SKIP_DIRS for part in f.parts)
        ]

        logger.info(f"PythonFlask adapter: scanning {len(source_files)} source files")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            if ".route(" not in content:
                continue

            file_apis = self._extract_from_file(content, file_path, root)
            apis.extend(file_apis)

        logger.info(f"PythonFlask adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_file(
        self, content: str, file_path: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从单个 Python 文件中提取 Flask 路由。

        Args:
            content: 文件内容。
            file_path: 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(file_path.relative_to(root))

        for match in _RE_FLASK_ROUTE.finditer(content):
            route_path = match.group(1)
            methods_str = match.group(2) or ""

            # 解析 HTTP 方法
            if methods_str:
                http_methods = re.findall(r'["\'](\w+)["\']', methods_str)
                if not http_methods:
                    http_methods = ["GET"]
            else:
                http_methods = ["GET"]

            line_number = content[: match.start()].count("\n") + 1

            # 查找函数定义
            func_name = "unknown"
            params: list[dict[str, Any]] = []
            auth_required = False

            sig_match = _RE_FUNC_SIGNATURE.search(content, match.end())
            if sig_match:
                func_name = sig_match.group(1)
                func_params_str = sig_match.group(2)
                params = self._parse_params(func_params_str)
                # 检测认证相关参数
                param_text = func_params_str.lower()
                if any(kw in param_text for kw in ("token", "auth", "jwt", "session")):
                    auth_required = True

            description = self._extract_docstring(content, sig_match.end() if sig_match else match.end())

            # 为每个 HTTP 方法创建一条记录
            for http_method in http_methods:
                apis.append(
                    {
                        "path": route_path,
                        "http_method": http_method.upper(),
                        "params": params,
                        "return_type": "Response",
                        "method_name": func_name,
                        "file": rel_path,
                        "line_number": line_number,
                        "auth_required": auth_required,
                        "description": description,
                    }
                )

        return apis

    def _parse_params(self, params_str: str) -> list[dict[str, Any]]:
        """
        解析函数参数。

        Args:
            params_str: 参数字符串。

        Returns:
            参数定义列表。
        """
        params: list[dict[str, Any]] = []
        if not params_str.strip():
            return params

        for raw_param in params_str.split(","):
            raw_param = raw_param.strip()
            if not raw_param or raw_param == "self":
                continue
            if raw_param.startswith("*"):
                continue

            if ":" in raw_param:
                parts = raw_param.split(":", 1)
                param_name = parts[0].strip()
                type_str = parts[1].split("=")[0].strip()
                params.append({
                    "name": param_name,
                    "location": "query",
                    "type": type_str,
                    "required": "=" not in parts[1],
                })
            else:
                param_name = raw_param.split("=")[0].strip()
                params.append({
                    "name": param_name,
                    "location": "query",
                    "type": "str",
                    "required": "=" not in raw_param,
                })

        return params

    def _extract_docstring(self, content: str, pos: int) -> str:
        """提取函数 docstring 首行。"""
        search_region = content[pos : pos + 200]
        for quote in ('"""', "'''"):
            start = search_region.find(quote)
            if start != -1:
                end = search_region.find(quote, start + 3)
                if end != -1:
                    docstring = search_region[start + 3 : end].strip()
                    lines = [l.strip() for l in docstring.split("\n") if l.strip()]
                    return lines[0] if lines else ""
        return ""
