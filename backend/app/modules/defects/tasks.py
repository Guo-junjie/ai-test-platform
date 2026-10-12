"""缺陷中心后台任务。"""
from app.celery_app import celery_app
from .notifications import run_dispatch
from .metrics import run_daily_metrics


@celery_app.task(name="app.modules.defects.tasks.dispatch_notifications")
def dispatch_notifications():
    return {"delivered": run_dispatch()}


@celery_app.task(name="app.modules.defects.tasks.snapshot_daily_metrics")
def snapshot_daily_metrics():
    return {"projects": run_daily_metrics()}
