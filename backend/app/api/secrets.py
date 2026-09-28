"""只读凭据目录：只暴露可引用名称，绝不返回密文或明文值。"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import DatabaseConnection, EnvironmentProfile, Project, User
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session

router = APIRouter()
_SECRET_HINTS = {"token", "secret", "password", "api_key", "apikey", "authorization", "cookie"}


def _collect_names(value: Any, prefix: str = "") -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in _SECRET_HINTS and child not in (None, ""):
                result.add(path)
            result.update(_collect_names(child, path))
    elif isinstance(value, list):
        for child in value:
            result.update(_collect_names(child, prefix))
    return result


@router.get("")
async def list_secret_names(
    project_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        pid = uuid.UUID(project_id) if project_id else None
    except ValueError as exc:
        raise HTTPException(400, "项目 ID 格式错误") from exc
    items: list[dict[str, str]] = []
    project_query = select(Project)
    env_query = select(EnvironmentProfile)
    db_query = select(DatabaseConnection)
    if pid:
        project_query = project_query.where(Project.id == pid)
        env_query = env_query.where(EnvironmentProfile.project_id == pid)
        db_query = db_query.where(DatabaseConnection.project_id == pid)
    for project in (await db.execute(project_query)).scalars().all():
        items.extend({"name": name, "scope": f"项目/{project.name}"} for name in _collect_names(project.source_config or {}))
    for env in (await db.execute(env_query)).scalars().all():
        items.extend({"name": name, "scope": f"环境/{env.name}"} for name in _collect_names(env.auth_config or {}))
    for conn in (await db.execute(db_query)).scalars().all():
        items.append({"name": f"database.{conn.name}", "scope": "数据库连接"})
    unique = {(item["name"], item["scope"]): item for item in items}
    return {"code": 0, "data": {"items": list(unique.values()), "total": len(unique)}, "message": "ok"}
