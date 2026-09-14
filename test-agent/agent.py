"""部署在被测主机的受限 Python 覆盖率 Agent（单进程 MVP）。

业务启动命令只能由主机管理员写入配置文件；平台请求只能选择已登记的服务。
Agent 应放在 HTTPS 反向代理后，令牌由环境变量提供。
"""

import hmac
import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


CONFIG_PATH = Path(os.environ.get("COVERAGE_AGENT_CONFIG", "/etc/aitp-coverage-agent.json"))
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
SERVICES = {item["name"]: item for item in CONFIG.get("services", [])}
ARTIFACT_ROOT = Path(CONFIG.get("artifact_root", "/var/lib/aitp-coverage"))
TOKEN = os.environ.get("COVERAGE_AGENT_TOKEN", "")
RUN_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
LOCK = threading.RLock()
SESSIONS: dict[tuple[str, str], dict[str, Any]] = {}
app = FastAPI(title="AITP Coverage Agent", docs_url=None, redoc_url=None, openapi_url=None)


class AgentRequest(BaseModel):
    run_id: str
    service: str


def authenticate(authorization: str = Header(default="")) -> None:
    if not TOKEN or not authorization.startswith("Bearer ") or not hmac.compare_digest(authorization[7:], TOKEN):
        raise HTTPException(401, "Invalid agent token")


def resolve(req: AgentRequest) -> tuple[dict[str, Any], Path]:
    if not RUN_ID.fullmatch(req.run_id):
        raise HTTPException(400, "run_id must be UUID")
    try:
        uuid.UUID(req.run_id)
    except ValueError as exc:
        raise HTTPException(400, "run_id must be UUID") from exc
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", req.service):
        raise HTTPException(400, "Invalid service name")
    service = SERVICES.get(req.service)
    if not service:
        raise HTTPException(404, "Service is not registered on this agent")
    return service, ARTIFACT_ROOT / req.service / req.run_id


@app.post("/agent/v1/coverage/prepare", dependencies=[Depends(authenticate)])
def prepare(req: AgentRequest):
    service, _ = resolve(req)
    workdir = Path(service["workdir"])
    source = Path(service["source"])
    command = service.get("command")
    python = Path(service.get("python_executable", sys.executable))
    if (not workdir.is_dir() or not source.exists() or not isinstance(command, list)
            or not command or not all(isinstance(arg, str) and arg for arg in command)
            or not python.is_file()):
        raise HTTPException(422, "Service code or static launch command is unavailable")
    try:
        max_seconds = int(service.get("max_run_seconds", 7200))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "max_run_seconds must be an integer") from exc
    if not 30 <= max_seconds <= 86400:
        raise HTTPException(422, "max_run_seconds must be between 30 and 86400")
    return {"status": "READY", "run_id": req.run_id, "service": req.service,
            "service_url": service.get("service_url", ""),
            "health_url": service.get("health_url") or service.get("service_url", ""),
            "commit_sha": service.get("commit_sha") or os.getenv("COVERAGE_DEPLOY_COMMIT")}


@app.post("/agent/v1/coverage/start", dependencies=[Depends(authenticate)])
def start(req: AgentRequest):
    service, output = resolve(req)
    prepare(req)
    key = (req.service, req.run_id)
    with LOCK:
        existing = SESSIONS.get(key)
        if existing and existing["process"].poll() is None:
            return {"status": "RUNNING", "service_url": service.get("service_url", ""),
                    "health_url": service.get("health_url") or service.get("service_url", "")}
        for (name, _), session in SESSIONS.items():
            if name == req.service and session["process"].poll() is None:
                raise HTTPException(409, "Service already has an active coverage run")
        if output.exists():
            raise HTTPException(409, "Coverage run directory already exists")
        output.mkdir(parents=True, exist_ok=False)
        workdir = Path(service["workdir"])
        log_file = (output / "service.log").open("ab")
        env = {**os.environ, "COVERAGE_FILE": str(output / ".coverage")}
        python = str(Path(service.get("python_executable", sys.executable)))
        command = [python, "-m", "coverage", "run", "--parallel-mode",
                   f"--source={service['source']}", *service["command"]]
        try:
            process = subprocess.Popen(command, cwd=workdir, env=env,
                                       stdout=log_file, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != "nt",
                                       creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
        except Exception:
            log_file.close()
            (output / "service.log").unlink(missing_ok=True)
            output.rmdir()
            raise
        log_file.close()
        SESSIONS[key] = {"process": process, "output": output, "workdir": workdir,
                         "python": python,
                         "service": service, "status": "RUNNING"}
        timer = threading.Timer(int(service.get("max_run_seconds", 7200)), expire_session, args=(req,))
        timer.daemon = True
        SESSIONS[key]["timer"] = timer
        timer.start()
    return {"status": "RUNNING", "service_url": service.get("service_url", ""),
            "health_url": service.get("health_url") or service.get("service_url", "")}


@app.post("/agent/v1/coverage/stop", dependencies=[Depends(authenticate)])
def stop(req: AgentRequest):
    resolve(req)
    session = SESSIONS.get((req.service, req.run_id))
    if not session:
        raise HTTPException(404, "Coverage run not started")
    with LOCK:
        if session["status"] == "COMPLETED":
            return {"status": "COMPLETED"}
        if session["status"] == "TIMED_OUT":
            return {"status": "TIMED_OUT"}
        session["timer"].cancel()
        process = session["process"]
        if process.poll() is None:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
        output = session["output"]
        env = {**os.environ, "COVERAGE_FILE": str(output / ".coverage")}
        if not list(output.glob(".coverage.*")):
            session["status"] = "NO_ARTIFACT"
            return {"status": "NO_ARTIFACT", "message": "Instrumented process produced no coverage data"}
        for args in (["combine", "--keep"], ["xml", "-o", str(output / "coverage.xml")]):
            result = subprocess.run([session["python"], "-m", "coverage", *args],
                                    cwd=session["workdir"], env=env, capture_output=True,
                                    text=True, timeout=60, check=False)
            if result.returncode:
                session["status"] = "FAILED"
                raise HTTPException(422, f"coverage {args[0]} failed: {result.stderr[-500:]}")
        session["status"] = "COMPLETED"
    return {"status": "COMPLETED"}


def expire_session(req: AgentRequest) -> None:
    """worker 异常退出或任务链未汇总时，也要回收插桩进程。"""
    try:
        stop(req)
    except Exception:
        session = SESSIONS.get((req.service, req.run_id))
        if session and session["process"].poll() is None:
            session["process"].terminate()
    with LOCK:
        session = SESSIONS.get((req.service, req.run_id))
        if session:
            session["status"] = "TIMED_OUT"


@app.get("/agent/v1/coverage/status/{service}/{run_id}", dependencies=[Depends(authenticate)])
def status(service: str, run_id: str):
    resolve(AgentRequest(run_id=run_id, service=service))
    session = SESSIONS.get((service, run_id))
    if not session:
        raise HTTPException(404, "Coverage run not started")
    return {"status": session["status"], "process_alive": session["process"].poll() is None}


@app.get("/agent/v1/coverage/artifact/{service}/{run_id}", dependencies=[Depends(authenticate)])
def artifact(service: str, run_id: str):
    _, output = resolve(AgentRequest(run_id=run_id, service=service))
    session = SESSIONS.get((service, run_id))
    path = output / "coverage.xml"
    if not session or session["status"] != "COMPLETED" or not path.is_file():
        raise HTTPException(404, "Coverage artifact not ready")
    return FileResponse(path, media_type="application/xml", filename="coverage.xml")
