"""
质量门禁 API 路由

提供：
- GET /config/{project_id} — 获取项目门禁配置
- PUT /config/{project_id} — 更新门禁配置（admin/tester权限）
- POST /evaluate/{run_id} — 评估指定测试运行的门禁状态
- GET /history/{project_id} — 门禁历史记录
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Project, TestRun, TestReport, Defect, User
from app.modules.auth.dependencies import get_current_user, require_tester
from app.modules.quality_gate import QualityGateEvaluator
from app.modules.audit.audit_service import AuditService
from app.utils.database import get_db_session
from app.utils.logger import get_logger
from app.utils.redis_client import cache_get, cache_set

logger = get_logger(__name__)

router = APIRouter()

# Redis 缓存 key 前缀
GATE_CONFIG_CACHE_PREFIX = "project:quality_gate:"


# ==================== 请求模型 ====================


class QualityGateConfigRequest(BaseModel):
    """质量门禁配置请求"""
    enabled: bool = True
    rules: dict[str, Any] = {}
    notify_on_fail: bool = True
    notify_channels: list[str] = []
    block_deployment: bool = True


# ==================== API 路由 ====================


@router.get("/config/{project_id}")
async def get_quality_gate_config(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取项目质量门禁配置。

    优先从 Redis 缓存读取，其次从数据库 Project.quality_gate_config 读取，
    最后返回默认配置。
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    # 1. 尝试从 Redis 读取
    cache_key = f"{GATE_CONFIG_CACHE_PREFIX}{project_id}"
    cached = await cache_get(cache_key)
    if cached:
        return {"code": 0, "data": cached, "message": "success"}

    # 2. 从数据库读取
    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")

    config = project.quality_gate_config or {}
    if not config:
        config = QualityGateEvaluator.get_default_config()

    # 写入缓存
    await cache_set(cache_key, config, ttl=3600)

    return {"code": 0, "data": config, "message": "success"}


@router.put("/config/{project_id}")
async def update_quality_gate_config(
    project_id: str,
    req: QualityGateConfigRequest,
    request: Request,
    current_user: User = Depends(require_tester),
    db: AsyncSession = Depends(get_db_session),
):
    """更新项目质量门禁配置（需要 admin/tester 权限）。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    result = await db.execute(select(Project).where(Project.id == pid))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(404, f"Project not found: {project_id}")

    # 验证配置
    config_dict = req.model_dump()
    try:
        validated = QualityGateEvaluator.validate_config(config_dict)
    except ValueError as e:
        raise HTTPException(400, f"配置验证失败: {e}")

    # 保存到数据库
    project.quality_gate_config = validated
    await db.commit()

    # 更新缓存
    cache_key = f"{GATE_CONFIG_CACHE_PREFIX}{project_id}"
    await cache_set(cache_key, validated, ttl=3600)

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_quality_gate_config",
        resource_type="project",
        resource_id=project_id,
        details={"enabled": validated.get("enabled"), "rules": validated.get("rules")},
        ip_address=ip,
    )

    logger.info(
        f"Quality gate config updated for project {project_id} by {current_user.username}"
    )

    return {"code": 0, "data": validated, "message": "质量门禁配置更新成功"}


@router.post("/evaluate/{run_id}")
async def evaluate_quality_gate(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    评估指定测试运行的门禁状态。

    从测试报告和缺陷数据中提取指标，使用项目门禁配置进行评估。
    """
    try:
        rid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    # 查询测试运行
    run_result = await db.execute(select(TestRun).where(TestRun.id == rid))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(404, f"Test run not found: {run_id}")

    # 查询测试报告
    report_result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == rid)
    )
    report = report_result.scalar_one_or_none()
    if report is None:
        raise HTTPException(400, "测试报告尚未生成，无法评估门禁")

    # 查询缺陷数据
    defect_result = await db.execute(
        select(Defect).where(Defect.test_run_id == rid)
    )
    defects = defect_result.scalars().all()

    # 构建缺陷摘要
    by_severity: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    by_type: dict[str, int] = {}
    for d in defects:
        sev = d.severity.value if d.severity else "P3"
        by_severity[sev] = by_severity.get(sev, 0) + 1
        dtype = d.defect_type.value if d.defect_type else "unknown"
        by_type[dtype] = by_type.get(dtype, 0) + 1

    defects_summary = {
        "summary": {
            "total": len(defects),
            "by_severity": by_severity,
            "by_type": by_type,
        }
    }

    # 从报告数据中提取测试摘要
    report_data = report.report_data or {}
    test_summary = report_data.get("test_summary", {})
    if not test_summary:
        # 尝试从 report_data 的其他字段构建
        test_summary = {
            "api_summary": report_data.get("api_summary", {"total": 0, "passed": 0}),
            "performance_summary": report_data.get("performance_summary", {"total": 0, "passed": 0}),
            "integration_summary": report_data.get("integration_summary", {"total": 0, "passed": 0}),
        }

    quality_score = report.quality_score or 0

    # 获取项目门禁配置
    cache_key = f"{GATE_CONFIG_CACHE_PREFIX}{run.project_id}"
    config = await cache_get(cache_key)

    if config is None:
        # 从数据库读取
        proj_result = await db.execute(
            select(Project).where(Project.id == run.project_id)
        )
        project = proj_result.scalar_one_or_none()
        config = (
            project.quality_gate_config
            if project and project.quality_gate_config
            else QualityGateEvaluator.get_default_config()
        )

    # 评估
    evaluator = QualityGateEvaluator(config)
    result = evaluator.evaluate(
        quality_score=quality_score,
        defects=defects_summary,
        test_summary=test_summary,
    )

    # 更新报告中的门禁结果
    report.gate_passed = result["passed"]
    report.gate_details = result
    await db.commit()

    # 如果门禁未通过且配置了通知，发送通知
    if not result["passed"] and config.get("notify_on_fail", True):
        try:
            from app.modules.notification.notifier import NotificationManager

            notifier = NotificationManager.from_settings()
            await notifier.send_notification(
                event_type="gate_failed",
                data={
                    "project_name": str(run.project_id),
                    "test_run_id": run_id,
                    "quality_score": quality_score,
                    "violations": "; ".join(
                        v.get("message", "") for v in result.get("violations", [])
                    ),
                },
                channels=config.get("notify_channels"),
            )
        except Exception as e:
            logger.error(f"Failed to send gate failure notification: {e}")

    logger.info(
        f"Quality gate evaluated for run {run_id}: passed={result['passed']}"
    )

    return {"code": 0, "data": result, "message": "评估完成"}


@router.get("/history/{project_id}")
async def get_gate_history(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """获取项目门禁评估历史记录。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    # 查询该项目下所有有报告的测试运行
    offset = (page - 1) * page_size

    # 总数
    count_result = await db.execute(
        select(TestReport)
        .join(TestRun, TestReport.test_run_id == TestRun.id)
        .where(TestRun.project_id == pid)
    )
    total = len(count_result.scalars().all())

    # 分页查询
    result = await db.execute(
        select(TestReport, TestRun)
        .join(TestRun, TestReport.test_run_id == TestRun.id)
        .where(TestRun.project_id == pid)
        .order_by(desc(TestReport.created_at))
        .offset(offset)
        .limit(page_size)
    )

    rows = result.fetchall()

    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "report_id": str(report.id),
                    "test_run_id": str(report.test_run_id),
                    "quality_score": report.quality_score,
                    "gate_passed": report.gate_passed,
                    "gate_details": report.gate_details,
                    "created_at": report.created_at.isoformat()
                    if report.created_at
                    else None,
                    "run_status": run.status.value if run.status else None,
                    "source_ref": run.source_ref,
                }
                for report, run in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }
