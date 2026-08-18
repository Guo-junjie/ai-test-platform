"""
能力5/6/7（脚本生成）请求/响应模型。

统一约定：
- 所有端点统一返回 {"code": 0, "data": ..., "message": "..."}
- 本文件仅定义请求体结构与响应模型，具体返回字典在 router 中构造。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateScriptRequest(BaseModel):
    """生成脚本请求 — 统一入口，支持三种脚本类型。"""

    script_type: str = Field(
        ..., description="脚本类型: pre_script / post_script / sql_script"
    )
    context: dict[str, Any] = Field(
        default_factory=dict, description="上下文信息（api_info, case_info, schema_context 等）"
    )
    project_id: Optional[int] = Field(
        default=None, description="项目 ID（用于 SQL 白名单校验）"
    )


class GenerateScriptResponse(BaseModel):
    """脚本生成响应。"""

    code: str = Field(default="", description="生成的脚本代码")
    language: str = Field(default="python", description="脚本语言: python / sql")
    script_type: str = Field(default="", description="脚本类型")
    valid: bool = Field(default=True, description="语法校验是否通过")
    error: Optional[str] = Field(default=None, description="校验错误信息")


class BindScriptRequest(BaseModel):
    """绑定脚本到用例资产请求。"""

    pre_script: Optional[str] = Field(default=None, description="前置脚本代码")
    post_script: Optional[str] = Field(default=None, description="后置脚本代码")
    sql_script: Optional[str] = Field(default=None, description="SQL 脚本代码")