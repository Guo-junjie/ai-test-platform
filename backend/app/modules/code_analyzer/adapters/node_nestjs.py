"""
Node.js NestJS 接口提取适配器

扫描 *.ts 文件，匹配 @Controller( / @Get( / @Post( / @Put( / @Delete( 装饰器，
提取控制器前缀和方法级别路由。
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

# 类级别 @Controller("/api/users")
_RE_CONTROLLER = re.compile(
    r'@Controller\s*\(\s*["\']([^"\']*)["\']\s*\)',
    re.MULTILINE,
)

# 方法级别装饰器：@Get("/path") / @Post("/path") / @Put() / @Delete(":id")
_RE_METHOD_DECORATOR = re.compile(
    r'@(Get|Post|Put|Delete|Patch)\s*\(\s*["\']?([^"\')]*)["\']?\s*\)',
    re.MULTILINE,
)

# 方法签名
_RE_METHOD_SIGNATURE = re.compile(
    r'(?:async\s+)?(\w+)\s*\(([^)]*)\)',
    re.MULTILINE,
)

# 认证装饰器
_RE_AUTH_DECORATOR = re.compile(r'@(UseGuards|Roles|Public)\b')

# 排除目录
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build",
    ".idea", ".vscode", "coverage",
}

_HTTP_METHOD_MAP = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
}


@register_adapter("node_nestjs")
class NodeNestJSAdapter(APIExtractorAdapter):
    """Node.js NestJS 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 TypeScript 源文件，提取 NestJS 路由接口。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        source_files = [
            f for f in root.rglob("*.ts")
            if not any(part in _SKIP_DIRS for part in f.parts)
            and not f.name.endswith((".d.ts", ".spec.ts"))
        ]

        logger.info(f"NodeNestJS adapter: scanning {len(source_files)} source files")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            if "@Controller" not in content:
                continue

            file_apis = self._extract_from_file(content, file_path, root)
            apis.extend(file_apis)

        logger.info(f"NodeNestJS adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_file(
        self, content: str, file_path: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从单个 TypeScript 文件中提取 NestJS 路由。

        Args:
            content: 文件内容。
            file_path: 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(file_path.relative_to(root))

        # 提取控制器前缀
        controller_prefix = ""
        ctrl_match = _RE_CONTROLLER.search(content)
        if ctrl_match:
            controller_prefix = ctrl_match.group(1)

        # 检测类级别认证
        class_auth = bool(_RE_AUTH_DECORATOR.search(content))

        # 提取方法级别路由
        for match in _RE_METHOD_DECORATOR.finditer(content):
            # 跳过 @Controller 之后的 @Get 等非路由装饰器（实际不会匹配到）
            http_method = _HTTP_METHOD_MAP.get(match.group(1), "GET")
            method_path = match.group(2)

            full_path = self._join_path(controller_prefix, method_path)
            line_number = content[: match.start()].count("\n") + 1

            # 查找方法签名
            method_name = "unknown"
            params: list[dict[str, Any]] = []
            return_type = "any"

            sig_match = _RE_METHOD_SIGNATURE.search(content, match.end())
            if sig_match:
                method_name = sig_match.group(1)
                params_str = sig_match.group(2)
                params = self._parse_params(params_str)

            # 检测认证
            auth_required = class_auth

            # 提取注释
            description = self._extract_comment(content, match.start())

            apis.append({
                "path": full_path,
                "http_method": http_method,
                "params": params,
                "return_type": return_type,
                "method_name": method_name,
                "file": rel_path,
                "line_number": line_number,
                "auth_required": auth_required,
                "description": description,
            })

        return apis

    def _parse_params(self, params_str: str) -> list[dict[str, Any]]:
        """解析 TypeScript 方法参数。"""
        params: list[dict[str, Any]] = []
        if not params_str.strip():
            return params

        for raw_param in self._split_params(params_str):
            raw_param = raw_param.strip()
            if not raw_param:
                continue

            # 去掉装饰器前缀
            param_clean = re.sub(r'@\w+\([^)]*\)\s*', '', raw_param).strip()

            # 解析 参数名: 类型
            if ":" in param_clean:
                parts = param_clean.split(":", 1)
                param_name = parts[0].strip().lstrip("?")
                type_str = parts[1].split("=")[0].strip()
                params.append({
                    "name": param_name,
                    "location": "body" if "Body" in raw_param else "query",
                    "type": type_str,
                    "required": not param_clean.startswith(param_name + "?"),
                })
            else:
                param_name = param_clean.split("=")[0].strip().lstrip("?")
                params.append({
                    "name": param_name,
                    "location": "query",
                    "type": "any",
                    "required": "=" not in param_clean,
                })

        return params

    def _split_params(self, params_str: str) -> list[str]:
        """按逗号分割参数，处理嵌套括号。"""
        parts: list[str] = []
        depth = 0
        current = ""
        for char in params_str:
            if char in "([{":
                depth += 1
                current += char
            elif char in ")]}":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += char
        if current.strip():
            parts.append(current)
        return parts

    def _join_path(self, prefix: str, suffix: str) -> str:
        """拼接路径。"""
        if not prefix and not suffix:
            return "/"
        if not prefix:
            return suffix if suffix.startswith("/") else "/" + suffix
        if not suffix:
            return prefix if prefix.startswith("/") else "/" + prefix
        return prefix.rstrip("/") + "/" + suffix.lstrip("/")

    def _extract_comment(self, content: str, pos: int) -> str:
        """提取注释。"""
        before = content[:pos]
        lines = before.split("\n")
        for line in reversed(lines[-5:]):
            stripped = line.strip()
            if stripped.startswith("//"):
                return stripped.lstrip("/").strip()
        return ""
