"""
统一接口提取器 — 根据技术栈自动选择适配器提取 API 接口

作为 StackDetector 和各适配器之间的调度层，提供统一的 extract() 入口。

- 框架项目（fastapi/flask/spring/...）：走对应适配器，提取 HTTP 接口。
- 通用语言项目（纯 python/java/js/... 无 Web 框架）：走通用提取器，
  提取函数 / 类 / 路由模式等代码单元，保证分析不为空。
"""

import re
from pathlib import Path
from typing import Any

from app.modules.code_analyzer.stack_detector import GENERIC_LANGUAGES
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 各语言源码扩展名
_LANG_EXT: dict[str, set[str]] = {
    "python": {".py"},
    "java": {".java"},
    "kotlin": {".kt", ".kts"},
    "go": {".go"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "php": {".php"},
}

# 函数 / 方法 / 类 提取正则（按语言）
_DEF_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"(?:async\s+)?def\s+(\w+)\s*\("),
        re.compile(r"class\s+(\w+)"),
    ],
    "javascript": [
        re.compile(r"(?:async\s+)?function\s+(\w+)\s*\("),
        re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*\([^)]*\)\s*=>"),
        re.compile(r"class\s+(\w+)"),
    ],
    "typescript": [
        re.compile(r"(?:async\s+)?function\s+(\w+)\s*\("),
        re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*\([^)]*\)\s*=>"),
        re.compile(r"class\s+(\w+)"),
    ],
    "java": [
        re.compile(
            r"(?:public|private|protected|static|final|synchronized|abstract|\s)+"
            r"[\w.<>\[\],\s]*?(\w+)\s*\("
        ),
        re.compile(r"class\s+(\w+)"),
        re.compile(r"interface\s+(\w+)"),
    ],
    "kotlin": [
        re.compile(r"fun\s+(\w+)\s*\("),
        re.compile(r"class\s+(\w+)"),
    ],
    "go": [
        re.compile(r"func\s+(?:\([^)]*\)\s*)?(\w+)\s*\("),
        re.compile(r"type\s+(\w+)\s+struct"),
    ],
    "php": [
        re.compile(r"function\s+(\w+)\s*\("),
        re.compile(r"class\s+(\w+)"),
    ],
}

# 路由模式（启发式，跨语言）
# 每个正则捕获组约定：
# - 2 组：(HTTP方法, 路径)
# - 1 组：(路径)，方法默认 GET
_ROUTE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'@(?:app|router|bp)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']*)["\']'),  # python fastapi
    re.compile(r'@(?:\w+)\.route\s*\(\s*["\']([^"\']*)["\']'),  # python flask 风格（方法默认 GET）
    re.compile(r'(?:router|app|r|routerGroup)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']*)["\']'),  # js/go
    re.compile(r'@(Get|Post|Put|Delete|Patch|RequestMapping)\s*\(\s*["\']([^"\']*)["\']'),  # java/spring
    re.compile(r'Route::(get|post|put|delete|patch)\s*\(\s*["\']([^"\']*)["\']'),  # php/laravel
    re.compile(r'\.HandleFunc\s*\(\s*["\']([^"\']*)["\']'),  # go http
]

_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "env", ".idea", ".vscode", "dist", "build", "target",
}


class APIExtractor:
    """
    统一接口提取器。

    根据 StackDetector 返回的技术栈信息，自动选择对应的适配器，
    调用适配器的 extract_apis() 方法提取所有 API 接口定义。
    无框架适配器但语言已知时，回退到通用提取器。
    """

    def extract(self, project_path: str, stack_info: dict[str, Any]) -> list[dict[str, Any]]:
        """
        根据技术栈选择适配器提取所有 API 接口。

        Args:
            project_path: 项目根目录路径。
            stack_info: StackDetector.detect() 返回的技术栈信息，
                需包含 "stack" 字段。

        Returns:
            标准化接口定义列表。如果技术栈不支持也无通用提取能力，返回空列表。
        """
        from app.modules.code_analyzer.adapters import get_adapter

        stack_name = stack_info.get("stack", "unknown")

        if stack_name == "unknown":
            logger.warning(
                f"Tech stack is unknown, cannot extract APIs. "
                f"Please check if the project has recognizable source files."
            )
            return []

        adapter = get_adapter(stack_name)

        if adapter is not None:
            logger.info(f"Extracting APIs using adapter: {stack_name}")
            try:
                apis = adapter.extract_apis(project_path)
                logger.info(
                    f"Extracted {len(apis)} APIs from {stack_name} project "
                    f"at {project_path}"
                )
                return apis
            except Exception as e:
                logger.error(
                    f"Failed to extract APIs for stack {stack_name}: {e}",
                    exc_info=True,
                )
                return []

        # 无框架适配器，但属于已知通用语言 → 通用提取
        if stack_name in GENERIC_LANGUAGES:
            logger.info(
                f"No framework adapter for stack {stack_name}; "
                f"falling back to generic code-unit extraction"
            )
            return self._generic_extract(project_path, stack_name)

        logger.warning(
            f"No adapter registered for stack: {stack_name}. "
            f"Skipping API extraction."
        )
        return []

    def _generic_extract(self, project_path: str, language: str) -> list[dict[str, Any]]:
        """
        通用代码单元提取（无 Web 框架时兜底）。

        扫描源码文件，提取：
        - 路由模式（启发式，跨语言）
        - 函数 / 方法 / 类 定义

        Args:
            project_path: 项目根目录路径。
            language: 已识别的编程语言名。

        Returns:
            代码单元字典列表（字段与框架适配器输出兼容）。
        """
        root = Path(project_path)
        exts = _LANG_EXT.get(language, set())
        if not exts:
            return []

        patterns = _DEF_PATTERNS.get(language, [])
        units: list[dict[str, Any]] = []

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in exts:
                continue
            if any(part in _SKIP_DIRS for part in file_path.parts):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            rel = str(file_path.relative_to(root))

            # 路由模式
            for rp in _ROUTE_PATTERNS:
                for m in rp.finditer(content):
                    groups = m.groups()
                    if len(groups) >= 2:
                        method = groups[0].upper()
                        route = groups[1]
                    else:
                        method = "GET"
                        route = groups[0]
                    line_number = content[: m.start()].count("\n") + 1
                    units.append({
                        "path": route if route.startswith("/") else "/" + route,
                        "http_method": method,
                        "params": [],
                        "return_type": "",
                        "method_name": "route",
                        "file": rel,
                        "line_number": line_number,
                        "auth_required": False,
                        "description": "",
                        "unit_type": "route",
                    })

            # 函数 / 类
            for pat in patterns:
                for m in pat.finditer(content):
                    name = m.group(1)
                    line_number = content[: m.start()].count("\n") + 1
                    units.append({
                        "path": f"{rel}::{name}",
                        "http_method": "CALL",
                        "params": [],
                        "return_type": "",
                        "method_name": name,
                        "file": rel,
                        "line_number": line_number,
                        "auth_required": False,
                        "description": "",
                        "unit_type": "function",
                    })

        logger.info(
            f"Generic extractor ({language}) extracted {len(units)} code units "
            f"from {project_path}"
        )
        return units
