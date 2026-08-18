"""
doc_review 包 — 接口文档多维评审（能力2）

对外暴露：
- review(endpoints, use_ai=True)：AI 评审 + 后端按权重复算总分；无 AI 时转规则兜底
- rule_review(endpoints)：确定性规则兜底评审
"""

from app.modules.doc_review.review_service import review
from app.modules.doc_review.rules import rule_review, DIMENSION_WEIGHTS

__all__ = ["review", "rule_review", "DIMENSION_WEIGHTS"]
