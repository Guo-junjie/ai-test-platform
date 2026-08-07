"""
Java Spring Boot 接口提取适配器

扫描 *.java / *.kt 文件，通过正则匹配 Spring MVC 注解提取 API 接口定义。
支持类级别 @RequestMapping 前缀 + 方法级别 @GetMapping/@PostMapping 等注解。
解析 @RequestBody / @PathVariable / @RequestParam / @RequestHeader 参数。
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

# 类级别 @RequestMapping(value="/api" 或 @RequestMapping("/api"
_RE_CLASS_MAPPING = re.compile(
    r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
    re.MULTILINE,
)

# 方法级别注解：@GetMapping / @PostMapping / @PutMapping / @DeleteMapping / @PatchMapping
_RE_METHOD_MAPPING = re.compile(
    r'@(Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']',
    re.MULTILINE,
)

# 方法签名：public ReturnType methodName(
_RE_METHOD_SIGNATURE = re.compile(
    r'(?:public|protected|private)\s+([\w<>.,\s\[\]]+?)\s+(\w+)\s*\(',
    re.MULTILINE,
)

# 参数注解
_RE_REQUEST_BODY = re.compile(r'@RequestBody\s*(?:\(\s*\))?\s*([\w<>]+)\s+(\w+)')
_RE_PATH_VARIABLE = re.compile(
    r'@PathVariable\s*(?:\(\s*(?:value\s*=\s*)?["\']?(\w+)["\']?\s*\))?\s*([\w<>]+)\s+(\w+)'
)
_RE_REQUEST_PARAM = re.compile(
    r'@RequestParam\s*(?:\(\s*(?:value\s*=\s*)?["\']?(\w+)["\']?\s*(?:,\s*required\s*=\s*(true|false))?\s*\))?\s*([\w<>]+)\s+(\w+)'
)
_RE_REQUEST_HEADER = re.compile(
    r'@RequestHeader\s*(?:\(\s*(?:value\s*=\s*)?["\']?(\w+)["\']?\s*\))?\s*([\w<>]+)\s+(\w+)'
)

# 检测是否为 Controller 类
_RE_CONTROLLER = re.compile(r'@(Rest)?Controller\b')

# 认证相关注解
_RE_AUTH_ANNOTATIONS = re.compile(
    r'@(PreAuthorize|Secured|RolesAllowed|RequiresAuthentication)\b'
)

_HTTP_METHOD_MAP = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
}


@register_adapter("java_spring")
class JavaSpringAdapter(APIExtractorAdapter):
    """Java Spring Boot 接口提取适配器。"""

    def extract_apis(self, project_path: str) -> list[dict[str, Any]]:
        """
        扫描 Java/Kotlin 源文件，提取 Spring Boot API 接口。

        Args:
            project_path: 项目根目录路径。

        Returns:
            标准化接口定义列表。
        """
        root = Path(project_path)
        apis: list[dict[str, Any]] = []

        # 收集所有 .java / .kt 文件
        source_files: list[Path] = []
        for ext in ("*.java", "*.kt"):
            source_files.extend(root.rglob(ext))

        # 排除 build / target 目录
        source_files = [
            f for f in source_files
            if not any(part in {"target", "build", ".gradle"} for part in f.parts)
        ]

        logger.info(f"JavaSpring adapter: scanning {len(source_files)} source files")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")
                continue

            if not _RE_CONTROLLER.search(content):
                continue

            file_apis = self._extract_from_file(content, file_path, root)
            apis.extend(file_apis)

        logger.info(f"JavaSpring adapter: extracted {len(apis)} APIs")
        return apis

    def _extract_from_file(
        self, content: str, file_path: Path, root: Path
    ) -> list[dict[str, Any]]:
        """
        从单个文件中提取 API 接口。

        Args:
            content: 文件内容。
            file_path: 文件路径。
            root: 项目根目录。

        Returns:
            接口定义列表。
        """
        apis: list[dict[str, Any]] = []
        rel_path = str(file_path.relative_to(root))

        # 提取类级别 @RequestMapping 前缀
        class_prefix = ""
        class_match = _RE_CLASS_MAPPING.search(content)
        if class_match:
            class_prefix = class_match.group(1)

        # 检测类级别认证要求
        class_auth = bool(_RE_AUTH_ANNOTATIONS.search(content))

        # 提取方法级别映射
        for match in _RE_METHOD_MAPPING.finditer(content):
            http_method = _HTTP_METHOD_MAP.get(match.group(1), "GET")
            method_path = match.group(2)

            # 拼接完整路径
            full_path = self._join_path(class_prefix, method_path)

            # 查找行号
            line_number = content[: match.start()].count("\n") + 1

            # 提取方法签名
            method_name = "unknown"
            return_type = "void"
            sig_match = _RE_METHOD_SIGNATURE.search(content, match.end())
            if sig_match:
                return_type = sig_match.group(1).strip()
                method_name = sig_match.group(2)

            # 提取参数
            params = self._extract_params(content, match.end())

            # 检测方法级别认证
            method_auth = class_auth or bool(
                _RE_AUTH_ANNOTATIONS.search(content[match.start():match.end() + 500])
            )

            # 提取 Javadoc 描述
            description = self._extract_javadoc(content, match.start())

            apis.append(
                {
                    "path": full_path,
                    "http_method": http_method,
                    "params": params,
                    "return_type": return_type,
                    "method_name": method_name,
                    "file": rel_path,
                    "line_number": line_number,
                    "auth_required": method_auth,
                    "description": description,
                }
            )

        return apis

    def _extract_params(
        self, content: str, start_pos: int
    ) -> list[dict[str, Any]]:
        """
        从方法参数区域提取参数定义。

        Args:
            content: 文件内容。
            start_pos: 方法注解结束位置。

        Returns:
            参数定义列表。
        """
        params: list[dict[str, Any]] = []

        # 在注解之后 500 字符内查找参数
        search_region = content[start_pos : start_pos + 500]

        # @RequestBody
        for m in _RE_REQUEST_BODY.finditer(search_region):
            params.append(
                {
                    "name": m.group(2),
                    "location": "body",
                    "type": m.group(1),
                    "required": True,
                }
            )

        # @PathVariable
        for m in _RE_PATH_VARIABLE.finditer(search_region):
            param_name = m.group(1) or m.group(3)
            params.append(
                {
                    "name": param_name,
                    "location": "path",
                    "type": m.group(2),
                    "required": True,
                }
            )

        # @RequestParam
        for m in _RE_REQUEST_PARAM.finditer(search_region):
            param_name = m.group(1) or m.group(4)
            required = m.group(2) != "false" if m.group(2) else True
            params.append(
                {
                    "name": param_name,
                    "location": "query",
                    "type": m.group(3),
                    "required": required,
                }
            )

        # @RequestHeader
        for m in _RE_REQUEST_HEADER.finditer(search_region):
            param_name = m.group(1) or m.group(3)
            params.append(
                {
                    "name": param_name,
                    "location": "header",
                    "type": m.group(2),
                    "required": True,
                }
            )

        return params

    def _join_path(self, prefix: str, suffix: str) -> str:
        """拼接路径前缀和后缀。"""
        if not prefix and not suffix:
            return "/"
        if not prefix:
            return suffix if suffix.startswith("/") else "/" + suffix
        if not suffix:
            return prefix
        return prefix.rstrip("/") + "/" + suffix.lstrip("/")

    def _extract_javadoc(self, content: str, pos: int) -> str:
        """
        提取方法上方的 Javadoc 注释作为描述。

        Args:
            content: 文件内容。
            pos: 注解位置。

        Returns:
            Javadoc 描述文本，无则返回空字符串。
        """
        # 向上查找最近的 /** ... */ 注释
        before = content[:pos].rstrip()
        if not before.endswith("*/"):
            return ""
        comment_start = before.rfind("/**")
        if comment_start == -1:
            return ""
        comment = content[comment_start:before.rfind("*/") + 2]
        # 提取第一行描述（去掉 * 前缀）
        lines = comment.split("\n")
        for line in lines[1:]:
            cleaned = line.strip().lstrip("*").strip()
            if cleaned and not cleaned.startswith("@"):
                return cleaned
        return ""
