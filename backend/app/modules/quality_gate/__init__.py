"""
质量门禁模块

提供：
- QualityGateEvaluator: 质量门禁评估器，基于可配置规则评估测试结果是否达标
"""

from app.modules.quality_gate.quality_gate import QualityGateEvaluator

__all__ = ["QualityGateEvaluator"]
