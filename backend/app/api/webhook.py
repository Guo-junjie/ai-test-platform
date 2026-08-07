"""
Webhook API 路由 — GitHub / SVN 自动触发代码拉取

GitHub Webhook：
- 验证 X-Hub-Signature-256 签名（HMAC SHA256）
- 解析 Push Event，提取 repo_url + branch + commit_sha
- 自动触发 SourceAdapterFactory.fetch_code()

SVN Post-commit Hook：
- 接收 HTTP 回调，解析 svn_url + revision
- 自动触发 SourceAdapterFactory.fetch_code()

当前同步执行拉取，后续 Phase 4 改为 Celery 异步任务。
"""

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import Project
from app.modules.source import SourceConfig, SourceAdapterFactory, SourceType
from app.utils.crypto import decrypt
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger()

router = APIRouter()


# ==================== GitHub Webhook ====================


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    GitHub Webhook 处理。

    1. 验证 Webhook Secret（HMAC SHA256 签名）
    2. 仅处理 push 事件
    3. 解析仓库 URL、分支、commit SHA
    4. 自动触发代码拉取
    """
    # 1. 读取原始请求体
    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty request body")

    # 2. 验证签名
    webhook_secret = settings.GITHUB_WEBHOOK_SECRET
    if webhook_secret:
        if not x_hub_signature_256:
            raise HTTPException(401, "Missing X-Hub-Signature-256 header")

        expected_signature = _compute_github_signature(webhook_secret, body)
        if not hmac.compare_digest(expected_signature, x_hub_signature_256):
            logger.warning("GitHub webhook signature verification failed")
            raise HTTPException(401, "Invalid webhook signature")
    else:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET not configured, skipping signature verification"
        )

    # 3. 解析事件类型
    if x_github_event != "push":
        logger.info(f"GitHub webhook ignored: event={x_github_event}")
        return {"code": 0, "message": f"Event {x_github_event} ignored"}

    # 4. 解析 Push Event
    payload: dict[str, Any] = json.loads(body)
    repo_url = payload.get("repository", {}).get("clone_url")
    if not repo_url:
        raise HTTPException(400, "Cannot extract repository URL from payload")

    ref = payload.get("ref", "refs/heads/main")
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else "main"
    commit_sha = payload.get("after")
    repo_name = payload.get("repository", {}).get("full_name", "unknown")

    logger.info(
        f"GitHub push event: repo={repo_name}, branch={branch}, commit={commit_sha[:8] if commit_sha else 'N/A'}"
    )

    # 5. 从数据库查找匹配的项目配置（获取 GitHub Token）
    github_token = await _lookup_github_token(db, repo_url)

    # 6. 触发代码拉取
    config = SourceConfig(
        source_type=SourceType.GITHUB,
        repo_url=repo_url,
        github_token=github_token,
        branch=branch,
        commit_sha=commit_sha,
        incremental=True,
    )

    # TODO: Phase 4 改为 Celery 异步任务
    try:
        result = SourceAdapterFactory.fetch_code(config)
        return {
            "code": 0,
            "data": {
                "event": "push",
                "repo": repo_name,
                "branch": branch,
                "commit": commit_sha,
                "result": {
                    "local_path": result.get("local_path"),
                    "version_id": result.get("version_id"),
                    "snapshot_id": result.get("snapshot_id"),
                    "total_files": result.get("total_files"),
                },
            },
            "message": "Webhook processed, code fetched successfully",
        }
    except Exception as e:
        logger.error(f"Webhook-triggered fetch failed: {e}")
        return {
            "code": 1,
            "data": {"event": "push", "repo": repo_name, "error": str(e)},
            "message": f"Webhook received but fetch failed: {e}",
        }


# ==================== SVN Webhook ====================


@router.post("/svn")
async def svn_webhook(request: Request):
    """
    SVN post-commit Hook 处理。

    接收 SVN 服务器 post-commit 钩子的 HTTP 回调，
    解析仓库 URL 和修订版本号，自动触发代码拉取。

    请求体格式（JSON）:
        {
            "svn_url": "https://svn.example.com/svn/project",
            "revision": "1234",
            "username": "optional_auth_user",
            "password": "optional_auth_pass"
        }
    """
    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty request body")

    try:
        payload: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body")

    svn_url = payload.get("svn_url")
    if not svn_url:
        raise HTTPException(400, "Missing required field: svn_url")

    revision = payload.get("revision")
    username = payload.get("username")
    password = payload.get("password")

    logger.info(
        f"SVN post-commit webhook: url={svn_url}, revision={revision}"
    )

    # 触发代码拉取
    config = SourceConfig(
        source_type=SourceType.SVN,
        svn_url=svn_url,
        svn_username=username,
        svn_password=password,
        svn_revision=revision,
        incremental=True,
    )

    # TODO: Phase 4 改为 Celery 异步任务
    try:
        result = SourceAdapterFactory.fetch_code(config)
        return {
            "code": 0,
            "data": {
                "svn_url": svn_url,
                "revision": revision,
                "result": {
                    "local_path": result.get("local_path"),
                    "version_id": result.get("version_id"),
                    "snapshot_id": result.get("snapshot_id"),
                    "total_files": result.get("total_files"),
                },
            },
            "message": "SVN webhook processed, code fetched successfully",
        }
    except Exception as e:
        logger.error(f"SVN webhook-triggered fetch failed: {e}")
        return {
            "code": 1,
            "data": {"svn_url": svn_url, "error": str(e)},
            "message": f"SVN webhook received but fetch failed: {e}",
        }


# ==================== 工具函数 ====================


async def _lookup_github_token(db: AsyncSession, repo_url: str) -> str:
    """
    从数据库查找与 repo_url 匹配的项目配置，解密获取 GitHub Token。

    遍历 projects 表中 source_type=github 的记录，
    匹配 source_config 中的 repo_url 字段。

    Args:
        db: 异步数据库会话。
        repo_url: GitHub 仓库 URL。

    Returns:
        解密后的 GitHub Token。未找到时返回空字符串。
    """
    from app.models.database import SourceType as ModelSourceType

    result = await db.execute(
        select(Project).where(
            Project.source_type == ModelSourceType.GITHUB,
            Project.is_active == True,  # noqa: E712
        )
    )
    projects = result.scalars().all()

    for proj in projects:
        source_config = proj.source_config or {}
        stored_url = source_config.get("repo_url", "")
        # 模糊匹配（去除 .git 后缀和尾部斜杠）
        if stored_url and _normalize_url(stored_url) == _normalize_url(repo_url):
            encrypted_token = source_config.get("github_token", "")
            if encrypted_token:
                try:
                    return decrypt(encrypted_token)
                except Exception as e:
                    logger.warning(f"Failed to decrypt GitHub token: {e}")
                    return encrypted_token  # 可能是明文
            return encrypted_token

    logger.warning(
        f"No matching GitHub project config found for {repo_url}. "
        f"Token will be empty — configure the source first."
    )
    return ""


def _normalize_url(url: str) -> str:
    """规范化 URL 用于比较（去除 .git 后缀和尾部斜杠，转小写）。"""
    return url.rstrip("/").lower().replace(".git", "")


def _compute_github_signature(secret: str, body: bytes) -> str:
    """
    计算 GitHub Webhook 签名（HMAC SHA256）。

    GitHub 发送的 X-Hub-Signature-256 格式为 "sha256=<hex>"。

    Args:
        secret: Webhook Secret。
        body: 原始请求体字节。

    Returns:
        签名字符串（"sha256=<hex>" 格式）。
    """
    signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"
