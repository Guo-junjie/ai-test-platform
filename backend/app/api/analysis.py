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
        raise
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
            shutil.copyfileobj(f.file, out)
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
