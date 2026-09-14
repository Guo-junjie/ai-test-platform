"""测试前应让原有执行器把请求发往 Agent 启动的插桩实例。"""

from app.modules.coverage.manager import CoverageManager
from app.modules.execution import engine


def test_agent_service_url_replaces_target_even_without_project_target(monkeypatch):
    async def begin(_run_id):
        return "http://instrumented.internal:8202"

    monkeypatch.setattr(CoverageManager, "begin", staticmethod(begin))
    monkeypatch.setattr(engine, "_check_cancelled", lambda *_: None)
    monkeypatch.setattr(engine, "_set_task_status_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_set_task_progress_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_probe_service_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Agent 已完成健康检查，不应重复发送 HTTP 请求")))

    result = engine.prepare_environment.run("run-id", {"tech_stack": {"stack": "python"}})
    assert result["service_url"] == "http://instrumented.internal:8202"


def test_plan_placeholder_uses_agent_when_configured(monkeypatch):
    async def begin(_run_id):
        return "http://java-test.internal:8080"

    monkeypatch.setattr(CoverageManager, "begin", staticmethod(begin))
    monkeypatch.setattr(engine, "_check_cancelled", lambda *_: None)
    monkeypatch.setattr(engine, "_set_task_status_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_set_task_progress_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_probe_service_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Agent 已完成健康检查，不应重复发送 HTTP 请求")))
    result = engine.prepare_environment.run("run-id", {"service_url_override": "http://plan-mode-no-sut"})
    assert result["service_url"] == "http://java-test.internal:8080"


def test_plan_placeholder_is_kept_without_coverage_service(monkeypatch):
    async def begin(_run_id):
        return None

    monkeypatch.setattr(CoverageManager, "begin", staticmethod(begin))
    monkeypatch.setattr(engine, "_check_cancelled", lambda *_: None)
    monkeypatch.setattr(engine, "_set_task_status_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_set_task_progress_sync", lambda *_args, **_kwargs: None)
    result = engine.prepare_environment.run("run-id", {"service_url_override": "http://plan-mode-no-sut"})
    assert result["service_url"] == "http://plan-mode-no-sut"


def test_substep_progress_does_not_complete_run(monkeypatch):
    """API 用例完成时仍须等待覆盖率封存，不能把整个 Run 写成完成。"""
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    cursor = MagicMock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setitem(sys.modules, "psycopg2", SimpleNamespace(connect=lambda *_: connection))
    monkeypatch.setattr(engine, "_get_sync_redis", lambda: MagicMock())

    engine._set_task_progress_sync("run-id", 75, "接口测试完成 (1/1)")

    sql = cursor.execute.call_args.args[0]
    assert "UPDATE test_runs SET progress" in sql
    assert "status" not in sql.lower()
    assert "completed_at" not in sql.lower()
