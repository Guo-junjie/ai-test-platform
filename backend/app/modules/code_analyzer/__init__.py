"""
代码解析模块 — 技术栈识别 + 接口提取 + AI 语义分析

导入此包时自动注册所有适配器到适配器注册中心。
"""

from app.modules.code_analyzer.stack_detector import StackDetector, STACK_SIGNATURES
from app.modules.code_analyzer.api_extractor import APIExtractor
from app.modules.code_analyzer.ai_analyzer import AICodeAnalyzer

# 导入所有适配器触发注册
from app.modules.code_analyzer.adapters import (
    java_spring,
    python_flask,
    python_fastapi,
    python_django,
    go_gin,
    node_express,
    node_nestjs,
    php_laravel,
)

__all__ = [
    "StackDetector",
    "STACK_SIGNATURES",
    "APIExtractor",
    "AICodeAnalyzer",
]
