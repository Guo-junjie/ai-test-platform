"""
缺陷管理 API — 独立缺陷中心（不只藏在报告里）

- GET /api/defects — 列表（项目/严重级/类型/状态/关键字过滤 + 分页 + 统计）
- POST /api/defects — 手动创建（测试执行外发现的问题，如探索性测试）
- PATCH /api/defects/{id}/status — 状态流转（open → in_fix → verified → closed / rejected）
- GET /api/defects/{id} — 详情
- DELETE /api/defects/{id} — 删除（manager 及以上）
"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    Defect,
    DefectSeverity,
    DefectType,
    Project,
    TestRun,
    User,
    UserRole,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 状态机：open → in_fix → verified → closed；任意状态可 rejected
DEFECT_STATUSES = ("open", "in_fix", "verified", "closed", "rejected")
_ALLOWED_TRANSITIONS = {
    "open": {"in_fix", "rejected", "closed"},
    "in_fix": {"verified", "open", "rejected"},
    "verified": {"closed", "open"},
    "closed": set(),
    "rejected": {"open"},
}
_STATUS_LABELS = {
    "open": "待处理", "in_fix": "修复中", "verified": "已验证", "closed": "已关闭", "rejected": "已驳回",
}
_TYPE_LABELS = {
    "business": "业务缺陷", "program": "程序缺陷", "performance": "性能缺陷",
    "integration": "集成缺陷", "security": "安全缺陷",
}


class DefectCreate(BaseModel):
    """手动创建缺陷。"""

    project_id: str
    title: str = Field(..., min_length=2, max_length=500)
    description: str
    severity: str = "P2"          # P0-P3
    defect_type: str = "business" # business/program/performance/integration/security
    reproduce_steps: list[str] = Field(default_factory=list)
    source: str = "manual"        # manual / pipeline（pipeline 为 AI 分析产生）


class DefectStatusUpdate(BaseModel):
    status: str
    note: str | None = None


def _severity_label(v: str) -> str:
    return {"P0": "致命", "P1": "严重", "P2": "一般", "P3": "轻微"}.get(v, v)


def _defect_to_dict(d: Defect, project_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "test_run_id": str(d.test_run_id) if d.test_run_id else None,
        "project_id": str(d.project_id) if hasattr(d, "project_id") and d.project_id else None,
        "project_name": project_name,
        "title": d.title,
        "description": d.description,
        "defect_type": d.defect_type.value if d.defect_type else "business",
        "defect_type_label": _TYPE_LABELS.get(d.defect_type.value if d.defect_type else "", ""),
        "severity": d.severity.value if d.severity else "P2",
        "severity_label": _severity_label(d.severity.value if d.severity else "P2"),
        "reproduce_steps": d.reproduce_steps or [],
        "root_cause": d.root_cause,
        "fix_suggestion": d.fix_suggestion,
        "status": _STATUS_LABELS.get(getattr(d, "status", None) or "open", "待处理"),
        "status_code": getattr(d, "status", None) or "open",
        "is_resolved": bool(d.is_resolved),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("")
async def list_defects(
    project_id: str | None = Query(None, description="按项目过滤"),
    severity: str | None = Query(None, description="P0/P1/P2/P3"),
    defect_type: str | None = Query(None),
    status_code: str | None = Query(None, description="open/in_fix/verified/closed/rejected"),
    q: str | None = Query(None, description="标题/描述关键字"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """缺陷列表：多条件过滤 + 分页 + 分组统计。"""
    # 基础查询（Defect 无 project_id 列，经 TestRun 关联）
    stmt = select(Defect, TestRun.project_id, Project.name).outerjoin(
        TestRun, TestRun.id == Defect.test_run_id
    ).outerjoin(Project, Project.id == TestRun.project_id)
    count_stmt = select(func.count()).select_from(Defect).outerjoin(
        TestRun, TestRun.id == Defect.test_run_id
    )

    conds = []
    if project_id:
        conds.append(TestRun.project_id == uuid.UUID(project_id))
    if severity:
        try:
            conds.append(Defect.severity == DefectSeverity(severity))
        except ValueError:
            raise HTTPException(400, f"Invalid severity: {severity}")
    if defect_type:
        try:
            conds.append(Defect.defect_type == DefectType(defect_type))
        except ValueError:
            raise HTTPException(400, f"Invalid defect_type: {defect_type}")
    if status_code:
        conds.append(Defect.status == status_code)  # status 为 String 列
    if q:
        like = f"%{q}%"
        conds.append(or_(Defect.title.ilike(like), Defect.description.ilike(like)))

    for c in conds:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)

    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(Defect.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).fetchall()

    # 统计（不受分页影响，受过滤影响）
    by_severity: dict[str, int] = {s: 0 for s in ("P0", "P1", "P2", "P3")}
    by_status: dict[str, int] = {s: 0 for s in DEFECT_STATUSES}
    if conds:
        stat_stmt = select(Defect.severity, Defect.status, func.count()).where(*conds).group_by(Defect.severity, Defect.status)
    else:
        stat_stmt = select(Defect.severity, Defect.status, func.count()).group_by(Defect.severity, Defect.status)
    for sev, st, cnt in (await db.execute(stat_stmt)).fetchall():
        if sev is not None:
            by_severity[sev.value] = cnt
        if st:
            by_status[st] = cnt

    return {
        "code": 0,
        "data": {
            "list": [_defect_to_dict(d, pname) for d, _pid, pname in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "stats": {"by_severity": by_severity, "by_status": by_status},
        },
        "message": "success",
    }


@router.post("")
async def create_defect(
    req: DefectCreate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)),
    db: AsyncSession = Depends(get_db_session),
):
    """手动创建缺陷（测试执行之外发现的问题）。"""
    project = (
        await db.execute(select(Project).where(Project.id == uuid.UUID(req.project_id)))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {req.project_id}")

    try:
        sev, dtype = DefectSeverity(req.severity), DefectType(req.defect_type)
    except ValueError as e:
        raise HTTPException(400, str(e))

    defect = Defect(
        id=uuid.uuid4(),
        test_run_id=None,  # 手动创建不挂 run
        title=req.title.strip(),
        description=req.description.strip(),
        defect_type=dtype,
        severity=sev,
        reproduce_steps=req.reproduce_steps,
        status="open",
        is_resolved=False,
    )
    db.add(defect)
    await db.commit()
    await db.refresh(defect)
    return {"code": 0, "data": _defect_to_dict(defect, project.name), "message": "created"}


@router.get("/{defect_id}")
async def get_defect(
    defect_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        did = uuid.UUID(defect_id)
    except ValueError:
        raise HTTPException(400, f"Invalid defect id: {defect_id}")
    row = (
        await db.execute(
            select(Defect, Project.name)
            .outerjoin(TestRun, TestRun.id == Defect.test_run_id)
            .outerjoin(Project, Project.id == TestRun.project_id)
            .where(Defect.id == did)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Defect not found")
    return {"code": 0, "data": _defect_to_dict(row[0], row[1]), "message": "success"}


@router.patch("/{defect_id}/status")
async def update_defect_status(
    defect_id: str,
    req: DefectStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """缺陷状态流转（校验合法迁移）：open→in_fix→verified→closed；可驳回/重开。"""
    if req.status not in DEFECT_STATUSES:
        raise HTTPException(400, f"Invalid status, allowed: {DEFECT_STATUSES}")
    try:
        did = uuid.UUID(defect_id)
    except ValueError:
        raise HTTPException(400, f"Invalid defect id: {defect_id}")

    defect = (
        await db.execute(select(Defect).where(Defect.id == did))
    ).scalar_one_or_none()
    if defect is None:
        raise HTTPException(404, "Defect not found")

    cur = defect.status or "open"
    if req.status not in _ALLOWED_TRANSITIONS.get(cur, set()):
        raise HTTPException(
            400,
            f"非法状态迁移: {cur} → {req.status}（允许: {_ALLOWED_TRANSITIONS.get(cur) or '无，终态'}）",
        )

    defect.status = req.status
    if req.note:
        notes = list(defect.reproduce_steps or [])
        notes.append(f"[{datetime.utcnow().strftime('%m-%d %H:%M')} {current_user.username}] {req.note}")
        defect.reproduce_steps = notes[:50]  # 复用 steps 存流转备注，避免改表
    defect.is_resolved = req.status in ("verified", "closed")
    await db.commit()
    return {"code": 0, "data": {"id": defect_id, "status": req.status}, "message": "success"}


@router.delete("/{defect_id}")
async def delete_defect(
    defect_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        did = uuid.UUID(defect_id)
    except ValueError:
        raise HTTPException(400, f"Invalid defect id: {defect_id}")
    defect = (
        await db.execute(select(Defect).where(Defect.id == did))
    ).scalar_one_or_none()
    if defect is None:
        raise HTTPException(404, "Defect not found")
    await db.delete(defect)
    await db.commit()
    return {"code": 0, "data": {"deleted": True}, "message": "success"}
