"""
数据源接入 API 路由

提供统一的数据源管理接口：
- POST /fetch — 拉取代码（GitHub/SVN/Upload 统一入口）
- GET /configs — 列出已配置的数据源
- POST /connect — 创建新的数据源配置
- DELETE /{source_id} — 软删除数据源
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Project, SourceType as ModelSourceType, User
from app.modules.auth.dependencies import get_current_user
from app.modules.source import SourceConfig, SourceAdapterFactory, SourceType
from app.utils.crypto import encrypt_dict, mask_api_key
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger()

router = APIRouter()


# ==================== 请求模型 ====================


class FetchRequest(BaseModel):
    """代码拉取请求"""

    source_type: str  # github / svn / upload
    # GitHub
    github_token: str | None = None
    repo_url: str | None = None
    branch: str = "main"
    commit_sha: str | None = None
    # SVN
    svn_url: str | None = None
    svn_username: str | None = None
    svn_password: str | None = None
    svn_revision: str | None = None
    # Upload
    upload_file_path: str | None = None
    # 通用
    incremental: bool = True


class ConnectRequest(BaseModel):
    """数据源连接配置请求"""

    name: str
    source_type: str  # github / svn / upload
    config: dict[str, Any]
    owner_id: str | None = None


# ==================== API 路由 ====================


@router.post("/fetch")
async def fetch_code(req: FetchRequest):
    """
    拉取代码 — 统一入口。

    根据 source_type 选择适配器，执行代码拉取并创建快照。
    返回标准化结果（local_path / version_id / snapshot_id / files_changed / total_files）。
    """
    try:
        source_type = SourceType(req.source_type)
    except ValueError:
        raise HTTPException(
            400,
            f"Invalid source_type: {req.source_type}. "
            f"Supported: {[t.value for t in SourceType]}",
        )

    config = SourceConfig(
        source_type=source_type,
        github_token=req.github_token,
        repo_url=req.repo_url,
        branch=req.branch,
        commit_sha=req.commit_sha,
        svn_url=req.svn_url,
        svn_username=req.svn_username,
        svn_password=req.svn_password,
        svn_revision=req.svn_revision,
        upload_file_path=req.upload_file_path,
        incremental=req.incremental,
    )

    try:
        result = SourceAdapterFactory.fetch_code(config)
        return {"code": 0, "data": result, "message": "success"}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Code fetch failed: {e}")
        raise HTTPException(500, f"Code fetch failed: {e}")


@router.get("/configs")
async def list_source_configs(
    db: AsyncSession = Depends(get_db_session),
):
    """
    列出已配置的数据源。

    从 projects 表查询所有活跃的数据源配置。
    敏感字段（token / password）在返回时脱敏。
    """
    result = await db.execute(
        select(Project).where(Project.is_active == True)  # noqa: E712
    )
    projects = result.scalars().all()

    configs = []
    for proj in projects:
        source_config = proj.source_config or {}
        # 脱敏处理
        masked_config = _mask_sensitive_fields(source_config)
        configs.append(
            {
                "id": str(proj.id),
                "name": proj.name,
                "source_type": proj.source_type.value
                if hasattr(proj.source_type, "value")
                else str(proj.source_type),
                "config": masked_config,
                "is_active": proj.is_active,
                "created_at": proj.created_at.isoformat()
                if proj.created_at
                else None,
            }
        )

    return {"code": 0, "data": {"list": configs, "total": len(configs)}, "message": "success"}


@router.post("/connect")
async def connect_source(
    req: ConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    创建新的数据源配置。

    将数据源配置写入 projects 表的 source_config JSONB 字段。
    敏感字段（github_token / svn_password）存入前加密。
    """
    try:
        source_type = ModelSourceType(req.source_type)
    except ValueError:
        raise HTTPException(
            400,
            f"Invalid source_type: {req.source_type}. "
            f"Supported: {[t.value for t in ModelSourceType]}",
        )

    # 加密敏感字段
    encrypted_config = encrypt_dict(req.config)

    project = Project(
        id=uuid.uuid4(),
        name=req.name,
        description=f"Data source: {req.source_type}",
        owner_id=current_user.id,
        source_type=source_type,
        source_config=encrypted_config,
        quality_gate_config={},
        is_active=True,
    )

    db.add(project)
    await db.flush()

    logger.info(f"Source config created: {req.name} ({req.source_type})")

    return {
        "code": 0,
        "data": {"id": str(project.id), "name": req.name, "source_type": req.source_type},
        "message": "Data source connected successfully",
    }


@router.delete("/{source_id}")
async def disconnect_source(
    source_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """软删除数据源 — 设置 is_active=False。"""
    result = await db.execute(
        select(Project).where(Project.id == uuid.UUID(source_id))
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(404, f"Source config not found: {source_id}")

    project.is_active = False
    project.updated_at = datetime.utcnow()

    logger.info(f"Source config deactivated: {source_id}")

    return {"code": 0, "data": None, "message": "Data source disconnected"}


# ==================== 工具函数 ====================

SENSITIVE_FIELD_NAMES = {"github_token", "svn_password", "password", "token", "api_key"}


def _mask_sensitive_fields(config: dict[str, Any]) -> dict[str, Any]:
    """
    对配置中的敏感字段进行脱敏处理。

    Args:
        config: 原始配置字典。

    Returns:
        敏感字段已脱敏的配置字典副本。
    """
    masked: dict[str, Any] = {}
    for key, value in config.items():
        if key.lower() in SENSITIVE_FIELD_NAMES and isinstance(value, str) and value:
            masked[key] = mask_api_key(value)
        else:
            masked[key] = value
    return masked
