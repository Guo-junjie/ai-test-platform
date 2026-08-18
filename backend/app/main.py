"""
AI 自动化测试平台 — FastAPI 应用入口
"""

import inspect
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text

from app.config import settings
from app.utils.logger import setup_logger


async def _run_lifecycle_step(
    name: str,
    func: Callable[[], Any],
    phase: str = "startup",
) -> bool:
    """
    执行单个生命周期步骤（启动初始化 / 关停清理），失败只记录日志、不中断进程。

    为什么必须隔离异常：
    容器里 uvicorn 以 `--reload` 运行时，父进程只对 8000 端口做了 bind() 而没有
    listen()（listen 发生在子进程的 loop.create_server 里）。一旦子进程在 ASGI
    lifespan startup 阶段抛异常，子进程退出、端口停留在 bound-but-not-listening，
    内核对新连接直接回 RST —— nginx 侧就是
    `connect() failed (111: Connection refused)` 并给浏览器返回 502。
    因此任何一步初始化失败都不允许把整个 HTTP 服务拖死：服务必须活着，
    让 /api/health 与业务接口把真实错误暴露出来。

    Args:
        name: 步骤名称，用于日志。
        func: 无参可调用对象，可为同步函数或协程函数。
        phase: 阶段标签，startup / shutdown，仅用于日志前缀。

    Returns:
        True 表示成功，False 表示失败（异常已被吞掉并记录）。
    """
    try:
        result = func()
        if inspect.isawaitable(result):
            await result
        logger.info(f"[{phase}] {name}: OK")
        return True
    except Exception as exc:
        logger.exception(
            f"[{phase}] {name}: FAILED -> {exc.__class__.__name__}: {exc} "
            f"(已跳过该步骤，HTTP 服务继续运行)"
        )
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化日志系统
    setup_logger()
    logger.info(f"Starting AI Test Platform in {settings.APP_ENV} mode...")

    from app.models.database import init_db
    from app.modules.ai.model_router import init_default_models
    from app.modules.auth.auth_service import AuthService
    from app.utils.storage import init_minio

    # 每步独立容错，任一步失败都不会导致 uvicorn 退出（避免 8000 端口无监听 → 502）
    await _run_lifecycle_step("Database initialization", init_db)
    await _run_lifecycle_step("MinIO storage initialization", init_minio)
    await _run_lifecycle_step("AI model configurations", init_default_models)
    await _run_lifecycle_step("Default accounts seeding", AuthService.init_default_admin)

    logger.info("AI Test Platform startup finished, serving on :8000")

    yield

    # 清理资源（同样不允许因单点异常打断关停流程）
    from app.utils.database import dispose_engine
    from app.utils.redis_client import close_redis

    await _run_lifecycle_step("Redis client close", close_redis, phase="shutdown")
    await _run_lifecycle_step("Database engine dispose", dispose_engine, phase="shutdown")
    logger.info("Shutting down AI Test Platform...")


app = FastAPI(
    title="AI 自动化测试平台",
    description="企业级 AI 自动化测试与质量保障平台",
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
# 必须真探数据库：main.py 已让启动失败也不拖垮 HTTP 服务，若这里只返回 healthy，
# 编排系统（compose depends_on / K8s liveness）会误判服务健康，出现"进程在跑但库挂了"的静默故障。
@app.get("/api/health")
async def health_check():
    try:
        from app.models.database import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
        return {"status": "healthy", "env": settings.APP_ENV}
    except Exception as exc:
        logger.warning(f"health check failed: {exc.__class__.__name__}: {exc}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "env": settings.APP_ENV,
                "detail": "database unreachable",
            },
        )

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

# 接口文档资产（能力1：AI 解析接口文档导入 / 能力2：AI 评审接口文档）
from app.api.doc import router as doc_router
app.include_router(doc_router, prefix="/api/docs", tags=["接口文档资产"])

# 用例资产（能力3：AI 生成单接口用例·接纳闭环）
from app.api.case_library import router as case_library_router
app.include_router(case_library_router, prefix="/api/cases", tags=["用例资产"])

# 测试场景（能力4：AI 编排测试场景）
from app.api.scenario import router as scenario_router
app.include_router(scenario_router, prefix="/api/scenarios", tags=["测试场景"])

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

# 变更审批
from app.api.change_request import router as change_request_router
app.include_router(change_request_router, prefix="/api/change-requests")
