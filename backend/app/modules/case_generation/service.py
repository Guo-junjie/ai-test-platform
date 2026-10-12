"""接口文档用例生成任务的预检、执行与持久化。"""

from datetime import datetime
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    ApiEndpoint, CaseGenerationTask, Notification, TestCaseAsset,
    TestCaseAssetVersion, User,
)


MIN_CASES_PER_ENDPOINT = 15
MAX_ENDPOINTS_PER_TASK = 30


def endpoint_to_dict(endpoint: ApiEndpoint) -> dict[str, Any]:
    return {
        "endpoint_id": str(endpoint.id), "path": endpoint.path,
        "http_method": endpoint.method, "params": endpoint.params or [],
        "auth_required": bool(endpoint.auth_required), "summary": endpoint.summary or "",
    }


async def resolve_endpoints(db: AsyncSession, project_id: uuid.UUID,
                            endpoint_ids: list[str] | None = None,
                            endpoint_id: str | None = None) -> list[ApiEndpoint]:
    raw_ids = list(dict.fromkeys(endpoint_ids or ([endpoint_id] if endpoint_id else [])))
    if raw_ids:
        try:
            ids = [uuid.UUID(str(value)) for value in raw_ids]
        except (TypeError, ValueError) as exc:
            raise ValueError("接口 ID 格式错误") from exc
        rows = (await db.execute(select(ApiEndpoint).where(
            ApiEndpoint.project_id == project_id, ApiEndpoint.id.in_(ids), ApiEndpoint.is_active.is_(True),
        ))).scalars().all()
        by_id = {row.id: row for row in rows}
        missing = [str(value) for value in ids if value not in by_id]
        if missing:
            raise ValueError("部分接口不存在、未启用或不属于当前项目")
        endpoints = [by_id[value] for value in ids]
    else:
        endpoints = list((await db.execute(select(ApiEndpoint).where(
            ApiEndpoint.project_id == project_id, ApiEndpoint.is_active.is_(True),
        ).order_by(ApiEndpoint.method, ApiEndpoint.path).limit(MAX_ENDPOINTS_PER_TASK + 1))).scalars().all())
    if not endpoints:
        raise ValueError("未找到可用接口，请先导入接口资产")
    if len(endpoints) > MAX_ENDPOINTS_PER_TASK:
        raise ValueError(f"单次最多生成 {MAX_ENDPOINTS_PER_TASK} 个接口，请分批提交")
    return endpoints


async def preview_generation(db: AsyncSession, project_id: uuid.UUID,
                             endpoint_ids: list[str] | None = None,
                             endpoint_id: str | None = None) -> dict[str, Any]:
    endpoints = await resolve_endpoints(db, project_id, endpoint_ids, endpoint_id)
    ids = [row.id for row in endpoints]
    existing = int((await db.execute(select(func.count()).select_from(TestCaseAsset).where(
        TestCaseAsset.project_id == project_id, TestCaseAsset.endpoint_id.in_(ids),
    ))).scalar_one() or 0)
    warnings = []
    if existing:
        warnings.append(f"所选接口已有 {existing} 条用例，本次生成会新增草稿，请在预览后去重评审")
    return {
        "endpoint_count": len(endpoints),
        "estimated_case_count": len(endpoints) * MIN_CASES_PER_ENDPOINT,
        "existing_case_count": existing,
        "endpoints": [{"id": str(row.id), "method": row.method, "path": row.path,
                       "summary": row.summary or ""} for row in endpoints],
        "warnings": warnings,
        "execution_mode": "异步生成；AI 不可用时自动切换规则模板",
    }


def task_to_dict(task: CaseGenerationTask) -> dict[str, Any]:
    return {
        "id": str(task.id), "project_id": str(task.project_id),
        "created_by": str(task.created_by),
        "source_doc_id": str(task.source_doc_id) if task.source_doc_id else None,
        "endpoint_ids": list(task.endpoint_ids or []), "endpoint_count": task.endpoint_count,
        "estimated_case_count": task.estimated_case_count,
        "generated_case_count": task.generated_case_count,
        "status": task.status, "progress": task.progress,
        "generation_engine": task.generation_engine,
        "degraded": task.generation_engine == "rule_degraded",
        "degraded_reason": task.degraded_reason, "error_message": task.error_message,
        "result_summary": task.result_summary or {},
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _case_snapshot(asset: TestCaseAsset) -> dict[str, Any]:
    return {
        "title": asset.title, "description": asset.description or "",
        "execution_kind": asset.execution_kind, "case_type": asset.case_type,
        "request_data": asset.request_data or {}, "expected_result": asset.expected_result or {},
        "priority": asset.priority, "folder": asset.folder or "", "tags": list(asset.tags or []),
        "pre_script": "", "post_script": "", "sql_script": "",
    }


async def run_generation_task(task_id: uuid.UUID) -> None:
    """执行一个生成任务。模型调用期间不持有数据库事务。"""
    from app.modules.ai.model_router import refresh_model_router_for_worker
    from app.modules.case_generator.case_generator import TestCaseGenerator
    from app.utils.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            task = (await db.execute(select(CaseGenerationTask).where(
                CaseGenerationTask.id == task_id,
            ).with_for_update())).scalar_one_or_none()
            if task is None or task.status != "pending":
                return
            task.status, task.progress, task.started_at = "running", 5, datetime.utcnow()
            endpoints = await resolve_endpoints(db, task.project_id, list(task.endpoint_ids or []))
            endpoint_payload = [endpoint_to_dict(row) for row in endpoints]
            creator_id, project_id = task.created_by, task.project_id
            await refresh_model_router_for_worker(db)
            await db.commit()

        generator = TestCaseGenerator()
        cases = await generator.generate_all(endpoint_payload, {}, project_id=str(project_id))
        async with AsyncSessionLocal() as db:
            task = await db.get(CaseGenerationTask, task_id)
            if task is None:
                return
            saved_ids = []
            for case in cases.get("api", []):
                asset = TestCaseAsset(
                    id=uuid.uuid4(), project_id=project_id,
                    endpoint_id=uuid.UUID(case["endpoint_id"]) if case.get("endpoint_id") else None,
                    case_type=case.get("case_type", "positive"), execution_kind="api",
                    design_type=case.get("case_type", "positive"), title=case.get("case_name", ""),
                    description=case.get("description", ""), request_data=case.get("request", {}),
                    expected_result=case.get("expected") or {}, priority=case.get("priority", "P2"),
                    status="draft", review_state="draft", source="ai_generated", version=1,
                    generation_context={"channel": "api_document", "endpoint_id": case.get("endpoint_id"),
                                        "generation_task_id": str(task_id),
                                        "generator": "rule_degraded" if generator.degraded_reasons else "ai_case_generator"},
                    created_by=creator_id,
                )
                db.add(asset)
                await db.flush()
                db.add(TestCaseAssetVersion(case_asset_id=asset.id, version=1,
                                             snapshot=_case_snapshot(asset), change_type="generated",
                                             changed_by=creator_id))
                saved_ids.append(str(asset.id))
            reason = "；".join(generator.degraded_reasons)[:4000] or None
            task.status, task.progress = "completed", 100
            task.generated_case_count = len(saved_ids)
            task.generation_engine = "rule_degraded" if reason else "ai"
            task.degraded_reason, task.completed_at = reason, datetime.utcnow()
            task.result_summary = {"case_ids": saved_ids, "api": len(saved_ids),
                                   "performance": len(cases.get("performance", [])),
                                   "integration": len(cases.get("integration", []))}
            db.add(Notification(
                user_id=creator_id, title="接口用例生成完成",
                content=f"已为 {task.endpoint_count} 个接口生成 {len(saved_ids)} 条用例"
                        + ("，模型不可用的部分已使用规则模板生成" if reason else ""),
                type="case_generation",
                related_url=f"/case-generation?source=interface&project_id={project_id}&task_id={task_id}",
                resource_type="case_generation_task", resource_id=task.id,
                dedupe_key=f"case-generation:{task.id}:completed",
            ))
            await db.commit()
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            task = await db.get(CaseGenerationTask, task_id)
            if task:
                creator_id, project_id = task.created_by, task.project_id
                task.status, task.progress = "failed", 100
                task.error_message, task.completed_at = (str(exc).strip() or exc.__class__.__name__)[:4000], datetime.utcnow()
                db.add(Notification(
                    user_id=creator_id, title="接口用例生成失败", content=task.error_message,
                    type="case_generation",
                    related_url=f"/case-generation?source=interface&project_id={project_id}&task_id={task_id}",
                    resource_type="case_generation_task", resource_id=task.id,
                    dedupe_key=f"case-generation:{task.id}:failed",
                ))
                await db.commit()
        raise
