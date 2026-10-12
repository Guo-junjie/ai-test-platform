"""缺陷中心输入结构；状态和来源只由领域服务写入。"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Priority = Literal["urgent", "high", "normal", "low"]
Severity = Literal["P0", "P1", "P2", "P3"]
DefectKind = Literal["business", "program", "performance", "integration", "security"]


class ReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["requirement", "case", "defect"]
    requirement_doc_id: UUID | None = None
    requirement_item_key: str | None = Field(None, max_length=200)
    case_asset_id: UUID | None = None
    related_defect_id: UUID | None = None
    relation: Literal["relates", "blocks"] = "relates"

    @model_validator(mode="after")
    def target(self):
        targets = [self.requirement_doc_id, self.case_asset_id, self.related_defect_id]
        position = {"requirement": 0, "case": 1, "defect": 2}[self.kind]
        if not targets[position] or sum(value is not None for value in targets) != 1:
            raise ValueError("关联类型必须与唯一关联对象一致")
        if self.kind != "requirement" and self.requirement_item_key:
            raise ValueError("只有需求关联可以指定需求条目")
        return self


class DefectFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(None, min_length=2, max_length=500)
    description: str | None = Field(None, min_length=1, max_length=30000)
    severity: Severity | None = None
    defect_type: DefectKind | None = None
    priority: Priority | None = None
    module_id: UUID | None = None
    iteration_id: UUID | None = None
    environment_profile_id: UUID | None = None
    preconditions: str | None = Field(None, max_length=10000)
    expected_result: str | None = Field(None, max_length=10000)
    actual_result: str | None = Field(None, max_length=10000)
    reproduce_steps: list[str] | None = Field(None, max_length=100)
    reproducibility: Literal["always", "intermittent", "once", "unknown"] | None = None
    assignee_id: UUID | None = None
    verifier_id: UUID | None = None
    labels: list[str] | None = Field(None, max_length=20)
    due_at: datetime | None = None
    affected_release_ids: list[UUID] | None = Field(None, max_length=50)

    @field_validator("labels")
    @classmethod
    def labels_valid(cls, value):
        if value is None:
            return value
        cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if any(len(item) > 40 for item in cleaned):
            raise ValueError("每个标签最多 40 字符")
        return cleaned

    @field_validator("reproduce_steps")
    @classmethod
    def steps_valid(cls, value):
        if value is None:
            return value
        cleaned = [item.strip() for item in value if item.strip()]
        if any(len(item) > 2000 for item in cleaned):
            raise ValueError("单个复现步骤最多 2000 字符")
        return cleaned

    @field_validator("due_at")
    @classmethod
    def due_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("截止时间必须包含时区")
        return value


class DefectCreate(DefectFields):
    project_id: UUID
    title: str = Field(..., min_length=2, max_length=500)
    description: str = Field(..., min_length=1, max_length=30000)
    severity: Severity = "P2"
    defect_type: DefectKind = "business"
    priority: Priority = "normal"
    reproduce_steps: list[str] = Field(default_factory=list, max_length=100)
    labels: list[str] = Field(default_factory=list, max_length=20)
    reproducibility: Literal["always", "intermittent", "once", "unknown"] = "unknown"
    references: list[ReferenceInput] = Field(default_factory=list, max_length=50)
    creation_request_id: UUID | None = None
    # 保留旧手工请求字段，但不能由外部请求冒充流水线。
    source: Literal["manual"] = "manual"


class DefectUpdate(DefectFields):
    expected_version: int = Field(..., ge=1)
    note: str = Field("", max_length=5000)

    @model_validator(mode="after")
    def required_not_null(self):
        for name in ("title", "description", "severity", "defect_type", "priority", "labels", "reproduce_steps", "reproducibility"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为空")
        if self.affected_release_ids is None and "affected_release_ids" in self.model_fields_set:
            raise ValueError("影响版本清空请传空数组")
        return self


class TransitionFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    assignee_id: UUID | None = None
    verifier_id: UUID | None = None
    fix_release_id: UUID | None = None
    fix_build: str | None = Field(None, max_length=200)
    verified_release_id: UUID | None = None
    verified_build: str | None = Field(None, max_length=200)
    actual_result: str | None = Field(None, max_length=10000)
    resolution: Literal["duplicate", "not_a_bug", "wont_fix", "cannot_reproduce"] | None = None
    duplicate_of_id: UUID | None = None
    fix_available: bool | None = None


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action_id: str = Field(..., max_length=64)
    expected_version: int = Field(..., ge=1)
    request_id: UUID
    note: str = Field("", max_length=5000)
    fields: TransitionFields = Field(default_factory=TransitionFields)


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(..., ge=1)
    request_id: UUID
    assignee_id: UUID | None = None
    verifier_id: UUID | None = None
    note: str = Field("", max_length=5000)


class LegacyStatusRequest(BaseModel):
    status: Literal["open", "in_fix", "verified", "closed", "rejected"]
    note: str = Field("", max_length=5000)
    expected_version: int = Field(..., ge=1)
    request_id: UUID
    fields: TransitionFields = Field(default_factory=TransitionFields)


class DirectoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: UUID | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    build_ref: str | None = Field(None, max_length=200)
    released_at: datetime | None = None
    status: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def dates_valid(self):
        for value in (self.start_date, self.end_date, self.released_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("时间必须包含时区")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("结束时间不能早于开始时间")
        return self
