"""远程采集配置边界与 API 路由回归。"""

import pytest

from app.modules.coverage.manager import validate_agent_service


def _service(**overrides):
    return {"name": "orders", "agent_url": "https://coverage.example.test:9443",
            "token_env": "COVERAGE_AGENT_ORDERS_TOKEN", "language": "python",
            "tool": "coverage.py", **overrides}


def test_agent_requires_allowed_host_and_https(monkeypatch):
    monkeypatch.setenv("COVERAGE_AGENT_ALLOWED_HOSTS", "coverage.example.test")
    assert validate_agent_service(_service())["name"] == "orders"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_agent_service(_service(agent_url="http://coverage.example.test:9443"))
    with pytest.raises(ValueError, match="未加入"):
        validate_agent_service(_service(agent_url="https://unregistered.example.test"))


def test_agent_rejects_untrusted_fields(monkeypatch):
    monkeypatch.setenv("COVERAGE_AGENT_ALLOWED_HOSTS", "coverage.example.test")
    with pytest.raises(ValueError, match="token_env"):
        validate_agent_service(_service(token_env="PATH"))
    assert validate_agent_service(_service(language="go", tool="go_cover"))["tool"] == "go_cover"
    with pytest.raises(ValueError, match="仅支持"):
        validate_agent_service(_service(language="go"))
    with pytest.raises(ValueError, match="服务名"):
        validate_agent_service(_service(name="../other"))


def test_coverage_run_list_path_is_not_report_id():
    from app.api.coverage import router

    assert any(route.path == "/projects/{project_id}/runs" for route in router.routes)
    assert any(route.path == "/runs/{test_run_id}" for route in router.routes)
