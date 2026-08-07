"""
AI 自动化测试平台 — FastAPI 应用入口
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.utils.logger import setup_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化日志系统
    setup_logger()
    logger.info(f"Starting AI Test Platform in {settings.APP_ENV} mode...")

    # 初始化数据库连接
    from app.models.database import init_db
    await init_db()
    logger.info("Database initialized")

    # 初始化 MinIO
    from app.utils.storage import init_minio
    init_minio()
    logger.info("MinIO storage initialized")

    # 初始化默认 AI 模型配置
    from app.modules.ai.model_router import init_default_models
    await init_default_models()
    logger.info("AI model configurations initialized")

    # 初始化默认管理员账户
    from app.modules.auth.auth_service import AuthService
    await AuthService.init_default_admin()
    logger.info("Default admin user initialized")

    yield

    # 清理资源
    from app.utils.redis_client import close_redis
    from app.utils.database import dispose_engine
    await close_redis()
    await dispose_engine()
    logger.info("Shutting down AI Test Platform...")


app = FastAPI(
    title="AI 自动化测试平台",
    description="100% 自闭环、无人工干预的 AI 自动化测试平台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.APP_DEBUG else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 注册路由 ============

# 健康检查
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "env": settings.APP_ENV}

# 数据源接入
from app.api.source import router as source_router
app.include_router(source_router, prefix="/api/source", tags=["数据源"])

# 文件上传
from app.api.upload import router as upload_router
app.include_router(upload_router, prefix="/api/upload", tags=["上传"])

# Webhook
from app.api.webhook import router as webhook_router
app.include_router(webhook_router, prefix="/api/webhook", tags=["Webhook"])

# AI 模型配置
from app.api.model_config import router as model_config_router
app.include_router(model_config_router, prefix="/api/models", tags=["AI模型配置"])

# 项目
from app.api.project import router as project_router
app.include_router(project_router, prefix="/api/projects", tags=["项目"])

# 测试任务
from app.api.test_run import router as test_run_router
app.include_router(test_run_router, prefix="/api/test-runs", tags=["测试任务"])

# 报告
from app.api.report import router as report_router
app.include_router(report_router, prefix="/api/reports", tags=["报告"])

# 用户认证
from app.api.auth import router as auth_router
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])

# 系统配置
from app.api.settings import router as settings_router
app.include_router(settings_router, prefix="/api/settings", tags=["系统配置"])

# 审计日志
from app.api.audit import router as audit_router
app.include_router(audit_router, prefix="/api/audit", tags=["审计日志"])

# 代码解析
from app.api.analysis import router as analysis_router
app.include_router(analysis_router, prefix="/api/analysis", tags=["代码解析"])

# 仪表盘与趋势看板
from app.api.dashboard import router as dashboard_router
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["仪表盘"])

# 质量门禁
from app.api.quality_gate import router as quality_gate_router
app.include_router(quality_gate_router, prefix="/api/quality-gate", tags=["质量门禁"])

# 质量趋势
from app.api.trend import router as trend_router
app.include_router(trend_router, prefix="/api/trend", tags=["质量趋势"])

# 站内通知
from app.api.notification import router as notification_router
app.include_router(notification_router, prefix="/api/notifications", tags=["站内通知"])
