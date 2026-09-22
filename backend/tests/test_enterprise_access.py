"""真实路由认证矩阵与 SQLite 数据隔离测试，不连接线上数据库。"""
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, update, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Session, aliased

from app.models import database as m
from app.modules.auth import access_policy as policy
from app.modules.auth.project_scope import ProjectScope
from app.modules.auth.report_sharing import create_report_token, verify_report_token


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@compiles(PGUUID, "sqlite")
def sqlite_uuid(element, compiler, **kw):
    return "CHAR(32)"


@pytest.fixture
def scoped_db():
    engine = create_engine("sqlite://")
    tables = [m.User, m.Project, m.ProjectMember, m.TestRun, m.TestReport, m.TestCaseAsset,
              m.TestPlan, m.TestPlanCase, m.KnowledgeChunk, m.KnowledgeConversation, m.KnowledgeMessage]
    m.Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    session = Session(engine)
    user_id, other_id, project_a, project_b = [uuid4() for _ in range(4)]
    session.add_all([
        m.User(id=user_id, username="one", email="one@example.test", hashed_password="unused", role=m.UserRole.TESTER),
        m.User(id=other_id, username="two", email="two@example.test", hashed_password="unused", role=m.UserRole.TESTER),
        m.Project(id=project_a, name="allowed", owner_id=user_id, source_type=m.SourceType.UPLOAD),
        m.Project(id=project_b, name="hidden", owner_id=other_id, source_type=m.SourceType.UPLOAD),
    ])
    run_a, run_b = uuid4(), uuid4()
    session.add_all([
        m.TestRun(id=run_a, project_id=project_a, user_id=user_id, source_type=m.SourceType.UPLOAD),
        m.TestRun(id=run_b, project_id=project_b, user_id=other_id, source_type=m.SourceType.UPLOAD),
        m.TestReport(id=uuid4(), test_run_id=run_a, quality_score=90, report_data={}),
        m.TestReport(id=uuid4(), test_run_id=run_b, quality_score=10, report_data={}),
    ])
    session.commit()
    session.expunge_all()
    session.info["project_scope"] = ProjectScope(user_id, (project_a,), (project_a,))
    yield session, user_id, project_a, project_b, run_a, run_b
    session.close()
    engine.dispose()


def test_lists_aggregate_aliases_and_indirect_report_are_scoped(scoped_db):
    db, user_id, project_a, project_b, run_a, run_b = scoped_db
    assert db.scalars(select(m.Project.id)).all() == [project_a]
    assert db.scalar(select(func.count()).select_from(m.TestRun)) == 1
    assert db.scalar(select(func.avg(m.TestReport.quality_score))) == 90
    assert db.scalars(select(m.TestReport.test_run_id)).all() == [run_a]
    alias = aliased(m.TestRun)
    assert db.scalars(select(alias.id)).all() == [run_a]
    assert db.get(m.TestRun, run_b) is None


def test_new_scope_does_not_reuse_previous_users_query_cache(scoped_db):
    db, user_id, project_a, project_b, run_a, run_b = scoped_db
    assert db.scalars(select(m.TestRun.id)).all() == [run_a]
    db.info["project_scope"] = ProjectScope(uuid4(), (project_b,), ())
    assert db.scalars(select(m.TestRun.id)).all() == [run_b]


def test_bulk_mutation_cannot_touch_other_project(scoped_db):
    db, _, project_a, project_b, *_ = scoped_db
    assert db.execute(update(m.Project).where(m.Project.id == project_b).values(name="stolen")).rowcount == 0
    assert db.execute(update(m.Project).where(m.Project.id == project_a).values(name="mine")).rowcount == 1


def test_insertion_or_repointing_to_other_project_is_rejected(scoped_db):
    db, user_id, project_a, project_b, *_ = scoped_db
    db.add(m.TestPlan(id=uuid4(), project_id=project_b, name="injected"))
    with pytest.raises(HTTPException) as error:
        db.flush()
    assert error.value.status_code == 403
    db.rollback()
    project = db.get(m.Project, project_a)
    db.info["project_scope"] = ProjectScope(user_id, (project_a,), ())
    project.name = "read-only write"
    with pytest.raises(HTTPException):
        db.flush()


def test_scoped_session_rejects_raw_sql(scoped_db):
    with pytest.raises(HTTPException):
        scoped_db[0].execute(text("SELECT * FROM projects"))


def test_share_tokens_expire_are_report_bound_and_not_login_tokens():
    from datetime import datetime, timedelta
    from jose import jwt
    from app.config import settings
    from app.modules.auth.auth_service import AuthService
    token = create_report_token("run-a", "nonce")
    assert verify_report_token(token, "run-a", "nonce")["purpose"] == "report_share"
    assert AuthService.verify_token(token) is None
    for run_id, nonce in [("run-b", "nonce"), ("run-a", "revoked")]:
        with pytest.raises(HTTPException):
            verify_report_token(token, run_id, nonce)
    expired = jwt.encode({"purpose": "report_share", "run_id": "run-a", "nonce": "nonce",
                          "exp": datetime.utcnow() - timedelta(seconds=1)}, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(HTTPException):
        verify_report_token(expired, "run-a")


@pytest.mark.asyncio
async def test_every_registered_business_route_requires_authentication():
    from app.main import app
    from app.utils.database import get_db_session
    async def fake_db():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = fake_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            checked = 0
            for route in app.routes:
                if not route.path.startswith("/api/"):
                    continue
                for method in route.methods:
                    if (method, route.path) in policy.PUBLIC_ROUTES | policy.CREDENTIAL_ROUTES:
                        continue
                    path = route.path
                    for name in route.param_convertors:
                        path = path.replace("{" + name + "}", str(uuid4()))
                    response = await client.request(method, path, json={} if method in {"POST", "PUT", "PATCH"} else None)
                    assert response.status_code == 401, (method, path, response.status_code, response.text)
                    checked += 1
            assert checked >= 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("role", [m.UserRole.VIEWER, m.UserRole.AUDITOR])
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/scheduled-tasks"), ("DELETE", "/api/scheduled-tasks/{task_id}"),
    ("POST", "/api/scripts/generate"), ("POST", "/api/reports/{run_id}/generate"),
    ("GET", "/api/models/configs"), ("GET", "/api/reports/{run_id}/share"),
])
def test_read_only_role_cannot_trigger_business_mutations(role, method, path):
    with pytest.raises(HTTPException) as error:
        policy.enforce_role(SimpleNamespace(role=role), method, path)
    assert error.value.status_code == 403


def test_audit_and_personal_actions_have_separate_permissions():
    with pytest.raises(HTTPException):
        policy.enforce_role(SimpleNamespace(role=m.UserRole.VIEWER), "GET", "/api/audit")
    policy.enforce_role(SimpleNamespace(role=m.UserRole.AUDITOR), "GET", "/api/audit")
    policy.enforce_role(SimpleNamespace(role=m.UserRole.VIEWER), "POST", "/api/knowledge/conversations")
    policy.enforce_role(SimpleNamespace(role=m.UserRole.VIEWER), "POST", "/api/notifications/read-all")


def test_production_rejects_development_credentials_and_handles_url_passwords():
    from app.config import Settings
    config = Settings(APP_ENV="production", APP_DEBUG=True, SECRET_KEY="short",
                      AES_ENCRYPTION_KEY="0" * 32, POSTGRES_PASSWORD="short")
    with pytest.raises(RuntimeError):
        config.validate_production()
    secure = Settings(APP_ENV="production", APP_DEBUG=False, SECRET_KEY="a" * 48,
        AES_ENCRYPTION_KEY="b" * 32, POSTGRES_PASSWORD="pass@word:/+?123456789",
        REDIS_PASSWORD="c" * 24, RABBITMQ_PASSWORD="d" * 24, MINIO_SECRET_KEY="e" * 24)
    secure.validate_production()
    assert "pass%40word%3A%2F%2B%3F123456789" in secure.database_url


@pytest.mark.asyncio
async def test_unsigned_alternative_entrypoints_are_closed():
    from app.main import app
    from app.utils.database import get_db_session
    async def fake_db():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = fake_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for method, path in (("POST", "/api/webhook/trigger"),
                ("GET", f"/api/webhook/ci-result/{uuid4()}"),
                ("GET", f"/api/reports/{uuid4()}/share-view")):
                response = await client.request(method, path)
                assert response.status_code == 401
            response = await client.post("/api/webhook/github", json={})
            assert response.status_code in {401, 503}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_scheduled_execution_rechecks_disabled_actor(monkeypatch):
    from unittest.mock import MagicMock
    from app.modules.scheduler import executor
    user_id, project_id, task_id = uuid4(), uuid4(), uuid4()
    task = SimpleNamespace(project_id=project_id, created_by=user_id)
    project = SimpleNamespace(owner_id=user_id)
    actor = SimpleNamespace(id=user_id, is_active=False, role=m.UserRole.TESTER)
    db = AsyncMock()
    db.execute.side_effect = [MagicMock(scalar_one_or_none=lambda value=value: value)
                             for value in (task, project, actor)]
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(executor, "AsyncSessionLocal", lambda: context)
    result = await executor.execute_scheduled_chain(str(task_id))
    assert result["status"] == "failed"
    assert result["test_run_id"] is None
    assert "执行权限" in result["error"]
