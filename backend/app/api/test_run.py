"""
测试任务 API 路由

提供测试任务的完整生命周期管理：
- POST / — 创建测试任务（代码拉取 → 解析 → 用例生成 → 执行调度）
- GET / — 列出所有测试任务
- GET /{test_run_id} — 获取任务详情
- GET /{test_run_id}/progress — 获取任务进度（从 Redis 读取）
- POST /{test_run_id}/cancel — 取消测试任务
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    Project,
    RunEvent,
    RunSnapshot,
    TestRun,
    TestStatus,
    User,
    SourceType as ModelSourceType,
)
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session
from app.utils.logger import get_logger
from app.utils.redis_client import get_task_progress, get_task_status

logger = get_logger(__name__)

router = APIRouter()


# ==================== 请求模型 ====================


class CreateTestRunRequest(BaseModel):
    """创建测试任务请求（P0 模式分支）

    mode 决定走哪条链路：
    - plan:  plan_id 必填；跳过 fetch/analyze/AI 生成，直接执行测试计划内用例
    - auto:  source_type 决定 fetch 方式（github/svn/upload）；AI 生成用例后执行
    - upload: 历史上传压缩包模式（auto 模式的特例，保留向后兼容）
    """
    mode: str = "auto"            # plan / auto / upload
    # plan 模式必填
    plan_id: str | None = None
    # R1：代码版本引用 —— 代码是项目的属性，任务可直接引用项目已有版本，
    # pipeline 跳过 fetch 直接使用版本的 local_path
    code_version_id: str | None = None
    # auto 模式字段
    source_type: str = "github"  # github / svn / upload
    repo_url: str | None = None
    branch: str = "main"
    commit_sha: str | None = None
    svn_url: str | None = None
    svn_username: str | None = None
    svn_password: str | None = None
    upload_file_path: str | None = None
    github_token: str | None = None
    project_id: str | None = None
    # 真实被测环境 URL（例如 http://192.168.1.100:8080），留空则尝试继承项目配置或本地启动
    target_service_url: str | None = None
    # 已废弃：任务归属方一律取自 JWT 中的当前登录用户（current_user.id），
    # 保留字段仅为兼容旧前端传参，后端不再将其用作外键。
    owner_id: str | None = None


# ==================== API 路由 ====================


@router.get("")
async def list_test_runs(
    project_id: str | None = Query(None, description="按项目ID过滤"),
    status: str | None = Query(None, description="按状态过滤（pulling/executing/completed/failed...）"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """列出测试任务（支持项目/状态过滤）。"""
    # outerjoin Project 让项目名为空时也能保留 run（项目被删/未关联兜底）
    stmt = (
        select(TestRun, Project)
        .outerjoin(Project, Project.id == TestRun.project_id)
        .order_by(TestRun.created_at.desc())
        .limit(limit)
    )
    if project_id:
        try:
            stmt = stmt.where(TestRun.project_id == uuid.UUID(project_id))
        except ValueError:
            raise HTTPException(400, f"Invalid project_id: {project_id}")
    if status:
        try:
            stmt = stmt.where(TestRun.status == TestStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    result = await db.execute(stmt)
    rows = result.fetchall()

    run_list = []
    stuck_run_ids = []
    for run, project in rows:
        st_val = run.status.value if run.status else "pending"
        step_val = run.current_step or "pending"
        prog_val = run.progress or 0
        if prog_val >= 100 or ("完成" in step_val):
            if st_val in ("pulling", "pending", "executing", "analyzing", "generating"):
                st_val = "completed"
                stuck_run_ids.append(run.id)

        run_list.append({
            "id": str(run.id),
            "project_id": str(run.project_id) if run.project_id else None,
            "project_name": project.name if project else "—",
            "status": st_val,
            "progress": prog_val,
            "source_type": run.source_type.value if run.source_type else None,
            "source_ref": run.source_ref,
            "branch": run.branch,
            "commit_sha": run.commit_sha,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "plan_id": str(run.plan_id) if run.plan_id else None,
            "current_step": step_val,
            "target_service_url": getattr(run, "target_service_url", None),
        })

    # 异步自愈落库脏数据（避免下次再判断）
    if stuck_run_ids:
        try:
            from sqlalchemy import update as sa_update
            from datetime import datetime as _dt
            await db.execute(
                sa_update(TestRun)
                .where(TestRun.id.in_(stuck_run_ids))
                .values(status=TestStatus.COMPLETED, completed_at=func.coalesce(TestRun.completed_at, _dt.utcnow()))
            )
            await db.commit()
        except Exception as _heal_err:
            logger.warning(f"Self-heal stuck test runs DB commit failed: {_heal_err}")

    return {
        "code": 0,
        "data": {
            "list": run_list,
            "total": len(rows),
        },
        "message": "success",
    }


@router.post("")
async def create_test_run(
    req: CreateTestRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    创建测试任务 — 触发完整测试流程。

    流程：
    1. 创建 TestRun 记录
    2. 调用 SourceAdapterFactory.fetch_code() 拉取代码
    3. 调用 StackDetector + APIExtractor + AICodeAnalyzer 做代码解析
    4. 调用 TestCaseGenerator.generate_all() 生成用例
    5. 触发 TestExecutionEngine.execute_all() 异步执行
    6. 返回 test_run_id
    """
    logger.info(
        f"Creating test run: source_type={req.source_type}, "
        f"repo_url={req.repo_url}, user={current_user.username}"
    )

    # 1. 解析 source_type
    try:
        source_type = ModelSourceType(req.source_type)
    except ValueError:
        raise HTTPException(400, f"Invalid source_type: {req.source_type}")

    # 2. 查找或创建 Project
    project_id = uuid.uuid4()
    if req.project_id:
        try:
            project_id = uuid.UUID(req.project_id)
        except ValueError:
            raise HTTPException(400, f"Invalid project_id: {req.project_id}")

        # 校验项目存在，避免写入 TestRun 时触发外键违反
        existing_project = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        if existing_project.scalar_one_or_none() is None:
            raise HTTPException(404, f"Project not found: {req.project_id}")
    else:
        # 创建临时 Project
        project = Project(
            id=project_id,
            name=f"Test Run {datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            description="Auto-created project for test run",
            owner_id=current_user.id,
            source_type=source_type,
            source_config={},
            quality_gate_config={},
            is_active=True,
        )
        db.add(project)
        await db.flush()

    # 3. 创建 TestRun 记录
    target_url = (req.target_service_url or "").strip() or None
    if not target_url and req.project_id:
        proj_row = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if proj_row and proj_row.source_config:
            target_url = proj_row.source_config.get("target_service_url")

    test_run = TestRun(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=current_user.id,
        source_type=source_type,
        source_ref=req.repo_url or req.svn_url or req.upload_file_path or "",
        branch=req.branch,
        commit_sha=req.commit_sha,
        status=TestStatus.PULLING,
        progress=0,
        target_service_url=target_url,
        started_at=datetime.utcnow(),
    )
    db.add(test_run)
    await db.flush()

    test_run_id = str(test_run.id)
    logger.info(f"TestRun created: {test_run_id}, target_service_url={target_url}")

    # 4. 派发到 Celery worker 执行完整流程（API 进程立即返回，不阻塞事件循环）
    from app.modules.pipeline import run_test_pipeline

    req_payload = req.model_dump()
    req_payload["target_service_url"] = target_url
    async_result = run_test_pipeline.delay(test_run_id, req_payload)

    # 记录根任务 ID（取消时 revoke 用）；7 天过期与任务状态键一致
    from app.utils.redis_client import get_async_redis

    try:
        redis = await get_async_redis()
        await redis.set(f"task:celery:{test_run_id}", async_result.id, ex=7 * 24 * 3600)
    except Exception as exc:  # noqa: BLE001 - Redis 异常不影响创建
        logger.warning(f"Failed to store celery task id: {exc}")

    return {
        "code": 0,
        "data": {
            "test_run_id": test_run_id,
            "status": "pulling",
            "message": "Test run created, pipeline started",
        },
        "message": "Test run created successfully",
    }


@router.get("/{test_run_id}")
async def get_test_run(
    test_run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取测试任务详情。"""
    try:
        run_id = uuid.UUID(test_run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")

    result = await db.execute(select(TestRun).where(TestRun.id == run_id))
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(404, f"Test run not found: {test_run_id}")

    status_val = run.status.value if run.status else "pending"
    progress_val = run.progress or 0
    current_step_val = run.current_step or ""
    try:
        from app.modules.execution.engine import get_task_progress, get_task_status
        live_status = await get_task_status(test_run_id)
        live_prog = await get_task_progress(test_run_id)
        if live_status and live_status.get("status"):
            status_val = live_status["status"]
        if live_prog:
            if live_prog.get("progress") is not None:
                progress_val = live_prog["progress"]
            if live_prog.get("step"):
                current_step_val = live_prog["step"]
    except Exception:
        pass

    return {
        "code": 0,
        "data": {
            "id": str(run.id),
            "project_id": str(run.project_id),
            "status": status_val,
            "progress": progress_val,
            "current_step": current_step_val,
            "source_type": run.source_type.value if run.source_type else None,
            "source_ref": run.source_ref,
            "branch": run.branch,
            "commit_sha": run.commit_sha,
            "commit_message": run.commit_message,
            "error_message": run.error_message,
            "analysis_result": run.analysis_result,
            "snapshot_id": run.snapshot_id,
            "target_service_url": getattr(run, "target_service_url", None),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            # M3：触发统一化与快照引用
            "trigger_type": run.trigger_type or "manual",
            "trigger_context": run.trigger_context or {},
            "environment_profile_id": str(run.environment_profile_id) if run.environment_profile_id else None,
            "environment_revision_id": str(run.environment_revision_id) if run.environment_revision_id else None,
            "run_snapshot_id": str(run.run_snapshot_id) if run.run_snapshot_id else None,
        },
        "message": "success",
    }


@router.get("/{test_run_id}/events")
async def get_run_events(
    test_run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """运行事件时间线（M3）—— 按序返回状态迁移与关键节点事件。"""
    try:
        rid = uuid.UUID(test_run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")
    events = (
        await db.execute(
            select(RunEvent)
            .where(RunEvent.test_run_id == rid)
            .order_by(RunEvent.sequence.asc(), RunEvent.created_at.asc())
        )
    ).scalars().all()
    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "sequence": e.sequence,
                    "event_type": e.event_type,
                    "payload": e.payload or {},
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
            "total": len(events),
        },
        "message": "success",
    }


@router.get("/{test_run_id}/snapshot")
async def get_run_snapshot(
    test_run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """运行快照（M3）—— 执行时固化的计划/环境/用例集合引用。"""
    try:
        rid = uuid.UUID(test_run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")
    snap = (
        await db.execute(select(RunSnapshot).where(RunSnapshot.test_run_id == rid))
    ).scalar_one_or_none()
    if snap is None:
        return {"code": 0, "data": None, "message": "no snapshot (历史运行，证据可能不完整)"}
    return {
        "code": 0,
        "data": {
            "id": str(snap.id),
            "engine_version": snap.engine_version,
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "snapshot": snap.snapshot_json or {},
        },
        "message": "success",
    }


@router.get("/{test_run_id}/progress")
async def get_progress(test_run_id: str):
    """
    获取任务进度（从 Redis 读取）。

    返回实时进度百分比和当前步骤描述。
    """
    progress_data = await get_task_progress(test_run_id)
    status_data = await get_task_status(test_run_id)

    if progress_data is None and status_data is None:
        return {
            "code": 0,
            "data": {
                "test_run_id": test_run_id,
                "progress": 0,
                "status": "pending",
                "step": "",
            },
            "message": "No progress data found",
        }

    return {
        "code": 0,
        "data": {
            "test_run_id": test_run_id,
            "progress": progress_data.get("progress", 0) if progress_data else 0,
            "step": progress_data.get("step", "") if progress_data else "",
            "status": status_data.get("status", "pending") if status_data else "pending",
            "extra": status_data.get("extra", {}) if status_data else {},
        },
        "message": "success",
    }


@router.post("/{test_run_id}/cancel")
async def cancel_test_run(
    test_run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """取消测试任务：DB 状态 + Redis 取消标志 + revoke 未开始的根任务。

    worker 在流水线各阶段检查点轮询取消标志，执行中的任务会在下一阶段边界中止；
    仅改 DB 状态不 interrupt 执行是历史 bug（任务跑完会把状态覆盖回 COMPLETED）。
    """
    try:
        run_id = uuid.UUID(test_run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")

    result = await db.execute(select(TestRun).where(TestRun.id == run_id))
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(404, f"Test run not found: {test_run_id}")

    if run.status in (TestStatus.COMPLETED, TestStatus.FAILED, TestStatus.CANCELLED):
        raise HTTPException(400, f"Cannot cancel test run in status: {run.status.value}")

    # 1) DB 标记（幂等兜底：即使 worker 漏检，completed 覆盖前也以取消时间为准）
    run.status = TestStatus.CANCELLED
    run.completed_at = datetime.utcnow()
    run.error_message = "Cancelled by user"

    # 2) Redis 取消标志（worker 检查点轮询）+ revoke 根任务（未开始时直接终止）
    from app.celery_app import celery_app as celery
    from app.utils.redis_client import get_async_redis

    redis = await get_async_redis()
    try:
        await redis.set(f"task:cancel:{test_run_id}", "1", ex=7 * 24 * 3600)
        root_task_id = await redis.get(f"task:celery:{test_run_id}")
        if root_task_id:
            root_task_id = root_task_id.decode() if isinstance(root_task_id, bytes) else root_task_id
            celery.control.revoke(root_task_id, terminate=True, signal="SIGTERM")
            logger.info(
                f"Test run cancelled: {test_run_id} (root celery task {root_task_id} revoked)"
            )
        else:
            logger.info(f"Test run cancelled: {test_run_id} (no root task id recorded)")
    except Exception as exc:  # noqa: BLE001 - Redis/MQ 异常时 DB 状态已改，仅告警
        logger.warning(f"Cancel flag/revoke failed (DB status already set): {exc}")

    return {
        "code": 0,
        "data": {"test_run_id": test_run_id, "status": "cancelled"},
        "message": "Test run cancelled",
    }


# ==================== P0：执行摘要（解决测试依据不可见问题）====================


@router.get("/{run_id}/exec-summary")
async def get_exec_summary(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """执行摘要：来源描述/用例数/通过/失败/缺陷/计划上下文/报告链接。

    让用户一打开任务详情就知道"它跑的是什么、跑成什么、产物在哪"，
    解决"测试依据不可见"的体验问题。
    """
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    from sqlalchemy import func as _f
    from app.models.database import (
        Defect, TestCase, TestResult, TestRun, TestPlan, TestPlanExecution, TestReport,
    )

    run = (await db.execute(select(TestRun).where(TestRun.id == rid))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Test run not found")

    cases_total = (await db.execute(
        select(_f.count()).select_from(TestCase).where(TestCase.test_run_id == rid)
    )).scalar() or 0
    results_total = (await db.execute(
        select(_f.count()).select_from(TestResult).where(TestResult.test_run_id == rid)
    )).scalar() or 0
    passed = (await db.execute(
        select(_f.count()).select_from(TestResult).where(
            TestResult.test_run_id == rid, TestResult.is_passed.is_(True)
        )
    )).scalar() or 0
    defects = (await db.execute(
        select(_f.count()).select_from(Defect).where(Defect.test_run_id == rid)
    )).scalar() or 0
    report = (await db.execute(
        select(TestReport).where(TestReport.test_run_id == rid)
    )).scalar_one_or_none()

    plan_name = None
    plan_execution = None
    if run.plan_id:
        p = (await db.execute(select(TestPlan).where(TestPlan.id == run.plan_id))).scalar_one_or_none()
        plan_name = p.name if p else None
        pe = (await db.execute(
            select(TestPlanExecution).where(TestPlanExecution.test_run_id == rid)
        )).scalar_one_or_none()
        if pe:
            plan_execution = {
                "id": str(pe.id),
                "total": pe.total, "passed": pe.passed, "failed": pe.failed,
                "duration_ms": pe.duration_ms,
                "started_at": pe.started_at.isoformat() if pe.started_at else None,
                "finished_at": pe.finished_at.isoformat() if pe.finished_at else None,
            }

    # 来源描述（人类可读）
    if run.plan_id and plan_name:
        source_desc = f"测试计划《{plan_name}》+ {cases_total} 用例"
    elif run.source_type and run.source_type.value == "upload" and (run.source_ref or "").startswith("plan:"):
        source_desc = f"测试计划 + {cases_total} 用例"
    elif run.source_type and run.source_type.value == "upload":
        source_desc = f"上传代码 + 自动生成 {results_total} 用例执行"
    elif run.branch:
        sha = (run.commit_sha or "")[:8]
        source_desc = f"{run.source_type.value}/{run.branch}" + (f" @ {sha}" if sha else "")
    else:
        source_desc = run.source_ref or "-"

    return {
        "code": 0,
        "data": {
            "run_id": str(run.id),
            "project_id": str(run.project_id) if run.project_id else None,
            "mode": "plan" if run.plan_id else "auto",
            "status": run.status.value if run.status else "pending",
            "progress": run.progress or 0,
            "current_step": run.current_step or "pending",
            "source_description": source_desc,
            "plan_id": str(run.plan_id) if run.plan_id else None,
            "plan_name": plan_name,
            "cases_total": cases_total,
            "results_total": results_total,
            "results_passed": passed,
            "results_failed": (results_total - passed),
            "defect_count": defects,
            "has_report": report is not None,
            "report_id": str(report.id) if report else None,
            "report_quality_score": report.quality_score if report else None,
            "plan_execution": plan_execution,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "message": "success",
    }
