"""
能力8（定时任务）请求/响应模型。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ScheduledTaskRequest(BaseModel):
    """创建定时任务请求。"""

    name: str = Field(..., description="任务名称")
    cron_expression: str = Field(default="0 0 * * *", description="Cron 表达式")
    target_type: str = Field(default="scenario", description="目标类型: scenario / case_collection / plan")
    target_id: Optional[str] = Field(default=None, description="目标 ID")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")
    description: str = Field(default="", description="任务描述")
    nl_schedule: Optional[str] = Field(default=None, description="自然语言调度描述")
    target_config: Optional[dict] = Field(default=None, description="目标配置（JSON）")
    env_config: Optional[dict] = Field(default=None, description="环境配置（JSON）")
    status: str = Field(default="active", description="状态: active / paused")


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求 — 所有字段可选。"""

    name: Optional[str] = Field(default=None, description="任务名称")
    cron_expression: Optional[str] = Field(default=None, description="Cron 表达式")
    target_type: Optional[str] = Field(default=None, description="目标类型")
    target_id: Optional[str] = Field(default=None, description="目标 ID")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")
    description: Optional[str] = Field(default=None, description="任务描述")
    nl_schedule: Optional[str] = Field(default=None, description="自然语言调度描述")
    status: Optional[str] = Field(default=None, description="状态")


class ParseCronRequest(BaseModel):
    """NL→Cron 解析请求。"""

    nl_schedule: str = Field(..., description="自然语言描述，如 '每天早上8点执行'")