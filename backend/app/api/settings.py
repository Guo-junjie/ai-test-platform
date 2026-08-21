"""
系统配置 API 路由

提供：
- GET / — 获取系统配置（含质量门禁规则）
- PUT / — 更新系统配置
- GET /quality-gate — 获取质量门禁配置
- PUT /quality-gate — 更新质量门禁配置
- POST /quality-gate/test — 测试质量门禁评估
- GET /notification — 获取通知配置
- PUT /notification — 更新通知配置
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import User
from app.modules.auth.dependencies import require_admin, get_current_user
from app.modules.audit.audit_service import AuditService
from app.modules.quality_gate import QualityGateEvaluator
from app.utils.database import get_db_session
from app.utils.logger import get_logger
from app.utils.redis_client import cache_get, cache_set, cache_delete

logger = get_logger(__name__)

router = APIRouter()

# Redis 缓存 key
SETTINGS_CACHE_KEY = "system:settings"
QUALITY_GATE_CACHE_KEY = "system:quality_gate_config"
NOTIFICATION_CACHE_KEY = "system:notification_config"

# 永久缓存 TTL（1 年）
PERMANENT_TTL = 365 * 24 * 3600


# ==================== 请求模型 ====================


class QualityGateConfigRequest(BaseModel):
    """质量门禁配置请求"""
    enabled: bool = True
    rules: dict[str, Any] = {}
    notify_on_fail: bool = True
    notify_channels: list[str] = []
    block_deployment: bool = True


class NotificationConfigRequest(BaseModel):
    """通知配置请求"""
    webhook_url: str = ""
    dingtalk_webhook: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: list[str] = []


class TestGateRequest(BaseModel):
    """测试质量门禁请求"""
    quality_score: int
    defects: dict[str, Any] = {}
    test_summary: dict[str, Any] = {}


# ==================== 系统配置 ====================


@router.get("")
async def get_system_settings(
    current_user: User = Depends(require_admin),
):
    """获取系统基础配置。"""
    # 从 Redis 读取自定义配置
    custom = await cache_get(SETTINGS_CACHE_KEY) or {}

    return {
        "code": 0,
        "data": {
            "app_env": settings.APP_ENV,
            "app_debug": settings.APP_DEBUG,
            "workspace_dir": settings.WORKSPACE_DIR,
            "report_dir": settings.REPORT_DIR,
            "minio_endpoint": settings.MINIO_ENDPOINT,
            "minio_bucket": settings.MINIO_BUCKET,
            "redis_host": settings.REDIS_HOST,
            "redis_port": settings.REDIS_PORT,
            "postgres_host": settings.POSTGRES_HOST,
            "postgres_db": settings.POSTGRES_DB,
            "custom": custom,
        },
        "message": "success",
    }


@router.put("")
async def update_system_settings(
    data: dict[str, Any],
    request: Request,
    current_user: User = Depends(require_admin),
):
    """更新系统自定义配置。"""
    # 只允许更新 custom 字段中的配置
    await cache_set(SETTINGS_CACHE_KEY, data, ttl=PERMANENT_TTL)

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_settings",
        resource_type="system",
        details={"keys": list(data.keys())},
        ip_address=ip,
    )

    return {
        "code": 0,
        "data": data,
        "message": "配置更新成功",
    }


# ==================== 质量门禁配置 ====================


@router.get("/quality-gate")
async def get_quality_gate_config(
    current_user: User = Depends(get_current_user),
):
    """获取质量门禁配置。"""
    # 从 Redis 读取
    config = await cache_get(QUALITY_GATE_CACHE_KEY)
    if config is None:
        config = QualityGateEvaluator.get_default_config()

    return {
        "code": 0,
        "data": config,
        "message": "success",
    }


@router.put("/quality-gate")
async def update_quality_gate_config(
    req: QualityGateConfigRequest,
    request: Request,
    current_user: User = Depends(require_admin),
):
    """更新质量门禁配置。"""
    config_dict = req.model_dump()

    # 验证配置
    try:
        validated = QualityGateEvaluator.validate_config(config_dict)
    except ValueError as e:
        raise HTTPException(400, f"配置验证失败: {e}")

    # 保存到 Redis
    await cache_set(QUALITY_GATE_CACHE_KEY, validated, ttl=PERMANENT_TTL)

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_quality_gate",
        resource_type="system",
        details={"enabled": validated.get("enabled"), "rules": validated.get("rules")},
        ip_address=ip,
    )

    logger.info(f"Quality gate config updated by {current_user.username}")

    return {
        "code": 0,
        "data": validated,
        "message": "质量门禁配置更新成功",
    }


@router.post("/quality-gate/test")
async def test_quality_gate(
    req: TestGateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    测试质量门禁评估。

    使用当前保存的门禁配置，对给定的测试结果进行评估，
    返回是否通过及违规项列表。
    """
    config = await cache_get(QUALITY_GATE_CACHE_KEY)
    if config is None:
        config = QualityGateEvaluator.get_default_config()

    evaluator = QualityGateEvaluator(config)
    result = evaluator.evaluate(
        quality_score=req.quality_score,
        defects=req.defects,
        test_summary=req.test_summary,
    )

    return {
        "code": 0,
        "data": result,
        "message": "success",
    }


# ==================== 通知配置 ====================


@router.get("/notification")
async def get_notification_config(
    current_user: User = Depends(require_admin),
):
    """获取通知配置。"""
    config = await cache_get(NOTIFICATION_CACHE_KEY) or {
        "webhook_url": "",
        "dingtalk_webhook": "",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "email_from": "",
        "email_to": [],
    }

    # 脱敏密码
    if config.get("smtp_password"):
        config["smtp_password"] = "****"

    return {
        "code": 0,
        "data": config,
        "message": "success",
    }


@router.put("/notification")
async def update_notification_config(
    req: NotificationConfigRequest,
    request: Request,
    current_user: User = Depends(require_admin),
):
    """更新通知配置。"""
    config_dict = req.model_dump()

    # 如果密码为 ****，保留原密码
    if config_dict.get("smtp_password") == "****":
        old_config = await cache_get(NOTIFICATION_CACHE_KEY) or {}
        config_dict["smtp_password"] = old_config.get("smtp_password", "")

    await cache_set(NOTIFICATION_CACHE_KEY, config_dict, ttl=PERMANENT_TTL)

    # 记录审计日志
    ip = request.client.host if request.client else None
    await AuditService.log_action(
        user_id=str(current_user.id),
        action="update_notification_config",
        resource_type="system",
        details={"channels": [k for k, v in config_dict.items() if v]},
        ip_address=ip,
    )

    logger.info(f"Notification config updated by {current_user.username}")

    return {
        "code": 0,
        "data": {k: v for k, v in config_dict.items() if k != "smtp_password"},
        "message": "通知配置更新成功",
    }
