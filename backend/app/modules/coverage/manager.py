"""覆盖率会话编排：启动临时实例或打开常驻 Java 采集窗口，测试后收集产物。"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.models.database import (
    CoverageReport, CoverageRun, CoverageService, CoverageSource, CoverageTool,
    Project, TestRun, TestStatus,
)
from app.modules.coverage.parser import parse_coverage_report
from app.utils.database import AsyncSessionLocal


ARTIFACT_ROOT = Path("/app/data/uploads/coverage/runs")
SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
ENV_NAME = re.compile(r"^COVERAGE_AGENT_[A-Z0-9_]{1,80}$")


class CoverageLifecycleError(RuntimeError):
    def __init__(self, message: str, required: bool = False):
        super().__init__(message)
        self.required = required


def coverage_threshold_errors(config: dict, line_rate: float | None,
                              branch_rate: float | None) -> list[str]:
    """只依据本次 Coverage Run 的聚合结果评估门槛。"""
    errors = []
    for key, label, actual in (("min_line_rate", "行覆盖率", line_rate),
                               ("min_branch_rate", "分支覆盖率", branch_rate)):
        minimum = config.get(key)
        if minimum is None:
            continue
        if actual is None or actual < float(minimum):
            current = f"{actual}%" if actual is not None else "未提供"
            errors.append(f"{label} {current} 低于门槛 {minimum}%")
    return errors


def validate_agent_service(config: dict) -> dict:
    """仅允许远程 Agent 白名单配置，不接受运行时命令或任意服务路径。"""
    name = str(config.get("name") or "")
    url = str(config.get("agent_url") or "").rstrip("/")
    token_env = str(config.get("token_env") or "")
    parsed = urlparse(url)
    if not SERVICE_NAME.fullmatch(name):
        raise ValueError("服务名只能包含字母、数字、点、下划线和连字符")
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError(f"{name}: Agent URL 无效")
    allowed_hosts = {"localhost", "127.0.0.1", "host.docker.internal"}
    allowed_hosts.update(host.strip().lower() for host in os.getenv("COVERAGE_AGENT_ALLOWED_HOSTS", "").split(",") if host.strip())
    if parsed.hostname.lower() not in allowed_hosts:
        raise ValueError(f"{name}: Agent 主机未加入 COVERAGE_AGENT_ALLOWED_HOSTS")
    if parsed.scheme == "http" and not (
        parsed.hostname in {"localhost", "127.0.0.1", "host.docker.internal"}
        or os.getenv("COVERAGE_AGENT_ALLOW_HTTP") == "1"
    ):
        raise ValueError(f"{name}: 远程 Agent 必须使用 HTTPS")
    if not ENV_NAME.fullmatch(token_env):
        raise ValueError(f"{name}: token_env 必须是 COVERAGE_AGENT_ 开头的环境变量名")
    language = config.get("language")
    tool = config.get("tool")
    if (language, tool) not in {("python", "coverage.py"), ("go", "go_cover"), ("java", "jacoco")}:
        raise ValueError(f"{name}: Agent 仅支持 Python coverage.py、Go go_cover 或 Java JaCoCo")
    return {"name": name, "agent_url": url, "token_env": token_env,
            "language": language, "tool": tool,
            "primary": bool(config.get("primary", False))}


async def _agent_request(service: CoverageService, action: str, run_id: uuid.UUID) -> httpx.Response:
    token = os.getenv(service.token_env)
    if not token:
        raise CoverageLifecycleError(f"{service.name}: 未设置 Agent 凭据环境变量 {service.token_env}")
    path = f"/agent/v1/coverage/{action}"
    action_timeout = 180 if action == "stop" else 45
    async with httpx.AsyncClient(timeout=httpx.Timeout(action_timeout, connect=5), verify=True, trust_env=False) as client:
        if action == "artifact":
            response = await client.get(f"{service.agent_url}{path}/{service.name}/{run_id}",
                                        headers={"Authorization": f"Bearer {token}"})
        elif action == "status":
            response = await client.get(f"{service.agent_url}{path}/{service.name}/{run_id}",
                                        headers={"Authorization": f"Bearer {token}"})
        else:
            response = await client.post(f"{service.agent_url}{path}",
                                         json={"run_id": str(run_id), "service": service.name},
                                         headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response


async def _download_artifact(service: CoverageService, run_id: uuid.UUID) -> bytes:
    """流式取回 Artifact；在下载过程中实施大小限制，避免 worker 内存被耗尽。"""
    token = os.getenv(service.token_env)
    if not token:
        raise CoverageLifecycleError(f"{service.name}: 未设置 Agent 凭据环境变量 {service.token_env}")
    url = f"{service.agent_url}/agent/v1/coverage/artifact/{service.name}/{run_id}"
    chunks = []
    size = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), verify=True, trust_env=False) as client:
        async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise CoverageLifecycleError(f"{service.name}: Artifact 超过 20MB")
                chunks.append(chunk)
    return b"".join(chunks)


async def _wait_service_ready(url: str, timeout_seconds: int = 60) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await client.get(url)
                if 200 <= response.status_code < 400:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise CoverageLifecycleError(f"插桩服务在 {timeout_seconds} 秒内未就绪: {url}")


class CoverageManager:
    """复用既有 TestRun/Celery/Report，记录覆盖率独立状态。"""

    @staticmethod
    async def begin(test_run_id: str) -> str | None:
        """启动远程 Agent；返回插桩实例 URL，供原有测试执行器发请求。"""
        run_id = uuid.UUID(test_run_id)
        async with AsyncSessionLocal() as db:
            run = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one_or_none()
            if not run:
                return None
            project = (await db.execute(select(Project).where(Project.id == run.project_id))).scalar_one()
            config = ((project.source_config or {}).get("coverage_config") or {})
            if config.get("enabled") is False or (project.quality_gate_config or {}).get("auto_coverage") is False:
                return None
            service_configs = config.get("services") or []
            if not service_configs:
                if config.get("required"):
                    raise CoverageLifecycleError("严格模式已开启，但未配置任何覆盖率 Agent 服务", required=True)
                return None  # 兼容旧的报告上传/HTTP 策略
            required = bool(config.get("required", False))
            existing = (await db.execute(select(CoverageRun).where(CoverageRun.test_run_id == run_id))).scalar_one_or_none()
            if existing:
                if existing.status == "RUNNING":
                    first = (await db.execute(select(CoverageService).where(CoverageService.coverage_run_id == existing.id)
                                              .order_by(CoverageService.primary.desc(), CoverageService.name))).scalars().first()
                    return first.service_url if first else None
                raise CoverageLifecycleError(f"覆盖率会话已存在，状态 {existing.status}", required)
            try:
                items = [validate_agent_service(item) for item in service_configs]
                if len({item["name"] for item in items}) != len(items):
                    raise ValueError("覆盖率服务名不能重复")
                if len(items) > 1 and sum(item["primary"] for item in items) != 1:
                    raise ValueError("多服务配置必须指定唯一的 primary 测试入口")
            except ValueError as exc:
                raise CoverageLifecycleError(str(exc), required) from exc
            coverage_run = CoverageRun(test_run_id=run.id, project_id=run.project_id,
                                       commit_sha=run.commit_sha, status="PREPARING", required=required)
            db.add(coverage_run)
            await db.flush()
            services = []
            for item in items:
                service = CoverageService(coverage_run_id=coverage_run.id, name=item["name"],
                                          primary=item["primary"] or len(items) == 1,
                                          language=item["language"], tool=item["tool"],
                                          agent_url=item["agent_url"], token_env=item["token_env"],
                                          status="PREPARING")
                db.add(service)
                services.append((service, item["primary"]))
            await db.commit()

        primary_url = None
        started = []
        try:
            for service, primary in services:
                prepared = (await _agent_request(service, "prepare", coverage_run.id)).json()
                if prepared.get("status") != "READY":
                    raise CoverageLifecycleError(f"{service.name}: Agent 未就绪")
                reported_adapter = (prepared.get("language"), prepared.get("tool"))
                if any(reported_adapter) and reported_adapter != (service.language, service.tool):
                    raise CoverageLifecycleError(f"{service.name}: Agent 采集器与项目配置不一致")
                if service.tool in {"go_cover", "jacoco"} and prepared.get("tool") != service.tool:
                    raise CoverageLifecycleError(f"{service.name}: Agent 不支持 {service.tool} 采集")
                deployed_commit = prepared.get("commit_sha")
                if coverage_run.commit_sha and required and not deployed_commit:
                    raise CoverageLifecycleError(f"{service.name}: 严格模式要求 Agent 报告部署 commit")
                if coverage_run.commit_sha and deployed_commit and deployed_commit != coverage_run.commit_sha:
                    raise CoverageLifecycleError(
                        f"{service.name}: 部署版本 {deployed_commit} 与测试版本 {coverage_run.commit_sha} 不一致")
                started_result = (await _agent_request(service, "start", coverage_run.id)).json()
                if started_result.get("status") != "RUNNING":
                    raise CoverageLifecycleError(f"{service.name}: 插桩服务启动失败")
                started.append(service)
                service_url = started_result.get("service_url") or prepared.get("service_url")
                if not service_url:
                    raise CoverageLifecycleError(f"{service.name}: Agent 未返回被测服务 URL")
                await _wait_service_ready(started_result.get("health_url") or prepared.get("health_url") or service_url)
                await asyncio.sleep(0.5)
                health = (await _agent_request(service, "status", coverage_run.id)).json()
                if not health.get("process_alive"):
                    raise CoverageLifecycleError(f"{service.name}: 插桩进程提前退出；请检查 Agent 的 service.log")
                service.service_url = service_url
                service.deployed_commit_sha = deployed_commit
                service.status = "RUNNING"
                if primary or len(services) == 1:
                    primary_url = service_url
            async with AsyncSessionLocal() as db:
                test_row = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one()
                if test_row.status == TestStatus.CANCELLED:
                    raise CoverageLifecycleError("测试任务已取消")
                await db.merge(coverage_run)
                for service in started:
                    await db.merge(service)
                row = (await db.execute(select(CoverageRun).where(CoverageRun.id == coverage_run.id))).scalar_one()
                row.status = "RUNNING"
                row.started_at = datetime.utcnow()
                await db.commit()
            return primary_url
        except Exception as exc:
            for service in started:
                try:
                    await _agent_request(service, "stop", coverage_run.id)
                except Exception:
                    pass
            async with AsyncSessionLocal() as db:
                row = (await db.execute(select(CoverageRun).where(CoverageRun.id == coverage_run.id))).scalar_one()
                test_row = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one()
                row.status = "CANCELLED" if test_row.status == TestStatus.CANCELLED else "FAILED"
                row.error_message = str(exc)[:2000]
                row.finished_at = datetime.utcnow()
                for service, _ in services:
                    item = (await db.execute(select(CoverageService).where(CoverageService.id == service.id))).scalar_one()
                    item.status = "FAILED"
                    item.error_message = str(exc)[:2000]
                await db.commit()
            raise CoverageLifecycleError(f"覆盖率启动失败: {exc}", required) from exc

    @staticmethod
    async def finish(test_run_id: str) -> CoverageRun | None:
        """停止所有服务，取回 XML 并为每个服务保存报告和聚合统计。"""
        run_id = uuid.UUID(test_run_id)
        async with AsyncSessionLocal() as db:
            coverage_run = (await db.execute(select(CoverageRun).where(CoverageRun.test_run_id == run_id))).scalar_one_or_none()
            if not coverage_run or coverage_run.status in {"COMPLETED", "PARTIAL", "FAILED", "NO_ARTIFACT", "CANCELLED"}:
                return coverage_run
            services = (await db.execute(select(CoverageService).where(
                CoverageService.coverage_run_id == coverage_run.id))).scalars().all()
            coverage_run.status = "COLLECTING"
            await db.commit()
            results = []
            errors = []
            for service in services:
                try:
                    stopped = (await _agent_request(service, "stop", coverage_run.id)).json()
                    if stopped.get("status") != "COMPLETED":
                        raise CoverageLifecycleError(f"{service.name}: {stopped.get('status', 'NO_ARTIFACT')}")
                    content = await _download_artifact(service, coverage_run.id)
                    parsed = parse_coverage_report(service.tool, content.decode("utf-8-sig"))
                    if parsed["total_lines"] <= 0:
                        raise CoverageLifecycleError(f"{service.name}: 报告没有可统计的代码行，请核对部署版本和 classfiles")
                    output = ARTIFACT_ROOT / str(coverage_run.id)
                    output.mkdir(parents=True, exist_ok=True)
                    artifact_path = output / f"{service.name}{'.out' if service.tool == 'go_cover' else '.xml'}"
                    artifact_path.write_bytes(content)
                    report = CoverageReport(project_id=coverage_run.project_id, test_run_id=run_id,
                                            coverage_run_id=coverage_run.id, service_name=service.name,
                                            tool=CoverageTool(service.tool), language=service.language,
                                            source=CoverageSource.AUTO, storage_key=str(artifact_path),
                                            line_rate=parsed["line_rate"], branch_rate=parsed["branch_rate"],
                                            total_lines=parsed["total_lines"], covered_lines=parsed["covered_lines"],
                                            total_branches=parsed["total_branches"],
                                            covered_branches=parsed["covered_branches"],
                                            files_json=[{k: v for k, v in f.items() if k != "lines"}
                                                        for f in parsed["files"][:2000]],
                                            line_json={f["path"]: {"lines": f.get("lines", [])}
                                                       for f in parsed["files"][:2000]})
                    db.add(report)
                    await db.flush()
                    service.report_id = report.id
                    service.artifact_sha256 = hashlib.sha256(content).hexdigest()
                    service.status = "COMPLETED"
                    await db.commit()
                    results.append(parsed)
                except Exception as exc:
                    await db.rollback()
                    service = (await db.execute(select(CoverageService).where(CoverageService.id == service.id))).scalar_one()
                    coverage_run = (await db.execute(select(CoverageRun).where(CoverageRun.id == coverage_run.id))).scalar_one()
                    service.status = "NO_ARTIFACT" if "NO_ARTIFACT" in str(exc) else "FAILED"
                    service.error_message = str(exc)[:2000]
                    errors.append(f"{service.name}: {exc}")
                    await db.commit()
            services = (await db.execute(select(CoverageService).where(
                CoverageService.coverage_run_id == coverage_run.id))).scalars().all()
            coverage_run = (await db.execute(select(CoverageRun).where(
                CoverageRun.id == coverage_run.id))).scalar_one()
            if results:
                coverage_run.total_lines = sum(r["total_lines"] for r in results)
                coverage_run.covered_lines = sum(r["covered_lines"] for r in results)
                coverage_run.line_rate = round(100 * coverage_run.covered_lines / coverage_run.total_lines, 2)
                coverage_run.total_branches = sum(r["total_branches"] for r in results)
                coverage_run.covered_branches = sum(r["covered_branches"] for r in results)
                coverage_run.branch_rate = (round(100 * coverage_run.covered_branches / coverage_run.total_branches, 2)
                                            if coverage_run.total_branches else None)
            project = (await db.execute(select(Project).where(Project.id == coverage_run.project_id))).scalar_one()
            thresholds = ((project.source_config or {}).get("coverage_config") or {})
            gate_errors = coverage_threshold_errors(thresholds, coverage_run.line_rate,
                                                    coverage_run.branch_rate) if results else []
            errors.extend(gate_errors)
            coverage_run.status = ("FAILED" if gate_errors else
                                   "PARTIAL" if results and errors else
                                   "NO_ARTIFACT" if errors and all(s.status == "NO_ARTIFACT" for s in services) else
                                   "FAILED" if errors else "COMPLETED")
            coverage_run.error_message = "; ".join(errors)[:2000] if errors else None
            coverage_run.finished_at = datetime.utcnow()
            await db.commit()
            if errors and coverage_run.required:
                raise CoverageLifecycleError(coverage_run.error_message, required=True)
            return coverage_run

    @staticmethod
    async def abort(test_run_id: str, reason: str, cancelled: bool = False) -> None:
        """预检失败或取消时停止已启动的插桩实例，避免遗留后台服务。"""
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(CoverageRun).where(
                CoverageRun.test_run_id == uuid.UUID(test_run_id)))).scalar_one_or_none()
            if not row or row.status not in {"PREPARING", "RUNNING", "COLLECTING"}:
                return
            services = (await db.execute(select(CoverageService).where(
                CoverageService.coverage_run_id == row.id))).scalars().all()
            for service in services:
                if service.status == "RUNNING":
                    try:
                        await _agent_request(service, "stop", row.id)
                    except Exception:
                        pass
                    service.status = "FAILED"
            row.status = "CANCELLED" if cancelled else "FAILED"
            row.error_message = reason[:2000]
            row.finished_at = datetime.utcnow()
            await db.commit()
