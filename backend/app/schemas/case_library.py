"""
能力3（AI 生成单接口用例·接纳闭环）请求/响应模型。

统一约定：
- 写操作（生成/采纳/废弃/批量接纳/编辑/删除）均需 ``Depends(get_current_user)``。
- 所有端点统一返回 ``{"code": 0, "data": ..., "message": "..."}``，
  本文件仅定义请求体结构与资产序列化模型，具体返回字典在 router 中构造。

注：使用 ``from __future__ import annotations`` 以支持前向引用，避免 Pydantic
模型间相互引用时触发模块加载期 NameError。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """生成用例请求 — 支持三粒度：整项目 / 多接口 / 单接口。"""

    project_id: str
    # 多接口粒度：指定待生成的接口资产 id 列表
    endpoint_ids: list[str] | None = None
    # 单接口粒度：指定单个接口资产 id（与 endpoint_ids 互斥，优先级次之）
    endpoint_id: str | None = None


class UpdateCaseRequest(BaseModel):
    """编辑用例资产请求 — 所有字段可选，仅更新传入项（status 不在此变更）。"""

    title: str | None = None
    description: str | None = None
    request_data: dict[str, Any] | None = None
    expected_result: dict[str, Any] | None = None
    priority: str | None = None
    case_type: str | None = None


class AdoptBatchRequest(BaseModel):
    """批量接纳请求 — 传入用例资产 id 列表。"""

    ids: list[str] = Field(default_factory=list)


class CaseAssetResponse(BaseModel):
    """用例资产序列化模型。"""

    id: str
    project_id: str
    endpoint_id: str | None = None
    case_type: str
    title: str
    description: str | None = None
    request_data: dict[str, Any] = Field(default_factory=dict)
    expected_result: dict[str, Any] | None = None
    priority: str = "P2"
    status: str
    source: str
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
