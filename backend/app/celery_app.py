"""
AI 自动化测试平台 — Celery 配置
"""

from celery import Celery
from app.config import settings

celery_app = Celery(
    "ai_test_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.modules.execution.engine",
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


@celery_app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
