"""真实 Go HTTP 请求应只统计插桩二进制执行到的语句。"""

import importlib.util
import json
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


def _go_with_build_coverage():
    go = shutil.which("go")
    if not go:
        pytest.skip("Go toolchain is not installed")
    version = subprocess.check_output([go, "version"], text=True)
    match = re.search(r"go(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (1, 20):
        pytest.skip("go build -cover requires Go 1.20+")
    return go


@pytest.mark.parametrize("instrumented", [True, False])
def test_go_request_reports_actual_artifact_state(tmp_path, monkeypatch, instrumented):
    go = _go_with_build_coverage()
    source = Path(__file__).resolve().parents[1] / "examples" / "go"
    binary = tmp_path / "sample-go"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # The sample listens on a fixed port; replace it in a temporary source copy.
    isolated = tmp_path / "src"
    isolated.mkdir()
    (isolated / "go.mod").write_bytes((source / "go.mod").read_bytes())
    (isolated / "main.go").write_text((source / "main.go").read_text().replace(':8203', f':{port}'))
    build = [go, "build", *(["-cover"] if instrumented else []), "-o", str(binary), "."]
    subprocess.run(build, cwd=isolated,
                   check=True, capture_output=True, timeout=120)
    config = tmp_path / "agent.json"
    config.write_text(json.dumps({"artifact_root": str(tmp_path / "artifacts"), "services": [{
        "name": "sample-go", "language": "go", "tool": "go_cover", "workdir": str(tmp_path),
        "command": [str(binary)], "go_executable": go,
        "service_url": f"http://127.0.0.1:{port}",
        "health_url": f"http://127.0.0.1:{port}/health"}]}), encoding="utf-8")
    monkeypatch.setenv("COVERAGE_AGENT_CONFIG", str(config))
    monkeypatch.setenv("COVERAGE_AGENT_TOKEN", "local-go-test-token")
    agent_file = Path(__file__).resolve().parents[1] / "agent.py"
    spec = importlib.util.spec_from_file_location("coverage_go_test_agent", agent_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    headers = {"Authorization": "Bearer local-go-test-token"}
    payload = {"service": "sample-go", "run_id": str(uuid.uuid4())}
    with TestClient(module.app) as client:
        ready = client.post("/agent/v1/coverage/prepare", json=payload, headers=headers)
        assert ready.status_code == 200, ready.text
        assert ready.json()["tool"] == "go_cover"
        started = client.post("/agent/v1/coverage/start", json=payload, headers=headers)
        assert started.status_code == 200, started.text
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                pytest.fail("instrumented Go service did not start")
            assert httpx.get(f"http://127.0.0.1:{port}/orders/1", timeout=2).json()["status"] == "paid"
            stopped = client.post("/agent/v1/coverage/stop", json=payload, headers=headers)
            assert stopped.status_code == 200, stopped.text
            artifact = client.get(f"/agent/v1/coverage/artifact/sample-go/{payload['run_id']}", headers=headers)
            if not instrumented:
                assert stopped.json()["status"] == "NO_ARTIFACT"
                assert artifact.status_code == 404
                return
            assert stopped.json()["status"] == "COMPLETED"
            assert artifact.status_code == 200
            assert artifact.text.startswith("mode:")
            blocks = [line.rsplit(" ", 2) for line in artifact.text.splitlines()[1:]]
            assert any(len(block) == 3 and int(block[2]) > 0 for block in blocks)
            assert any(len(block) == 3 and int(block[2]) == 0 for block in blocks)
        finally:
            session = module.SESSIONS.get(("sample-go", payload["run_id"]))
            if session and session["process"].poll() is None:
                session["process"].terminate()
                session["process"].wait(timeout=5)
