"""B/C 批次：规则单测与隔离 PostgreSQL HTTP 闭环。"""
import os
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.defect_management import _safe_cell, _validate_workflow
from app.config import settings
from app.models import database as m
from app.modules.auth.auth_service import AuthService
from app.modules.defects.workflow import DEFAULT_WORKFLOW
from app.schemas.defect_management import BatchOperation, SavedViewInput


def test_workflow_definition_rejects_code_like_actions_and_rule_weakening():
    unknown = deepcopy(DEFAULT_WORKFLOW)
    unknown["transitions"][0]["action_id"] = "run_script"
    with pytest.raises(HTTPException):
        _validate_workflow(unknown)
    weakened = deepcopy(DEFAULT_WORKFLOW)
    weakened["transitions"][2]["required_fields"] = []
    with pytest.raises(HTTPException):
        _validate_workflow(weakened)
    assert _validate_workflow(deepcopy(DEFAULT_WORKFLOW))["schema_version"] == 1


def test_export_formula_injection_and_management_input_limits():
    assert _safe_cell("=HYPERLINK('x')").startswith("'")
    assert _safe_cell("普通标题") == "普通标题"
    with pytest.raises(Exception):
        SavedViewInput(name="x", columns=["x"] * 31)
    with pytest.raises(Exception):
        BatchOperation(project_id=uuid4(), defect_ids=[uuid4()] * 101, operation="priority")


pytestmark_integration = pytest.mark.skipif(os.getenv("DEFECT_MANAGEMENT_INTEGRATION") != "true", reason="仅在隔离数据库运行")


@pytestmark_integration
@pytest.mark.asyncio
async def test_collaboration_batch_import_metrics_and_workflow_http():
    assert settings.POSTGRES_DB.startswith("aitp_defect019_check_bc_")
    from app.main import app
    from app.utils.database import get_db_session
    engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    manager_id, qa_id, project_id = uuid4(), uuid4(), uuid4()
    tokens = {
        "manager": AuthService.create_access_token(str(manager_id), "bc_manager", m.UserRole.TEST_MANAGER.value),
        "qa": AuthService.create_access_token(str(qa_id), "bc_qa", m.UserRole.TESTER.value),
    }
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False, autoflush=False,
                                join_transaction_mode="create_savepoint") as db:
            db.add_all([
                m.User(id=manager_id, username="bc_manager", email=f"{manager_id}@test.invalid", role=m.UserRole.TEST_MANAGER, hashed_password="x", is_active=True),
                m.User(id=qa_id, username="bc_qa", email=f"{qa_id}@test.invalid", role=m.UserRole.TESTER, hashed_password="x", is_active=True),
            ])
            await db.flush()
            db.add(m.Project(id=project_id, name="BC 缺陷验收", owner_id=manager_id, source_type=m.SourceType.UPLOAD))
            await db.flush()
            db.add(m.ProjectMember(project_id=project_id, user_id=qa_id, access="write"))
            await db.commit()

            async def isolated_db():
                db.info.pop("project_scope", None)
                try:
                    yield db
                finally:
                    db.info.pop("project_scope", None)

            app.dependency_overrides[get_db_session] = isolated_db
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://verify") as client:
                async def call(actor, method, path, *, payload=None, params=None, files=None, data=None, expected=200):
                    response = await client.request(method, path, json=payload, params=params, files=files, data=data,
                        headers={"Authorization": "Bearer " + tokens[actor]})
                    assert response.status_code == expected, response.text
                    return response.json().get("data", response.json())

                project = str(project_id)
                defect = await call("qa", "POST", "/api/defects", payload={"project_id": project,
                    "title": "批次闭环问题", "description": "用于验证 B/C", "creation_request_id": str(uuid4())})
                defect_id = defect["id"]
                comment = await call("qa", "POST", f"/api/defects/{defect_id}/comments", payload={
                    "body": "@负责人 请确认修复范围", "mention_user_ids": [str(manager_id)], "attachment_ids": []})
                assert comment["mention_user_ids"] == [str(manager_id)]
                await call("qa", "POST", f"/api/defects/{defect_id}/watchers", payload={})
                watchers = await call("qa", "GET", f"/api/defects/{defect_id}/watchers")
                assert watchers["items"][0]["user_id"] == str(qa_id)
                comments = await call("manager", "GET", f"/api/defects/{defect_id}/comments")
                assert comments["items"][0]["body"].startswith("@负责人")
                attachment = await call("qa", "POST", "/api/defect-attachments",
                    data={"project_id": project, "defect_id": defect_id},
                    files={"file": ("evidence.log", b"request failed with 500", "text/plain")})
                download = await client.get(f"/api/defect-attachments/{attachment['id']}/download",
                    headers={"Authorization": "Bearer " + tokens["manager"]})
                assert download.status_code == 200 and download.content == b"request failed with 500"
                await call("qa", "DELETE", f"/api/defect-attachments/{attachment['id']}")

                view = await call("qa", "POST", "/api/defect-management/views", params={"project_id": project}, payload={
                    "name": "我的高优先级", "visibility": "private", "query": {"priority": "high"}, "columns": [], "sort": []})
                assert view["name"] == "我的高优先级"
                preview = await call("manager", "POST", "/api/defect-management/batch", payload={
                    "project_id": project, "defect_ids": [defect_id], "operation": "priority", "values": {"priority": "high"}, "preview": True})
                version = preview["succeeded"][0]["row_version"]
                denied_preview = await call("manager", "POST", "/api/defect-management/batch", payload={
                    "project_id": project, "defect_ids": [defect_id], "operation": "transition",
                    "values": {"action_id": "close", "note": "当前状态不可关闭"}, "preview": True})
                assert denied_preview["summary"] == {"success": 0, "failed": 1}
                result = await call("manager", "POST", "/api/defect-management/batch", payload={
                    "project_id": project, "defect_ids": [defect_id], "operation": "priority",
                    "values": {"priority": "high", "expected_versions": {defect_id: version}}, "preview": False})
                assert result["summary"] == {"success": 1, "failed": 0}

                csv_data = "标题,描述,严重程度,优先级,缺陷类型\n导入缺陷,导入闭环,P1,high,program\n".encode("utf-8-sig")
                imported = await call("qa", "POST", "/api/defect-management/imports/preview",
                    data={"project_id": project, "request_key": str(uuid4())}, files={"file": ("defects.csv", csv_data, "text/csv")})
                assert imported["valid"] == 1
                committed = await call("qa", "POST", f"/api/defect-management/imports/{imported['job_id']}/commit",
                    payload={"request_key": str(uuid4())})
                assert committed["success"] == 1

                metrics = await call("manager", "GET", "/api/defect-management/metrics", params={"project_id": project, "days": 30})
                assert metrics["summary"]["total"] == 2 and len(metrics["trend"]) == 30
                settings_data = await call("manager", "GET", "/api/defect-management/settings", params={"project_id": project})
                updated = await call("manager", "PUT", "/api/defect-management/settings", params={"project_id": project}, payload={
                    "expected_version": settings_data["row_version"], "timezone": "Asia/Shanghai",
                    "field_config": {"required_on_create": ["reproduce_steps"]},
                    "permission_config": {"allow_reporter_edit": True},
                    "notification_config": {"enabled_events": ["*"], "notify_actor": False}})
                assert updated["field_config"]["required_on_create"] == ["reproduce_steps"]
                await call("qa", "POST", "/api/defects", payload={"project_id": project,
                    "title": "缺少步骤", "description": "应失败", "creation_request_id": str(uuid4())}, expected=422)

                workflow = await call("manager", "POST", "/api/defect-management/workflows", payload={"project_id": project, "name": "研发协作流"})
                saved = await call("manager", "PUT", f"/api/defect-management/workflow-revisions/{workflow['revision_id']}",
                    payload={"definition": workflow["definition"]})
                published = await call("manager", "POST", f"/api/defect-management/workflow-revisions/{workflow['revision_id']}/publish")
                assert published["active_revision_id"] == workflow["revision_id"] and saved["definition"]["schema_version"] == 1
                mapping = {item["key"]: item["key"] for item in saved["definition"]["states"]}
                migration_key = str(uuid4())
                migration_preview = await call("manager", "POST", "/api/defect-management/workflow-migrations",
                    params={"project_id": project}, payload={"target_revision_id": workflow["revision_id"],
                    "state_mapping": mapping, "defect_ids": [], "request_key": migration_key, "preview": True})
                assert migration_preview["can_execute"] and len(migration_preview["items"]) == 2
                migrated = await call("manager", "POST", "/api/defect-management/workflow-migrations",
                    params={"project_id": project}, payload={"target_revision_id": workflow["revision_id"],
                    "state_mapping": mapping, "defect_ids": [], "request_key": migration_key, "preview": False})
                assert migrated["migrated"] == 2

                assert (await db.execute(select(func.count()).select_from(m.NotificationOutbox).where(
                    m.NotificationOutbox.project_id == project_id))).scalar_one() >= 4
            app.dependency_overrides.pop(get_db_session, None)
        await transaction.rollback()
    await engine.dispose()


@pytestmark_integration
@pytest.mark.asyncio
async def test_notification_outbox_delivers_mentions_once():
    assert settings.POSTGRES_DB.startswith("aitp_defect019_check_bc_")
    from app.modules.defects.notifications import dispatch_outbox
    from app.modules.defects.service import append_event, create_defect, snapshot
    from app.schemas.defects import DefectCreate
    engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    manager_id, qa_id, project_id = uuid4(), uuid4(), uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        manager = m.User(id=manager_id, username="notify_manager_" + manager_id.hex[:8], email=f"{manager_id}@test.invalid",
                         role=m.UserRole.TEST_MANAGER, hashed_password="x", is_active=True)
        qa = m.User(id=qa_id, username="notify_qa_" + qa_id.hex[:8], email=f"{qa_id}@test.invalid",
                    role=m.UserRole.TESTER, hashed_password="x", is_active=True)
        db.add_all([manager, qa]); await db.flush()
        db.add(m.Project(id=project_id, name="通知 Outbox 验收", owner_id=manager_id, source_type=m.SourceType.UPLOAD)); await db.flush()
        db.add(m.ProjectMember(project_id=project_id, user_id=qa_id, access="write")); await db.flush()
        defect = await create_defect(db, qa, DefectCreate(project_id=project_id, title="通知幂等验收", description="评论提醒负责人", creation_request_id=uuid4()))
        comment = m.DefectComment(id=uuid4(), defect_id=defect.id, project_id=project_id, author_id=qa_id,
                                  body="@负责人 请处理", mention_user_ids=[str(manager_id)])
        db.add(comment)
        append_event(db, defect, qa, "comment_added", snapshot(defect), note=comment.body,
                     extra={"comment_id": str(comment.id), "mention_user_ids": [str(manager_id)]})
        await db.commit()
        defect_id = defect.id
    try:
        first = await dispatch_outbox()
        second = await dispatch_outbox()
        assert first >= 1 and second == 0
        async with AsyncSession(engine) as check:
            notifications = (await check.execute(select(m.Notification).where(
                m.Notification.user_id == manager_id, m.Notification.resource_id == defect_id))).scalars().all()
            assert len(notifications) >= 1
            assert len({item.dedupe_key for item in notifications}) == len(notifications)
    finally:
        async with AsyncSession(engine) as cleanup:
            outbox_ids = select(m.NotificationOutbox.id).where(m.NotificationOutbox.project_id == project_id)
            await cleanup.execute(m.NotificationDelivery.__table__.delete().where(m.NotificationDelivery.outbox_id.in_(outbox_ids)))
            await cleanup.execute(m.Notification.__table__.delete().where(m.Notification.resource_id == defect_id))
            await cleanup.execute(m.NotificationOutbox.__table__.delete().where(m.NotificationOutbox.project_id == project_id))
            await cleanup.execute(m.DefectComment.__table__.delete().where(m.DefectComment.project_id == project_id))
            await cleanup.execute(m.AuditLog.__table__.delete().where(m.AuditLog.user_id.in_([manager_id, qa_id])))
            await cleanup.execute(m.DefectEvent.__table__.delete().where(m.DefectEvent.project_id == project_id))
            await cleanup.execute(m.Defect.__table__.delete().where(m.Defect.project_id == project_id))
            await cleanup.execute(m.ProjectDefectSettings.__table__.delete().where(m.ProjectDefectSettings.project_id == project_id))
            await cleanup.execute(m.DefectWorkflow.__table__.update().where(
                m.DefectWorkflow.project_id == project_id).values(active_revision_id=None))
            await cleanup.execute(m.DefectWorkflowRevision.__table__.delete().where(m.DefectWorkflowRevision.project_id == project_id))
            await cleanup.execute(m.DefectWorkflow.__table__.delete().where(m.DefectWorkflow.project_id == project_id))
            await cleanup.execute(m.ProjectMember.__table__.delete().where(m.ProjectMember.project_id == project_id))
            await cleanup.execute(m.Project.__table__.delete().where(m.Project.id == project_id))
            await cleanup.execute(m.User.__table__.delete().where(m.User.id.in_([manager_id, qa_id])))
            await cleanup.commit()
        await engine.dispose()
