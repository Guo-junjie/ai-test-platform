"""
报告生成模块 — 测试报告生成与图表构建
"""

from app.modules.report.generator import ReportGenerator, persist_defects_to_db
from app.modules.report.charts import ChartBuilder

__all__ = ["ReportGenerator", "ChartBuilder", "persist_defects_to_db"]
