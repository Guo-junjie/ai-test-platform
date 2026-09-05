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
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    Project,
    TestCaseAsset,
    TestPlan,
    TestPlanCase,
    TestPlanExecution,
    TestRun,
    TestStatus,
    User,
    UserRole,
)
from app.modules.auth.dependencies import get_current_user, require_role
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


def _plan_to_dict(p: TestPlan, total: int = 0, enabled: int = 0) -> dict[str, Any]:
    return {
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

    return {
        "code": 0,
        "data": {
            "list": [
                _plan_to_dict(r, *stats_map.get(str(r.id), (0, 0))) for r in rows
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

    return {
        "code": 0,
        "data": {
            **_plan_to_dict(plan),
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


@router.post("/{plan_id}/execute")
async def execute_plan(
    plan_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)),
    db: AsyncSession = Depends(get_db_session),
):
    """触发执行测试计划：建 TestRun(plan_id=this)，派发完整流水线。

    用例来源从 test_plan_cases 读取：仅 enabled=True 的 case_asset_id。
    同一测试任务的流水线（pipeline.run_test_pipeline）兼容 plan 模式将在阶段3实现；
    本阶段先做"建 TestRun + 写快照"骨架，阶段3再接完整执行。
    """
    plan = await _require_plan(plan_id, db)
    if plan.status != "active":
        raise HTTPException(400, f"Cannot execute {plan.status} plan")

    # 检查启用用例数（scalars() 已提取 case_asset_id 列本身，直接是 UUID 列表）
    case_ids = (
        await db.execute(
            select(TestPlanCase.case_asset_id).where(
                TestPlanCase.plan_id == plan.id,
                TestPlanCase.enabled.is_(True),
            )
        )
    ).scalars().all()
    if not case_ids:
        raise HTTPException(400, "计划内无启用用例，请先加入用例")

    # 创建 TestRun（plan_id 标记新模式，source_type=upload 兼容老链路）
    run = TestRun(
        id=uuid.uuid4(),
        project_id=plan.project_id,
        user_id=current_user.id,
        source_type="upload",  # 兼容老 source_type 枚举（plan 模式由 plan_id 决定）
        source_ref=f"plan:{plan.id}",
        status=TestStatus.PULLING,
        progress=0,
        plan_id=plan.id,
        current_step="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # 派发流水线（plan 模式由 engine 在阶段3支持）
    from app.celery_app import celery_app as _celery
    from app.utils.redis_client import get_async_redis

    async_result = _celery.send_task(
        "app.modules.pipeline.run_test_pipeline",
        args=[str(run.id), {
            "source_type": "plan",
            "plan_id": str(plan.id),
            "case_asset_ids": [str(c) for c in case_ids],
            "project_id": str(plan.project_id),
        }],
    )
    try:
        redis = await get_async_redis()
        await redis.set(f"task:celery:{run.id}", async_result.id, ex=7 * 24 * 3600)
    except Exception:  # noqa: BLE001
        pass
    return {
        "code": 0,
        "data": {
            "test_run_id": str(run.id),
            "plan_id": str(plan.id),
            "case_count": len(case_ids),
            "status": "dispatched",
        },
        "message": "test plan execution dispatched",
    }
