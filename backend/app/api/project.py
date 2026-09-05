"""
项目 API 路由

提供：
- GET / — 列出项目（供质量门禁、测试任务等页面选择真实项目 UUID）
- GET /{project_id} — 获取项目详情

注意：router 本身不带 prefix，统一由 main.py 以 ``prefix="/api/projects"``
注册，与其它路由（source / report / auth 等）保持一致的注册风格。
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Project, SourceType, User
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.dependencies import require_admin, require_role
from app.models.database import UserRole
from app.utils.crypto import encrypt
from app.utils.database import get_db_session
from pydantic import BaseModel
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
    """获取单个项目详情（含脱敏后的仓库配置，供「修改代码来源」回填）。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")

    data = _project_to_dict(project)
    from app.api.source import _mask_sensitive_fields

    data["source_config"] = _mask_sensitive_fields(project.source_config or {})
    return {"code": 0, "data": data, "message": "success"}


class ProjectUpdate(BaseModel):
    """更新项目请求（R3：代码来源支持修改）。"""

    name: str | None = None
    description: str | None = None
    source_type: str | None = None
    # 合并语义：值为空字符串/None 的键不覆盖已有配置（token 留空 = 保持不变）
    source_config: dict | None = None


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    req: ProjectUpdate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """更新项目基础信息与代码来源（source_type + 仓库配置）。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")

    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(400, "项目名称不能为空")
        if name != project.name:
            dup = (
                await db.execute(select(Project).where(Project.name == name))
            ).scalar_one_or_none()
            if dup is not None:
                raise HTTPException(409, f"项目已存在: {name}")
            project.name = name
    if req.description is not None:
        project.description = req.description.strip() or None
    if req.source_type is not None:
        try:
            project.source_type = SourceType(req.source_type)
        except ValueError:
            raise HTTPException(400, f"Invalid source_type: {req.source_type}")
    if req.source_config is not None:
        merged = dict(project.source_config or {})
        for key, value in req.source_config.items():
            # 空 / 脱敏占位值不覆盖，避免把已有 token 冲掉
            if value is None or value == "" or (isinstance(value, str) and value.startswith("****")):
                continue
            merged[key] = value
        project.source_config = merged

    project.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(project)
    return {"code": 0, "data": _project_to_dict(project), "message": "updated"}


# ==================== 项目级配置（覆盖率开关 / CI/CD 集成） ====================


class CoverageConfigUpdate(BaseModel):
    """项目级自动覆盖率开关。"""

    auto_coverage: bool


class CIConfigUpdate(BaseModel):
    """项目 CI/CD 集成配置（写入 source_config）。"""

    callback_url: str | None = None      # 测试完成后回调的 CI 地址
    auto_trigger_enabled: bool = False   # GitHub push 是否自动触发完整测试
    auto_trigger_branches: list[str] = []  # 触发的分支白名单，空 = 全部分支


class ProjectCreate(BaseModel):
    """创建项目请求。"""

    name: str
    description: str | None = None
    source_type: str = "upload"
    source_config: dict = {}
    quality_gate_config: dict = {}


@router.post("")
async def create_project(
    req: ProjectCreate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """显式创建项目（super_admin/admin/test_manager）。

    此前项目只能由测试任务隐式自动创建——用户无法先建项目再上传
    接口文档/生成用例，属产品缺口（集成测试 2026-08-30 实锤）。
    """
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "项目名称不能为空")
    dup = (
        await db.execute(select(Project).where(Project.name == name))
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"项目已存在: {name}")

    try:
        st = SourceType(req.source_type)
    except ValueError:
        raise HTTPException(400, f"Invalid source_type: {req.source_type}")

    project = Project(
        id=uuid.uuid4(),
        name=name,
        description=(req.description or "").strip() or None,
        owner_id=current_user.id,
        source_type=st,
        source_config=req.source_config or {},
        quality_gate_config=req.quality_gate_config or {},
        is_active=True,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {"code": 0, "data": _project_to_dict(project), "message": "success"}


async def _require_project(project_id: str, db: AsyncSession) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")
    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return project


async def _coverage_config_impl(
    project_id: str, req: CoverageConfigUpdate,
    current_user: User, db: AsyncSession,
):
    project = await _require_project(project_id, db)
    cfg = project.quality_gate_config or {}
    cfg["auto_coverage"] = bool(req.auto_coverage)
    project.quality_gate_config = cfg
    await db.commit()
    return {"code": 0, "data": {"project_id": project_id, "auto_coverage": bool(req.auto_coverage)}, "message": "success"}


@router.put("/{project_id}/coverage-config")
async def update_coverage_config(
    project_id: str,
    req: CoverageConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """设置项目级自动覆盖率开关（super_admin/admin/test_manager）。

    生效规则：平台 AUTO_COVERAGE=0 时一律不采集；=1 时按本项目开关（未设置默认采集）。
    """
    return await _coverage_config_impl(project_id, req, current_user, db)


@router.get("/{project_id}/ci-config")
async def get_ci_config(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """查看项目 CI/CD 集成配置（token 脱敏，不回传明文）。"""
    project = await _require_project(project_id, db)
    cfg = project.source_config or {}
    trigger = cfg.get("auto_trigger") or {}
    token_enc = cfg.get("ci_token_encrypted") or ""
    return {
        "code": 0,
        "data": {
            "project_id": project_id,
            "has_token": bool(token_enc),
            "callback_url": cfg.get("ci_callback_url") or "",
            "auto_trigger": {
                "enabled": bool(trigger.get("enabled")),
                "branches": trigger.get("branches") or [],
            },
            # 项目级自动覆盖率开关（未设置 = 默认开启）
            "auto_coverage": bool((project.quality_gate_config or {}).get("auto_coverage", True)),
        },
        "message": "success",
    }


@router.put("/{project_id}/ci-config")
async def update_ci_config(
    project_id: str,
    req: CIConfigUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """更新 CI/CD 集成配置（仅 super_admin/admin）。"""
    project = await _require_project(project_id, db)
    cfg = dict(project.source_config or {})
    cfg["ci_callback_url"] = (req.callback_url or "").strip()
    cfg["auto_trigger"] = {
        "enabled": bool(req.auto_trigger_enabled),
        "branches": [b.strip() for b in (req.auto_trigger_branches or []) if b.strip()],
    }
    project.source_config = cfg
    await db.commit()
    return {"code": 0, "data": {"project_id": project_id}, "message": "success"}


@router.post("/{project_id}/ci-token")
async def rotate_ci_token(
    project_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """生成/轮换项目 CI Token（仅 super_admin/admin）。

    明文仅本次响应返回一次（CI 侧妥善保存）；库中只存 AES 加密串。
    CI 调用方式：请求头 X-CI-Token: <明文>。
    """
    import secrets

    project = await _require_project(project_id, db)
    plain = secrets.token_hex(20)
    cfg = dict(project.source_config or {})
    cfg["ci_token_encrypted"] = encrypt(plain)
    project.source_config = cfg
    await db.commit()
    return {
        "code": 0,
        "data": {"project_id": project_id, "token": plain},
        "message": "token 已生成，请立即保存（仅本次可见）",
    }
