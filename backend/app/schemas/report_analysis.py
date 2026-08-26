"""
能力9（报告分析）请求/响应模型。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ReportAnalysisRequest(BaseModel):
    """报告分析请求。

    report_id 已通过 URL 路径传入，此处不再要求 body 必填。
    """

    report_id: Optional[str] = Field(default=None, description="报告 ID（路径已携带，可选）")
    analysis_type: str = Field(
        default="summary",
        description="报告分析类型，目前固定为 summary（报告摘要）",
    )
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")
    result_id: Optional[str] = Field(default=None, description="保留字段，报告分析不使用")


class ResultAnalysisRequest(BaseModel):
    """单结果分析请求。

    result_id 已通过 URL 路径传入，此处不再要求 body 必填。
    """

    result_id: Optional[str] = Field(default=None, description="测试结果 ID（路径已携带，可选）")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")


class CompareRequest(BaseModel):
    """结果对比请求。

    result_id 已通过 URL 路径传入，此处不再要求 body 必填。
    """

    result_id: Optional[str] = Field(default=None, description="当前测试结果 ID（路径已携带，可选）")
    compare_run_id: str = Field(..., description="对比的测试运行 ID")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")