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

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateManualCaseRequest(BaseModel):
    """人工录入的手工执行用例；步骤数组的顺序即执行顺序。"""

    project_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    folder: str = Field(default="", max_length=200)
    preconditions: str = Field(default="", max_length=10000)
    steps: list[str] = Field(min_length=1, max_length=100)
    expected_result: str = Field(min_length=1, max_length=10000)
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    case_type: Literal["functional", "positive", "negative", "boundary", "exception"] = "functional"
    tags: list[str] = Field(default_factory=list, max_length=20)
    requirement_doc_id: UUID | None = None
    requirement_ref: str = Field(default="", max_length=500)
    allow_duplicate: bool = False

    @field_validator("title", "expected_result", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, values: list[str]) -> list[str]:
        steps = [value.strip() for value in values]
        if any(not value for value in steps):
            raise ValueError("每个操作步骤都必须填写内容")
        if any(len(value) > 5000 for value in steps):
            raise ValueError("单个操作步骤不能超过 5000 个字符")
        return steps

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        tags = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 40 for value in tags):
            raise ValueError("单个标签不能超过 40 个字符")
        return tags


class GenerateRequest(BaseModel):
    """生成用例请求 — 支持三粒度：整项目 / 多接口 / 单接口。"""

    project_id: str
    # 多接口粒度：指定待生成的接口资产 id 列表
    endpoint_ids: list[str] | None = None
    # 单接口粒度：指定单个接口资产 id（与 endpoint_ids 互斥，优先级次之）
    endpoint_id: str | None = None


class CreateCaseGenerationTaskRequest(GenerateRequest):
    """创建异步生成任务；source_doc_id 仅用于来源追踪。"""

    source_doc_id: UUID | None = None


class CompleteManualExecutionRequest(BaseModel):
    """提交手工执行结论；每个步骤必须有明确结果。"""

    status: Literal["passed", "failed", "blocked", "cancelled"]
    step_results: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    actual_result: str = Field(default="", max_length=20000)
    notes: str = Field(default="", max_length=10000)
    defect_id: UUID | None = None

    @field_validator("step_results")
    @classmethod
    def validate_step_results(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for index, item in enumerate(values, start=1):
            result = str(item.get("status") or "").strip()
            if result not in {"passed", "failed", "blocked", "skipped"}:
                raise ValueError(f"第 {index} 步缺少有效执行结果")
            normalized.append({
                "index": index,
                "step": str(item.get("step") or "").strip()[:5000],
                "status": result,
                "actual": str(item.get("actual") or "").strip()[:10000],
            })
        return normalized


class UpdateCaseRequest(BaseModel):
    """编辑用例资产请求 — 所有字段可选，仅更新传入项（status 不在此变更）。"""

    title: str | None = None
    description: str | None = None
    request_data: dict[str, Any] | None = None
    expected_result: dict[str, Any] | None = None
    priority: str | None = None
    case_type: str | None = None
    execution_kind: str | None = None  # manual → api 时必须填写真实请求与断言
    folder: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = None


class CreateCaseReviewTaskRequest(BaseModel):
    """把当前不可变用例版本提交给指定评审人。"""

    reviewer_ids: list[UUID] = Field(min_length=1, max_length=20)
    comment: str = Field(default="", max_length=2000)
    due_at: datetime | None = None

    @field_validator("reviewer_ids")
    @classmethod
    def unique_reviewers(cls, values: list[UUID]) -> list[UUID]:
        reviewers = list(dict.fromkeys(values))
        if not reviewers:
            raise ValueError("至少指定一名评审人")
        return reviewers

    @field_validator("comment", mode="before")
    @classmethod
    def strip_review_comment(cls, value):
        return value.strip() if isinstance(value, str) else value


class CaseReviewTaskDecisionRequest(BaseModel):
    decision: Literal["approve", "changes_requested"]
    comment: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_rejection_comment(self):
        self.comment = self.comment.strip()
        if self.decision == "changes_requested" and not self.comment:
            raise ValueError("退回时必须填写修改意见")
        return self


class AdoptBatchRequest(BaseModel):
    """批量接纳请求 — 传入用例资产 id 列表。"""

    ids: list[str] = Field(default_factory=list)


class BatchUpdateCaseRequest(BaseModel):
    """批量归类与标签维护。folder 为空字符串表示清除归类。"""

    ids: list[str] = Field(default_factory=list, min_length=1, max_length=500)
    folder: str | None = Field(default=None, max_length=200)
    add_tags: list[str] = Field(default_factory=list, max_length=20)


class CaseImportRow(BaseModel):
    """预检后的标准导入行；提交阶段仍会重新执行同一组校验。"""

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    execution_kind: Literal["api", "manual"] = "api"
    case_type: Literal["functional", "positive", "negative", "boundary", "exception"] = "positive"
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    folder: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    request_data: dict[str, Any] = Field(default_factory=dict)
    expected_result: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("tags")
    @classmethod
    def normalize_import_tags(cls, values: list[str]) -> list[str]:
        tags = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if any(len(value) > 40 for value in tags):
            raise ValueError("单个标签不能超过 40 个字符")
        return tags

    @model_validator(mode="after")
    def validate_manual_content(self):
        if self.execution_kind != "manual":
            return self
        steps = self.request_data.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("手工用例至少需要一个操作步骤")
        normalized_steps = [str(value).strip() for value in steps]
        if any(not value for value in normalized_steps):
            raise ValueError("每个操作步骤都必须填写内容")
        if any(len(value) > 5000 for value in normalized_steps):
            raise ValueError("单个操作步骤不能超过 5000 个字符")
        expected = self.expected_result.get("text")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError("手工用例必须填写预期结果")
        self.request_data = {**self.request_data, "steps": normalized_steps}
        self.expected_result = {**self.expected_result, "text": expected.strip()}
        return self


class CaseImportCommitRequest(BaseModel):
    project_id: UUID
    duplicate_strategy: Literal["skip", "create"] = "skip"
    rows: list[CaseImportRow] = Field(min_length=1, max_length=2000)


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
    execution_kind: str = "api"
    review_state: str = "draft"
    folder: str | None = None
    tags: list[str] = Field(default_factory=list)
    version: int = 1
    generation_context: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
