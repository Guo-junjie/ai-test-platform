"""
文档解析统一中间表示（Intermediate Representation）

所有解析器（openapi / har / docx / pdf）只负责把"格式 → ApiSpec"，
下游（预览 / 导入 / 评审）只认 ApiSpec，彻底解耦异构输入。

ApiSpec 为文档级容器：{ title, version, servers, base_path, endpoints: List[ApiEndpointSpec] }
ApiEndpointSpec 为单接口描述。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


class ParamSpec(BaseModel):
    """请求参数（query / header / path / cookie / body）"""

    model_config = ConfigDict(populate_by_name=True)

    name: str = ""
    # "in" 是 Python 关键字，用 in_ 承载，序列化别名 in
    in_: str = Field(default="query", alias="in")  # query | header | path | cookie | body
    type: str = "string"  # string | integer | number | boolean | array | object
    required: bool = False
    description: str = ""
    example: Any | None = None


class ApiRequestBody(BaseModel):
    """请求体"""

    model_config = ConfigDict(populate_by_name=True)

    content_type: str = "application/json"
    required: bool = False
    schema_: Optional[dict] = Field(default=None, alias="schema")
    example: Any | None = None


class ResponseSpec(BaseModel):
    """响应定义"""

    model_config = ConfigDict(populate_by_name=True)

    status_code: int = 200
    description: str = ""
    content_type: str = "application/json"
    schema_: Optional[dict] = Field(default=None, alias="schema")
    example: Any | None = None


class ApiEndpointSpec(BaseModel):
    """单接口统一描述（解析结果的最小单元）"""

    model_config = ConfigDict(populate_by_name=True)

    path: str
    method: str  # 归一化大写
    summary: str = ""
    description: str = ""
    params: list[ParamSpec] = Field(default_factory=list)
    request_body: ApiRequestBody | None = None
    responses: list[ResponseSpec] = Field(default_factory=list)
    auth_required: bool = False
    auth_type: str | None = None  # bearer | basic | apikey | oauth2 | none
    confidence: float = 1.0  # 规则解析=1.0；AI 由模型自评
    evidence: str = ""  # AI 提取时标注来源位置，便于人工复核


class ApiSpec(BaseModel):
    """文档级统一中间表示"""

    title: str = ""
    version: str = ""
    servers: list[str] = Field(default_factory=list)
    base_path: str = ""
    endpoints: list[ApiEndpointSpec] = Field(default_factory=list)

    def endpoint_keys(self) -> list[str]:
        """返回 [METHOD PATH, ...] 用于预览/勾选/导入去重。"""
        return [f"{e.method} {e.path}" for e in self.endpoints]


# ==================== 需求文档中间表示（能力10：需求文档解析） ====================


class RequirementItem(BaseModel):
    """单条需求（功能点 / 验收标准）"""

    model_config = ConfigDict(populate_by_name=True)

    rid: str = ""  # 需求编号，如 REQ-001 / FR-2.1；AI 未给则运行时补全
    title: str = ""  # 需求标题
    description: str = ""  # 需求描述 / 详细说明
    category: str = "functional"  # functional(功能) / non_functional(非功能) / interface(接口) / security(安全)
    priority: str = "P2"  # P0/P1/P2/P3
    source_section: str = ""  # 出处章节，便于人工复核
    acceptance_criteria: list[str] = Field(default_factory=list)  # 验收标准
    related_modules: list[str] = Field(default_factory=list)  # 关联模块 / 子系统
    test_points: list[str] = Field(default_factory=list)  # 建议测试点（AI 提示，供生成用例参考）
    confidence: float = 0.8  # AI 自评置信度；规则兜底 0.3
    evidence: str = ""  # AI 标注的原文出处


class RequirementSpec(BaseModel):
    """需求文档级统一中间表示"""

    title: str = ""
    total: int = 0
    items: list[RequirementItem] = Field(default_factory=list)
