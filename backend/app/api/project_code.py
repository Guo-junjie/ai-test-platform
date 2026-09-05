"""项目代码版本 API —— 代码是项目的属性（R1 重构）

- POST /api/projects/{project_id}/code/upload   上传 zip/tar.gz → 解压 → 建版本
- POST /api/projects/{project_id}/code/fetch    从仓库拉取（缺省读项目 source_config）→ 建版本
- GET  /api/projects/{project_id}/code/versions 版本列表（最新在前）

测试任务创建时传 code_version_id 即可复用版本的 local_path，
pipeline 跳过各自的 fetch 步骤（代码从"任务输入"变为"项目属性"）。
"""
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    Project,
    ProjectCodeVersion,
    User,
    UserRole,
)
from app.models.database import SourceType as ModelSourceType
from app.modules.auth.dependencies import get_current_user, require_role
# 注意：SourceAdapterFactory 注册表用的是 app.modules.source.SourceType，
# 与 app.models.database.SourceType 是两个同名枚举，不能混用
from app.modules.source import SourceAdapterFactory, SourceConfig, SourceType
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 与 /api/upload 保持一致的保存目录与限制
UPLOAD_DIR = Path("/app/data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_SIZE = 500 * 1024 * 1024
SUPPORTED_EXTENSIONS = (".zip", ".tar.gz", ".tgz", ".tar")
CHUNK_SIZE = 1024 * 1024


# ==================== 请求模型 ====================


class CodeFetchRequest(BaseModel):
    """仓库拉取请求 —— 字段缺省时回退到项目 source_config。"""

    repo_url: str | None = None
    branch: str | None = None
    github_token: str | None = None
    svn_url: str | None = None
    svn_username: str | None = None
    svn_password: str | None = None
    commit_sha: str | None = None
    note: str | None = None


# ==================== 工具函数 ====================


def _version_to_dict(v: ProjectCodeVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "project_id": str(v.project_id),
        "source_type": v.source_type.value if v.source_type else None,
        "version_id": v.version_id,
        "branch": v.branch,
        "commit_message": v.commit_message,
        "local_path": v.local_path,
        "snapshot_id": v.snapshot_id,
        "total_files": v.total_files or 0,
        "note": v.note,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


async def _require_project(project_id: str, db: AsyncSession) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, f"Invalid project_id: {project_id}")
    proj = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, f"Project not found: {project_id}")
    return proj


# ==================== 路由 ====================


@router.post("/{project_id}/code/upload")
async def upload_project_code(
    project_id: str,
    file: UploadFile = File(...),
    note: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """上传代码压缩包 → 解压 → 登记为项目代码版本。"""
    proj = await _require_project(project_id, db)

    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(400, f"不支持的文件格式，仅支持 {SUPPORTED_EXTENSIONS}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = UPLOAD_DIR / f"{timestamp}_{filename}"
    total_size = 0
    try:
        with open(save_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    f.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(413, f"文件过大，上限 {MAX_UPLOAD_SIZE // 1024 // 1024}MB")
                f.write(chunk)
    finally:
        await file.close()

    try:
        result = SourceAdapterFactory.fetch_code(
            SourceConfig(source_type=SourceType.UPLOAD, upload_file_path=str(save_path))
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        save_path.unlink(missing_ok=True)
        logger.error(f"Project code upload failed: {e}", exc_info=True)
        raise HTTPException(500, f"代码解压失败: {e}")

    version = ProjectCodeVersion(
        project_id=proj.id,
        source_type=ModelSourceType.UPLOAD,
        version_id=result.get("version_id") or f"upload_{timestamp}",
        local_path=result.get("local_path", ""),
        snapshot_id=result.get("snapshot_id"),
        total_files=result.get("total_files", 0),
        note=note or filename,
        created_by=current_user.id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    logger.info(f"Project code version created: project={proj.id} version={version.id}")
    return {"code": 0, "data": _version_to_dict(version), "message": "created"}


@router.post("/{project_id}/code/fetch")
async def fetch_project_code(
    project_id: str,
    req: CodeFetchRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER, UserRole.DEVELOPER)),
    db: AsyncSession = Depends(get_db_session),
):
    """从仓库拉取代码 → 登记为项目代码版本。

    仓库参数缺省时回退到项目的 source_config（数据源管理页配置的仓库）。
    """
    proj = await _require_project(project_id, db)
    cfg = proj.source_config or {}

    # 未提供任何仓库信息且项目配置里也没有 → 明确引导，而不是抛 500 裸错误
    has_repo_info = bool(
        req.repo_url or req.svn_url or cfg.get("repo_url") or cfg.get("svn_url")
    )
    if not has_repo_info:
        raise HTTPException(
            400,
            f"项目「{proj.name}」尚未配置仓库地址（当前代码来源：{proj.source_type.value if proj.source_type else '未知'}）。"
            "请先在项目详情点「修改代码来源」填写 GitHub/SVN 仓库地址，再执行拉取。",
        )

    source_type = SourceType.GITHUB if (req.repo_url or cfg.get("repo_url")) else SourceType.SVN
    if req.svn_url or cfg.get("svn_url"):
        source_type = SourceType.SVN

    config = SourceConfig(
        source_type=source_type,
        repo_url=req.repo_url or cfg.get("repo_url"),
        github_token=req.github_token or cfg.get("github_token") or "",
        branch=req.branch or cfg.get("branch") or "main",
        commit_sha=req.commit_sha,
        svn_url=req.svn_url or cfg.get("svn_url"),
        svn_username=req.svn_username or cfg.get("svn_username"),
        svn_password=req.svn_password or cfg.get("svn_password"),
        svn_revision=req.commit_sha,
        incremental=False,
    )

    # 二次校验：避免适配器抛出裸错误（如 svn_url is required）
    if source_type == SourceType.GITHUB and not config.repo_url:
        raise HTTPException(400, "缺少 GitHub 仓库地址（repo_url），请先在「修改代码来源」中填写")
    if source_type == SourceType.SVN and not config.svn_url:
        raise HTTPException(400, "缺少 SVN 地址（svn_url），请先在「修改代码来源」中填写")

    try:
        result = SourceAdapterFactory.fetch_code(config)
    except ValueError as e:
        raise HTTPException(400, f"仓库配置有误：{e}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Project code fetch failed: {e}", exc_info=True)
        raise HTTPException(500, f"仓库拉取失败: {e}")

    local_path = result.get("local_path", "")
    if not local_path or not Path(local_path).exists():
        raise HTTPException(500, "拉取完成但代码目录不存在")

    version = ProjectCodeVersion(
        project_id=proj.id,
        source_type=ModelSourceType(source_type.value),
        version_id=result.get("version_id") or req.commit_sha or datetime.now().strftime("%Y%m%d%H%M%S"),
        branch=config.branch,
        commit_message=result.get("commit_message"),
        local_path=local_path,
        snapshot_id=result.get("snapshot_id"),
        total_files=result.get("total_files", 0),
        note=req.note,
        created_by=current_user.id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    logger.info(f"Project code version fetched: project={proj.id} version={version.id}")
    return {"code": 0, "data": _version_to_dict(version), "message": "created"}


@router.get("/{project_id}/code/versions")
async def list_project_code_versions(
    project_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """项目的代码版本列表（最新在前）。"""
    proj = await _require_project(project_id, db)
    rows = (
        await db.execute(
            select(ProjectCodeVersion)
            .where(ProjectCodeVersion.project_id == proj.id)
            .order_by(ProjectCodeVersion.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return {
        "code": 0,
        "data": {"list": [_version_to_dict(v) for v in rows], "total": len(rows)},
        "message": "success",
    }
