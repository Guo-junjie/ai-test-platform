"""真实 PostgreSQL 与真实 HTTP 鉴权验收；专用验证数据库，外层事务回滚。"""
import os
import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import database as m
from app.modules.auth.auth_service import AuthService
from app.modules.report.generator import persist_defects_to_db

pytestmark = pytest.mark.skipif(os.getenv("DEFECT_CENTER_INTEGRATION") != "true", reason="仅在明确指定的隔离数据库运行")


@pytest.fixture(autouse=True)
def restore_http_dependencies():
    from app.main import app
    saved = dict(app.dependency_overrides)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


@pytest.mark.asyncio
async def test_two_database_sessions_cannot_overwrite_same_defect_version():
    assert settings.POSTGRES_DB.startswith("aitp_defect019_check_")
    from fastapi import HTTPException
    from app.modules.defects.service import create_defect, edit_defect
    from app.schemas.defects import DefectCreate, DefectUpdate
    engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    user_id, project_id = uuid4(), uuid4()
    defect_id = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as seed:
            user = m.User(id=user_id, username="lock_" + user_id.hex, email=user_id.hex + "@test.invalid", role=m.UserRole.TEST_MANAGER, hashed_password="unused", is_active=True)
            seed.add(user)
            await seed.flush()
            seed.add(m.Project(id=project_id, name="并发验证", owner_id=user_id, source_type=m.SourceType.UPLOAD))
            await seed.flush()
            defect = await create_defect(seed, user, DefectCreate(project_id=project_id, title="并发修改验收", description="原始内容", creation_request_id=uuid4()))
            defect_id = defect.id
            await seed.commit()
        async with AsyncSession(engine, expire_on_commit=False) as first, AsyncSession(engine, expire_on_commit=False) as second:
            await edit_defect(first, user, defect_id, DefectUpdate(expected_version=1, description="第一个请求的内容"))
            started = asyncio.Event()
            async def other_editor():
                started.set()
                try:
                    await edit_defect(second, user, defect_id, DefectUpdate(expected_version=1, description="试图覆盖的内容"))
                except HTTPException as failure:
                    await second.rollback()
                    return failure.status_code
                return 200
            task = asyncio.create_task(other_editor())
            await started.wait()
            await asyncio.sleep(0.1)
            assert not task.done(), "第二个请求应等待数据库行锁"
            await first.commit()
            assert await asyncio.wait_for(task, timeout=5) == 409
        async with AsyncSession(engine) as check:
            saved = await check.get(m.Defect, defect_id)
            assert saved.description == "第一个请求的内容" and saved.row_version == 2
            assert (await check.execute(select(func.count()).select_from(m.DefectEvent).where(m.DefectEvent.defect_id == defect_id))).scalar_one() == 2
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(m.AuditLog).where(m.AuditLog.user_id == user_id))
            await cleanup.execute(delete(m.DefectEvent).where(m.DefectEvent.project_id == project_id))
            await cleanup.execute(delete(m.Defect).where(m.Defect.project_id == project_id))
            await cleanup.execute(delete(m.ProjectDefectSettings).where(m.ProjectDefectSettings.project_id == project_id))
            await cleanup.execute(delete(m.DefectWorkflowRevision).where(m.DefectWorkflowRevision.project_id == project_id))
            await cleanup.execute(delete(m.DefectWorkflow).where(m.DefectWorkflow.project_id == project_id))
            await cleanup.execute(delete(m.Project).where(m.Project.id == project_id))
            await cleanup.execute(delete(m.User).where(m.User.id == user_id))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_defect_collaboration_full_cycle_and_project_boundaries():
    assert settings.POSTGRES_DB.startswith("aitp_defect019_check_"), "不能在平台业务数据库中运行此测试"
    from app.main import app
    from app.utils.database import get_db_session
    engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    ids = {key: uuid4() for key in ("manager", "qa", "dev", "reader", "outsider", "a", "b", "doc", "asset", "run", "case", "result")}
    roles = {"manager": m.UserRole.TEST_MANAGER, "qa": m.UserRole.TESTER, "dev": m.UserRole.DEVELOPER,
             "reader": m.UserRole.VIEWER, "outsider": m.UserRole.DEVELOPER}
    tokens = {key: AuthService.create_access_token(str(ids[key]), "defect_" + key, role.value) for key, role in roles.items()}
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint") as db:
            for name, role in roles.items():
                db.add(m.User(id=ids[name], username="defect_" + name + "_" + ids[name].hex[:8],
                              email=ids[name].hex + "@test.invalid", role=role, hashed_password="unused", is_active=True))
            await db.flush()
            db.add_all([m.Project(id=ids["a"], name="缺陷闭环验收 A", owner_id=ids["manager"], source_type=m.SourceType.UPLOAD),
                        m.Project(id=ids["b"], name="隔离项目 B", owner_id=ids["outsider"], source_type=m.SourceType.UPLOAD)])
            await db.flush()
            db.add_all([m.ProjectMember(project_id=ids["a"], user_id=ids[key], access="read" if key == "reader" else "write") for key in ("qa", "dev", "reader")])
            db.add(m.ProjectDefectRole(project_id=ids["a"], user_id=ids["dev"], role_key="qa"))
            db.add(m.RequirementDoc(id=ids["doc"], project_id=ids["a"], filename="订单需求.md", format=m.DocFormat.TXT,
                                    storage_key="transaction-only", requirements_json={"features": [{"id": "REQ-1", "name": "订单"}]}))
            db.add(m.TestCaseAsset(id=ids["asset"], project_id=ids["a"], title="订单用例", case_type="positive", request_data={}))
            db.add(m.TestRun(id=ids["run"], project_id=ids["a"], user_id=ids["qa"], source_type=m.SourceType.UPLOAD))
            await db.flush()
            db.add(m.TestCase(id=ids["case"], test_run_id=ids["run"], case_asset_id=ids["asset"], case_type="api",
                             case_name="订单接口", request_data={"method": "POST", "url": "/orders"}, api_path="/orders", http_method="POST"))
            await db.flush()
            db.add(m.TestResult(id=ids["result"], test_run_id=ids["run"], test_case_id=ids["case"], case_type="api", is_passed=False, status_code=500))
            await db.commit()

            async def isolated_db():
                db.info.pop("project_scope", None)
                try:
                    yield db
                except Exception:
                    await db.rollback()
                    raise
                finally:
                    db.info.pop("project_scope", None)

            app.dependency_overrides[get_db_session] = isolated_db
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://verify") as client:
                async def call(actor, method, path, *, payload=None, params=None, expected=200):
                    response = await client.request(method, path, json=payload, params=params,
                                                     headers={"Authorization": "Bearer " + tokens[actor]})
                    assert response.status_code in (expected if isinstance(expected, tuple) else (expected,)), response.text
                    return response.json().get("data", response.json())

                project = str(ids["a"])
                metadata = await call("qa", "GET", "/api/defects/metadata", params={"project_id": project})
                assert metadata["can_create"] and not metadata["can_configure"]
                module = await call("manager", "POST", f"/api/projects/{project}/modules", payload={"name": "订单"})
                release = await call("manager", "POST", f"/api/projects/{project}/releases", payload={"name": "v1.0", "build_ref": "build1"})
                await call("qa", "POST", f"/api/projects/{project}/modules", payload={"name": "越权模块"}, expected=403)
                foreign_module = await call("outsider", "POST", f"/api/projects/{ids['b']}/modules", payload={"name": "项目 B"})
                payload = {"project_id": project, "title": "订单金额错误", "description": "优惠未正确生效", "severity": "P1",
                           "priority": "high", "module_id": module["id"], "reproduce_steps": ["登录", "提交订单"],
                           "expected_result": "金额正确", "actual_result": "金额偏高", "labels": ["回归"],
                           "affected_release_ids": [release["id"]], "references": [
                               {"kind": "requirement", "requirement_doc_id": str(ids["doc"]), "requirement_item_key": "REQ-1"},
                               {"kind": "case", "case_asset_id": str(ids["asset"])}], "creation_request_id": str(uuid4())}
                defect = await call("qa", "POST", "/api/defects", payload=payload)
                defect_id = defect["id"]
                assert defect["workflow_state"] == "new" and defect["status_code"] == "open"
                assert len(defect["references"]) == 2 and defect["affected_release_ids"] == [release["id"]]
                retry = await call("qa", "POST", "/api/defects", payload=payload)
                assert retry["id"] == defect_id
                await call("manager", "PATCH", f"/api/projects/{project}/modules/{module['id']}", payload={"name": "订单", "is_active": False})
                await call("manager", "PATCH", f"/api/projects/{project}/releases/{release['id']}", payload={"name": "v1.0", "status": "archived"})
                defect = await call("manager", "PUT", f"/api/defects/{defect_id}", payload={
                    "expected_version": defect["row_version"], "description": "补充证据但保留历史目录", "module_id": module["id"], "affected_release_ids": [release["id"]]})
                assert defect["module_id"] == module["id"] and defect["affected_release_ids"] == [release["id"]]
                await call("manager", "PATCH", f"/api/projects/{project}/modules/{module['id']}", payload={"name": "订单", "is_active": True})
                await call("manager", "PATCH", f"/api/projects/{project}/releases/{release['id']}", payload={"name": "v1.0", "status": "released"})
                await call("qa", "POST", "/api/defects", payload={**payload, "title": "请求号复用"}, expected=409)
                await call("qa", "POST", "/api/defects", payload={**payload, "source": "pipeline"}, expected=422)
                await call("qa", "POST", "/api/defects", payload={**payload, "creation_request_id": str(uuid4()), "module_id": foreign_module["id"]}, expected=(403, 404, 422))
                await call("reader", "POST", "/api/defects", payload=payload, expected=403)
                await call("outsider", "GET", "/api/defects/" + defect_id, expected=404)
                await call("qa", "POST", f"/api/defects/{defect_id}/assign", payload={"assignee_id": str(ids["dev"]), "expected_version": defect["row_version"], "request_id": str(uuid4())}, expected=403)

                async def move(actor, action, fields=None, note="", expected=200, request=None):
                    nonlocal defect
                    body = request or {"action_id": action, "expected_version": defect["row_version"], "request_id": str(uuid4()), "fields": fields or {}, "note": note}
                    response = await call(actor, "POST", f"/api/defects/{defect_id}/transitions", payload=body, expected=expected)
                    if expected == 200:
                        defect = response["detail"]
                    return response, body

                await move("manager", "close", expected=422)
                await move("manager", "triage")
                assigned = await call("manager", "POST", f"/api/defects/{defect_id}/assign", payload={
                    "assignee_id": str(ids["dev"]), "verifier_id": str(ids["qa"]), "expected_version": defect["row_version"], "request_id": str(uuid4())})
                defect = assigned["detail"]
                await move("dev", "start")
                await call("qa", "PUT", f"/api/defects/{defect_id}", payload={"expected_version": 1, "description": "旧版本覆盖"}, expected=409)
                await move("dev", "submit_fix", {"fix_available": True}, "已修复", expected=422)
                await move("dev", "submit_fix", {"fix_build": "build1", "fix_available": True, "verifier_id": str(ids["dev"])}, "自验", expected=422)
                _, submit_request = await move("dev", "submit_fix", {"fix_build": "build1", "fix_available": True, "verifier_id": str(ids["qa"])}, "调整优惠计算")
                old_version = defect["row_version"]
                replay, _ = await move("dev", "submit_fix", request=submit_request)
                assert replay["row_version"] == old_version
                assert defect["workflow_state"] == "pending_verification" and not defect["is_resolved"]
                transferred = await call("manager", "POST", f"/api/defects/{defect_id}/assign", payload={
                    "verifier_id": str(ids["dev"]), "expected_version": defect["row_version"], "request_id": str(uuid4()), "note": "模拟转派不能绕过本人验证限制"})
                defect = transferred["detail"]
                await move("dev", "verify_pass", {"verified_build": "build1"}, "转派后的自验", expected=403)
                transferred = await call("manager", "POST", f"/api/defects/{defect_id}/assign", payload={
                    "verifier_id": str(ids["qa"]), "expected_version": defect["row_version"], "request_id": str(uuid4()), "note": "交由测试人员验证"})
                defect = transferred["detail"]
                await move("qa", "verify_fail", {"actual_result": "边界金额仍不正确"}, "首次验证失败")
                assert defect["workflow_state"] == "reopened" and defect["reopened_count"] == 1 and not defect["fix_build"]
                await move("dev", "resume")
                await move("dev", "submit_fix", {"fix_build": "build2", "fix_available": True, "verifier_id": str(ids["qa"])}, "补齐边界处理")
                await move("qa", "verify_pass", {"verified_build": "build2"}, "回归通过")
                assert defect["is_resolved"] and defect["resolved_at"] and defect["resolution"] == "fixed"
                await move("qa", "close")
                assert defect["workflow_state"] == "closed"
                await move("qa", "reopen", note="另一个输入场景出现同类问题")
                assert defect["reopened_count"] == 2 and defect["first_resolved_at"] and not defect["resolved_at"]
                assert defect["reproduce_steps"] == ["登录", "提交订单"]
                await move("manager", "reject", {"resolution": "not_a_bug"}, "核对后属于规则预期")
                await move("manager", "reopen", note="规则已变更，重新受理")
                listing = await call("qa", "GET", "/api/defects", params={"project_id": project})
                assert listing["total"] == 1 and listing["stats"]["by_severity"]["P1"] == 1
                events = await call("qa", "GET", f"/api/defects/{defect_id}/events")
                assert any(item["event_type"] == "submit_fix" and item["note"] == "调整优惠计算" for item in events["items"])
                assert len([item for item in events["items"] if item["event_type"] == "submit_fix"]) == 2
                duplicates = await call("qa", "GET", "/api/defects/duplicates", params={"project_id": project, "title": payload["title"]})
                assert duplicates["items"][0]["id"] == defect_id
                trace = await call("qa", "GET", f"/api/cases/{ids['asset']}/traceability")
                assert any(item["id"] == defect_id for item in trace["defects"])
                trend = await call("qa", "GET", "/api/trend/defect", params={"project_id": project})
                assert sum(trend["totals"]) == 1
                dashboard = await call("qa", "GET", "/api/dashboard/defect-trend")
                assert sum(dashboard["totals"]) >= 1
                other = await call("outsider", "GET", "/api/defects")
                assert all(item["id"] != defect_id for item in other["list"])
                await call("manager", "DELETE", f"/api/defects/{defect_id}", params={"expected_version": defect["row_version"]})
                assert (await call("qa", "GET", "/api/defects", params={"project_id": project}))["total"] == 0
                deleted = await call("manager", "GET", f"/api/defects/{defect_id}")
                assert deleted["deleted_at"] and deleted["permissions"]["restore"]
                restored = await call("manager", "POST", f"/api/defects/{defect_id}/restore", params={"expected_version": deleted["row_version"]})
                assert restored["deleted_at"] is None

                db.info.pop("project_scope", None)
                raw = {"defects": [{"case_id": str(ids["case"]), "title": "AI 原始标题", "category": "program_bug", "severity": "P1", "reproduction_steps": ["请求接口"]}]}
                assert await persist_defects_to_db(ids["run"], raw, ids["a"], db) == 1
                await db.commit()
                pipeline_defect = (await db.execute(select(m.Defect).where(m.Defect.test_run_id == ids["run"]))).scalar_one()
                pipeline_id = pipeline_defect.id
                pipeline_defect.description = "人工补充的关键证据"
                await db.commit()
                raw["defects"][0]["title"] = "AI 重新措辞后不同的标题"
                assert await persist_defects_to_db(ids["run"], raw, ids["a"], db) == 0
                await db.commit()
                unchanged = (await db.execute(select(m.Defect).where(m.Defect.id == pipeline_id))).scalar_one()
                assert unchanged.description == "人工补充的关键证据" and unchanged.title == "AI 原始标题"
                assert (await db.execute(select(func.count()).select_from(m.DefectOccurrence).where(m.DefectOccurrence.defect_id == pipeline_id))).scalar_one() == 1
                assert await persist_defects_to_db(ids["run"], {"defects": [{"case_id": "invalid", "title": "无法追溯的建议"}]}, ids["a"], db) == 0
                related_case_id = uuid4()
                db.add(m.TestCase(id=related_case_id, test_run_id=ids["run"], case_type="api", case_name="同根因的另一个失败", request_data={}))
                await db.flush()
                db.add(m.TestResult(test_run_id=ids["run"], test_case_id=related_case_id, case_type="api", is_passed=False, status_code=500))
                await db.commit()
                raw["defects"][0]["related_cases"] = [{"case_id": str(related_case_id), "case_name": "关联失败"}]
                assert await persist_defects_to_db(ids["run"], raw, ids["a"], db) == 1
                await db.commit()
                raw["defects"][0]["case_id"] = str(related_case_id)
                raw["defects"][0]["related_cases"] = [{"case_id": str(ids["case"])}]
                assert await persist_defects_to_db(ids["run"], raw, ids["a"], db) == 0
                assert (await db.execute(select(func.count()).select_from(m.DefectOccurrence).where(m.DefectOccurrence.test_run_id == ids["run"]))).scalar_one() == 2
                from app.api.auth import apply_delete_user
                deletion = await apply_delete_user(db, ids["dev"])
                assert deletion["soft"]
                await db.commit()
                assert not (await db.get(m.User, ids["dev"])).is_active
                participants = await call("qa", "GET", "/api/defects/participants", params={"project_id": project})
                assert all(item["id"] != str(ids["dev"]) for item in participants["items"])
                # 重复结果只关联同项目主缺陷，不能指向自身，也不能构成循环。
                defect = restored
                main = await call("manager", "POST", "/api/defects", payload={"project_id": project,
                    "title": "独立主缺陷", "description": "用于验证重复关系", "creation_request_id": str(uuid4())})
                foreign = await call("outsider", "POST", "/api/defects", payload={"project_id": str(ids["b"]),
                    "title": "外部项目缺陷", "description": "不可关联到项目 A", "creation_request_id": str(uuid4())})
                await move("manager", "reject", {"resolution": "duplicate", "duplicate_of_id": defect_id}, "不可重复自身", expected=422)
                await move("manager", "reject", {"resolution": "duplicate", "duplicate_of_id": foreign["id"]}, "不可跨项目重复", expected=422)
                await move("manager", "reject", {"resolution": "duplicate", "duplicate_of_id": main["id"]}, "确认与主缺陷相同")
                assert defect["resolution"] == "duplicate" and not defect["is_resolved"]
                await call("manager", "POST", f"/api/defects/{main['id']}/transitions", payload={
                    "action_id": "reject", "expected_version": main["row_version"], "request_id": str(uuid4()),
                    "note": "不能反向构成循环", "fields": {"resolution": "duplicate", "duplicate_of_id": defect_id}}, expected=422)
                unchanged_main = await call("manager", "GET", f"/api/defects/{main['id']}")
                assert unchanged_main["workflow_state"] == "new" and unchanged_main["duplicate_of_id"] is None
            app.dependency_overrides.pop(get_db_session, None)
        await transaction.rollback()
    await engine.dispose()
