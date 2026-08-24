"""
AI 自动化测试平台 — Celery 配置
"""

from celery import Celery
from celery.signals import worker_process_init
from loguru import logger

from app.config import settings

celery_app = Celery(
    "ai_test_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.modules.execution.engine",
        "app.modules.pipeline",
        "app.modules.scheduler.tasks",
        "app.modules.knowledge.tasks",
    ],
)

# Celery 配置
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 任务路由
    task_routes={
        "app.modules.execution.engine.*": {"queue": "execution"},
    },

    # 重试配置
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # 结果过期时间（7天）
    result_expires=7 * 24 * 3600,

    # 任务时间限制（30分钟软限制，60分钟硬限制）
    task_soft_time_limit=30 * 60,
    task_time_limit=60 * 60,
)

# Celery Beat 配置 — 使用 django-celery-beat DatabaseScheduler
try:
    celery_app.conf.update(
        beat_scheduler="django_celery_beat.schedulers:DatabaseScheduler",
    )
except ImportError:
    # django-celery-beat 未安装时的容错
    pass


@celery_app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")


@worker_process_init.connect
def _init_celery_worker(**_kwargs) -> None:
    """Celery prefork worker 子进程启动 hook：清理 fork 继承的 async engine 连接池。

    根因
    ----
    Celery 默认 prefork 模式：主进程加载代码 → fork 出 worker 子进程。
    `app.utils.database.async_engine` 是模块级单例，fork 后子进程继承其内部状态；
    asyncpg 持有的 Future / Socket 状态绑定的是主进程的 event loop。
    子进程 `asyncio.run(...)` 会创建新 event loop，复用连接会抛：
        RuntimeError: ... got Future ... attached to a different loop

    修复
    ----
    子进程启动时 dispose 父进程的 connection pool，迫使 asyncpg 在本进程首次
    访问时按本进程的 event loop 重新建立连接。这是 Celery 官方推荐做法。
    """
    try:
        # 延迟导入，避免主进程启动时过早加载数据库连接
        from app.utils.database import async_engine
        # async_engine.pool 是同步 API；直接 dispose 所有 inherited 连接
        async_engine.pool.dispose()
        logger.info(
            "Celery worker 子进程已 dispose 继承的 async engine 连接池，"
            "下次访问将按子进程 event loop 重建。"
        )
    except Exception as exc:  # noqa: BLE001
        # 任何意外不影响 worker 启动；engine 仍可下次访问时惰性重建
        logger.warning(f"worker_process_init dispose failed (non-fatal): {exc}")
