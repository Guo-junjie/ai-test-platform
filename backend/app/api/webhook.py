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

    # 匹配到项目且开启 auto_trigger 时，直接触发完整测试流水线
    # （pipeline 第一步就是拉代码，此处跳过手工 fetch 避免重复）
    trigger_project = await _find_project_by_repo(db, repo_url)
    if trigger_project is not None and _auto_trigger_matches(trigger_project, branch):
        run_id = await _dispatch_pipeline_for_project(
            db, trigger_project, branch=branch, commit_sha=commit_sha
        )
        if run_id:
            return {
                "code": 0,
                "data": {
                    "event": "push", "repo": repo_name, "branch": branch,
                    "commit": commit_sha, "triggered_test_run_id": run_id,
                },
                "message": "push 已自动触发完整测试流水线",
            }

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


# ==================== CI/CD 双向集成 ====================


async def _find_project_by_ci_token(db, token: str):
    """按 CI Token（AES 加密存储）匹配项目。项目量级小，遍历比对可接受。"""
    from app.utils.crypto import decrypt

    result = await db.execute(select(Project).where(Project.is_active == True))  # noqa: E712
    for proj in result.scalars().all():
        enc = (proj.source_config or {}).get("ci_token_encrypted") or ""
        if not enc:
            continue
        try:
            if hmac.compare_digest(decrypt(enc), token):
                return proj
        except Exception:  # noqa: BLE001 - 解密失败跳过该项目
            continue
    return None


async def _find_project_by_repo(db, repo_url: str):
    result = await db.execute(select(Project).where(Project.is_active == True))  # noqa: E712
    for proj in result.scalars().all():
        stored = (proj.source_config or {}).get("repo_url") or ""
        if stored and _normalize_url(stored) == _normalize_url(repo_url):
            return proj
    return None


def _auto_trigger_matches(project: Project, branch: str) -> bool:
    trigger = (project.source_config or {}).get("auto_trigger") or {}
    if not trigger.get("enabled"):
        return False
    branches = trigger.get("branches") or []
    return not branches or branch in branches


async def _dispatch_pipeline_for_project(
    db, project: Project, branch: str | None = None, commit_sha: str | None = None,
) -> str | None:
    """基于项目数据源配置创建 TestRun 并派发完整流水线，返回 test_run_id。"""
    import uuid as _uuid
    from datetime import datetime as _dt

    from app.celery_app import celery_app as _celery
    from app.models.database import TestRun, TestStatus
    from app.utils.redis_client import get_async_redis

    cfg = project.source_config or {}
    repo_url = cfg.get("repo_url") or ""

    run = TestRun(
        id=_uuid.uuid4(),
        project_id=project.id,
        user_id=project.owner_id,
        source_type=project.source_type,
        source_ref=repo_url,
        branch=branch or cfg.get("branch") or "main",
        commit_sha=commit_sha,
        status=TestStatus.PULLING,
        progress=0,
        started_at=_dt.utcnow(),
    )
    db.add(run)
    await db.flush()
    await db.commit()
    run_id = str(run.id)

    req_dict = {
        "source_type": project.source_type.value if project.source_type else "github",
        "repo_url": repo_url,
        "branch": run.branch,
        "commit_sha": commit_sha,
        "project_id": str(project.id),
    }
    async_result = _celery.send_task(
        "app.modules.pipeline.run_test_pipeline", args=[run_id, req_dict]
    )
    try:
        redis = await get_async_redis()
        await redis.set(f"task:celery:{run_id}", async_result.id, ex=7 * 24 * 3600)
    except Exception:  # noqa: BLE001
        pass
    logger.info(f"CI triggered pipeline for project {project.id}: run={run_id}")
    return run_id


@router.post("/trigger")
async def ci_trigger(request: Request, db: AsyncSession = Depends(get_db_session)):
    """通用 CI 触发入口（Jenkins / GitLab CI / GitHub Actions 一行 curl 调用）。

    鉴权：请求头 X-CI-Token: <项目 Token>（平台「数据源管理 → CI/CD 集成」生成）。
    Body 可选：{"branch": "main", "commit_sha": "..."}；缺省用项目数据源配置。
    返回 test_run_id，CI 轮询 /api/webhook/ci-result/{run_id} 做卡点判断。
    """
    token = request.headers.get("X-CI-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-CI-Token header")
    project = await _find_project_by_ci_token(db, token)
    if project is None:
        raise HTTPException(401, "Invalid CI token")

    branch = commit_sha = None
    body = await request.body()
    if body:
        try:
            payload = json.loads(body)
            branch = payload.get("branch")
            commit_sha = payload.get("commit_sha")
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON body")

    run_id = await _dispatch_pipeline_for_project(db, project, branch, commit_sha)
    return {
        "code": 0,
        "data": {
            "test_run_id": run_id,
            "project_id": str(project.id),
            "ci_result_url": f"/api/webhook/ci-result/{run_id}",
        },
        "message": "测试流水线已触发",
    }


@router.get("/ci-result/{run_id}")
async def ci_result(
    run_id: str,
    request: Request,
    token: str = None,  # noqa: ANN001
    db: AsyncSession = Depends(get_db_session),
):
    """CI 结果查询 + 门禁判定（供流水线卡点，X-CI-Token 头或 ?token= 鉴权）。

    门禁未配置/报告未生成时退化为通过率判定（≥80% 视为通过）。
    """
    auth = request.headers.get("X-CI-Token") or token
    if not auth:
        raise HTTPException(401, "Missing token (X-CI-Token header or ?token=)")
    project = await _find_project_by_ci_token(db, auth)
    if project is None:
        raise HTTPException(401, "Invalid CI token")

    import uuid as _uuid

    try:
        rid = _uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    from app.models.database import TestResult, TestReport, TestRun

    run = (
        await db.execute(select(TestRun).where(TestRun.id == rid))
    ).scalar_one_or_none()
    if run is None or run.project_id != project.id:
        raise HTTPException(404, "Test run not found for this project")

    results = (
        await db.execute(select(TestResult).where(TestResult.test_run_id == rid))
    ).scalars().all()
    total = len(results)
    passed = sum(1 for r in results if r.is_passed)
    failed = total - passed
    pass_rate = round(passed * 100.0 / total, 1) if total else 0.0

    report = (
        await db.execute(select(TestReport).where(TestReport.test_run_id == rid))
    ).scalar_one_or_none()
    gate_passed, reasons, score = None, [], None
    if report is not None:
        score = report.quality_score
        gate_passed = bool(report.gate_passed) if report.gate_passed is not None else None
        details = report.gate_details or {}
        reasons = [v.get("message", str(v)) for v in details.get("violations", [])]

    status = run.status.value if run.status else "unknown"
    ci_passed = (status == "completed") and (gate_passed is not False) and (
        total > 0 and pass_rate >= 80.0
    )

    return {
        "code": 0,
        "data": {
            "test_run_id": run_id, "status": status,
            "total": total, "passed": passed, "failed": failed,
            "pass_rate": pass_rate,
            "quality_score": score,
            "gate_passed": gate_passed,
            "gate_reasons": reasons,
            "ci_passed": ci_passed,
            "message": "测试通过" if ci_passed else "测试未通过（未完成/通过率或门禁未达标）",
        },
        "message": "success",
    }


@router.get("/badge/{project_id}.svg")
async def quality_badge(project_id: str, db: AsyncSession = Depends(get_db_session)):
    """项目质量徽章（SVG，公开——仅暴露通过率状态，供项目 README 引用）。"""
    import uuid as _uuid

    from fastapi import Response

    from app.models.database import TestResult, TestRun

    try:
        pid = _uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    run = (
        await db.execute(
            select(TestRun)
            .where(TestRun.project_id == pid)
            .order_by(TestRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    label, value, color = "tests", "no runs", "#9e9e9e"
    if run is not None and run.status and run.status.value == "completed":
        results = (
            await db.execute(select(TestResult).where(TestResult.test_run_id == run.id))
        ).scalars().all()
        if results:
            passed = sum(1 for r in results if r.is_passed)
            rate = round(passed * 100.0 / len(results))
            value = str(rate) + "% passing"
            color = "#4c1" if rate >= 80 else ("#dfb317" if rate >= 50 else "#e05d44")
        else:
            value = "no results"

    badge = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="20">'
        '<rect rx="3" width="150" height="20" fill="#555"/>'
        '<rect rx="3" x="58" width="92" height="20" fill="' + color + '"/>'
        '<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">'
        '<text x="29" y="14">tests</text>'
        '<text x="104" y="14">' + value + "</text></g></svg>"
    )
    return Response(content=badge, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-cache"})
