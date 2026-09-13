"""P0 测试计划 API（CRUD + 用例管理 + 执行触发）

- GET    /api/plans                       列表（项目过滤/搜索/分页，附统计）
- POST   /api/plans                       创建（manager+）
- GET    /api/plans/{id}                  详情（计划用例清单）
- PUT    /api/plans/{id}                  修改名称/描述/状态
- DELETE /api/plans/{id}                  删除（manager+，级联）
- GET    /api/plans/{id}/cases            计划内用例清单
- POST   /api/plans/{id}/cases            加入用例（按 case_asset_ids）
- DELETE /api/plans/{id}/cases/{case_id}  移除用例
- PUT    /api/plans/{id}/cases/{case_id}  启用/禁用（enabled 切换）
- POST   /api/plans/{id}/cases/bulk-add   批量加入（按 filter 自动匹配）
- GET    /api/plans/{id}/executions        执行历史
- POST   /api/plans/{id}/execute          触发执行（创建 TestRun + 派发流水线）
"""
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    EnvironmentProfile,
    Project,
    TestCaseAsset,
    TestPlan,
    TestPlanCase,
    TestPlanExecution,
    TestPlanRevision,
    TestPlanRevisionCase,
    TestRun,
    TestStatus,
    User,
    UserRole,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.runs.case_snapshot import case_content_hash, executable_case_payload
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 请求/响应模型 ====================


class PlanCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=2, max_length=200)
    description: str | None = None
    status: str = "active"  # active / archived


class PlanUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = None
    status: str | None = None  # active / archived


class PlanCaseAdd(BaseModel):
    case_asset_ids: list[str] = Field(..., min_length=1)


class PlanCaseToggle(BaseModel):
    enabled: bool


class PlanBulkAdd(BaseModel):
    """按 filter 批量匹配用例资产（用例库的过滤参数）。"""

    status: str | None = None        # adopted / deprecated
    case_type: str | None = None      # positive / negative / boundary / exception
    priority: str | None = None      # P0-P3
    keyword: str | None = None
    limit: int = Field(100, ge=1, le=500)


# ==================== 内部工具 ====================


async def _plan_state(plan_id: uuid.UUID, db: AsyncSession) -> tuple[str, list]:
    """计算计划当前编辑态指纹与启停用例行（TestPlanCase, TestCaseAsset）。"""
    rows = (
        await db.execute(
            select(TestPlanCase, TestCaseAsset)
            .outerjoin(TestCaseAsset, TestCaseAsset.id == TestPlanCase.case_asset_id)
            .where(TestPlanCase.plan_id == plan_id)
            .order_by(TestPlanCase.sort_order.asc(), TestPlanCase.added_at.asc())
        )
    ).all()
    state = [
        {
            "case_asset_id": str(pc.case_asset_id),
            "enabled": pc.enabled,
            "execution_kind": a.execution_kind if a else None,
            "description": a.description if a else None,
            "content_hash": case_content_hash(a),
        }
        for pc, a in rows
    ]
    state_hash = hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return state_hash, rows


async def _latest_published_revision(plan_id: uuid.UUID, db: AsyncSession) -> TestPlanRevision | None:
    return (
        await db.execute(
            select(TestPlanRevision)
            .where(
                TestPlanRevision.plan_id == plan_id,
                TestPlanRevision.status == "published",
            )
            .order_by(TestPlanRevision.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _plan_to_dict(p: TestPlan, total: int = 0, enabled: int = 0, m2: dict[str, Any] | None = None) -> dict[str, Any]:
    d = {
        "id": str(p.id),
        "project_id": str(p.project_id),
        "name": p.name,
        "description": p.description,
        "status": p.status or "active",
        "source": p.source or "manual",
        "created_by": str(p.created_by) if p.created_by else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "stats": {"total_cases": total, "enabled_cases": enabled},
    }
    if m2:
        d.update(m2)
    return d


def _plan_case_to_dict(pc: TestPlanCase, asset: TestCaseAsset | None) -> dict[str, Any]:
    return {
        "plan_id": str(pc.plan_id),
        "case_asset_id": str(pc.case_asset_id),
        "sort_order": pc.sort_order or 0,
        "enabled": bool(pc.enabled),
        "added_at": pc.added_at.isoformat() if pc.added_at else None,
        "case": {
            "id": str(asset.id),
            "title": asset.title,
            "case_type": asset.case_type,
            "priority": asset.priority,
            "status": asset.status.value if asset.status else "draft",
        } if asset else None,
    }


async def _require_plan(plan_id: str, db: AsyncSession) -> TestPlan:
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(400, f"Invalid plan_id: {plan_id}")
    plan = (
        await db.execute(select(TestPlan).where(TestPlan.id == pid))
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(404, f"Test plan not found: {plan_id}")
    return plan


# ==================== 计划 CRUD ====================


@router.get("")
async def list_plans(
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """测试计划列表（项目/状态/关键字过滤 + 分页 + 统计）。"""
    stmt = select(TestPlan).order_by(TestPlan.updated_at.desc())
    count_stmt = select(func.count()).select_from(TestPlan)

    conds = []
    if project_id:
        try:
            conds.append(TestPlan.project_id == uuid.UUID(project_id))
        except ValueError:
            raise HTTPException(400, f"Invalid project_id: {project_id}")
    if status:
        conds.append(TestPlan.status == status)
    if q:
        like = f"%{q}%"
        conds.append(TestPlan.name.ilike(like))
    for c in conds:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)

    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    # 批量统计：每计划的用例数 / 启用数（避免 N+1）
    stats_map: dict[str, tuple[int, int]] = {}
    if rows:
        from sqlalchemy import Integer as _Int
        ids = [r.id for r in rows]
        st_rows = (
            await db.execute(
                select(
                    TestPlanCase.plan_id,
                    func.count(),
                    func.sum(func.cast(TestPlanCase.enabled, _Int)),
                )
                .where(TestPlanCase.plan_id.in_(ids))
                .group_by(TestPlanCase.plan_id)
            )
        ).all()
        for pid_, total_cnt, enabled_cnt in st_rows:
            stats_map[str(pid_)] = (int(total_cnt or 0), int(enabled_cnt or 0))

    # M2：每计划的最新发布修订 + 未发布变更检测
    m2_map: dict[str, dict[str, Any]] = {}
    if rows:
        ids = [r.id for r in rows]
        # 每计划最新修订（任意状态，取 revision 最大）
        latest_rows = (
            await db.execute(
                select(
                    TestPlanRevision.plan_id,
                    func.max(TestPlanRevision.revision).label("max_rev"),
                )
                .where(TestPlanRevision.plan_id.in_(ids))
                .group_by(TestPlanRevision.plan_id)
            )
        ).all()
        latest_map = {str(pid_): int(mr or 0) for pid_, mr in latest_rows}
        # 最新 published 修订
        pub_rows = (
            await db.execute(
                select(TestPlanRevision)
                .where(
                    TestPlanRevision.plan_id.in_(ids),
                    TestPlanRevision.status == "published",
                )
                .order_by(TestPlanRevision.revision.desc())
            )
        ).scalars().all()
        pub_map: dict[str, TestPlanRevision] = {}
        for r in pub_rows:
            pub_map.setdefault(str(r.plan_id), r)
        # 当前编辑态指纹
        state_map: dict[str, str] = {}
        for r in rows:
            h, _ = await _plan_state(r.id, db)
            state_map[str(r.id)] = h
        for r in rows:
            key = str(r.id)
            pub = pub_map.get(key)
            m2_map[key] = {
                "latest_revision": latest_map.get(key, 0),
                "published_revision": pub.revision if pub else 0,
                "published_state_hash": pub.plan_state_hash[:12] if pub else None,
                "has_unpublished_changes": bool(pub is None or pub.plan_state_hash != state_map[key]),
            }

    return {
        "code": 0,
        "data": {
            "list": [
                _plan_to_dict(r, *stats_map.get(str(r.id), (0, 0)), m2=m2_map.get(str(r.id)))
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.post("")
async def create_plan(
    req: PlanCreate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """创建测试计划。"""
    try:
        pid = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {req.project_id}")
    proj = (await db.execute(select(Project).where(Project.id == pid))).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, f"Project not found: {req.project_id}")
    if req.status not in ("active", "archived"):
        raise HTTPException(400, "status must be active or archived")

    name = req.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    dup = (
        await db.execute(
            select(TestPlan).where(TestPlan.project_id == pid, TestPlan.name == name)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"Test plan already exists: {name}")

    plan = TestPlan(
        id=uuid.uuid4(),
        project_id=pid,
        name=name,
        description=(req.description or "").strip() or None,
        status=req.status,
        source="manual",
        created_by=current_user.id,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {"code": 0, "data": _plan_to_dict(plan), "message": "created"}


@router.get("/{plan_id}")
async def get_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """计划详情（含计划内用例清单 + 关联测试任务最近执行）。"""
    plan = await _require_plan(plan_id, db)

    # 计划内用例（LEFT JOIN 用例资产取标题/类型）
    plan_cases_rows = (
        await db.execute(
            select(TestPlanCase, TestCaseAsset)
            .outerjoin(TestCaseAsset, TestCaseAsset.id == TestPlanCase.case_asset_id)
            .where(TestPlanCase.plan_id == plan.id)
            .order_by(TestPlanCase.sort_order.asc(), TestPlanCase.added_at.asc())
        )
    ).all()

    # 最近一次执行
    latest_exec = (
        await db.execute(
            select(TestPlanExecution)
            .where(TestPlanExecution.plan_id == plan.id)
            .order_by(TestPlanExecution.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # M2：修订信息 + 未发布变更检测
    state_hash, _rows = await _plan_state(plan.id, db)
    latest_pub = await _latest_published_revision(plan.id, db)
    m2_info = {
        "published_revision": latest_pub.revision if latest_pub else 0,
        "published_state_hash": latest_pub.plan_state_hash[:12] if latest_pub else None,
        "has_unpublished_changes": bool(latest_pub is None or latest_pub.plan_state_hash != state_hash),
    }

    return {
        "code": 0,
        "data": {
            **_plan_to_dict(plan, m2=m2_info),
            "cases": [_plan_case_to_dict(pc, a) for pc, a in plan_cases_rows],
            "latest_execution": {
                "id": str(latest_exec.id),
                "test_run_id": str(latest_exec.test_run_id),
                "total": latest_exec.total,
                "passed": latest_exec.passed,
                "failed": latest_exec.failed,
                "started_at": latest_exec.started_at.isoformat() if latest_exec.started_at else None,
                "finished_at": latest_exec.finished_at.isoformat() if latest_exec.finished_at else None,
            } if latest_exec else None,
        },
        "message": "success",
    }


@router.put("/{plan_id}")
async def update_plan(
    plan_id: str,
    req: PlanUpdate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """修改计划名称/描述/状态（status=archived 表示归档禁用）。"""
    plan = await _require_plan(plan_id, db)

    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            raise HTTPException(400, "name cannot be empty")
        if new_name != plan.name:
            dup = (
                await db.execute(
                    select(TestPlan).where(
                        TestPlan.project_id == plan.project_id,
                        TestPlan.name == new_name,
                        TestPlan.id != plan.id,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise HTTPException(409, f"Test plan already exists: {new_name}")
            plan.name = new_name
    if req.description is not None:
        plan.description = req.description.strip() or None
    if req.status is not None:
        if req.status not in ("active", "archived"):
            raise HTTPException(400, "status must be active or archived")
        plan.status = req.status
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {"code": 0, "data": _plan_to_dict(plan), "message": "updated"}


@router.delete("/{plan_id}")
async def delete_plan(
    plan_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """删除计划（级联删除 plan_cases，已生成 TestRun 保留不受影响）。"""
    plan = await _require_plan(plan_id, db)
    await db.delete(plan)  # cascade via TestPlanCase FK
    await db.commit()
    return {"code": 0, "data": {"deleted": True}, "message": "success"}


# ==================== 计划用例管理 ====================


@router.get("/{plan_id}/cases")
async def list_plan_cases(
    plan_id: str,
    enabled_only: bool = Query(False, description="仅返回启用的用例"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """计划内用例清单。"""
    plan = await _require_plan(plan_id, db)
    stmt = (
        select(TestPlanCase, TestCaseAsset)
        .outerjoin(TestCaseAsset, TestCaseAsset.id == TestPlanCase.case_asset_id)
        .where(TestPlanCase.plan_id == plan.id)
        .order_by(TestPlanCase.sort_order.asc(), TestPlanCase.added_at.asc())
    )
    if enabled_only:
        stmt = stmt.where(TestPlanCase.enabled.is_(True))
    rows = (await db.execute(stmt)).all()
    return {
        "code": 0,
        "data": {"items": [_plan_case_to_dict(pc, a) for pc, a in rows]},
        "message": "success",
    }


@router.post("/{plan_id}/cases")
async def add_plan_cases(
    plan_id: str,
    req: PlanCaseAdd,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """向计划加入用例资产（idempotent——已加入的静默跳过）。"""
    plan = await _require_plan(plan_id, db)
    if plan.status != "active":
        raise HTTPException(400, f"Cannot edit {plan.status} plan")

    # 校验 case_asset_ids 合法
    parsed_ids: list[uuid.UUID] = []
    for cid in req.case_asset_ids:
        try:
            parsed_ids.append(uuid.UUID(cid))
        except ValueError:
            raise HTTPException(400, f"Invalid case_asset_id: {cid}")
    # 校验属于同一项目
    rows = (
        await db.execute(
            select(TestCaseAsset.id, TestCaseAsset.project_id)
            .where(TestCaseAsset.id.in_(parsed_ids))
        )
    ).all()
    id_to_proj = {rid: pid for rid, pid in rows}
    missing = [str(c) for c in parsed_ids if c not in id_to_proj]
    if missing:
        raise HTTPException(404, f"Case asset not found: {missing}")
    cross = [str(c) for c, pid in id_to_proj.items() if pid != plan.project_id]
    if cross:
        raise HTTPException(400, f"Case assets cross project: {cross}")

    # 已存在
    existing = {
        pc.case_asset_id
        for pc in (
            await db.execute(
                select(TestPlanCase).where(
                    TestPlanCase.plan_id == plan.id,
                    TestPlanCase.case_asset_id.in_(parsed_ids),
                )
            )
        ).scalars().all()
    }
    added = 0
    for cid in parsed_ids:
        if cid in existing:
            continue
        db.add(TestPlanCase(plan_id=plan.id, case_asset_id=cid))
        added += 1
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "code": 0,
        "data": {"requested": len(parsed_ids), "added": added, "skipped_duplicates": len(parsed_ids) - added},
        "message": f"added {added} case(s)",
    }


@router.delete("/{plan_id}/cases/{case_id}")
async def remove_plan_case(
    plan_id: str,
    case_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    plan = await _require_plan(plan_id, db)
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, f"Invalid case_id: {case_id}")
    pc = (
        await db.execute(
            select(TestPlanCase).where(
                TestPlanCase.plan_id == plan.id,
                TestPlanCase.case_asset_id == cid,
            )
        )
    ).scalar_one_or_none()
    if pc is None:
        raise HTTPException(404, "Case not in plan")
    await db.delete(pc)
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {"code": 0, "data": {"removed": True}, "message": "removed"}


@router.put("/{plan_id}/cases/{case_id}")
async def toggle_plan_case(
    plan_id: str,
    case_id: str,
    req: PlanCaseToggle,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    plan = await _require_plan(plan_id, db)
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, f"Invalid case_id: {case_id}")
    pc = (
        await db.execute(
            select(TestPlanCase).where(
                TestPlanCase.plan_id == plan.id,
                TestPlanCase.case_asset_id == cid,
            )
        )
    ).scalar_one_or_none()
    if pc is None:
        raise HTTPException(404, "Case not in plan")
    pc.enabled = bool(req.enabled)
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {"code": 0, "data": {"enabled": pc.enabled}, "message": "updated"}


@router.post("/{plan_id}/cases/bulk-add")
async def bulk_add_plan_cases(
    plan_id: str,
    req: PlanBulkAdd,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """按 filter 自动匹配同项目用例资产并加入计划（用于：项目刚建好，把"所有已采纳用例"一键收编）。"""
    plan = await _require_plan(plan_id, db)
    if plan.status != "active":
        raise HTTPException(400, f"Cannot edit {plan.status} plan")

    from app.models.database import CaseAssetStatus  # 局部导入避免循环

    stmt = select(TestCaseAsset).where(TestCaseAsset.project_id == plan.project_id)
    if req.status:
        try:
            stmt = stmt.where(TestCaseAsset.status == CaseAssetStatus(req.status))
        except ValueError:
            raise HTTPException(400, f"Invalid status: {req.status}")
    if req.case_type:
        stmt = stmt.where(TestCaseAsset.case_type == req.case_type)
    if req.priority:
        stmt = stmt.where(TestCaseAsset.priority == req.priority)
    if req.keyword:
        like = f"%{req.keyword}%"
        from sqlalchemy import or_  # noqa: PLC0415

        stmt = stmt.where(
            or_(
                TestCaseAsset.title.ilike(like),
                TestCaseAsset.description.ilike(like),
            )
        )
    assets = (await db.execute(stmt.order_by(TestCaseAsset.created_at.desc()).limit(req.limit))).scalars().all()

    if not assets:
        return {"code": 0, "data": {"matched": 0, "added": 0, "skipped": 0}, "message": "no matches"}

    # 排除已加入
    existing = {
        pc.case_asset_id
        for pc in (
            await db.execute(
                select(TestPlanCase).where(
                    TestPlanCase.plan_id == plan.id,
                    TestPlanCase.case_asset_id.in_([a.id for a in assets]),
                )
            )
        ).scalars().all()
    }
    added = 0
    max_sort = (
        await db.execute(
            select(func.coalesce(func.max(TestPlanCase.sort_order), 0)).where(TestPlanCase.plan_id == plan.id)
        )
    ).scalar() or 0
    for asset in assets:
        if asset.id in existing:
            continue
        max_sort += 1
        db.add(TestPlanCase(plan_id=plan.id, case_asset_id=asset.id, sort_order=max_sort))
        added += 1
    plan.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "code": 0,
        "data": {"matched": len(assets), "added": added, "skipped_duplicates": len(assets) - added},
        "message": f"added {added} case(s)",
    }


# ==================== 执行历史 + 触发执行 ====================


@router.get("/{plan_id}/executions")
async def list_plan_executions(
    plan_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    plan = await _require_plan(plan_id, db)
    total = (
        await db.execute(
            select(func.count()).select_from(TestPlanExecution).where(TestPlanExecution.plan_id == plan.id)
        )
    ).scalar() or 0
    rows = (
        await db.execute(
            select(TestPlanExecution, TestRun.status)
            .outerjoin(TestRun, TestRun.id == TestPlanExecution.test_run_id)
            .where(TestPlanExecution.plan_id == plan.id)
            .order_by(TestPlanExecution.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "id": str(e.id),
                    "test_run_id": str(e.test_run_id),
                    "status": run_status.value if run_status else "unknown",
                    "total": e.total or 0,
                    "passed": e.passed or 0,
                    "failed": e.failed or 0,
                    "skipped": e.skipped or 0,
                    "duration_ms": e.duration_ms or 0,
                    "started_at": e.started_at.isoformat() if e.started_at else None,
                    "finished_at": e.finished_at.isoformat() if e.finished_at else None,
                }
                for e, run_status in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.post("/{plan_id}/publish")
async def publish_plan(
    plan_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """发布计划：固化当前编辑态用例集合为不可变修订版（企业化改造 M2）。

    发布后计划被修改不会影响已发布修订版；执行始终基于最新已发布修订版。
    """
    plan = await _require_plan(plan_id, db)
    if plan.status != "active":
        raise HTTPException(400, f"Cannot publish {plan.status} plan")

    state_hash, rows = await _plan_state(plan.id, db)
    enabled_rows = [(pc, a) for pc, a in rows if pc.enabled]
    if not enabled_rows:
        raise HTTPException(400, "计划内无启用用例，无法发布")

    # 已发布且状态未变 → 无需重复发布
    latest = await _latest_published_revision(plan.id, db)
    if latest is not None and latest.plan_state_hash == state_hash:
        return {
            "code": 0,
            "data": {
                "revision": latest.revision,
                "plan_state_hash": latest.plan_state_hash,
                "unchanged": True,
                "message": "当前状态与最新已发布修订版一致，无需重新发布",
            },
            "message": "unchanged",
        }

    # 绑定的默认环境（若档案已删除/未发布则置空）
    env_id = plan.environment_profile_id if hasattr(plan, "environment_profile_id") else None

    max_rev = (
        await db.execute(
            select(func.coalesce(func.max(TestPlanRevision.revision), 0)).where(
                TestPlanRevision.plan_id == plan.id
            )
        )
    ).scalar() or 0

    now = datetime.utcnow()
    revision = TestPlanRevision(
        plan_id=plan.id,
        revision=int(max_rev) + 1,
        plan_state_hash=state_hash,
        case_count=len(rows),
        enabled_count=len(enabled_rows),
        status="published",
        created_by=current_user.id,
        published_at=now,
        published_by=current_user.id,
    )
    db.add(revision)
    await db.flush()

    for i, (pc, a) in enumerate(rows):
        db.add(TestPlanRevisionCase(
            revision_id=revision.id,
            case_asset_id=pc.case_asset_id,
            title=(a.title if a else "（用例已删除）"),
            execution_kind=(a.execution_kind if a else "api"),
            design_type=(a.design_type or (a.case_type if a else None)),
            enabled=pc.enabled,
            sort_order=i,
            content_hash=case_content_hash(a),
            case_payload=executable_case_payload(a) if a else None,
        ))

    # 旧 published → superseded（排除当前，规避 autoflush 覆盖——M1 教训）
    old_revs = (
        await db.execute(
            select(TestPlanRevision).where(
                TestPlanRevision.plan_id == plan.id,
                TestPlanRevision.status == "published",
                TestPlanRevision.id != revision.id,
            )
        )
    ).scalars().all()
    for r in old_revs:
        r.status = "superseded"

    await db.commit()
    await db.refresh(revision)
    logger.info(f"Plan published: plan={plan.id} revision={revision.revision} cases={revision.enabled_count}")
    return {
        "code": 0,
        "data": {
            "revision": revision.revision,
            "revision_id": str(revision.id),
            "plan_state_hash": revision.plan_state_hash,
            "case_count": revision.case_count,
            "enabled_count": revision.enabled_count,
            "published_at": revision.published_at.isoformat(),
        },
        "message": "published",
    }


@router.get("/{plan_id}/revisions")
async def list_plan_revisions(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """计划修订版历史（发布记录）。"""
    plan = await _require_plan(plan_id, db)
    revs = (
        await db.execute(
            select(TestPlanRevision)
            .where(TestPlanRevision.plan_id == plan.id)
            .order_by(TestPlanRevision.revision.desc())
        )
    ).scalars().all()
    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "revision": r.revision,
                    "status": r.status,
                    "case_count": r.case_count,
                    "enabled_count": r.enabled_count,
                    "plan_state_hash": r.plan_state_hash[:12],
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                }
                for r in revs
            ]
        },
        "message": "success",
    }


class ExecutePlanRequest(BaseModel):
    target_service_url: str | None = None
    # M1：环境档案 —— 优先级高于 target_service_url；须为该项目下「已发布」环境
    environment_profile_id: str | None = None
    # M2：指定执行的修订版（缺省 = 最新已发布修订版）
    plan_revision_id: str | None = None


@router.post("/{plan_id}/execute")
async def execute_plan(
    plan_id: str,
    req: ExecutePlanRequest = ExecutePlanRequest(),
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)),
    db: AsyncSession = Depends(get_db_session),
):
    """触发执行测试计划：建 TestRun(plan_id=this)，派发完整流水线。

    用例来源为已发布修订版，并在运行快照中固化完整执行载荷。
    目标环境解析优先级：环境档案（须已发布）> 显式 target_service_url（废弃标记）>
    项目 source_config 回退。
    """
    from app.modules.runs.orchestrator import RunBlocked, RunOrchestrator

    try:
        result = await RunOrchestrator.create_plan_run(
            plan_id=plan_id,
            db=db,
            environment_profile_id=req.environment_profile_id,
            plan_revision_id=req.plan_revision_id,
            trigger_type="manual",
            trigger_context={"via": "plan-execute", "user": current_user.username},
            user_id=current_user.id,
            legacy_target_url=req.target_service_url,
        )
    except RunBlocked as e:
        status = 404 if "不存在" in e.reason else 400
        raise HTTPException(status, e.reason)

    return {
        "code": 0,
        "data": {
            **result,
        },
        "message": "test plan execution dispatched",
    }
