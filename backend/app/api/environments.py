"""测试环境档案 API（企业化改造 M1）

取代执行时的临时 target_service_url：
- POST /api/projects/{project_id}/environments        创建环境草稿
- GET  /api/projects/{project_id}/environments        项目环境列表
- GET  /api/environments/{id}                          详情（含修订历史，auth 脱敏）
- PUT  /api/environments/{id}                          更新草稿配置
- POST /api/environments/{id}/healthcheck             按需健康检查（不发布）
- POST /api/environments/{id}/publish                 发布：固化不可变 revision
- DELETE /api/environments/{id}                       删除（被 Run 引用时拒绝）

发布语义：发布时把当前配置固化为 revision N（不可变），健康检查结果一并记录；
后续修改产生 revision N+1，历史 revision 供运行复现与审计。
"""
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    EnvironmentProfile,
    EnvironmentProfileRevision,
    Project,
    TestRun,
    User,
    UserRole,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.utils.crypto import decrypt, encrypt
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

SENSITIVE_AUTH_KEYS = {"token", "password", "api_key", "secret"}


# ==================== 请求模型 ====================


class EnvironmentUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    base_url: str = Field(..., min_length=1, max_length=500)
    healthcheck_path: str = Field(default="", max_length=300)
    auth_strategy: str = Field(default="none")
    # token/password 等明文传入，落库前加密；留空表示保持原有值
    auth_config: dict = Field(default_factory=dict)


# ==================== 工具函数 ====================


def _encrypt_auth(cfg: dict) -> dict:
    """auth_config 中敏感字段加密落库。"""
    out = {}
    for k, v in (cfg or {}).items():
        if k.lower() in SENSITIVE_AUTH_KEYS and isinstance(v, str) and v:
            try:
                out[k] = encrypt(v)
            except Exception:  # noqa: BLE001
                out[k] = v
        else:
            out[k] = v
    return out


def _mask_auth(cfg: dict) -> dict:
    """auth_config 敏感字段脱敏展示。"""
    from app.utils.crypto import mask_api_key

    out = {}
    for k, v in (cfg or {}).items():
        if k.lower() in SENSITIVE_AUTH_KEYS and isinstance(v, str) and v:
            try:
                out[k] = mask_api_key(decrypt(v))
            except Exception:  # noqa: BLE001
                out[k] = mask_api_key(v)
        else:
            out[k] = v
    return out


def _normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if url and not urlparse(url).scheme:
        url = "http://" + url
    return url.rstrip("/")


def _profile_to_dict(p: EnvironmentProfile, revision: EnvironmentProfileRevision | None = None) -> dict[str, Any]:
    cfg = {}
    if p.auth_config:
        try:
            cfg = _mask_auth(p.auth_config)
        except Exception:  # noqa: BLE001
            cfg = {}
    return {
        "id": str(p.id),
        "project_id": str(p.project_id),
        "name": p.name,
        "description": p.description,
        "base_url": p.base_url,
        "healthcheck_path": p.healthcheck_path or "",
        "auth_strategy": p.auth_strategy,
        "auth_config": cfg,
        "status": p.status,
        "current_revision_id": str(p.current_revision_id) if p.current_revision_id else None,
        "revision": revision.revision if revision else None,
        "health_status": revision.health_status if revision else None,
        "published_at": revision.published_at.isoformat() if revision and revision.published_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _revision_to_dict(r: EnvironmentProfileRevision) -> dict[str, Any]:
    cfg = r.config_json or {}
    masked = {**cfg}
    if masked.get("auth_config"):
        masked["auth_config"] = _mask_auth(masked["auth_config"])
    return {
        "id": str(r.id),
        "profile_id": str(r.profile_id),
        "revision": r.revision,
        "config": masked,
        "health_status": r.health_status,
        "health_detail": r.health_detail,
        "status": r.status,
        "published_at": r.published_at.isoformat() if r.published_at else None,
    }


async def _require_profile(env_id: str, db: AsyncSession) -> EnvironmentProfile:
    try:
        eid = uuid.UUID(env_id)
    except ValueError:
        raise HTTPException(400, f"Invalid environment id: {env_id}")
    p = (
        await db.execute(select(EnvironmentProfile).where(EnvironmentProfile.id == eid))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, f"Environment not found: {env_id}")
    return p


async def _current_revision(profile: EnvironmentProfile, db: AsyncSession) -> EnvironmentProfileRevision | None:
    if not profile.current_revision_id:
        return None
    return (
        await db.execute(
            select(EnvironmentProfileRevision).where(
                EnvironmentProfileRevision.id == profile.current_revision_id
            )
        )
    ).scalar_one_or_none()


async def _do_healthcheck(profile: EnvironmentProfile) -> tuple[str, str]:
    """对 base_url + healthcheck_path 发 GET，返回 (health_status, detail)。"""
    base = _normalize_base_url(profile.base_url)
    path = (profile.healthcheck_path or "").strip()
    if not path:
        return "skipped", "未配置健康检查路径"
    url = base + ("/" + path.lstrip("/") if path else "")
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if 200 <= resp.status_code < 400:
            return "healthy", f"HTTP {resp.status_code}"
        return "unreachable", f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        return "unreachable", f"连接失败: {type(e).__name__}"
    except Exception as e:  # noqa: BLE001
        return "error", str(e)[:300]


# ==================== 路由 ====================


@router.post("/projects/{project_id}/environments")
async def create_environment(
    project_id: str,
    req: EnvironmentUpsertRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)),
    db: AsyncSession = Depends(get_db_session),
):
    """创建环境草稿（发布前不生效于任何执行）。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")
    proj = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, f"Project not found: {project_id}")

    if req.auth_strategy not in ("none", "bearer", "basic", "apikey"):
        raise HTTPException(400, f"Invalid auth_strategy: {req.auth_strategy}")

    env = EnvironmentProfile(
        project_id=pid,
        name=req.name.strip(),
        description=(req.description or "").strip() or None,
        base_url=_normalize_base_url(req.base_url),
        healthcheck_path=(req.healthcheck_path or "").strip(),
        auth_strategy=req.auth_strategy,
        auth_config=_encrypt_auth(req.auth_config),
        status="draft",
        created_by=current_user.id,
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    logger.info(f"Environment created: project={pid} env={env.id}")
    return {"code": 0, "data": _profile_to_dict(env), "message": "created"}


@router.get("/projects/{project_id}/environments")
async def list_environments(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """项目的环境档案列表（草稿与已发布均返回，标明状态）。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    rows = (
        await db.execute(
            select(EnvironmentProfile)
            .where(EnvironmentProfile.project_id == pid)
            .order_by(EnvironmentProfile.created_at.desc())
        )
    ).scalars().all()

    items = []
    for p in rows:
        rev = await _current_revision(p, db)
        items.append(_profile_to_dict(p, rev))
    return {"code": 0, "data": {"list": items, "total": len(items)}, "message": "success"}


@router.get("/environments/{env_id}")
async def get_environment(
    env_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """环境详情（含修订历史，敏感字段脱敏）。"""
    profile = await _require_profile(env_id, db)
    revs = (
        await db.execute(
            select(EnvironmentProfileRevision)
            .where(EnvironmentProfileRevision.profile_id == profile.id)
            .order_by(EnvironmentProfileRevision.revision.desc())
        )
    ).scalars().all()
    cur = await _current_revision(profile, db)
    return {
        "code": 0,
        "data": {
            **_profile_to_dict(profile, cur),
            "revisions": [_revision_to_dict(r) for r in revs],
        },
        "message": "success",
    }


@router.put("/environments/{env_id}")
async def update_environment(
    env_id: str,
    req: EnvironmentUpsertRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)),
    db: AsyncSession = Depends(get_db_session),
):
    """更新环境草稿配置（发布后修改需重新发布产生新 revision）。"""
    profile = await _require_profile(env_id, db)
    if req.auth_strategy not in ("none", "bearer", "basic", "apikey"):
        raise HTTPException(400, f"Invalid auth_strategy: {req.auth_strategy}")

    profile.name = req.name.strip() or profile.name
    profile.description = (req.description or "").strip() or None
    profile.base_url = _normalize_base_url(req.base_url)
    profile.healthcheck_path = (req.healthcheck_path or "").strip()
    profile.auth_strategy = req.auth_strategy

    # auth_config 合并语义：明文留空的敏感键保持原值（不覆盖加密内容）
    new_cfg = _encrypt_auth(req.auth_config)
    merged = dict(profile.auth_config or {})
    for k, v in new_cfg.items():
        if v in (None, ""):
            continue
        merged[k] = v
    profile.auth_config = merged
    profile.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(profile)
    cur = await _current_revision(profile, db)
    return {"code": 0, "data": _profile_to_dict(profile, cur), "message": "updated"}


@router.post("/environments/{env_id}/healthcheck")
async def run_healthcheck(
    env_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """按需健康检查（不发布、不改状态，仅返回结果）。"""
    profile = await _require_profile(env_id, db)
    status, detail = await _do_healthcheck(profile)
    return {
        "code": 0,
        "data": {"health_status": status, "health_detail": detail, "checked_at": datetime.utcnow().isoformat()},
        "message": "success",
    }


@router.post("/environments/{env_id}/publish")
async def publish_environment(
    env_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """发布环境：固化当前配置为不可变 revision，记录健康检查结果。

    健康检查失败不阻断发布（结果记入 revision 供审计），由执行预检在
    运行时再次校验。
    """
    profile = await _require_profile(env_id, db)

    # 健康检查
    health_status, health_detail = await _do_healthcheck(profile)

    # 新 revision 编号
    max_rev = (
        await db.execute(
            select(func.coalesce(func.max(EnvironmentProfileRevision.revision), 0)).where(
                EnvironmentProfileRevision.profile_id == profile.id
            )
        )
    ).scalar() or 0

    now = datetime.utcnow()
    revision = EnvironmentProfileRevision(
        profile_id=profile.id,
        revision=int(max_rev) + 1,
        config_json={
            "base_url": profile.base_url,
            "healthcheck_path": profile.healthcheck_path or "",
            "auth_strategy": profile.auth_strategy,
            "auth_config": dict(profile.auth_config or {}),
        },
        health_status=health_status,
        health_detail=health_detail,
        status="published",
        created_by=current_user.id,
        published_at=now,
        published_by=current_user.id,
    )
    db.add(revision)
    await db.flush()

    # 旧 published revision 置为 superseded（排除刚创建的当前版，
    # 否则 autoflush 会把它一起查出来覆盖掉发布状态）
    old_revs = (
        await db.execute(
            select(EnvironmentProfileRevision).where(
                EnvironmentProfileRevision.profile_id == profile.id,
                EnvironmentProfileRevision.status == "published",
                EnvironmentProfileRevision.id != revision.id,
            )
        )
    ).scalars().all()
    for r in old_revs:
        r.status = "superseded"

    profile.status = "published"
    profile.current_revision_id = revision.id
    profile.updated_at = now
    await db.commit()
    await db.refresh(revision)

    logger.info(f"Environment published: env={profile.id} revision={revision.revision} health={health_status}")
    return {
        "code": 0,
        "data": {
            **_profile_to_dict(profile, revision),
            "health": {"status": health_status, "detail": health_detail},
        },
        "message": "published",
    }


@router.delete("/environments/{env_id}")
async def delete_environment(
    env_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """删除环境档案（已被任何 Run 引用时拒绝，保证历史可解释）。"""
    profile = await _require_profile(env_id, db)
    used = (
        await db.execute(
            select(func.count()).select_from(TestRun).where(TestRun.environment_profile_id == profile.id)
        )
    ).scalar() or 0
    if used:
        raise HTTPException(409, f"该环境已被 {used} 次测试运行引用，不能删除（可归档）")
    # 先提交删除修订版子行（FK 引用 profile），再删档案本身；
    # 无 relationship 时 unit-of-work 不保证删除顺序，分两个事务最稳
    await db.execute(
        delete(EnvironmentProfileRevision).where(EnvironmentProfileRevision.profile_id == profile.id)
    )
    await db.commit()
    await db.delete(profile)
    await db.commit()
    return {"code": 0, "data": None, "message": "deleted"}
