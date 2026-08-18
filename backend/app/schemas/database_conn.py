"""
能力7（数据库连接管理）请求/响应模型。

密码字段使用 app.utils.crypto 加密存储，API 响应时脱敏显示。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DatabaseConnectionRequest(BaseModel):
    """创建数据库连接请求。"""

    name: str = Field(..., description="连接名称")
    db_type: str = Field(..., description="数据库类型: postgresql / mysql / sqlite / mssql")
    host: str = Field(default="localhost", description="主机地址")
    port: int = Field(default=5432, description="端口号")
    username: str = Field(default="", description="用户名")
    password: str = Field(default="", description="密码（明文传入，加密存储）")
    database: str = Field(default="", description="数据库名")
    project_id: Optional[str] = Field(default=None, description="所属项目 ID")


class DatabaseConnectionUpdate(BaseModel):
    """更新数据库连接请求 — 所有字段可选。"""

    name: Optional[str] = Field(default=None, description="连接名称")
    db_type: Optional[str] = Field(default=None, description="数据库类型")
    host: Optional[str] = Field(default=None, description="主机地址")
    port: Optional[int] = Field(default=None, description="端口号")
    username: Optional[str] = Field(default=None, description="用户名")
    password: Optional[str] = Field(default=None, description="密码（明文传入，加密存储）")
    database: Optional[str] = Field(default=None, description="数据库名")


class DatabaseConnectionResponse(BaseModel):
    """数据库连接响应 — 密码已脱敏。"""

    id: str
    name: str
    db_type: str
    host: str
    port: int
    username: str
    password: str = Field(default="****", description="密码已脱敏")
    database: str
    project_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None