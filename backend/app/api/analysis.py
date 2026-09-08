"""
代码解析 API 路由

提供代码分析接口：
- POST /run         — 通过本地绝对路径执行代码解析（兼容）
- POST /upload      — 上传代码文件或 zip 包执行代码解析（新增）
- GET  /{analysis_id} — 查询历史解析结果（从 TestRun 表查）

v1.3 改进：
- 新增 /upload 端点，避免用户手动输入容器内路径
- 支持多种输入：单文件 / 多文件 / zip 包
- 抽 `do_analyze` 公共函数：/run 与 /upload 共享同一份栈识别+接口提取+AI 语义逻辑
"""

import asyncio
import io
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TestRun
from app.modules.ai.model_router import ModelNotConfiguredError
from app.modules.code_analyzer import AICodeAnalyzer, APIExtractor, StackDetector
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 请求模型 ====================


class AnalysisRequest(BaseModel):
    """代码解析请求（兼容旧版：手动 path）"""

    local_path: str
    test_run_id: str | None = None  # 可选，关联测试任务


class RemoteAnalysisRequest(BaseModel):
    """远程仓库代码解析请求（Git / SVN）"""

    source_type: str = "github"  # github / svn
    repo_url: str | None = None
    branch: str = "main"
    commit_sha: str | None = None
    github_token: str | None = None
    svn_url: str | None = None
    svn_username: str | None = None
    svn_password: str | None = None
    svn_revision: str | None = None
    test_run_id: str | None = None


# ==================== 公共分析函数 ====================


async def do_analyze(project_path: str, db: AsyncSession, test_run_id: str | None) -> dict[str, Any]:
    """
    跑一次完整代码解析：栈识别 → 接口提取 → AI 语义分析。

    Args:
        project_path: 容器能读到的代码根目录绝对路径（也支持单文件自动降级）。
        db: 异步 DB session（用于写回 analysis_result）。
        test_run_id: 可选。若提供则把结果挂到 TestRun.analysis_result。

    Returns:
        analysis_result dict（与 /run /upload 一致）。
    """
    logger.info(f"Analysis request: path={project_path}, test_run_id={test_run_id}")

    # 1. 技术栈识别
    detector = StackDetector()
    stack_info = detector.detect(project_path)

    # 2. API 接口提取（栈未知时 extractor 内部会返回空列表，已为友好降级）
    extractor = APIExtractor()
    apis: list[dict[str, Any]] = extractor.extract(project_path, stack_info)

    # 3. AI 语义分析增强
    ai_analyzer = AICodeAnalyzer()
    try:
        ai_analysis = await ai_analyzer.analyze_project(project_path, apis, stack_info)
    except ModelNotConfiguredError:
        # 无 AI 模型：降级为规则化分析，保证返回可用结果而非 500
        logger.warning(
            "AI model not configured; falling back to rule-based analysis"
        )
        ai_analysis = ai_analyzer.rule_based_analysis(project_path, apis, stack_info)
    except Exception as e:
        logger.error(f"AI analysis failed (non-blocking): {e}", exc_info=True)
        ai_analysis = {
            "business_modules": [],
            "data_flow": {},
            "risk_areas": [],
            "api_analyses": [],
            "error": str(e),
        }

    # 4. 组装
    analysis_result: dict[str, Any] = {
        "tech_stack": stack_info,
        "apis": apis,
        "ai_analysis": ai_analysis,
        "total_apis": len(apis),
    }

    # 5. 写回 TestRun（可选）
    if test_run_id:
        try:
            result = await db.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
            )
            test_run = result.scalar_one_or_none()
            if test_run is not None:
                test_run.analysis_result = analysis_result
                await db.flush()
                logger.info(f"Analysis result saved to TestRun: {test_run_id}")
            else:
                logger.warning(f"TestRun not found: {test_run_id}, analysis result will not be persisted")
        except Exception as e:
            logger.error(f"Failed to update TestRun {test_run_id}: {e}", exc_info=True)

    logger.info(
        f"Analysis completed: stack={stack_info.get('stack')}, "
        f"apis={len(apis)}, modules={len(ai_analysis.get('business_modules', []))}, "
        f"risks={len(ai_analysis.get('risk_areas', []))}"
    )
    return analysis_result


# ==================== 文件落地辅助 ====================


# 容器内代码解析专用临时目录
CODE_ANALYSIS_DIR = os.path.join("/app", "data", "code_analysis")
os.makedirs(CODE_ANALYSIS_DIR, exist_ok=True)


def _materialize_uploaded_files(files: list[UploadFile]) -> Path:
    """把上传的多文件落盘到 ``/app/data/code_analysis/{uuid}/``，返回该目录绝对路径。

    - 多文件保留原始相对路径（如传 ``src/main.py`` 则落到目录下 ``src/main.py``）
    - 单文件、二进制 zip 都 OK
    - 目录创建后立刻 chdir-safe
    """
    if not files:
        raise HTTPException(400, "no files received")
    target = Path(CODE_ANALYSIS_DIR) / str(uuid.uuid4())
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        # filename 可能包含子目录路径
        rel = (f.filename or "unnamed").lstrip("/\\")
        # 防御 zip slip：reject 穿越
        if ".." in Path(rel).parts:
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as out_f:
            shutil.copyfileobj(f.file, out_f)
    return target


def _materialize_zip(file: UploadFile) -> Path:
    """解压 zip 到 ``CODE_ANALYSIS_DIR/{uuid}/``。"""
    target = Path(CODE_ANALYSIS_DIR) / str(uuid.uuid4())
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(file.file) as zf:
            for member in zf.namelist():
                # zip slip 防御
                member_path = (target / member).resolve()
                if not str(member_path).startswith(str(target.resolve())):
                    continue
                zf.extract(member, target)
    except zipfile.BadZipFile:
        raise HTTPException(400, "上传的文件不是合法 zip 包")
    return target


# ==================== API 路由 ====================


@router.post("/run")
async def run_analysis(
    req: AnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """通过手动指定容器内路径执行代码解析（向后兼容）。"""
    return {
        "code": 0,
        "data": await do_analyze(req.local_path, db, req.test_run_id),
        "message": "Analysis completed successfully",
    }


@router.post("/upload")
async def upload_analysis(
    files: list[UploadFile] = File(default=[], description="多个源文件（自动按相对路径组织）"),
    zip_file: UploadFile | None = File(default=None, description="可选：上传 zip 压缩包"),
    test_run_id: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    上传代码文件或 zip 包执行代码解析（推荐用法）。

    至少提供一个 ``files`` 或 ``zip_file``。
    解析完成后本次上传的目录会被保留（后续查询可复用）；如需清理可调 DELETE
    （暂未实现，可手动 docker exec rm -rf /app/data/code_analysis/{uuid}）。
    """
    if not files and not zip_file:
        raise HTTPException(
            400,
            "请至少提供一个 files 或 zip_file",
        )

    # 落地为目录
    target: Path
    if zip_file is not None:
        target = _materialize_zip(zip_file)
    if files:
        # 已 zip 落地 → target = zip root
        target = _materialize_uploaded_files(files)

    logger.info(
        f"Uploaded code materialized at: {target} "
        f"(files={len(files)}, zip={'yes' if zip_file else 'no'})"
    )

    # 调用公共解析
    return {
        "code": 0,
        "data": await do_analyze(str(target), db, test_run_id),
        "message": f"Analysis completed (uploaded to {target.name})",
    }


@router.post("/remote")
async def remote_analysis(
    req: RemoteAnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    通过远程 Git / SVN 仓库执行代码解析。

    在后端自动拉取代码至临时分析目录，并执行完整栈识别 + 接口提取 + AI 分析。
    """
    from app.modules.source import SourceAdapterFactory, SourceConfig, SourceType

    try:
        st = SourceType(req.source_type)
    except ValueError:
        raise HTTPException(
            400,
            f"Unsupported source_type: {req.source_type}. Supported: github, svn",
        )

    if st == SourceType.GITHUB and not req.repo_url:
        raise HTTPException(400, "repo_url is required for GitHub source")
    if st == SourceType.SVN and not req.svn_url:
        raise HTTPException(400, "svn_url is required for SVN source")

    # 临时工作目录
    temp_target = Path(CODE_ANALYSIS_DIR) / str(uuid.uuid4())
    temp_target.mkdir(parents=True, exist_ok=True)

    source_config = SourceConfig(
        source_type=st,
        repo_url=req.repo_url.strip() if req.repo_url else None,
        branch=req.branch.strip() if req.branch else "main",
        commit_sha=req.commit_sha.strip() if req.commit_sha else None,
        github_token=req.github_token.strip() if req.github_token else None,
        svn_url=req.svn_url.strip() if req.svn_url else None,
        svn_username=req.svn_username.strip() if req.svn_username else None,
        svn_password=req.svn_password.strip() if req.svn_password else None,
        svn_revision=req.svn_revision.strip() if req.svn_revision else None,
        workspace_dir=str(temp_target),
        incremental=False,
    )

    try:
        # fetch_code 是同步阻塞调用，在线程池中执行避免阻塞事件循环
        fetch_result = await asyncio.to_thread(SourceAdapterFactory.fetch_code, source_config)
        local_path = fetch_result.get("local_path", str(temp_target))
        logger.info(f"Remote source fetched successfully to {local_path}")
    except Exception as exc:
        logger.error(f"Remote fetch failed: {exc}", exc_info=True)
        raise HTTPException(400, f"代码拉取失败: {exc}")

    result = await do_analyze(local_path, db, req.test_run_id)
    return {
        "code": 0,
        "data": result,
        "meta": {
            "source_type": req.source_type,
            "repo_url": req.repo_url or req.svn_url,
            "branch": req.branch,
            "commit_sha": fetch_result.get("version_id"),
            "total_files": fetch_result.get("total_files", 0),
        },
        "message": "Remote analysis completed successfully",
    }


@router.post("/project/{project_id}")
async def project_analysis(
    project_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    针对系统内已有项目执行代码解析。

    - 若该项目已有拉取过的有效代码版本（ProjectCodeVersion），直接基于已落地的 local_path 秒级解析；
    - 若该项目尚未拉取代码，则自动使用该项目绑定的 source_config 拉取最新代码并解析。
    """
    from app.models.database import Project, ProjectCodeVersion
    from app.modules.source import SourceAdapterFactory, SourceConfig, SourceType
    from app.utils.crypto import decrypt_dict

    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")

    project = (await db.execute(select(Project).where(Project.id == pid))).scalar_one_or_none()
    if not project:
        raise HTTPException(404, f"Project not found: {project_id}")

    # 1. 优先寻找已有且目录存在的代码版本
    versions = (
        await db.execute(
            select(ProjectCodeVersion)
            .where(ProjectCodeVersion.project_id == pid)
            .order_by(ProjectCodeVersion.created_at.desc())
        )
    ).scalars().all()

    chosen_path: str | None = None
    matched_version = None
    for v in versions:
        if v.local_path and os.path.exists(v.local_path):
            chosen_path = v.local_path
            matched_version = v
            break

    # 2. 若没有现成版本，且项目有仓库配置，则自动拉取
    if not chosen_path:
        source_config_dict = decrypt_dict(project.source_config or {})
        st_val = (
            project.source_type.value
            if hasattr(project.source_type, "value")
            else str(project.source_type)
        )
        if st_val == "upload" and not source_config_dict.get("upload_file_path"):
            raise HTTPException(
                400,
                "该项目为本地上传类型，但尚未上传任何代码包，请先在「项目管理」上传代码包。",
            )

        try:
            st = SourceType(st_val)
        except ValueError:
            raise HTTPException(400, f"项目数据源类型无效: {st_val}")

        source_cfg = SourceConfig(
            source_type=st,
            repo_url=source_config_dict.get("repo_url"),
            branch=source_config_dict.get("branch") or "main",
            commit_sha=source_config_dict.get("commit_sha"),
            github_token=source_config_dict.get("github_token"),
            svn_url=source_config_dict.get("svn_url"),
            svn_username=source_config_dict.get("svn_username"),
            svn_password=source_config_dict.get("svn_password"),
            svn_revision=source_config_dict.get("svn_revision"),
            upload_file_path=source_config_dict.get("upload_file_path"),
            workspace_dir=f"/app/data/repos/{project.id}",
            incremental=True,
        )

        try:
            fetch_res = await asyncio.to_thread(SourceAdapterFactory.fetch_code, source_cfg)
            chosen_path = fetch_res.get("local_path", "")
        except Exception as exc:
            raise HTTPException(400, f"自动拉取项目代码失败: {exc}")

    if not chosen_path or not os.path.exists(chosen_path):
        raise HTTPException(400, "未能找到或拉取到有效的项目代码目录")

    result = await do_analyze(chosen_path, db, test_run_id=None)
    return {
        "code": 0,
        "data": result,
        "meta": {
            "project_id": str(project.id),
            "project_name": project.name,
            "source_type": (
                project.source_type.value
                if hasattr(project.source_type, "value")
                else str(project.source_type)
            ),
            "version_id": matched_version.version_id if matched_version else "latest",
            "local_path": chosen_path,
        },
        "message": f"Project {project.name} analysis completed successfully",
    }


@router.get("/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    查询历史解析结果。

    从 TestRun 表的 analysis_result 字段获取。
    """
    try:
        run_id = uuid.UUID(analysis_id)
    except ValueError:
        raise HTTPException(400, f"Invalid analysis_id format: {analysis_id}")

    result = await db.execute(select(TestRun).where(TestRun.id == run_id))
    test_run = result.scalar_one_or_none()

    if test_run is None:
        raise HTTPException(404, f"Analysis not found: {analysis_id}")

    analysis_result = test_run.analysis_result or {}

    return {
        "code": 0,
        "data": {
            "test_run_id": str(test_run.id),
            "status": test_run.status.value if test_run.status else None,
            "analysis_result": analysis_result,
        },
        "message": "success",
    }
