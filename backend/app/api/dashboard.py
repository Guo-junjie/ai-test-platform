"""
仪表盘与趋势看板 API 路由

提供：
- GET /statistics — 总览统计数据（任务总数、通过率、缺陷数、平均时长）
- GET /quality-trend — 质量评分趋势
- GET /test-trend — 测试任务数量与通过率趋势
- GET /defect-trend — 缺陷数量趋势
- GET /recent-runs — 最近测试任务列表（含质量评分）
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    TestRun,
    TestReport,
    Project,
    TestStatus,
    Defect,
    DefectSeverity,
    EnvironmentProfile,
    TestCaseAsset,
    User,
)
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/todos")
async def get_dashboard_todos(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """返回由真实业务状态聚合的个人待办。"""
    items: list[dict[str, Any]] = []
    project_count = (await db.execute(select(func.count(Project.id)))).scalar_one()
    if project_count == 0:
        items.append({"id": "create-project", "title": "创建第一个测试项目", "description": "建立项目后才能导入文档、设计用例和执行测试", "path": "/projects", "priority": "high"})
    pending_reviews = (await db.execute(select(func.count(TestCaseAsset.id)).where(TestCaseAsset.review_state == "pending"))).scalar_one()
    if pending_reviews:
        items.append({"id": "case-reviews", "title": f"评审 {pending_reviews} 条待审用例", "description": "用例批准后才能加入自动化测试计划", "path": "/case-library?tab=review", "priority": "high"})
    unconfigured = (await db.execute(
        select(Project).where(~Project.id.in_(select(EnvironmentProfile.project_id).where(EnvironmentProfile.status == "published"))).limit(5)
    )).scalars().all()
    for project in unconfigured:
        items.append({"id": f"environment-{project.id}", "title": f"为「{project.name}」发布测试环境", "description": "执行计划与定时任务需要已发布环境", "path": f"/projects/{project.id}/environments", "project_id": str(project.id), "priority": "medium"})
    failed_runs = (await db.execute(select(func.count(TestRun.id)).where(TestRun.status == TestStatus.FAILED))).scalar_one()
    if failed_runs:
        items.append({"id": "failed-runs", "title": f"查看 {failed_runs} 次失败运行", "description": "定位失败断言并决定是否登记缺陷", "path": "/runs?status=failed", "priority": "medium"})
    return {"code": 0, "data": {"items": items[:10]}, "message": "success"}


@router.get("/projects-summary")
async def get_dashboard_projects(
    limit: int = Query(6, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    projects = (await db.execute(select(Project).order_by(desc(Project.updated_at)).limit(limit))).scalars().all()
    items = []
    for project in projects:
        case_count = (await db.execute(select(func.count(TestCaseAsset.id)).where(TestCaseAsset.project_id == project.id))).scalar_one()
        latest = (await db.execute(select(TestRun, TestReport).outerjoin(TestReport, TestReport.test_run_id == TestRun.id).where(TestRun.project_id == project.id).order_by(desc(TestRun.created_at)).limit(1))).first()
        env_ready = (await db.execute(select(func.count(EnvironmentProfile.id)).where(EnvironmentProfile.project_id == project.id, EnvironmentProfile.status == "published"))).scalar_one() > 0
        items.append({"id": str(project.id), "name": project.name, "case_count": case_count, "ready": env_ready,
                      "recent_run_at": latest[0].created_at.isoformat() if latest and latest[0].created_at else None,
                      "recent_run_status": latest[0].status.value if latest and latest[0].status else None,
                      "quality_score": latest[1].quality_score if latest and latest[1] else None})
    return {"code": 0, "data": {"items": items}, "message": "success"}


def _parse_days(time_range: str) -> int:
    """将时间范围字符串转换为天数。"""
    mapping = {"7d": 7, "30d": 30, "90d": 90}
    return mapping.get(time_range, 30)


@router.get("/statistics")
async def get_statistics(
    days: int = Query(30, ge=1, le=365, description="统计时间范围（天）"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取仪表盘总览统计数据。

    返回：
    - 测试任务总数
    - 通过率
    - 发现缺陷数
    - 平均执行时长
    - 按状态分布
    """
    since = datetime.utcnow() - timedelta(days=days)

    # 测试任务总数
    total_result = await db.execute(
        select(func.count(TestRun.id)).where(TestRun.created_at >= since)
    )
    total_runs = total_result.scalar() or 0

    # 已完成任务数
    completed_result = await db.execute(
        select(func.count(TestRun.id)).where(
            and_(
                TestRun.created_at >= since,
                TestRun.status.in_([TestStatus.COMPLETED, TestStatus.FAILED]),
            )
        )
    )
    completed_runs = completed_result.scalar() or 0

    # 通过的任务数（有报告且 gate_passed=True）
    passed_result = await db.execute(
        select(func.count(TestReport.id)).where(
            and_(
                TestReport.created_at >= since,
                TestReport.gate_passed == True,  # noqa: E712
            )
        )
    )
    passed_runs = passed_result.scalar() or 0

    pass_rate = round(passed_runs / completed_runs * 100, 1) if completed_runs > 0 else 0

    # 缺陷总数（统计周期内发现的所有缺陷，涵盖自动化测试与手动登记）
    defect_result = await db.execute(
        select(func.count(Defect.id)).where(Defect.created_at >= since, Defect.deleted_at.is_(None))
    )
    total_defects = defect_result.scalar() or 0

    # 平均执行时长（已完成任务）
    duration_result = await db.execute(
        select(
            func.avg(
                func.extract("epoch", TestRun.completed_at - TestRun.started_at)
            )
        ).select_from(TestRun).where(
            and_(
                TestRun.created_at >= since,
                TestRun.started_at.isnot(None),
                TestRun.completed_at.isnot(None),
            )
        )
    )
    avg_duration_seconds = duration_result.scalar() or 0
    avg_duration_min = round(avg_duration_seconds / 60, 1) if avg_duration_seconds else 0

    # 按状态分布
    status_result = await db.execute(
        select(TestRun.status, func.count(TestRun.id))
        .where(TestRun.created_at >= since)
        .group_by(TestRun.status)
    )
    status_distribution = {
        (row[0].value if row[0] else "unknown"): row[1]
        for row in status_result.fetchall()
    }

    # 质量评分统计
    score_result = await db.execute(
        select(
            func.avg(TestReport.quality_score),
            func.max(TestReport.quality_score),
            func.min(TestReport.quality_score),
        ).where(TestReport.created_at >= since)
    )
    score_row = score_result.fetchone()
    avg_score = round(score_row[0], 1) if score_row[0] else 0
    max_score = score_row[1] or 0
    min_score = score_row[2] or 0

    return {
        "code": 0,
        "data": {
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "passed_runs": passed_runs,
            "pass_rate": pass_rate,
            "total_defects": total_defects,
            "avg_duration_min": avg_duration_min,
            "avg_quality_score": avg_score,
            "max_quality_score": max_score,
            "min_quality_score": min_score,
            "status_distribution": status_distribution,
            "days": days,
        },
        "message": "success",
    }


@router.get("/quality-trend")
async def get_quality_trend(
    time_range: str = Query("30d", description="时间范围: 7d/30d/90d"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取质量评分趋势数据。

    返回每天的：平均质量评分、最高评分、最低评分。
    """
    days = _parse_days(time_range)
    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date_trunc("day", TestReport.created_at).label("date"),
            func.avg(TestReport.quality_score).label("avg_score"),
            func.max(TestReport.quality_score).label("max_score"),
            func.min(TestReport.quality_score).label("min_score"),
            func.count(TestReport.id).label("count"),
        )
        .where(TestReport.created_at >= since)
        .group_by("date")
        .order_by("date")
    )

    rows = result.fetchall()

    return {
        "code": 0,
        "data": {
            "dates": [row[0].strftime("%Y-%m-%d") if row[0] else "" for row in rows],
            "avg_scores": [round(row[1], 1) if row[1] else 0 for row in rows],
            "max_scores": [row[2] or 0 for row in rows],
            "min_scores": [row[3] or 0 for row in rows],
            "counts": [row[4] for row in rows],
        },
        "message": "success",
    }


@router.get("/test-trend")
async def get_test_trend(
    time_range: str = Query("30d", description="时间范围: 7d/30d/90d"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取测试任务趋势数据。

    返回每天的：任务总数、完成数、失败数。
    """
    days = _parse_days(time_range)
    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date_trunc("day", TestRun.created_at).label("date"),
            func.count(TestRun.id).label("total"),
            func.count(
                func.nullif(TestRun.status != TestStatus.COMPLETED, False)  # type: ignore
            ).label("completed"),
            func.count(
                func.nullif(TestRun.status != TestStatus.FAILED, False)  # type: ignore
            ).label("failed"),
        )
        .where(TestRun.created_at >= since)
        .group_by("date")
        .order_by("date")
    )

    rows = result.fetchall()

    return {
        "code": 0,
        "data": {
            "dates": [row[0].strftime("%Y-%m-%d") if row[0] else "" for row in rows],
            "totals": [row[1] for row in rows],
            "completed": [row[2] for row in rows],
            "failed": [row[3] for row in rows],
        },
        "message": "success",
    }


@router.get("/defect-trend")
async def get_defect_trend(
    time_range: str = Query("30d", description="时间范围: 7d/30d/90d"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取缺陷数量趋势数据。

    返回每天的：缺陷总数、P0数、P1数、P2数、P3数。
    """
    days = _parse_days(time_range)
    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date_trunc("day", Defect.created_at).label("date"),
            func.count(Defect.id).label("total"),
            func.count(
                func.nullif(Defect.severity != DefectSeverity.P0, True)  # type: ignore
            ).label("p0"),
            func.count(
                func.nullif(Defect.severity != DefectSeverity.P1, True)  # type: ignore
            ).label("p1"),
            func.count(
                func.nullif(Defect.severity != DefectSeverity.P2, True)  # type: ignore
            ).label("p2"),
            func.count(
                func.nullif(Defect.severity != DefectSeverity.P3, True)  # type: ignore
            ).label("p3"),
        )
        .select_from(Defect)
        .where(Defect.created_at >= since, Defect.deleted_at.is_(None))
        .group_by("date")
        .order_by("date")
    )

    rows = result.fetchall()

    return {
        "code": 0,
        "data": {
            "dates": [row[0].strftime("%Y-%m-%d") if row[0] else "" for row in rows],
            "totals": [row[1] for row in rows],
            "p0": [row[2] for row in rows],
            "p1": [row[3] for row in rows],
            "p2": [row[4] for row in rows],
            "p3": [row[5] for row in rows],
        },
        "message": "success",
    }


@router.get("/recent-runs")
async def get_recent_runs(
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=50),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取最近测试任务列表（含质量评分和门禁结果）。
    """
    # outerjoin Project 让项目名为空时也能保留 run（project_id 缺失/项目被删的兜底）
    size = page_size or limit
    total = (await db.execute(select(func.count(TestRun.id)))).scalar_one()
    result = await db.execute(
        select(TestRun, Project, TestReport)
        .outerjoin(Project, Project.id == TestRun.project_id)
        .outerjoin(TestReport, TestReport.test_run_id == TestRun.id)
        .order_by(desc(TestRun.created_at))
        .offset((page - 1) * size).limit(size)
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
                    "quality_score": report.quality_score if report else None,
                    "gate_passed": report.gate_passed if report else None,
                    "started_at": (run.started_at or run.created_at).isoformat() if (run.started_at or run.created_at) else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                }
                for run, project, report in rows
            ], "total": total, "page": page, "page_size": size,
        },
        "message": "success",
    }
