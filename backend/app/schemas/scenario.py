"""
能力4（AI 编排测试场景）请求/响应模型。

统一约定：写操作（创建/编辑/采纳）需 ``Depends(get_current_user)``；
所有端点统一返回 ``{"code": 0, "data": ..., "message": "..."}``。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateScenarioRequest(BaseModel):
    """创建场景请求 — 输入自然语言 + 项目，可选指定接口。"""

    project_id: str
    nl_input: str
    name: str | None = None
    endpoint_ids: list[str] | None = None


class DryRunRequest(BaseModel):
    """场景预览（dry-run）请求 — 仅编排不落库、不接真实 HTTP。"""

    project_id: str
    nl_input: str
    endpoint_ids: list[str] | None = None


class UpdateScenarioRequest(BaseModel):
    """编辑场景请求 — 仅更新传入项（status 由接纳端点管理）。"""

    name: str | None = None
    description: str | None = None
    nl_input: str | None = None
    steps: list[dict[str, Any]] | None = None


class ScenarioStep(BaseModel):
    """单步结构（与 scenarios.steps JSONB 对齐）。"""

    step_order: int
    endpoint_id: str | None = None
    action_desc: str | None = None
    method: str = "GET"
    url: str | None = None
    extract: dict[str, Any] = Field(default_factory=dict)
    inject: dict[str, Any] = Field(default_factory=dict)
    depend_on_step: Optional[int] = None
    request: dict[str, Any] = Field(default_factory=dict)


class ScenarioResponse(BaseModel):
    """场景序列化模型。"""

    id: str
    project_id: str
    name: str
    description: str | None = None
    nl_input: str
    status: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    engine: str | None = None  # 仅创建响应携带：ai / rule
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
