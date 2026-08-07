"""
质量趋势 API 路由

提供：
- GET /quality — 质量评分趋势（支持 project_id 过滤、days 参数默认30天）
- GET /pass-rate — 通过率趋势
- GET /defect — 缺陷数量趋势
- GET /summary — 汇总统计（总运行数、平均通过率、平均质量分、总缺陷数）
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, and_, outerjoin
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    TestRun,
    TestReport,
    TestStatus,
    Defect,
    DefectSeverity,
)
from app.modules.auth.dependencies import get_current_user
from app.models.database import User
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _parse_project_id(project_id: str | None) -> uuid.UUID | None:
    """安全解析 project_id。"""
    if not project_id:
        return None
    try:
        return uuid.UUID(project_id)
    except ValueError:
        return None


@router.get("/quality")
async def get_quality_trend(
    project_id: str | None = Query(None, description="按项目过滤"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取质量评分趋势。

    返回每天的：平均质量评分、最高评分、最低评分、报告数量。
    """
    since = datetime.utcnow() - timedelta(days=days)
    pid = _parse_project_id(project_id)

    query = (
        select(
            func.date_trunc("day", TestReport.created_at).label("date"),
            func.avg(TestReport.quality_score).label("avg_score"),
            func.max(TestReport.quality_score).label("max_score"),
            func.min(TestReport.quality_score).label("min_score"),
            func.count(TestReport.id).label("count"),
        )
        .join(TestRun, TestReport.test_run_id == TestRun.id)
        .where(TestReport.created_at >= since)
    )

    if pid is not None:
        query = query.where(TestRun.project_id == pid)

    query = query.group_by("date").order_by("date")

    result = await db.execute(query)
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


@router.get("/pass-rate")
async def get_pass_rate_trend(
    project_id: str | None = Query(None, description="按项目过滤"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取通过率趋势。

    返回每天的：任务总数、完成任务数、门禁通过数、通过率。
    """
    since = datetime.utcnow() - timedelta(days=days)
    pid = _parse_project_id(project_id)

    query = (
        select(
            func.date_trunc("day", TestRun.created_at).label("date"),
            func.count(TestRun.id).label("total"),
            func.count(
                func.nullif(TestRun.status != TestStatus.COMPLETED, False)  # type: ignore
            ).label("completed"),
        )
        .where(TestRun.created_at >= since)
    )

    if pid is not None:
        query = query.where(TestRun.project_id == pid)

    query = query.group_by("date").order_by("date")

    result = await db.execute(query)
    rows = result.fetchall()

    # 查询每天的门禁通过数
    pass_query = (
        select(
            func.date_trunc("day", TestReport.created_at).label("date"),
            func.count(TestReport.id).label("gate_passed_count"),
        )
        .join(TestRun, TestReport.test_run_id == TestRun.id)
        .where(
            and_(
                TestReport.created_at >= since,
                TestReport.gate_passed == True,  # noqa: E712
            )
        )
    )

    if pid is not None:
        pass_query = pass_query.where(TestRun.project_id == pid)

    pass_query = pass_query.group_by("date")
    pass_result = await db.execute(pass_query)
    pass_map = {
        row[0].strftime("%Y-%m-%d") if row[0] else "": row[1]
        for row in pass_result.fetchall()
    }

    dates: list[str] = []
    totals: list[int] = []
    completed: list[int] = []
    gate_passed: list[int] = []
    pass_rates: list[float] = []

    for row in rows:
        date_str = row[0].strftime("%Y-%m-%d") if row[0] else ""
        total = row[1]
        comp = row[2]
        gp = pass_map.get(date_str, 0)
        rate = round(gp / comp * 100, 1) if comp > 0 else 0

        dates.append(date_str)
        totals.append(total)
        completed.append(comp)
        gate_passed.append(gp)
        pass_rates.append(rate)

    return {
        "code": 0,
        "data": {
            "dates": dates,
            "totals": totals,
            "completed": completed,
            "gate_passed": gate_passed,
            "pass_rates": pass_rates,
        },
        "message": "success",
    }


@router.get("/defect")
async def get_defect_trend(
    project_id: str | None = Query(None, description="按项目过滤"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取缺陷数量趋势。

    返回每天的：缺陷总数、P0数、P1数、P2数、P3数。
    """
    since = datetime.utcnow() - timedelta(days=days)
    pid = _parse_project_id(project_id)

    query = (
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
        .join(TestRun, Defect.test_run_id == TestRun.id)
        .where(TestRun.created_at >= since)
    )

    if pid is not None:
        query = query.where(TestRun.project_id == pid)

    query = query.group_by("date").order_by("date")

    result = await db.execute(query)
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


@router.get("/summary")
async def get_summary(
    project_id: str | None = Query(None, description="按项目过滤"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取汇总统计。

    返回：总运行数、完成运行数、门禁通过数、平均通过率、平均质量分、总缺陷数。
    """
    since = datetime.utcnow() - timedelta(days=days)
    pid = _parse_project_id(project_id)

    # 测试运行总数
    run_query = select(
        func.count(TestRun.id).label("total_runs"),
        func.count(
            func.nullif(
                TestRun.status.notin_([TestStatus.COMPLETED, TestStatus.FAILED]),
                True,
            )
        ).label("completed_runs"),
    ).where(TestRun.created_at >= since)

    if pid is not None:
        run_query = run_query.where(TestRun.project_id == pid)

    run_result = await db.execute(run_query)
    run_row = run_result.fetchone()
    total_runs = run_row[0] or 0
    completed_runs = run_row[1] or 0

    # 门禁通过数和平均质量分
    report_query = (
        select(
            func.count(TestReport.id).label("total_reports"),
            func.count(
                func.nullif(TestReport.gate_passed != True, False)  # type: ignore # noqa: E712
            ).label("gate_passed_count"),
            func.avg(TestReport.quality_score).label("avg_score"),
        )
        .join(TestRun, TestReport.test_run_id == TestRun.id)
        .where(TestReport.created_at >= since)
    )

    if pid is not None:
        report_query = report_query.where(TestRun.project_id == pid)

    report_result = await db.execute(report_query)
    report_row = report_result.fetchone()
    gate_passed_count = report_row[1] or 0
    avg_score = round(report_row[2], 1) if report_row[2] else 0

    # 缺陷总数
    defect_query = (
        select(func.count(Defect.id))
        .join(TestRun, Defect.test_run_id == TestRun.id)
        .where(TestRun.created_at >= since)
    )

    if pid is not None:
        defect_query = defect_query.where(TestRun.project_id == pid)

    defect_result = await db.execute(defect_query)
    total_defects = defect_result.scalar() or 0

    pass_rate = (
        round(gate_passed_count / completed_runs * 100, 1)
        if completed_runs > 0
        else 0
    )

    return {
        "code": 0,
        "data": {
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "gate_passed_count": gate_passed_count,
            "pass_rate": pass_rate,
            "avg_quality_score": avg_score,
            "total_defects": total_defects,
            "days": days,
        },
        "message": "success",
    }
