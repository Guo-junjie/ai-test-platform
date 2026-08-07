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
        "language": "java",
        "framework": "spring-boot",
    },
    "python_flask": {
        "files": ["requirements.txt", "setup.py", "pyproject.toml"],
        "framework_imports": ["from flask import", "import flask"],
        "route_decorators": ["@app.route", "@blueprint.route", "@bp.route"],
        "language": "python",
        "framework": "flask",
    },
    "python_django": {
        "files": ["manage.py", "requirements.txt"],
        "framework_files": ["settings.py"],
        "framework_imports": ["from django", "import django"],
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
        "language": "typescript",
        "framework": "nestjs",
    },
    "php_laravel": {
        "files": ["composer.json"],
        "framework_files": ["artisan", "config/app.php"],
        "route_files": ["routes/api.php", "routes/web.php"],
        "language": "php",
        "framework": "laravel",
    },
}

# 读取源码文件时的最大扫描文件数，避免超大项目耗时过长
_MAX_SCAN_FILES = 200
# 单文件最大读取字符数
_MAX_FILE_READ_CHARS = 100_000


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
            project_path: 项目根目录路径。

        Returns:
            包含 stack / language / framework / confidence 的字典。
            如果都不匹配，返回 unknown + confidence=0.0。
        """
        root = Path(project_path)
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
