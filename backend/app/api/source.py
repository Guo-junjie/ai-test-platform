"""
数据源接入 API 路由

提供统一的数据源管理接口：
- POST /fetch — 拉取代码（GitHub/SVN/Upload 统一入口）
- GET /configs — 列出已配置的数据源
- POST /connect — 创建新的数据源配置
- DELETE /{source_id} — 软删除数据源
"""

import asyncio
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
from app.utils.crypto import decrypt_dict, encrypt_dict, mask_api_key
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger()

router = APIRouter()


# ==================== 请求模型 ====================


class FetchRequest(BaseModel):
    """代码拉取请求"""

    source_type: str  # github / svn / upload
    # 已配置数据源的 ID：提供后优先从数据库读取已加密配置并解密，
    # 使用真实凭据（如 github_token）拉取，避免前端回传脱敏串导致认证失败。
    source_id: str | None = None
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
async def fetch_code(
    req: FetchRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    拉取代码 — 统一入口。

    优先逻辑：
    - 若传入 source_id，则从数据库读取已加密的数据源配置并解密，使用真实凭据
      （如 github_token）拉取代码。前端无需、也不应再回传明文/脱敏后的 token，更安全。
    - 若未传 source_id（兼容旧调用），则沿用请求体中的字段。

    返回标准化结果（local_path / version_id / snapshot_id / files_changed / total_files）。
    """
    if req.source_id:
        result = await db.execute(
            select(Project).where(Project.id == uuid.UUID(req.source_id))
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(404, f"Source config not found: {req.source_id}")

        # 解密数据库中的敏感字段，使用真实凭据
        decrypted = decrypt_dict(project.source_config or {})
        db_source_type = (
            project.source_type.value
            if hasattr(project.source_type, "value")
            else str(project.source_type)
        )
        try:
            source_type = SourceType(db_source_type)
        except ValueError:
            raise HTTPException(
                400,
                f"Invalid source_type in DB: {db_source_type}. "
                f"Supported: {[t.value for t in SourceType]}",
            )

        config = SourceConfig(
            source_type=source_type,
            github_token=decrypted.get("github_token"),
            repo_url=decrypted.get("repo_url") or req.repo_url,
            branch=req.branch or decrypted.get("branch") or "main",
            commit_sha=req.commit_sha or decrypted.get("commit_sha"),
            svn_url=decrypted.get("svn_url") or req.svn_url,
            svn_username=decrypted.get("svn_username") or req.svn_username,
            svn_password=decrypted.get("svn_password") or req.svn_password,
            svn_revision=req.svn_revision or decrypted.get("svn_revision"),
            upload_file_path=decrypted.get("upload_file_path") or req.upload_file_path,
            incremental=req.incremental,
        )
    else:
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
        # ⚠️ fetch_code 内部是 git.Repo.clone_from 等【阻塞式】网络 I/O。
        # 绝不能在 async 处理器里直接同步调用，否则会冻结整个事件循环，
        # 导致其它所有请求排队超时（正是"很多页面操作显示超时"的根因）。
        # 必须丢到线程池执行，并加总超时保护。
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: SourceAdapterFactory.fetch_code(config)
                ),
                timeout=600,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                504,
                "代码拉取超时：GitHub 不可达或仓库过大。请确认部署机可访问 "
                "github.com、Token 有效；或改用「人工上传」数据源。",
            )
        return {"code": 0, "data": result, "message": "success"}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
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
