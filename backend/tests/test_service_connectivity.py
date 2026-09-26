"""被测服务连通测试与环境健康检查的状态语义。"""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api.environments import _do_healthcheck, _normalize_healthcheck_path
from app.api.project import ProbeUrlRequest, probe_url


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def fake_client(status_code: int, requested_urls: list[str] | None = None):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url: str):
            if requested_urls is not None:
                requested_urls.append(url)
            return FakeResponse(status_code)

    return FakeClient


@pytest.mark.asyncio
async def test_probe_does_not_report_404_as_success(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", fake_client(404))

    result = await probe_url(ProbeUrlRequest(url="http://service.example"), current_user=SimpleNamespace())

    assert result["code"] == 1
    assert result["data"]["reachable"] is False
    assert result["data"]["network_reachable"] is True
    assert result["data"]["status_code"] == 404
    assert "路径不存在" in result["data"]["message"]
    assert "连接成功" not in result["data"]["message"]


@pytest.mark.asyncio
async def test_probe_reports_2xx_as_success(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", fake_client(204))

    result = await probe_url(ProbeUrlRequest(url="http://service.example"), current_user=SimpleNamespace())

    assert result["code"] == 0
    assert result["data"]["reachable"] is True
    assert result["data"]["network_reachable"] is True
    assert "连接成功" in result["data"]["message"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("/health", "/health"),
        ("health", "/health"),
        ("GET /health", "/health"),
        ("get   /actuator/health", "/actuator/health"),
    ],
)
def test_healthcheck_path_normalization(raw: str, expected: str):
    assert _normalize_healthcheck_path(raw) == expected


@pytest.mark.parametrize("raw", ["POST /health", "http://service.example/health", "/bad path"])
def test_healthcheck_path_rejects_invalid_values(raw: str):
    with pytest.raises(HTTPException) as exc_info:
        _normalize_healthcheck_path(raw)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_healthcheck_accepts_get_prefix_and_reports_exact_url(monkeypatch):
    requested_urls: list[str] = []
    monkeypatch.setattr(httpx, "AsyncClient", fake_client(200, requested_urls))
    profile = SimpleNamespace(
        base_url="http://192.168.125.128:8302/",
        healthcheck_path="GET /health",
    )

    status, detail, health_url = await _do_healthcheck(profile)

    assert status == "healthy"
    assert health_url == "http://192.168.125.128:8302/health"
    assert requested_urls == [health_url]
    assert "HTTP 200" in detail


@pytest.mark.asyncio
async def test_healthcheck_distinguishes_404_from_network_failure(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", fake_client(404))
    profile = SimpleNamespace(base_url="http://service.example", healthcheck_path="/missing")

    status, detail, health_url = await _do_healthcheck(profile)

    assert status == "unhealthy"
    assert health_url == "http://service.example/missing"
    assert "路径不存在" in detail
