"""
能力9（报告分析）请求/响应模型。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ReportAnalysisRequest(BaseModel):
    """报告分析请求。"""

    report_id: str = Field(..., description="报告 ID")
    analysis_type: str = Field(
        default="failure_analysis",
        description="分析类型: failure_analysis / summary / compare",
    )
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")
    result_id: Optional[str] = Field(default=None, description="测试结果 ID（失败分析时使用）")


class ResultAnalysisRequest(BaseModel):
    """单结果分析请求。"""

    result_id: str = Field(..., description="测试结果 ID")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")


class CompareRequest(BaseModel):
    """结果对比请求。"""

    result_id: str = Field(..., description="当前测试结果 ID")
    compare_run_id: str = Field(..., description="对比的测试运行 ID")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")