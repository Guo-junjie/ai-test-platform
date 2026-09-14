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
    monkeypatch.setattr(engine, "_probe_service_url", lambda url, **_kwargs: (True, "HTTP 200", url))

    result = engine.prepare_environment.run("run-id", {"tech_stack": {"stack": "python"}})
    assert result["service_url"] == "http://instrumented.internal:8202"


def test_plan_placeholder_uses_agent_when_configured(monkeypatch):
    async def begin(_run_id):
        return "http://java-test.internal:8080"

    monkeypatch.setattr(CoverageManager, "begin", staticmethod(begin))
    monkeypatch.setattr(engine, "_check_cancelled", lambda *_: None)
    monkeypatch.setattr(engine, "_set_task_status_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_set_task_progress_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_probe_service_url", lambda url, **_kwargs: (True, "HTTP 200", url))
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
