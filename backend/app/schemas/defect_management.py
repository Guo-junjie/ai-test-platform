"""缺陷协作、批量管理与项目配置输入。"""
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(..., min_length=1, max_length=20000)
    mention_user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("mention_user_ids", "attachment_ids")
    @classmethod
    def unique_ids(cls, value):
        return list(dict.fromkeys(value))


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(..., min_length=1, max_length=20000)
    mention_user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    expected_version: int = Field(..., ge=1)


class WatcherInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID | None = None
    kind: Literal["watch", "cc"] = "watch"


class SavedViewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=100)
    visibility: Literal["private", "project"] = "private"
    query: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list, max_length=30)
    sort: list[dict[str, str]] = Field(default_factory=list, max_length=3)


class SavedViewUpdate(SavedViewInput):
    expected_version: int = Field(..., ge=1)


class BatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    defect_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    operation: Literal["assign", "priority", "module", "iteration", "add_labels", "remove_labels", "transition", "delete"]
    values: dict[str, Any] = Field(default_factory=dict)
    preview: bool = False

    @field_validator("defect_ids")
    @classmethod
    def unique_defects(cls, value):
        return list(dict.fromkeys(value))


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    defect_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    filters: dict[str, Any] = Field(default_factory=dict)
    format: Literal["csv", "xlsx"] = "xlsx"
    request_key: UUID


class ImportCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    row_numbers: list[int] | None = Field(None, max_length=5000)


class DefectSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(..., ge=1)
    timezone: str = Field("Asia/Shanghai", max_length=64)
    field_config: dict[str, Any] = Field(default_factory=dict)
    permission_config: dict[str, Any] = Field(default_factory=dict)
    notification_config: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=100)


class WorkflowDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]


class WorkflowMigrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_revision_id: UUID
    state_mapping: dict[str, str]
    defect_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    request_key: UUID
    preview: bool = True
