"""
技术栈智能识别器

通过文件签名、框架特征文件、导入语句、装饰器、路由模式等多维度特征
自动识别项目的技术栈（语言 + 框架），返回带置信度的识别结果。

支持 8 种技术栈：java_spring / python_flask / python_django / python_fastapi /
go_gin / node_express / node_nestjs / php_laravel。
"""

import re
from pathlib import Path
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 技术栈特征签名 ====================

STACK_SIGNATURES: dict[str, dict[str, Any]] = {
    "java_spring": {
        "files": ["pom.xml", "build.gradle"],
        "framework_files": [
            "src/main/resources/application.yml",
            "src/main/resources/application.properties",
        ],
        "annotations": [
            "@RestController",
            "@RequestMapping",
            "@GetMapping",
            "@PostMapping",
        ],
        "dep_markers": ["spring-boot"],
        "language": "java",
        "framework": "spring-boot",
    },
    "python_flask": {
        "files": ["requirements.txt", "setup.py", "pyproject.toml"],
        "framework_imports": ["from flask import", "import flask"],
        "route_decorators": ["@app.route", "@blueprint.route", "@bp.route"],
        "dep_markers": ["flask"],
        "language": "python",
        "framework": "flask",
    },
    "python_django": {
        "files": ["manage.py", "requirements.txt"],
        "framework_files": ["settings.py"],
        "framework_imports": ["from django", "import django"],
        "dep_markers": ["django"],
        "language": "python",
        "framework": "django",
    },
    "python_fastapi": {
        "files": ["requirements.txt", "pyproject.toml"],
        "framework_imports": ["from fastapi import", "import fastapi"],
        "route_decorators": [
            "@app.get",
            "@app.post",
            "@router.get",
            "@router.post",
        ],
        "dep_markers": ["fastapi"],
        "language": "python",
        "framework": "fastapi",
    },
    "go_gin": {
        "files": ["go.mod"],
        "framework_imports": ['"github.com/gin-gonic/gin"'],
        "route_patterns": [
            "r.GET(",
            "r.POST(",
            "router.GET(",
            "router.POST(",
        ],
        "dep_markers": ["github.com/gin-gonic/gin"],
        "language": "go",
        "framework": "gin",
    },
    "node_express": {
        "files": ["package.json"],
        "framework_files": ["node_modules/express"],
        "route_patterns": [
            "app.get(",
            "app.post(",
            "router.get(",
            "router.post(",
        ],
        "dep_markers": ["\"express\""],
        "language": "javascript",
        "framework": "express",
    },
    "node_nestjs": {
        "files": ["package.json"],
        "framework_files": ["nest-cli.json"],
        "annotations": [
            "@Controller(",
            "@Get(",
            "@Post(",
            "@Put(",
            "@Delete(",
        ],
        "dep_markers": ["@nestjs/core"],
        "language": "typescript",
        "framework": "nestjs",
    },
    "php_laravel": {
        "files": ["composer.json"],
        "framework_files": ["artisan", "config/app.php"],
        "route_files": ["routes/api.php", "routes/web.php"],
        "dep_markers": ["laravel/framework"],
        "language": "php",
        "framework": "laravel",
    },
}

# 读取源码文件时的最大扫描文件数，避免超大项目耗时过长
_MAX_SCAN_FILES = 200
# 单文件最大读取字符数
_MAX_FILE_READ_CHARS = 100_000

# 文件扩展名 → 编程语言（用于未识别到 Web 框架时的语言级兜底）
_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".php": "php",
    ".vue": "javascript",
}

# 通用提取支持的语言集合（无框架适配器时按语言做通用分析）
GENERIC_LANGUAGES = set(_EXT_LANG.values())


class StackDetector:
    """
    技术栈识别器。

    通过多维度特征匹配计算置信度评分，取最高分（> 0.5）作为识别结果。
    """

    def detect(self, project_path: str) -> dict[str, Any]:
        """
        识别项目技术栈。

        评分逻辑：
        - 文件签名存在：+0.3 / 个
        - 框架特征文件存在：+0.2 / 个
        - 导入/装饰器/注解/路由模式在源码中出现：+0.1 / 个

        Args:
            project_path: 项目**根目录**路径，或单个源文件路径。

        Returns:
            包含 stack / language / framework / confidence 的字典。
            如果都不匹配，返回 unknown + confidence=0.0。

        Note:
            支持两种输入（v1.3）：
            - 目录：完整识别（最强信号）
            - 单文件：用 ``Path.parent`` 作为 root，但仍执行同样的评分逻辑
              —— 这样用户直接选一个 main.py 也能拿到有用的栈识别结果（友好降级）。
              若要提取完整 API 列表请传目录；单文件仅做栈识别。
        """
        raw = Path(project_path)
        if not raw.exists():
            logger.warning(
                f"Project path does not exist: {project_path}; "
                "请确认路径（目录或源文件绝对路径）正确"
            )
            return {
                "stack": "unknown",
                "language": "unknown",
                "framework": "unknown",
                "confidence": 0.0,
                "hint": "路径不存在或不可访问。请上传代码包或在容器内放置该目录。",
            }

        if raw.is_file():
            # 单文件输入：把 root 设为所在目录（友好降级）
            root = raw.parent
            logger.info(
                f"project_path is a file ({raw.name}); 用父目录作为 root: {root}"
            )
        else:
            root = raw

        if not root.is_dir():
            logger.warning(f"Project path does not exist or is not a directory: {project_path}")
            return {
                "stack": "unknown",
                "language": "unknown",
                "framework": "unknown",
                "confidence": 0.0,
            }

        logger.info(f"Detecting tech stack for: {project_path}")

        # 预扫描：收集源码文件内容（限制数量）
        source_contents = self._scan_source_files(root)

        best_stack = "unknown"
        best_score = 0.0
        best_info: dict[str, Any] = {}

        for stack_name, signature in STACK_SIGNATURES.items():
            score = self._calculate_score(root, signature, source_contents)
            if score > best_score:
                best_score = score
                best_stack = stack_name
                best_info = signature

        if best_score > 0.5:
            result = {
                "stack": best_stack,
                "language": best_info.get("language", "unknown"),
                "framework": best_info.get("framework", "unknown"),
                "confidence": round(best_score, 2),
            }
        else:
            # 兜底：未识别到具体 Web 框架时，按文件扩展名识别主导语言，
            # 返回 language=语言名 / framework=unknown / stack=语言名，
            # 供 APIExtractor 走通用提取（提取函数/类/路由模式）。
            lang = self._detect_language(root)
            if lang:
                result = {
                    "stack": lang,
                    "language": lang,
                    "framework": "unknown",
                    "confidence": 0.3,
                    "hint": (
                        "未识别到具体 Web 框架，已按编程语言做通用分析"
                        "（提取函数/类与风险点）。上传完整项目可识别框架级接口。"
                    ),
                }
            else:
                result = {
                    "stack": "unknown",
                    "language": "unknown",
                    "framework": "unknown",
                    "confidence": 0.0,
                }

        logger.info(
            f"Tech stack detected: {result['stack']} "
            f"(language={result['language']}, framework={result['framework']}, "
            f"confidence={result['confidence']})"
        )
        return result

    def _calculate_score(
        self,
        root: Path,
        signature: dict[str, Any],
        source_contents: list[str],
    ) -> float:
        """
        计算单个技术栈的置信度评分。

        Args:
            root: 项目根目录。
            signature: 技术栈特征签名。
            source_contents: 预扫描的源码文件内容列表。

        Returns:
            置信度评分（0.0 ~ 1.0+）。
        """
        score = 0.0

        # 0. 依赖清单内容（最强信号 +0.5）：requirements.txt / package.json /
        #    composer.json / go.mod 里直接声明了框架依赖——轻量项目（单文件
        #    + 清单）此前只能得 0.3 分走 unknown 兜底，实测漏判 flask 项目
        dep_files = [
            "requirements.txt", "pyproject.toml", "setup.py",
            "package.json", "composer.json", "go.mod", "pom.xml", "build.gradle",
        ]
        dep_content = ""
        for df in dep_files:
            try:
                dep_content += (root / df).read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:  # noqa: BLE001
                continue
        if dep_content:
            for marker in signature.get("dep_markers", []):
                if marker.lower() in dep_content:
                    score += 0.5
                    break

        # 1. 文件签名（+0.3 / 个）
        for filename in signature.get("files", []):
            if (root / filename).exists():
                score += 0.3

        # 2. 框架特征文件（+0.2 / 个）
        for fw_file in signature.get("framework_files", []):
            if (root / fw_file).exists():
                score += 0.2

        # 3. 路由文件（+0.2 / 个，Laravel 专用）
        for route_file in signature.get("route_files", []):
            if (root / route_file).exists():
                score += 0.2

        # 4. 源码内容匹配
        # 4a. 导入语句（+0.1 / 个）
        for import_pattern in signature.get("framework_imports", []):
            for content in source_contents:
                if import_pattern in content:
                    score += 0.1
                    break  # 每个模式只计一次

        # 4b. 路由装饰器（+0.1 / 个）
        for decorator in signature.get("route_decorators", []):
            for content in source_contents:
                if decorator in content:
                    score += 0.1
                    break

        # 4c. 注解（+0.1 / 个）
        for annotation in signature.get("annotations", []):
            for content in source_contents:
                if annotation in content:
                    score += 0.1
                    break

        # 4d. 路由模式（+0.1 / 个）
        for route_pattern in signature.get("route_patterns", []):
            for content in source_contents:
                if route_pattern in content:
                    score += 0.1
                    break

        return score

    def _detect_language(self, root: Path) -> str | None:
        """
        按文件扩展名识别项目主导语言（框架识别失败时的兜底）。

        Args:
            root: 项目根目录。

        Returns:
            语言名（python/java/javascript/...）或 None（无任何已知源码）。
        """
        counts: dict[str, int] = {}
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            lang = _EXT_LANG.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1

        if not counts:
            return None
        # 取文件数最多的语言
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def _scan_source_files(self, root: Path) -> list[str]:
        """
        预扫描项目源码文件，返回文件内容列表。

        限制扫描文件数量和单文件读取大小，避免超大项目耗时过长。

        Args:
            root: 项目根目录。

        Returns:
            源码文件内容字符串列表。
        """
        source_extensions = {
            ".py", ".java", ".kt", ".go", ".js", ".ts", ".php",
            ".jsx", ".tsx", ".vue",
        }
        skip_dirs = {
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            "env", ".idea", ".vscode", "dist", "build", "target",
        }

        contents: list[str] = []
        count = 0

        for file_path in root.rglob("*"):
            if count >= _MAX_SCAN_FILES:
                break
            if not file_path.is_file():
                continue
            # 跳过排除目录
            if any(part in skip_dirs for part in file_path.parts):
                continue
            if file_path.suffix.lower() not in source_extensions:
                continue
            try:
                content = file_path.read_text(
                    encoding="utf-8", errors="ignore"
                )[:_MAX_FILE_READ_CHARS]
                contents.append(content)
                count += 1
            except Exception as e:
                logger.debug(f"Failed to read {file_path}: {e}")

        logger.debug(f"Scanned {count} source files for stack detection")
        return contents
