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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Project, TestRun, TestStatus, User, SourceType as ModelSourceType
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session
from app.utils.logger import get_logger
from app.utils.redis_client import get_task_progress, get_task_status

logger = get_logger(__name__)

router = APIRouter()


# ==================== 请求模型 ====================


class CreateTestRunRequest(BaseModel):
    """创建测试任务请求"""

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
    # 已废弃：任务归属方一律取自 JWT 中的当前登录用户（current_user.id），
    # 保留字段仅为兼容旧前端传参，后端不再将其用作外键。
    owner_id: str | None = None


# ==================== API 路由 ====================


@router.get("")
async def list_test_runs(
    db: AsyncSession = Depends(get_db_session),
):
    """列出所有测试任务。"""
    # outerjoin Project 让项目名为空时也能保留 run（项目被删/未关联兜底）
    result = await db.execute(
        select(TestRun, Project)
        .outerjoin(Project, Project.id == TestRun.project_id)
        .order_by(TestRun.created_at.desc())
        .limit(100)
    )
    rows = result.fetchall()

    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "id": str(run.id),
                    "project_id": str(run.project_id) if run.project_id else None,
                    "project_name": project.name if project else "—",
                    "status": run.status.value if run.status else "pending",
                    "progress": run.progress or 0,
                    "source_type": run.source_type.value if run.source_type else None,
                    "source_ref": run.source_ref,
                    "branch": run.branch,
                    "commit_sha": run.commit_sha,
                    "error_message": run.error_message,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                }
                for run, project in rows
            ],
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
        started_at=datetime.utcnow(),
    )
    db.add(test_run)
    await db.flush()

    test_run_id = str(test_run.id)
    logger.info(f"TestRun created: {test_run_id}")

    # 4. 派发到 Celery worker 执行完整流程（API 进程立即返回，不阻塞事件循环）
    from app.modules.pipeline import run_test_pipeline

    async_result = run_test_pipeline.delay(test_run_id, req.model_dump())

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

    return {
        "code": 0,
        "data": {
            "id": str(run.id),
            "project_id": str(run.project_id),
            "status": run.status.value if run.status else "pending",
            "progress": run.progress or 0,
            "source_type": run.source_type.value if run.source_type else None,
            "source_ref": run.source_ref,
            "branch": run.branch,
            "commit_sha": run.commit_sha,
            "commit_message": run.commit_message,
            "error_message": run.error_message,
            "analysis_result": run.analysis_result,
            "snapshot_id": run.snapshot_id,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
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
