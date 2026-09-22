"""可选 PostgreSQL 集成验收，仅接受专用临时数据库，CI 开启。

ENTERPRISE_ACCESS_INTEGRATION=true POSTGRES_DB=aitp_security_test_ci pytest ...
"""
import os
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.models import database as m
from app.modules.auth.auth_service import AuthService

pytestmark = pytest.mark.skipif(os.getenv("ENTERPRISE_ACCESS_INTEGRATION") != "true",
                                reason="需要显式指定隔离 PostgreSQL 数据库")


@pytest.mark.asyncio
async def test_postgres_project_authorization_end_to_end(monkeypatch):
    assert settings.POSTGRES_DB.startswith("aitp_security_test_"), "绝不能在业务数据库中运行此测试"
    from app.utils import database
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    async_engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
    AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "_current_session_maker", AsyncSessionLocal)
    from app.main import app
    from app.api import report as report_api
    async with async_engine.begin() as connection:
        await connection.run_sync(m.Base.metadata.create_all)
    ids = {key: uuid4() for key in ("admin", "manager", "reader", "outsider", "a", "b", "run_a", "run_b")}
    roles = {"admin": m.UserRole.SUPER_ADMIN, "manager": m.UserRole.TEST_MANAGER,
             "reader": m.UserRole.VIEWER, "outsider": m.UserRole.TESTER}
    async with AsyncSessionLocal() as db:
        for name, role in roles.items():
            db.add(m.User(id=ids[name], username=f"access_{name}_{ids[name].hex[:8]}",
                          email=f"{ids[name]}@test.invalid", hashed_password="unused", role=role))
        await db.flush()
        db.add_all([
            m.Project(id=ids["a"], name="scope-a", owner_id=ids["manager"], source_type=m.SourceType.UPLOAD),
            m.Project(id=ids["b"], name="scope-b", owner_id=ids["admin"], source_type=m.SourceType.UPLOAD),
        ])
        await db.flush()
        db.add(m.ProjectMember(project_id=ids["a"], user_id=ids["reader"], access="read"))
        for name in ("a", "b"):
            db.add(m.TestRun(id=ids[f"run_{name}"], project_id=ids[name], user_id=ids["manager"],
                            source_type=m.SourceType.UPLOAD, status=m.TestStatus.COMPLETED))
        await db.flush()
        for name in ("a", "b"):
            db.add(m.TestReport(test_run_id=ids[f"run_{name}"], report_data={}, quality_score=90,
                                html_path=f"{name}.html", share_token=uuid4().hex))
        await db.commit()
    tokens = {name: {"Authorization": "Bearer " + AuthService.create_access_token(str(ids[name]), name, role.value)}
              for name, role in roles.items()}
    monkeypatch.setattr(report_api, "_load_report_html", AsyncMock(return_value="<html>shared report</html>"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def call(method, path, role="reader", expected=200, **kwargs):
            response = await client.request(method, path, headers=tokens[role], **kwargs)
            assert response.status_code == expected, (method, path, response.status_code, response.text)
            return response.json()

        projects = await call("GET", "/api/projects")
        assert [p["id"] for p in projects["data"]["items"]] == [str(ids["a"])]
        await call("GET", f'/api/projects/{ids["b"]}', expected=403)
        await call("GET", f'/api/test-runs/{ids["run_b"]}/progress', expected=404)
        await call("GET", f'/api/reports/{ids["run_b"]}', expected=404)
        await call("GET", f'/api/reports/{ids["run_a"]}')
        stats = await call("GET", "/api/dashboard/statistics")
        assert stats["data"]["total_runs"] == 1
        outsider_stats = await call("GET", "/api/dashboard/statistics", role="outsider")
        assert outsider_stats["data"]["total_runs"] == 0
        for path in ("/api/dashboard/statistics", "/api/dashboard/recent-runs", "/api/dashboard/quality-trend",
                     "/api/test-runs", "/api/reports/history", "/api/plans", "/api/cases",
                     "/api/knowledge", "/api/knowledge/documents", "/api/knowledge/terms", "/api/defects",
                     "/api/databases", "/api/scheduled-tasks", f'/api/coverage?project_id={ids["a"]}', "/api/notifications"):
            await call("GET", path)
        await call("GET", "/api/audit", expected=403)
        await call("GET", "/api/models/configs", expected=403)
        await call("POST", "/api/scripts/preview", expected=403, json={})
        await call("POST", "/api/plans", expected=403, json={"project_id": str(ids["a"]), "name": "denied"})
        await call("POST", "/api/plans", role="manager", expected=403,
                   json={"project_id": str(ids["b"]), "name": "cross-project"})
        await call("POST", "/api/plans", role="manager", json={"project_id": str(ids["a"]), "name": "allowed"})
        scheduled = await call("POST", "/api/scheduled-tasks", role="manager", json={
            "project_id": str(ids["a"]), "name": "allowed-paused", "status": "paused",
            "target_type": "case_collection", "cron_expression": "0 2 * * *",
        })
        await call("GET", f'/api/scheduled-tasks/{scheduled["data"]["id"]}', role="reader")
        await call("DELETE", f'/api/scheduled-tasks/{scheduled["data"]["id"]}', role="reader", expected=403)
        created = await call("POST", "/api/projects", role="manager", json={"name": "new-owned-project"})
        await call("GET", f'/api/projects/{created["data"]["id"]}', role="manager")
        username = f'access_outsider_{ids["outsider"].hex[:8]}'
        await call("PUT", f'/api/projects/{ids["a"]}/members', role="manager", json={"username": username, "access": "read"})
        await call("GET", f'/api/projects/{ids["a"]}', role="outsider")
        await call("POST", "/api/scheduled-tasks", role="outsider", expected=403,
                   json={"project_id": str(ids["a"]), "name": "cannot-write", "target_type": "case_collection"})
        await call("DELETE", f'/api/projects/{ids["a"]}/members/{ids["outsider"]}', role="manager")
        await call("GET", f'/api/projects/{ids["a"]}', role="outsider", expected=403)
        conversation = await call("POST", "/api/knowledge/conversations", json={"project_id": str(ids["a"])})
        cid = conversation["data"]["id"]
        await call("GET", f"/api/knowledge/conversations/{cid}")
        await call("GET", f"/api/knowledge/conversations/{cid}", role="manager", expected=404)
        await call("PATCH", f"/api/knowledge/conversations/{cid}", json={"title": "read-only user personal chat"})
        await call("DELETE", f"/api/knowledge/conversations/{cid}")
        share = await call("GET", f'/api/reports/{ids["run_a"]}/share', role="manager")
        response = await client.get(share["data"]["share_url"])
        assert response.status_code == 200
        response = await client.get(f'/api/reports/{ids["run_a"]}/share-view')
        assert response.status_code == 401
        response = await client.get(share["data"]["share_url"].replace(str(ids["run_a"]), str(ids["run_b"])))
        assert response.status_code == 401
    await async_engine.dispose()
