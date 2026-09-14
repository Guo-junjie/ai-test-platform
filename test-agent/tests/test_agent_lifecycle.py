"""以真实 HTTP 请求验证 Python 服务在 Agent 插桩期产生代码覆盖率。"""

import importlib.util
import json
import socket
import time
import uuid
from pathlib import Path

import httpx
from fastapi.testclient import TestClient


def test_request_creates_real_coverage_artifact(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    source = tmp_path / "service.py"
    source.write_text(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "import signal, sys\n"
        "if hasattr(signal, 'SIGBREAK'):\n"
        "    signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path == '/hit':\n"
        "            self.send_response(200)\n"
        "        else:\n"
        "            self.send_response(404)\n"
        "        self.end_headers()\n"
        f"HTTPServer(('127.0.0.1', {port}), Handler).serve_forever()\n",
        encoding="utf-8",
    )
    config = tmp_path / "agent.json"
    config.write_text(json.dumps({"artifact_root": str(tmp_path / "artifacts"),
                                  "services": [{"name": "sample", "workdir": str(tmp_path),
                                                "source": str(tmp_path), "command": ["service.py"],
                                                "service_url": f"http://127.0.0.1:{port}",
                                                "health_url": f"http://127.0.0.1:{port}/health"}]}),
                      encoding="utf-8")
    monkeypatch.setenv("COVERAGE_AGENT_CONFIG", str(config))
    monkeypatch.setenv("COVERAGE_AGENT_TOKEN", "local-test-token")
    agent_file = Path(__file__).resolve().parents[1] / "agent.py"
    spec = importlib.util.spec_from_file_location("coverage_test_agent", agent_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    headers = {"Authorization": "Bearer local-test-token"}
    payload = {"service": "sample", "run_id": str(uuid.uuid4())}
    with TestClient(module.app) as client:
        assert client.post("/agent/v1/coverage/prepare", json=payload).status_code == 401
        assert client.post("/agent/v1/coverage/prepare", json=payload, headers=headers).json()["status"] == "READY"
        assert client.post("/agent/v1/coverage/start", json=payload, headers=headers).json()["status"] == "RUNNING"
        competing = {**payload, "run_id": str(uuid.uuid4())}
        assert client.post("/agent/v1/coverage/start", json=competing, headers=headers).status_code == 409
        deadline = time.monotonic() + 15
        try:
            while True:
                try:
                    response = httpx.get(f"http://127.0.0.1:{port}/hit", timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, "instrumented service did not start"
                time.sleep(0.1)
            stopped = client.post("/agent/v1/coverage/stop", json=payload, headers=headers)
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["status"] == "COMPLETED"
            assert client.post("/agent/v1/coverage/stop", json=payload, headers=headers).json()["status"] == "COMPLETED"
            artifact = client.get(f"/agent/v1/coverage/artifact/sample/{payload['run_id']}", headers=headers)
            assert artifact.status_code == 200
            assert b"service.py" in artifact.content
            from app.modules.coverage.parser import parse_coverage_report
            parsed = parse_coverage_report("coverage.py", artifact.text)
            assert parsed["covered_lines"] > 0
            assert parsed["total_lines"] >= parsed["covered_lines"]
            hits = {line["number"]: line["hits"] for file in parsed["files"]
                    if file["path"].endswith("service.py") for line in file["lines"]}
            assert hits[8] > 0  # /hit 请求实际执行的分支
            assert hits[10] == 0  # 未请求的分支不应被虚构为覆盖
        finally:
            if module.SESSIONS.get(("sample", payload["run_id"])):
                process = module.SESSIONS[("sample", payload["run_id"])]["process"]
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
