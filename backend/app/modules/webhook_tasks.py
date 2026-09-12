"""Webhook 入站事件异步处理（企业化改造 M5）。

流程（方案 4.5 变更影响运行·M5 子集）：
1. Webhook 端点验签后仅持久化 InboundEvent 并立即返回 202；
2. 本任务异步处理：同步代码 → 建 ProjectCodeVersion →
   可解释规则选择已发布计划 → RunOrchestrator 创建计划化 Run；
3. 计划选择结果写入 InboundEvent.plan_selection 与 Run 事件，
   让用户能回答「为什么这次跑了这个计划」。

M5 计划选择规则（可解释）：
  项目下有且仅有一个已发布计划 → 选它（唯一已发布计划）
  多个已发布计划 → 选最近更新的（原因注明，P1 增强标签/影响匹配）
  无已发布计划 → 事件标记 blocked，需要用户先发布计划
"""
import uuid
from datetime import datetime

from app.celery_app import app
from app.utils.logger import get_logger

logger = get_logger(__name__)


@app.task(name="app.modules.webhook_tasks.process_inbound_event", bind=True, max_retries=0)
def process_inbound_event(self, event_id: str) -> dict:
    """处理入站事件：拉代码 → 计划选择 → 计划化运行。"""
    import asyncio

    return asyncio.run(_process_async(event_id))


async def _process_async(event_id: str) -> dict:
    from sqlalchemy import select

    from app.models.database import (
        EnvironmentProfile,
        InboundEvent,
        Project,
        TestPlan,
        TestPlanRevision,
    )
    from app.modules.runs.orchestrator import RunBlocked, RunOrchestrator
    from app.utils.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        event = (
            await session.execute(select(InboundEvent).where(InboundEvent.id == uuid.UUID(event_id)))
        ).scalar_one_or_none()
        if event is None:
            logger.warning(f"[inbound:{event_id}] event not found")
            return {"status": "failed", "error": "event not found"}
        if event.status == "duplicate":
            return {"status": "duplicate"}
        if event.status == "processed":
            return {"status": "processed"}

        event.status = "processing"
        await session.commit()
        pid = event.project_id

        # ---- 1. 同步代码 → ProjectCodeVersion ----
        code_version_id: uuid.UUID | None = None
        try:
            summary = event.payload_summary or {}
            if event.provider == "github":
                from app.modules.source import SourceConfig, SourceAdapterFactory, SourceType

                proj = (
                    await session.execute(select(Project).where(Project.id == pid))
                ).scalar_one_or_none()
                cfg = proj.source_config or {} if proj else {}
                result = SourceAdapterFactory.fetch_code(SourceConfig(
                    source_type=SourceType.GITHUB,
                    repo_url=summary.get("repo_url") or cfg.get("repo_url"),
                    github_token=cfg.get("github_token") or "",
                    branch=summary.get("branch") or "main",
                    commit_sha=summary.get("commit_sha"),
                    incremental=False,
                ))
            elif event.provider == "svn":
                # SVN 凭据来自事件摘要（post-commit hook 携带）
                from app.modules.source import SourceConfig, SourceAdapterFactory, SourceType

                result = SourceAdapterFactory.fetch_code(SourceConfig(
                    source_type=SourceType.SVN,
                    svn_url=summary.get("svn_url"),
                    svn_username=summary.get("svn_username"),
                    svn_password=summary.get("svn_password"),
                    svn_revision=summary.get("revision"),
                    incremental=False,
                ))
            else:
                result = None

            if result and result.get("local_path"):
                from app.models.database import ProjectCodeVersion, SourceType as ModelSourceType

                cv = ProjectCodeVersion(
                    project_id=pid,
                    source_type=ModelSourceType.GITHUB if event.provider == "github" else ModelSourceType.SVN,
                    version_id=result.get("version_id") or summary.get("commit_sha") or datetime.utcnow().strftime("%Y%m%d%H%M%S"),
                    branch=summary.get("branch"),
                    commit_message=summary.get("commit_message"),
                    local_path=result.get("local_path", ""),
                    snapshot_id=result.get("snapshot_id"),
                    total_files=result.get("total_files", 0),
                    note=f"webhook:{event.provider}:{event.delivery_id[:12]}",
                )
                session.add(cv)
                await session.commit()
                await session.refresh(cv)
                code_version_id = cv.id
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[inbound:{event_id}] code fetch failed (non-fatal): {e}")

        # ---- 2. 可解释计划选择 ----
        plans = (
            await session.execute(
                select(TestPlan).where(
                    TestPlan.project_id == pid,
                    TestPlan.status == "active",
                )
            )
        ).scalars().all()
        published: list[tuple[TestPlan, TestPlanRevision]] = []
        for p in plans:
            rev = (
                await session.execute(
                    select(TestPlanRevision)
                    .where(
                        TestPlanRevision.plan_id == p.id,
                        TestPlanRevision.status == "published",
                    )
                    .order_by(TestPlanRevision.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if rev is not None:
                published.append((p, rev))

        if not published:
            event.status = "blocked"
            event.status_detail = "项目下没有已发布计划 —— 请先在项目工作区发布测试计划后再推送代码"
            event.code_version_id = code_version_id
            event.processed_at = datetime.utcnow()
            await session.commit()
            logger.warning(f"[inbound:{event_id}] blocked: no published plan")
            return {"status": "blocked", "error": event.status_detail}

        if len(published) == 1:
            sel_plan, sel_rev = published[0]
            selection_reason = "项目唯一的已发布计划"
        else:
            sel_plan, sel_rev = max(published, key=lambda t: t[1].published_at or t[1].created_at)
            selection_reason = f"项目有 {len(published)} 个已发布计划，默认选择最近发布的（标签/影响匹配将在后续版本增强）"

        # ---- 3. 编排器创建计划化 Run ----
        async with AsyncSessionLocal() as orch_session:
            result = await RunOrchestrator.create_plan_run(
                plan_id=sel_plan.id,
                db=orch_session,
                plan_revision_id=sel_rev.id,
                trigger_type="webhook",
                trigger_context={
                    "via": "webhook",
                    "provider": event.provider,
                    "delivery_id": event.delivery_id,
                    "inbound_event_id": str(event.id),
                    "plan_selection": selection_reason,
                    "code_version_id": str(code_version_id) if code_version_id else None,
                },
            )

        event.status = "processed"
        event.status_detail = f"已选择计划「{sel_plan.name}」r{sel_rev.revision}：{selection_reason}"
        event.code_version_id = code_version_id
        event.test_run_id = uuid.UUID(result["test_run_id"])
        event.plan_selection = {
            "plan_id": str(sel_plan.id),
            "plan_name": sel_plan.name,
            "revision": sel_rev.revision,
            "reason": selection_reason,
        }
        event.processed_at = datetime.utcnow()
        await session.commit()

        logger.info(
            f"[inbound:{event_id}] processed: plan={sel_plan.name} r{sel_rev.revision} "
            f"run={result['test_run_id']}"
        )
        return {"status": "processed", "test_run_id": result["test_run_id"], "plan": sel_plan.name}
