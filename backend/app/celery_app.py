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
    """Celery prefork worker 子进程启动 hook：完全重建 async engine。

    根因
    ----
    Celery 默认 prefork 模式：主进程加载代码 → fork 出 worker 子进程。
    ``app.utils.database.async_engine`` 是模块级单例，fork 后子进程继承其内部状态；
    asyncpg 持有的 Future / Socket 状态绑定的是主进程的 event loop。
    子进程 ``asyncio.run(...)`` 会创建新 event loop，复用连接会抛：
        RuntimeError: ... got Future ... attached to a different loop

    历史修复
    --------
    2728d61c 用 ``async_engine.pool.dispose()`` 关掉 inherited connection pool，
    但 **engine 内部其他状态仍可能含旧 loop 引用**——用户部署机仍偶发报错。

    最终修复（本次）
    ----------------
    通过 ``reset_async_engine()`` **完全重建** async engine + sessionmaker：
    1. 旧 engine 关闭（同步 dispose）
    2. 新 engine 创建（worker 子进程内全新的 engine + 全新的 pool）
    3. 新 sessionmaker 绑定新 engine
    4. module attr 替换完成
    5. 17 处 ``from app.utils.database import AsyncSessionLocal`` 拿到的都是 proxy 对象
       → proxy 内部始终从最新 module attr 取 → 自动用新 engine（**无需改 17 处 import**）

    这是 Celery 官方推荐做法 + 自定义 proxy 解决多 import 路径问题。
    """
    try:
        from app.utils.database import reset_async_engine
        reset_async_engine()
    except Exception as exc:  # noqa: BLE001
        # 任何意外不影响 worker 启动；engine 仍可下次访问时惰性重建
        logger.warning(f"worker_process_init reset failed (non-fatal): {exc}")
