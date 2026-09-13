"""统一运行编排器（企业化改造 M3）—— 所有触发来源的唯一建 Run 入口。

手动（plan execute）、定时任务、Webhook/CI 都适配为 RunRequest 调用本服务，
保证同一计划由不同来源触发时产生同构的 RunSnapshot / RunEvent / 报告 / 通知。

状态语义（方案 4.2，M3 落地核心子集）：
- queued    已创建待派发（无阻塞）
- blocked   预检不满足（未发布修订/无启用用例/环境未发布），未实际执行
- failed    由 pipeline 写入（平台/环境无法完成任务）
- completed 由 pipeline 写入（已获得完整结果；门禁结论另计）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    EnvironmentProfile,
    EnvironmentProfileRevision,
    Project,
    RunEvent,
    RunSnapshot,
    TestCaseAsset,
    TestPlan,
    TestPlanRevision,
    TestPlanRevisionCase,
    TestRun,
    TestStatus,
)
from app.utils.logger import get_logger
from app.modules.runs.case_snapshot import case_content_hash, resolve_revision_case_payload

logger = get_logger(__name__)


class RunBlocked(Exception):
    """预检不满足——携带面向用户的原因与修复引导。"""

    def __init__(self, reason: str, fix_hint: str = ""):
        self.reason = reason
        self.fix_hint = fix_hint
        super().__init__(reason)


class RunOrchestrator:
    """计划化运行的唯一编排入口。"""

    @staticmethod
    async def create_plan_run(
        plan_id: str | uuid.UUID,
        db: AsyncSession,
        *,
        environment_profile_id: str | uuid.UUID | None = None,
        plan_revision_id: str | uuid.UUID | None = None,
        trigger_type: str = "manual",
        trigger_context: dict[str, Any] | None = None,
        user_id: uuid.UUID | None = None,
        legacy_target_url: str | None = None,
    ) -> dict[str, Any]:
        """创建计划化 Run：预检 → 固化快照 → 建 Run/事件 → 派发流水线。

        返回 {test_run_id, plan_revision, case_count, snapshot_id, dispatched}。
        抛 RunBlocked 表示预检不满足（调用方转 400/blocked 语义）。
        """
        pid = uuid.UUID(str(plan_id))
        plan = (
            await db.execute(select(TestPlan).where(TestPlan.id == pid))
        ).scalar_one_or_none()
        if plan is None:
            raise RunBlocked(f"计划不存在: {plan_id}")
        if plan.status != "active":
            raise RunBlocked(f"计划状态为 {plan.status}，不能执行")

        # ---- 修订版解析（指定 > 最新已发布）----
        if plan_revision_id:
            revision = (
                await db.execute(
                    select(TestPlanRevision).where(TestPlanRevision.id == uuid.UUID(str(plan_revision_id)))
                )
            ).scalar_one_or_none()
            if revision is None or revision.plan_id != plan.id:
                raise RunBlocked(f"计划修订版不存在: {plan_revision_id}")
        else:
            revision = (
                await db.execute(
                    select(TestPlanRevision)
                    .where(TestPlanRevision.plan_id == plan.id, TestPlanRevision.status == "published")
                    .order_by(TestPlanRevision.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if revision is None:
                raise RunBlocked("计划尚未发布：请先在计划管理中发布后再执行（发布固化当前用例集）")

        # ---- 用例集合（来自修订版固化数据）----
        rev_cases = (
            await db.execute(
                select(TestPlanRevisionCase)
                .where(
                    TestPlanRevisionCase.revision_id == revision.id,
                    TestPlanRevisionCase.enabled.is_(True),
                )
                .order_by(TestPlanRevisionCase.sort_order.asc())
            )
        ).scalars().all()
        if not rev_cases:
            raise RunBlocked(f"修订版 r{revision.revision} 内无启用用例，请修改计划并重新发布")

        # ---- 环境解析：显式 > 修订版绑定 > 项目 source_config 回退 ----
        env_profile: EnvironmentProfile | None = None
        env_revision: EnvironmentProfileRevision | None = None
        target_url: str | None = None

        if environment_profile_id:
            env_profile = (
                await db.execute(
                    select(EnvironmentProfile).where(EnvironmentProfile.id == uuid.UUID(str(environment_profile_id)))
                )
            ).scalar_one_or_none()
            if env_profile is None:
                raise RunBlocked(f"环境档案不存在: {environment_profile_id}")
            if env_profile.project_id != plan.project_id:
                raise RunBlocked("环境档案不属于该计划所在项目")
        elif revision.environment_profile_id:
            env_profile = (
                await db.execute(
                    select(EnvironmentProfile).where(
                        EnvironmentProfile.id == revision.environment_profile_id
                    )
                )
            ).scalar_one_or_none()

        if env_profile is not None:
            if env_profile.status != "published" or not env_profile.current_revision_id:
                raise RunBlocked(f"环境「{env_profile.name}」尚未发布，请先在项目详情中发布后再执行")
            env_revision = (
                await db.execute(
                    select(EnvironmentProfileRevision).where(
                        EnvironmentProfileRevision.id == env_profile.current_revision_id
                    )
                )
            ).scalar_one_or_none()
            if env_revision is None or env_revision.status != "published":
                raise RunBlocked(f"环境「{env_profile.name}」的已发布修订版缺失，请重新发布")
            target_url = (env_revision.config_json or {}).get("base_url") or None
        else:
            # 回退：项目 source_config（历史行为，标记为无档案执行）
            proj = (
                await db.execute(select(Project).where(Project.id == plan.project_id))
            ).scalar_one_or_none()
            if proj and proj.source_config:
                target_url = proj.source_config.get("target_service_url")
            target_url = target_url or (legacy_target_url or "").strip() or None

        # ---- user_id 兜底：调度/Webhook 路径可能无明确操作者 ----
        if user_id is None:
            proj = (
                await db.execute(select(Project).where(Project.id == plan.project_id))
            ).scalar_one_or_none()
            user_id = proj.owner_id if proj else None
            if user_id is None:
                from app.models.database import User as _User, UserRole as _UserRole

                user_id = (
                    await db.execute(
                        select(_User.id)
                        .where(_User.role == _UserRole.SUPER_ADMIN)
                        .limit(1)
                    )
                ).scalar()

        # 在创建 Run 前解析完整用例载荷，旧修订版内容漂移时直接阻止执行。
        case_assets = (
            await db.execute(
                select(TestCaseAsset).where(TestCaseAsset.id.in_([c.case_asset_id for c in rev_cases]))
            )
        ).scalars().all()
        asset_map = {a.id: a for a in case_assets}
        try:
            snapshot_cases = [
                {
                    "case_asset_id": str(c.case_asset_id),
                    "title": c.title,
                    "execution_kind": c.execution_kind,
                    "content_hash": c.content_hash,
                    "current_content_hash": case_content_hash(asset_map.get(c.case_asset_id)),
                    "payload": resolve_revision_case_payload(c, asset_map.get(c.case_asset_id)),
                }
                for c in rev_cases
            ]
        except ValueError as exc:
            raise RunBlocked(str(exc)) from exc

        # ---- 创建 Run ----
        now = datetime.utcnow()
        run = TestRun(
            id=uuid.uuid4(),
            project_id=plan.project_id,
            user_id=user_id,
            source_type="upload",  # 兼容老枚举（plan 模式由 plan_id 决定）
            source_ref=f"plan:{plan.id}",
            status=TestStatus.PULLING,
            progress=0,
            plan_id=plan.id,
            current_step="pending",
            target_service_url=target_url,
            environment_profile_id=env_profile.id if env_profile else None,
            environment_revision_id=env_revision.id if env_revision else None,
            trigger_type=trigger_type,
            trigger_context=trigger_context or {},
        )
        db.add(run)
        await db.flush()

        # ---- 固化运行快照 ----
        snapshot_json = {
            "plan_id": str(plan.id),
            "plan_name": plan.name,
            "plan_revision_id": str(revision.id),
            "plan_revision": revision.revision,
            "cases": snapshot_cases,
            "environment": {
                "profile_id": str(env_profile.id) if env_profile else None,
                "revision_id": str(env_revision.id) if env_revision else None,
                "base_url": target_url,
                "archived": env_profile is None,  # 无档案=回退路径，证据不完整
            },
            "trigger": {"type": trigger_type, "context": trigger_context or {}},
        }
        snapshot = RunSnapshot(
            test_run_id=run.id,
            snapshot_json=snapshot_json,
            engine_version="pipeline-v1",
            created_at=now,
        )
        db.add(snapshot)
        await db.flush()
        run.run_snapshot_id = snapshot.id

        # ---- 事件 ----
        seq = 0
        for etype, payload in (
            ("run.created", {"trigger_type": trigger_type, "trigger_context": trigger_context or {}}),
            ("run.queued", {
                "plan_revision": revision.revision,
                "case_count": len(rev_cases),
                "environment": snapshot_json["environment"],
                "snapshot_id": str(snapshot.id),
            }),
        ):
            db.add(RunEvent(
                test_run_id=run.id,
                sequence=seq,
                event_type=etype,
                payload=payload,
                created_at=now,
            ))
            seq += 1

        await db.commit()
        await db.refresh(run)

        # ---- 派发流水线 ----
        from app.celery_app import celery_app as _celery
        from app.utils.redis_client import get_async_redis

        async_result = _celery.send_task(
            "app.modules.pipeline.run_test_pipeline",
            args=[str(run.id), {
                "source_type": "plan",
                "plan_id": str(plan.id),
                "plan_revision_id": str(revision.id),
                "plan_revision": revision.revision,
                "case_asset_ids": [str(c.case_asset_id) for c in rev_cases],
                "project_id": str(plan.project_id),
                "target_service_url": target_url,
            }],
        )
        try:
            redis = await get_async_redis()
            await redis.set(f"task:celery:{run.id}", async_result.id, ex=7 * 24 * 3600)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"orchestrator: failed to store celery task id: {e}")

        logger.info(
            f"[orchestrator] plan run created: run={run.id} plan={plan.id} "
            f"revision=r{revision.revision} trigger={trigger_type} env={'archived' if env_profile is None else 'profiled'}"
        )
        return {
            "test_run_id": str(run.id),
            "plan_id": str(plan.id),
            "plan_revision_id": str(revision.id),
            "plan_revision": revision.revision,
            "case_count": len(rev_cases),
            "snapshot_id": str(snapshot.id),
            "environment_archived": env_profile is None,
            "target_service_url": target_url,
            "status": "dispatched",
        }
