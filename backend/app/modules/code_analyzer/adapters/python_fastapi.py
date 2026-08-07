"""
Python FastAPI 接口提取适配器

扫描 *.py 文件，匹配 @app.get / @app.post / @router.get / @router.post 等装饰器，
提取路径和 HTTP 方法。解析 Pydantic 模型参数和 Depends() 依赖注入。
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

# FastAPI 路由装饰器：@app.get("/path") / @router.post("/path") / @app.put("/path") 等
_RE_ROUTE_DECORATOR = re.compile(
    r'@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']*)["\']'
    r'(?:.*?status_code\s*=\s*(\d+))?',
    re.MULTILINE,
)

# 函数签名：async def func_name( 或 def func_name(
_RE_FUNC_SIGNATURE = re.compile(
    r'(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)',
    re.MULTILINE,
)

# Pydantic 模型参数：param_name: ModelType
_RE_TYPED_PARAM = re.compile(r'(\w+)\s*:\s*([\w.]+)')

# Depends() 依赖注入
_RE_DEPENDS = re.compile(r'Depends\s*\(')

# 认证相关关键词
_AUTH_KEYWORDS = {"auth", "token", "jwt", "oauth", "api_key", "current_user"}

# 排除目录
_SKIP_DIRS = {
    "__pycache__", ".venv", "venv", "env", ".git",
    "node_modules", ".idea", ".vscode", "dist", "build",
}


@register_adapter("python_fastapi")
class PythonFastAPIAdapter(APIExtractorAdapter):
    """Python FastAPI 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 Python 源文件，提取 FastAPI 路由接口。

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

        logger.info(f"PythonFastAPI adapter: scanning {len(source_files)} source files")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            if "@app." not in content and "@router." not in content:
                continue

            file_apis = self._extract_from_file(content, file_path, root)
            apis.extend(file_apis)

        logger.info(f"PythonFastAPI adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_file(
        self, content: str, file_path: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从单个 Python 文件中提取 FastAPI 路由。

        Args:
            content: 文件内容。
            file_path: 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(file_path.relative_to(root))

        for match in _RE_ROUTE_DECORATOR.finditer(content):
            http_method = match.group(1).upper()
            route_path = match.group(2)
            line_number = content[: match.start()].count("\n") + 1

            # 查找紧随装饰器之后的函数定义
            func_name = "unknown"
            params: list[dict[str, Any]] = []
            return_type = "dict"
            auth_required = False

            sig_match = _RE_FUNC_SIGNATURE.search(content, match.end())
            if sig_match:
                func_name = sig_match.group(1)
                func_params_str = sig_match.group(2)
                params, auth_required = self._parse_func_params(func_params_str)

                # 尝试提取返回类型注解
                after_sig = content[sig_match.end():sig_sig_end + 200] if (
                    (sig_sig_end := sig_match.end()) < len(content)
                ) else ""
                ret_match = re.search(r'->\s*([\w.\[\]]+)', after_sig)
                if ret_match:
                    return_type = ret_match.group(1)

            # 提取 docstring 作为描述
            description = self._extract_docstring(content, sig_match.end() if sig_match else match.end())

            apis.append(
                {
                    "path": route_path if route_path.startswith("/") else "/" + route_path,
                    "http_method": http_method,
                    "params": params,
                    "return_type": return_type,
                    "method_name": func_name,
                    "file": rel_path,
                    "line_number": line_number,
                    "auth_required": auth_required,
                    "description": description,
                }
            )

        return apis

    def _parse_func_params(
        self, params_str: str
    ) -> tuple[list[dict[str, Any]], bool]:
        """
        解析函数参数字符串，提取参数定义和认证标记。

        Args:
            params_str: 函数参数字符串（括号内部分）。

        Returns:
            (参数列表, 是否需要认证)。
        """
        params: list[dict[str, Any]] = []
        auth_required = False

        if not params_str.strip():
            return params, auth_required

        # 按逗号分割参数（简单分割，不处理嵌套括号中的逗号）
        # 先标记 Depends() 参数
        has_depends = bool(_RE_DEPENDS.search(params_str))

        # 逐个参数解析
        for raw_param in self._split_params(params_str):
            raw_param = raw_param.strip()
            if not raw_param or raw_param == "self":
                continue

            # 跳过 *args / **kwargs
            if raw_param.startswith("*"):
                continue

            # 检查是否有类型注解
            if ":" in raw_param:
                parts = raw_param.split(":", 1)
                param_name = parts[0].strip()
                type_part = parts[1].strip()

                # 去掉默认值
                type_str = type_part.split("=")[0].strip()

                # 检查是否是路径参数（FastAPI 中 path 参数无特殊注解，通过路径中的 {param} 推断）
                # 检查认证相关
                param_lower = param_name.lower()
                type_lower = type_str.lower()
                if any(kw in param_lower or kw in type_lower for kw in _AUTH_KEYWORDS):
                    auth_required = True

                # 检查 Depends
                if "Depends" in type_str:
                    auth_required = auth_required or has_depends
                    params.append({
                        "name": param_name,
                        "location": "dependency",
                        "type": "Depends",
                        "required": True,
                    })
                elif type_str.startswith("Body") or "BaseModel" in type_str or "Pydantic" in type_str:
                    params.append({
                        "name": param_name,
                        "location": "body",
                        "type": type_str,
                        "required": True,
                    })
                else:
                    params.append({
                        "name": param_name,
                        "location": "query",
                        "type": type_str,
                        "required": "=" not in type_part,
                    })
            else:
                # 无类型注解的参数
                param_name = raw_param.split("=")[0].strip()
                params.append({
                    "name": param_name,
                    "location": "query",
                    "type": "str",
                    "required": "=" not in raw_param,
                })

        return params, auth_required

    def _split_params(self, params_str: str) -> list[str]:
        """
        按逗号分割参数，处理嵌套括号。

        Args:
            params_str: 参数字符串。

        Returns:
            参数片段列表。
        """
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

    def _extract_docstring(self, content: str, pos: int) -> str:
        """
        提取函数 docstring 作为描述。

        Args:
            content: 文件内容。
            pos: 函数定义后的位置。

        Returns:
            docstring 首行，无则返回空字符串。
        """
        # 在 pos 之后 200 字符内查找三引号
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
