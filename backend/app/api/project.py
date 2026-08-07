"""
项目 API 路由

提供：
- GET / — 列出项目（供质量门禁、测试任务等页面选择真实项目 UUID）
- GET /{project_id} — 获取项目详情

注意：router 本身不带 prefix，统一由 main.py 以 ``prefix="/api/projects"``
注册，与其它路由（source / report / auth 等）保持一致的注册风格。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Project, User
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 内部工具 ====================


def _project_to_dict(project: Project) -> dict:
    """将 Project ORM 对象序列化为前端可用的字典。"""
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "owner_id": str(project.owner_id) if project.owner_id else None,
        "source_type": project.source_type.value if project.source_type else None,
        "is_active": bool(project.is_active),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


# ==================== API 路由 ====================


@router.get("")
@router.get("/")
async def list_projects(
    include_inactive: bool = Query(
        False, description="是否包含已停用项目，默认只返回 is_active=True 的项目"
    ),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    列出项目，按 created_at 倒序。

    默认只返回 ``is_active=True`` 的项目；传 ``?include_inactive=true``
    可返回全量（含已停用）项目。
    """
    stmt = select(Project)
    if not include_inactive:
        stmt = stmt.where(Project.is_active.is_(True))
    stmt = stmt.order_by(Project.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    projects = result.scalars().all()

    items = [_project_to_dict(p) for p in projects]

    return {
        "code": 0,
        "data": {"list": items, "items": items, "total": len(items)},
        "message": "success",
    }


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """获取单个项目详情。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")

    return {"code": 0, "data": _project_to_dict(project), "message": "success"}
