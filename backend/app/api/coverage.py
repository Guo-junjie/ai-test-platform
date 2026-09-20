"""
代码覆盖率 API（能力11：行/分支覆盖率采集与展示）

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/coverage" 注册。

提供：
- POST /upload   上传覆盖率报告 XML（coverage.py / jacoco / istanbul / cobertura），解析并入库
- GET  /         按项目 / 测试任务列出覆盖率报告
- GET  /{id}     报告详情（含文件级明细）
- DELETE /{id}   删除报告

⚠ 历史 Bug：4 个端点原本误用 ``async with get_db_session() as db:``，
``get_db_session`` 是 FastAPI Depends 注入函数（AsyncGenerator）不是
async-context-manager，会抛 ``TypeError: 'async_generator' object does
not support the asynchronous context manager protocol``。全部改为：
``db: AsyncSession = Depends(get_db_session)``。
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AuditLog,
    CoverageReport,
    CoverageRun,
    CoverageService,
    CoverageSource,
    CoverageTool,
    Project,
    TestRun,
    User,
    UserRole,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.coverage.parser import parse_coverage_report
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _is_legacy_estimate(report: CoverageReport) -> bool:
    """隐藏旧版本把接口执行数伪装为代码行的历史报告，不删除原始数据。"""
    return report.source == CoverageSource.AUTO and any(
        item.get("path") == "api/endpoints_tested.py"
        for item in (report.files_json or [])
    )

COV_DIR = os.path.join("/app", "data", "uploads", "coverage")
os.makedirs(COV_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_EXT = {".xml", ".out"}


class DeleteResponse(BaseModel):
    pass


# ==================== 接口 ====================


@router.post("")
async def upload_coverage(
    project_id: str = Form(...),
    tool: str = Form(...),  # coverage.py / jacoco / istanbul / cobertura
    language: str = Form(None),  # python / java / javascript ...
    test_run_id: str = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """上传 JaCoCo/Cobertura XML 或 Go coverprofile 并解析入库。"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(400, "project_id 格式错误") from exc
    proj = (
        await db.execute(select(Project).where(Project.id == project_uuid))
    ).scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "项目不存在")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "仅支持 .xml 或 Go coverprofile .out 报告")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "文件超过 20MB 限制")
    try:
        raw_xml = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "报告不是 UTF-8 文本；JaCoCo .exec 需先转换为 jacoco.xml")

    # 解析
    try:
        result = parse_coverage_report(tool, raw_xml)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if tool == "go_cover" and not raw_xml.lstrip().startswith("mode:"):
        raise HTTPException(400, "选择 Go coverprofile 时请上传 go test -coverprofile 生成的 .out 文件")

    # 工具枚举
    actual_tool = "go_cover" if raw_xml.lstrip().startswith("mode:") else (
        "jacoco" if "<report" in raw_xml else tool
    )
    try:
        tool_enum = CoverageTool(actual_tool)
    except ValueError:
        raise HTTPException(400, f"不支持的覆盖率工具: {tool}")

    run_uuid = None
    test_run = None
    coverage_run = None
    if test_run_id:
        try:
            run_uuid = uuid.UUID(test_run_id)
        except ValueError:
            raise HTTPException(400, "test_run_id 格式错误")
        test_run = (
            await db.execute(select(TestRun).where(TestRun.id == run_uuid))
        ).scalar_one_or_none()
        if not test_run:
            raise HTTPException(404, "测试任务不存在")
        if test_run.project_id != project_uuid:
            raise HTTPException(400, "测试任务与覆盖率项目不一致")
        coverage_run = (
            await db.execute(select(CoverageRun).where(CoverageRun.test_run_id == run_uuid))
        ).scalar_one_or_none()
        if coverage_run and coverage_run.status in {"PREPARING", "RUNNING", "COLLECTING"}:
            raise HTTPException(409, "该测试任务正在自动采集覆盖率，请等待采集完成后再上传报告")
        if not coverage_run:
            coverage_run = CoverageRun(
                test_run_id=run_uuid,
                project_id=project_uuid,
                commit_sha=test_run.commit_sha,
                mode="upload",
                status="CREATED",
                required=False,
                started_at=datetime.utcnow(),
            )
            db.add(coverage_run)
            await db.flush()

    # 所有项目与运行关联校验通过后再落盘，避免无效请求留下孤儿文件。
    stored_name = f"{uuid.uuid4()}{ext}"
    storage_path = os.path.join(COV_DIR, stored_name)
    with open(storage_path, "wb") as f:
        f.write(content)

    report = CoverageReport(
        project_id=project_uuid,
        test_run_id=run_uuid,
        coverage_run_id=coverage_run.id if coverage_run else None,
        uploader_id=current_user.id,
        tool=tool_enum,
        language=language or ("go" if actual_tool == "go_cover" else "java" if actual_tool == "jacoco" else None),
        source=CoverageSource.UPLOAD,
        line_rate=result["line_rate"],
        branch_rate=result["branch_rate"],
        total_lines=result["total_lines"],
        covered_lines=result["covered_lines"],
        total_branches=result["total_branches"],
        covered_branches=result["covered_branches"],
        # P1：files_json 只存文件级汇总（去掉 lines 字段，减小体积）；行级明细放 line_json
        files_json=[
            {k: v for k, v in f.items() if k != "lines"}
            for f in result["files"][:2000]
        ],
        # P1：line_json = {path: {lines: [...]}}，供前端源码高亮按需加载
        line_json={
            f["path"]: {"lines": f.get("lines", [])}
            for f in result["files"][:2000]
        },
        storage_key=storage_path,
    )
    db.add(report)
    if coverage_run:
        coverage_run.mode = "upload"
        coverage_run.status = "COMPLETED"
        coverage_run.error_message = None
        coverage_run.total_lines = result["total_lines"]
        coverage_run.covered_lines = result["covered_lines"]
        coverage_run.line_rate = result["line_rate"]
        coverage_run.total_branches = result["total_branches"]
        coverage_run.covered_branches = result["covered_branches"]
        coverage_run.branch_rate = result["branch_rate"]
        coverage_run.started_at = coverage_run.started_at or datetime.utcnow()
        coverage_run.finished_at = datetime.utcnow()
    await db.commit()
    await db.refresh(report)

    return {
        "code": 0,
        "data": {
            "id": str(report.id),
            "coverage_run_id": str(coverage_run.id) if coverage_run else None,
            "test_run_id": str(run_uuid) if run_uuid else None,
            "coverage_status": coverage_run.status if coverage_run else None,
            "tool": report.tool.value,
            "line_rate": report.line_rate,
            "branch_rate": report.branch_rate,
            "total_lines": report.total_lines,
            "covered_lines": report.covered_lines,
            "total_branches": report.total_branches,
            "covered_branches": report.covered_branches,
            "file_count": len(result["files"]),
        },
        "message": "覆盖率报告已解析入库",
    }


@router.get("")
async def list_coverage(
    project_id: str | None = None,
    test_run_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """按项目 / 测试任务列出覆盖率报告（test_run_id 可单独使用，报告页互链）。"""
    if not project_id and not test_run_id:
        raise HTTPException(400, "project_id 与 test_run_id 至少提供一个")
    stmt = select(CoverageReport)
    if project_id:
        stmt = stmt.where(CoverageReport.project_id == uuid.UUID(project_id))
    if test_run_id:
        stmt = stmt.where(CoverageReport.test_run_id == uuid.UUID(test_run_id))
    stmt = stmt.order_by(CoverageReport.created_at.desc())
    rows = [r for r in (await db.execute(stmt)).scalars().all() if not _is_legacy_estimate(r)]
    return {
        "code": 0,
        "data": [
            {
                "id": str(r.id),
                "tool": r.tool.value,
                "language": r.language,
                "source": r.source.value,
                "line_rate": r.line_rate,
                "branch_rate": r.branch_rate,
                "total_lines": r.total_lines,
                "covered_lines": r.covered_lines,
                "total_branches": r.total_branches,
                "covered_branches": r.covered_branches,
                "test_run_id": str(r.test_run_id) if r.test_run_id else None,
                "coverage_run_id": str(r.coverage_run_id) if r.coverage_run_id else None,
                "service_name": r.service_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "message": "success",
    }


@router.get("/{report_id}")
async def get_coverage(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """覆盖率报告详情（含文件级明细）。"""
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")
    return {
        "code": 0,
        "data": {
            "id": str(r.id),
            "tool": r.tool.value,
            "language": r.language,
            "source": r.source.value,
            "line_rate": r.line_rate,
            "branch_rate": r.branch_rate,
            "total_lines": r.total_lines,
            "covered_lines": r.covered_lines,
            "total_branches": r.total_branches,
            "covered_branches": r.covered_branches,
            "files": r.files_json or [],
            "test_run_id": str(r.test_run_id) if r.test_run_id else None,
            "coverage_run_id": str(r.coverage_run_id) if r.coverage_run_id else None,
            "service_name": r.service_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        },
        "message": "success",
    }


@router.delete("/{report_id}")
async def delete_coverage(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """删除覆盖率报告。"""
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")
    await db.delete(r)
    await db.commit()
    try:
        if r.storage_key and os.path.exists(r.storage_key):
            os.remove(r.storage_key)
    except Exception:  # noqa: BLE001
        pass
    return {"code": 0, "data": None, "message": "已删除"}


# ==================== P1：覆盖率看板端点 ====================


@router.get("/dashboard/{project_id}")
async def coverage_dashboard(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：项目级聚合 —— 最新报告 + 较上次差值 + 文件数 / 报告数。"""
    # 最近两份报告（最新 + 上次），用于计算「较上次差值」
    stmt = (
        select(CoverageReport)
        .where(CoverageReport.project_id == project_id)
        .order_by(CoverageReport.created_at.desc())
    )
    rows = [r for r in (await db.execute(stmt)).scalars().all() if not _is_legacy_estimate(r)]
    if not rows:
        return {
            "code": 0,
            "data": {
                "latest": None,
                "diff_line_rate": 0.0,
                "diff_branch_rate": 0.0,
                "report_count": 0,
                "file_count": 0,
            },
            "message": "暂无覆盖率报告",
        }
    report_count = len(rows)
    rows = rows[:2]
    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    files = latest.files_json or []
    return {
        "code": 0,
        "data": {
            "latest": {
                "id": str(latest.id),
                "tool": latest.tool.value,
                "language": latest.language,
                "source": latest.source.value,
                "line_rate": latest.line_rate or 0.0,
                "branch_rate": latest.branch_rate,
                "total_lines": latest.total_lines or 0,
                "covered_lines": latest.covered_lines or 0,
                "total_branches": latest.total_branches or 0,
                "covered_branches": latest.covered_branches or 0,
                "created_at": latest.created_at.isoformat() if latest.created_at else None,
            },
            "diff_line_rate": round(
                (latest.line_rate or 0.0) - (prev.line_rate or 0.0), 2
            ) if prev else 0.0,
            "diff_branch_rate": round(
                (latest.branch_rate or 0.0) - (prev.branch_rate or 0.0), 2
            ) if prev and latest.branch_rate is not None and prev.branch_rate is not None else None,
            "report_count": report_count,
            "file_count": len(files),
        },
        "message": "success",
    }


@router.get("/trend/{project_id}")
async def coverage_trend(
    project_id: str,
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：项目覆盖率趋势（最近 N 天，按 created_at 升序）。"""
    days = max(1, min(int(days), 365))
    cutoff = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(CoverageReport)
        .where(
            CoverageReport.project_id == project_id,
            CoverageReport.created_at >= cutoff,
        )
        .order_by(CoverageReport.created_at.asc())
    )
    rows = [r for r in (await db.execute(stmt)).scalars().all() if not _is_legacy_estimate(r)]
    return {
        "code": 0,
        "data": {
            "labels": [
                r.created_at.strftime("%m-%d %H:%M") if r.created_at else ""
                for r in rows
            ],
            "line_rate": [float(r.line_rate or 0.0) for r in rows],
            "branch_rate": [float(r.branch_rate) if r.branch_rate is not None else None for r in rows],
        },
        "message": "success",
    }


@router.get("/files/{report_id}")
async def coverage_files(
    report_id: str,
    sort: str = "rate",  # rate | path | total_lines
    order: str = "asc",  # asc | desc
    page: int = 1,
    page_size: int = 50,
    q: str | None = None,  # 文件名模糊搜索
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：报告的文件清单（支持搜索 / 排序 / 分页）。"""
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")

    files = list(r.files_json or [])
    # 模糊搜索
    if q:
        ql = q.lower()
        files = [f for f in files if ql in (f.get("path") or "").lower()]
    # 排序
    key_map = {
        "rate": lambda f: float(f.get("line_rate") or 0.0),
        "path": lambda f: f.get("path") or "",
        "total_lines": lambda f: int(f.get("total_lines") or 0),
    }
    key_fn = key_map.get(sort, key_map["rate"])
    files.sort(key=key_fn, reverse=(order == "desc"))

    # 分页
    total = len(files)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))
    start = (page - 1) * page_size
    page_files = files[start : start + page_size]
    return {
        "code": 0,
        "data": {
            "files": page_files,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.get("/source/{report_id}")
async def coverage_source(
    report_id: str,
    file: str,  # 文件路径
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """P1 看板：单文件的行级覆盖率明细（供源码高亮用）。

    Args:
        file: 文件路径（URL ?file=xxx 传入，路径含 / 需前端 encodeURIComponent）
    """
    from urllib.parse import unquote
    file_path = unquote(file)
    r = (
        await db.execute(select(CoverageReport).where(CoverageReport.id == report_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "覆盖率报告不存在")

    line_data = (r.line_json or {}).get(file_path) or {}
    files_list = r.files_json or []
    file_summary = next(
        (f for f in files_list if f.get("path") == file_path), None
    )
    if not file_summary:
        raise HTTPException(404, f"该报告不含此文件: {file_path}")
    return {
        "code": 0,
        "data": {
            "path": file_path,
            "line_rate": file_summary.get("line_rate"),
            "branch_rate": file_summary.get("branch_rate"),
            "total_lines": file_summary.get("total_lines"),
            "covered_lines": file_summary.get("covered_lines"),
            "lines": line_data.get("lines", []),
        },
        "message": "success",
    }


# ==================== 探针探测、即时采集与项目配置 ====================


class ProbeCoverageRequest(BaseModel):
    strategy: str = "remote_tcp"  # remote_tcp | http_dump
    host: str | None = None
    port: int | None = 6300
    dump_url: str | None = None


@router.post("/probe")
async def probe_coverage(
    req: ProbeCoverageRequest,
    current_user: User = Depends(get_current_user),
):
    """测试远程覆盖率探针（JaCoCo TCP / HTTP Dump）连通性。"""
    from app.modules.coverage.collector import probe_coverage_target

    res = await probe_coverage_target(
        strategy=req.strategy,
        host=req.host or "",
        port=req.port or 6300,
        dump_url=req.dump_url or "",
    )
    return {"code": 0, "data": res, "message": "success"}


class CollectCoverageRequest(BaseModel):
    project_id: str
    test_run_id: str | None = None


@router.post("/collect")
async def trigger_collect_coverage(
    req: CollectCoverageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """即时触发项目的代码覆盖率采集。"""
    from app.modules.coverage.collector import collect_coverage_for_run

    report_id = await collect_coverage_for_run(
        test_run_id=req.test_run_id or "",
        project_id=req.project_id,
    )
    if not report_id:
        raise HTTPException(422, "未采集到真实覆盖率报告。请配置返回 XML/Go coverprofile 的 HTTP 地址，或在关联测试任务的代码工作空间生成报告；普通服务 URL 不提供代码覆盖率。")
    return {
        "code": 0,
        "data": {"report_id": report_id},
        "message": "覆盖率采集成功并已生成最新报告",
    }


class UpdateCoverageConfigRequest(BaseModel):
    enabled: bool = True
    tool: str = "jacoco"
    strategy: str = "remote_tcp"
    probe_host: str | None = None
    probe_port: int | None = 6300
    dump_url: str | None = None
    required: bool = False
    min_line_rate: float | None = Field(default=None, ge=0, le=100)
    min_branch_rate: float | None = Field(default=None, ge=0, le=100)
    services: list[dict[str, Any]] = Field(default_factory=list)


class ProbeAgentRequest(BaseModel):
    name: str
    agent_url: str
    token_env: str
    language: str = "python"
    tool: str = "coverage.py"


@router.post("/probe-agent")
async def probe_agent_config(
    req: ProbeAgentRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
):
    """校验 Agent 凭据、服务白名单与代码目录；不会启动被测服务。"""
    from app.modules.coverage.manager import _agent_request, validate_agent_service

    try:
        config = validate_agent_service(req.model_dump())
        service = CoverageService(name=config["name"], agent_url=config["agent_url"],
                                  token_env=config["token_env"], language=config["language"],
                                  tool=config["tool"])
        result = await _agent_request(service, "prepare", uuid.uuid4())
        return {"code": 0, "data": result.json(), "message": "Agent 配置可用"}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, f"Agent 预检失败: {exc}") from exc


@router.put("/projects/{project_id}/config")
async def update_project_coverage_config(
    project_id: str,
    req: UpdateCoverageConfigRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
):
    """更新项目的覆盖率探针配置。"""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    proj = (await db.execute(select(Project).where(Project.id == p_uuid))).scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "项目不存在")

    if req.enabled and req.strategy == "agent" and not req.services:
        raise HTTPException(422, "自动 Agent 采集需要至少配置一个服务")
    if req.enabled and req.required and not req.services:
        raise HTTPException(422, "严格模式需要至少配置一个 Agent 服务")

    if req.services:
        from app.modules.coverage.manager import validate_agent_service

        try:
            services = [validate_agent_service(item) for item in req.services]
            if len({item["name"] for item in services}) != len(services):
                raise ValueError("覆盖率服务名不能重复")
            if len(services) > 1 and sum(item["primary"] for item in services) != 1:
                raise ValueError("多服务配置必须指定唯一 primary 测试入口")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        services = []

    cfg = dict(proj.source_config or {})
    cfg["coverage_config"] = req.model_dump()
    cfg["coverage_config"]["services"] = services
    cfg["coverage_enabled"] = req.enabled
    proj.source_config = cfg
    await db.commit()
    return {
        "code": 0,
        "data": cfg["coverage_config"],
        "message": "覆盖率配置已更新",
    }


@router.get("/runs/{test_run_id}")
async def get_coverage_run(
    test_run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """查询一次自动化测试的覆盖率生命周期及每个服务的采集结果。"""
    try:
        run_uuid = uuid.UUID(test_run_id)
    except ValueError as exc:
        raise HTTPException(400, "test_run_id 格式错误") from exc
    run = (await db.execute(select(CoverageRun).where(CoverageRun.test_run_id == run_uuid))).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "该测试任务没有 Coverage Run")
    services = (await db.execute(select(CoverageService).where(
        CoverageService.coverage_run_id == run.id).order_by(CoverageService.name))).scalars().all()
    return {"code": 0, "data": {
        "id": str(run.id), "test_run_id": str(run.test_run_id),
        "project_id": str(run.project_id), "commit_sha": run.commit_sha,
        "status": run.status, "required": run.required,
        "error_message": run.error_message,
        "line_rate": run.line_rate, "branch_rate": run.branch_rate,
        "total_lines": run.total_lines, "covered_lines": run.covered_lines,
        "total_branches": run.total_branches, "covered_branches": run.covered_branches,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "services": [{"name": item.name, "language": item.language,
                      "primary": item.primary, "deployed_commit_sha": item.deployed_commit_sha,
                      "status": item.status, "error_message": item.error_message,
                      "report_id": str(item.report_id) if item.report_id else None,
                      "artifact_sha256": item.artifact_sha256}
                     for item in services],
    }, "message": "success"}


@router.get("/projects/{project_id}/runs")
async def list_coverage_runs(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """项目最近的覆盖率会话；即使没有报告也显示 FAILED/NO_ARTIFACT。"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(400, "project_id 格式错误") from exc
    rows = (await db.execute(select(CoverageRun).where(CoverageRun.project_id == project_uuid)
                             .order_by(CoverageRun.created_at.desc()).limit(30))).scalars().all()
    return {"code": 0, "data": [{
        "id": str(row.id), "test_run_id": str(row.test_run_id), "status": row.status,
        "required": row.required, "line_rate": row.line_rate,
        "total_lines": row.total_lines, "covered_lines": row.covered_lines,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows], "message": "success"}
