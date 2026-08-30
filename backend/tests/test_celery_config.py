"""Celery 配置回归测试——防"配置改了但没人消费"级别断点复发。

回归背景：
- 2026-08-30 实锤 execution 队列路由了任务但没有 worker 消费（任务永久 PENDING）；
- beat 曾配置 django-celery-beat（FastAPI 项目无 Django settings，启动即崩），
  现为静态 tick + 每日知识同步。本文件锁住这两个关键配置。
"""
# include 列表里的模块只有 worker 启动时才会加载；测试显式 import 触发任务注册
import importlib  # noqa: E402

for _mod in (
    "app.modules.pipeline",
    "app.modules.execution.engine",
    "app.modules.scheduler.tasks",
    "app.modules.knowledge.tasks",
):
    importlib.import_module(_mod)

from app.celery_app import celery_app  # noqa: E402


class TestTaskRoutes:
    def test_execution_queue_has_route(self):
        routes = celery_app.conf.task_routes
        assert "app.modules.execution.engine.*" in routes
        assert routes["app.modules.execution.engine.*"]["queue"] == "execution"


class TestBeatSchedule:
    def test_scheduled_tick_registered(self):
        entry = celery_app.conf.beat_schedule.get("scheduled-tick-every-30s")
        assert entry is not None
        assert entry["task"] == "app.modules.scheduler.tasks.scheduled_tick"
        assert entry["schedule"] == 30.0

    def test_kb_auto_sync_registered(self):
        entry = celery_app.conf.beat_schedule.get("kb-auto-sync-daily-3am")
        assert entry is not None
        assert entry["task"] == "app.modules.knowledge.tasks.auto_sync_knowledge"

    def test_no_django_scheduler(self):
        """FastAPI 项目没有 Django settings，django-celery-beat 会让 beat 启动即崩。"""
        scheduler = celery_app.conf.beat_scheduler
        assert not (scheduler and "django" in str(scheduler))


class TestTaskRegistration:
    def test_pipeline_task_registered(self):
        assert "app.modules.pipeline.run_test_pipeline" in celery_app.tasks

    def test_execution_chain_tasks_registered(self):
        for name in (
            "app.modules.execution.engine.prepare_environment",
            "app.modules.execution.engine.run_api_tests",
            "app.modules.execution.engine.run_performance_tests",
            "app.modules.execution.engine.run_integration_tests",
            "app.modules.execution.engine.aggregate_results",
        ):
            assert name in celery_app.tasks, f"missing task: {name}"

    def test_scheduler_tasks_registered(self):
        for name in (
            "app.modules.scheduler.tasks.scheduled_tick",
            "app.modules.scheduler.tasks.execute_scheduled_task",
        ):
            assert name in celery_app.tasks, f"missing task: {name}"

    def test_knowledge_tasks_registered(self):
        for name in (
            "app.modules.knowledge.tasks.rebuild_knowledge_base",
            "app.modules.knowledge.tasks.process_knowledge_document",
            "app.modules.knowledge.tasks.auto_sync_knowledge",
        ):
            assert name in celery_app.tasks, f"missing task: {name}"
