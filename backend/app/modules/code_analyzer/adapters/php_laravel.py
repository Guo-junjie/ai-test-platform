"""
PHP Laravel 接口提取适配器

解析 routes/api.php 和 routes/web.php 路由文件，
匹配 Route::get( / Route::post( / Route::resource( 模式。
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

# Route::get("/path", [Controller::class, 'method'])
_RE_ROUTE_METHOD = re.compile(
    r'Route::(get|post|put|delete|patch|options|any)\s*\(\s*'
    r'["\']([^"\']+)["\']\s*,\s*'
    r'(?:\[?([\w\\]+)::class\s*,\s*[\'"](\w+)[\'"]\]?|([\w\\\\]+@?\w*))',
)

# Route::resource("users", UserController::class)
_RE_RESOURCE = re.compile(
    r'Route::resource\s*\(\s*'
    r'["\']([^"\']+)["\']\s*,\s*'
    r'([\w\\]+)::class',
)

# Route::group(["prefix" => "api"], function() { ... })
_RE_GROUP_PREFIX = re.compile(
    r'Route::group\s*\(\s*\[[^\]]*["\']prefix["\']\s*=>\s*["\']([^"\']+)["\']',
)

# 标准资源路由方法映射
_RESOURCE_METHODS = {
    "index": ("GET", ""),
    "create": ("GET", "/create"),
    "store": ("POST", ""),
    "show": ("GET", "/{id}"),
    "edit": ("GET", "/{id}/edit"),
    "update": ("PUT", "/{id}"),
    "destroy": ("DELETE", "/{id}"),
}


@register_adapter("php_laravel")
class PhpLaravelAdapter(APIExtractorAdapter):
    """PHP Laravel 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 Laravel 路由文件，提取 API 接口。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        # 查找路由文件
        route_file_paths = [
            root / "routes" / "api.php",
            root / "routes" / "web.php",
        ]

        existing_route_files = [f for f in route_file_paths if f.exists()]

        # 也扫描其他 routes 目录下的 .php 文件
        routes_dir = root / "routes"
        if routes_dir.is_dir():
            for php_file in routes_dir.glob("*.php"):
                if php_file not in existing_route_files:
                    existing_route_files.append(php_file)

        logger.info(
            f"PhpLaravel adapter: scanning {len(existing_route_files)} route files"
        )

        for route_file in existing_route_files:
            try:
                content = route_file.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {route_file}: {e}")
                continue

            rel_path = str(route_file.relative_to(root))

            # 提取 group 前缀
            group_prefix = ""
            group_match = _RE_GROUP_PREFIX.search(content)
            if group_match:
                group_prefix = group_match.group(1)

            # 提取 Route::method 路由
            for match in _RE_ROUTE_METHOD.finditer(content):
                http_method = match.group(1).upper()
                route_path = match.group(2)
                controller_name = match.group(3) or match.group(5) or ""
                method_name = match.group(4) or ""

                full_path = self._join_path(group_prefix, route_path)
                line_number = content[: match.start()].count("\n") + 1

                apis.append({
                    "path": full_path,
                    "http_method": http_method,
                    "params": [],
                    "return_type": "Response",
                    "method_name": f"{controller_name}::{method_name}" if method_name else controller_name,
                    "file": rel_path,
                    "line_number": line_number,
                    "auth_required": "auth" in content[: match.start()].lower(),
                    "description": f"Laravel route: {route_path}",
                })

            # 提取 Route::resource 路由（自动展开为 7 个 RESTful 方法）
            for match in _RE_RESOURCE.finditer(content):
                resource_name = match.group(1)
                controller_name = match.group(2)

                line_number = content[: match.start()].count("\n") + 1

                for action, (http_method, path_suffix) in _RESOURCE_METHODS.items():
                    full_path = self._join_path(
                        group_prefix,
                        resource_name + path_suffix,
                    )
                    apis.append({
                        "path": full_path,
                        "http_method": http_method,
                        "params": [],
                        "return_type": "Response",
                        "method_name": f"{controller_name}::{action}",
                        "file": rel_path,
                        "line_number": line_number,
                        "auth_required": "auth" in content[: match.start()].lower(),
                        "description": f"Laravel resource: {resource_name}.{action}",
                    })

        logger.info(f"PhpLaravel adapter: extracted {len(apis)} APIs")
        return apis

    def _join_path(self, prefix: str, suffix: str) -> str:
        """拼接路径。"""
        if not prefix:
            return suffix if suffix.startswith("/") else "/" + suffix
        if not suffix:
            return prefix
        return prefix.rstrip("/") + "/" + suffix.lstrip("/")
