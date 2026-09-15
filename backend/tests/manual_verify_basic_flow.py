"""在真实服务上验收：需求草稿 → 评审 → API 计划 → 执行结果。"""

import asyncio
import uuid

import httpx
from sqlalchemy import select

from app.models.database import (
    DocFormat, DocStatus, Project, RequirementDoc, SourceType,
    TestResult, TestRun, TestStatus, User, UserRole,
)
from app.modules.auth.auth_service import AuthService
from app.utils.database import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.role == UserRole.SUPER_ADMIN).limit(1))).scalar_one()
        project = Project(name=f"基础闭环验收 {uuid.uuid4().hex[:8]}", owner_id=user.id,
                          source_type=SourceType.UPLOAD,
                          source_config={"target_service_url": "http://aitp-java-sample:8204"})
        db.add(project)
        await db.flush()
        doc = RequirementDoc(project_id=project.id, uploader_id=user.id,
                             filename="订单需求.txt", format=DocFormat.TXT, storage_key="/tmp/basic-flow.txt",
                             status=DocStatus.PARSED, parse_engine="rule_degraded",
                             requirements_json={"total": 1, "items": [{
                                 "rid": "FR-1", "title": "查询订单", "priority": "P1",
                                 "description": "按编号查询订单", "test_points": ["查询现有订单"],
                                 "acceptance_criteria": ["返回订单详情"],
                             }]})
        db.add(doc)
        await db.commit()
        project_id, doc_id = str(project.id), str(doc.id)
        token = AuthService.create_access_token(user_id=str(user.id), username=user.username,
                                                role=user.role.value)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30,
                                 headers={"Authorization": f"Bearer {token}"}) as client:
        async def call(method: str, path: str, payload: dict | None = None,
                       expected_status: int = 200) -> dict:
            response = await client.request(method, path, json=payload)
            assert response.status_code == expected_status, (path, response.status_code, response.text[:500])
            return response.json()

        first = await call("POST", f"/api/requirements/{doc_id}/generate-cases", {"use_ai": False})
        second = await call("POST", f"/api/requirements/{doc_id}/generate-cases", {"use_ai": False})
        assert first["data"]["assets_created"] == 1 and second["data"]["assets_created"] == 0
        case_id = first["data"]["case_ids"][0]
        case = (await call("GET", f"/api/cases/{case_id}"))["data"]
        assert case["execution_kind"] == "manual" and "status_code" not in case["expected_result"]

        plan = (await call("POST", "/api/plans", {"project_id": project_id,
                                                   "name": "基础 API 验收计划"}))["data"]
        plan_id = plan["id"]
        await call("POST", f"/api/cases/{case_id}/submit-review")
        await call("POST", f"/api/cases/{case_id}/review", {"decision": "approve"})
        await call("POST", f"/api/plans/{plan_id}/cases", {"case_asset_ids": [case_id]}, 422)

        await call("PUT", f"/api/cases/{case_id}", {
            "execution_kind": "api", "request_data": {"method": "GET", "url": "/orders/1",
                                                     "related_requirement": "FR-1", "requirement_doc_id": doc_id},
            "expected_result": {"status_code": 200},
        })
        changed = (await call("GET", f"/api/cases/{case_id}"))["data"]
        assert changed["status"] == "draft" and changed["review_state"] == "draft"
        await call("POST", f"/api/cases/{case_id}/submit-review")
        await call("POST", f"/api/cases/{case_id}/review",
                   {"decision": "changes_requested", "comment": "请确认断言"})
        await call("PUT", f"/api/cases/{case_id}", {"description": "已确认状态码断言"})
        await call("POST", f"/api/cases/{case_id}/submit-review")
        await call("POST", f"/api/cases/{case_id}/review", {"decision": "approve"})
        events = (await call("GET", f"/api/cases/{case_id}/review-events"))["data"]
        assert [event["action"] for event in events].count("approve") == 2
        assert any(event["comment"] == "请确认断言" for event in events)

        await call("POST", f"/api/plans/{plan_id}/cases", {"case_asset_ids": [case_id]})
        await call("POST", f"/api/plans/{plan_id}/publish")
        dispatched = (await call("POST", f"/api/plans/{plan_id}/execute", {
            "target_service_url": "http://aitp-java-sample:8204"}))
        run_id = dispatched["data"]["test_run_id"]
        for _ in range(90):
            await asyncio.sleep(2)
            run = (await call("GET", f"/api/test-runs/{run_id}"))["data"]
            if run["status"] in {"completed", "failed", "cancelled"}:
                assert run["status"] == "completed", run
                break
        else:
            raise AssertionError("计划执行超时")

    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(TestRun).where(TestRun.id == uuid.UUID(run_id)))).scalar_one()
        results = (await db.execute(select(TestResult).where(TestResult.test_run_id == run.id))).scalars().all()
        assert run.status == TestStatus.COMPLETED
        assert len(results) == 1 and results[0].is_passed and results[0].status_code == 200
    print({"project_id": project_id, "case_id": case_id, "plan_id": plan_id,
           "test_run_id": run_id, "review_events": len(events), "api_status": 200}, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
