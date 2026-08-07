"""
Python Django 接口提取适配器

解析 urls.py 文件中的 URLconf 路由映射，匹配 path() / re_path() / url() 模式，
关联 views 中的方法签名。
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

# Django path() / re_path() / url() 路由
_RE_DJANGO_PATH = re.compile(
    r'(?:path|re_path|url)\s*\(\s*'
    r'(?:r?["\'])([^"\']+)(?:["\'])\s*,\s*'
    r'([\w.]+)\.(\w+)\s*'
    r'(?:,\s*name\s*=\s*["\'](\w+)["\'])?',
)

# 函数签名
_RE_FUNC_SIGNATURE = re.compile(
    r'def\s+(\w+)\s*\(([^)]*)\)',
)

# 排除目录
_SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "env", ".git",
    "node_modules", ".idea", ".vscode", "dist", "build",
}


@register_adapter("python_django")
class PythonDjangoAdapter(APIExtractorAdapter):
    """Python Django 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 Django 项目的 urls.py 文件，提取路由映射。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        # 查找所有 urls.py 文件
        url_files = [
            f for f in root.rglob("urls.py")
            if not any(part in _SKIP_DIRS for part in f.parts)
        ]

        logger.info(f"PythonDjango adapter: scanning {len(url_files)} urls.py files")

        for url_file in url_files:
            try:
                content = url_file.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {url_file}: {e}")
                continue

            file_apis = self._extract_from_urls(content, url_file, root)
            apis.extend(file_apis)

        logger.info(f"PythonDjango adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_urls(
        self, content: str, url_file: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从 urls.py 内容中提取路由。

        Args:
            content: 文件内容。
            url_file: urls.py 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(url_file.relative_to(root))

        for match in _RE_DJANGO_PATH.finditer(content):
            route_path = match.group(1)
            view_module = match.group(2)
            view_name = match.group(3)
            route_name = match.group(4) or ""

            line_number = content[: match.start()].count("\n") + 1

            # 尝试推断 HTTP 方法（Django 默认处理所有方法）
            # 从路由名称推断
            http_method = self._infer_http_method(route_name, route_path)

            # 尝试查找 view 函数的参数
            params: list[dict[str, Any]] = []
            auth_required = False
            description = ""

            # 尝试在同一文件中查找 view 定义
            view_params = self._find_view_params(content, view_name)
            if view_params:
                params = view_params
                if any("request" in p.get("name", "").lower() for p in params):
                    pass  # request 参数是标准的
                if any("token" in p.get("name", "").lower() or "auth" in p.get("name", "").lower() for p in params):
                    auth_required = True

            apis.append({
                "path": route_path if route_path.startswith("/") else "/" + route_path,
                "http_method": http_method,
                "params": params,
                "return_type": "HttpResponse",
                "method_name": f"{view_module}.{view_name}",
                "file": rel_path,
                "line_number": line_number,
                "auth_required": auth_required,
                "description": f"Django view: {view_name}" + (f" (name={route_name})" if route_name else ""),
            })

        return apis

    def _infer_http_method(self, route_name: str, path: str) -> str:
        """
        从路由名称或路径推断 HTTP 方法。

        Args:
            route_name: 路由名称。
            path: 路由路径。

        Returns:
            推断的 HTTP 方法。
        """
        combined = (route_name + " " + path).lower()
        if any(kw in combined for kw in ("create", "add", "new", "store", "post")):
            return "POST"
        if any(kw in combined for kw in ("update", "edit", "modify", "put", "patch")):
            return "PUT"
        if any(kw in combined for kw in ("delete", "remove", "destroy")):
            return "DELETE"
        return "GET"

    def _find_view_params(self, content: str, view_name: str) -> list[dict[str, Any]]:
        """
        在文件中查找 view 函数定义并提取参数。

        Args:
            content: 文件内容。
            view_name: view 函数名。

        Returns:
            参数定义列表。
        """
        pattern = re.compile(r'def\s+' + re.escape(view_name) + r'\s*\(([^)]*)\)')
        match = pattern.search(content)
        if not match:
            return []

        params_str = match.group(1)
        params: list[dict[str, Any]] = []

        for raw_param in params_str.split(","):
            raw_param = raw_param.strip()
            if not raw_param or raw_param == "self":
                continue
            param_name = raw_param.split(":")[0].split("=")[0].strip()
            if param_name.startswith("*"):
                continue
            params.append({
                "name": param_name,
                "location": "query",
                "type": "Any",
                "required": "=" not in raw_param,
            })

        return params
