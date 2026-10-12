"""人工录入的 HTTP 校验、真实 SQL 持久化和项目边界回归；仅使用内存 SQLite。"""
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api import case_library as api
from app.models import database as m
from app.modules.auth.access_policy import authorize_request
from app.modules.auth.dependencies import get_current_user
from app.schemas.case_library import CreateManualCaseRequest
from app.utils.database import get_db_session


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@compiles(PGUUID, "sqlite")
def sqlite_uuid(element, compiler, **kw):
    return "CHAR(32)"


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session
        self.info = session.info

    async def execute(self, statement):
        return self.session.execute(statement)

    async def flush(self):
        self.session.flush()

    def add(self, item):
        self.session.add(item)


@pytest.fixture
def manual_env():
    engine = create_engine("sqlite://")
    tables = [m.User, m.Project, m.ProjectMember, m.RequirementDoc, m.TestCaseAsset,
              m.TestCaseAssetVersion, m.TestPlan, m.TestPlanCase, m.TestPlanRevision,
              m.TestPlanRevisionCase, m.TestRun, m.TestCase, m.TestResult, m.Defect, m.DefectReference]
    # 仅转换测试库 DDL；序列编号、JSONB 默认值由真实 PostgreSQL 验收覆盖。
    metadata = MetaData()
    for table in m.Base.metadata.tables.values():
        table.to_metadata(metadata)
    for model in tables:
        for column in metadata.tables[model.__tablename__].columns:
            if column.server_default is not None:
                column.server_default = None
    metadata.create_all(engine, tables=[metadata.tables[model.__tablename__] for model in tables])
    session = Session(engine)
    user = m.User(id=uuid4(), username="manual-tester", email="tester@example.test",
                  hashed_password="unused", role=m.UserRole.TESTER)
    other = m.User(id=uuid4(), username="other", email="other@example.test",
                   hashed_password="unused", role=m.UserRole.TESTER)
    project = m.Project(id=uuid4(), name="订单", owner_id=user.id, source_type=m.SourceType.UPLOAD)
    foreign = m.Project(id=uuid4(), name="其他项目", owner_id=other.id, source_type=m.SourceType.UPLOAD)
    document = m.RequirementDoc(id=uuid4(), project_id=project.id, filename="订单需求.md",
                               format=m.DocFormat.TXT, storage_key="unused", parse_engine="rule")
    hidden_doc = m.RequirementDoc(id=uuid4(), project_id=foreign.id, filename="其他需求.md",
                                 format=m.DocFormat.TXT, storage_key="unused")
    session.add_all([user, other, project, foreign, document, hidden_doc])
    session.commit()
    db = AsyncSessionAdapter(session)
    app = FastAPI(dependencies=[Depends(authorize_request)])
    app.include_router(api.router, prefix="/api/cases")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: db
    @app.middleware("http")
    async def inject_test_identity(request, call_next):
        # 全局授权直接调用认证函数，使用其已有的 request.state 缓存注入测试身份。
        request.state.current_user = user
        return await call_next(request)
    yield SimpleNamespace(app=app, db=db, user=user, project=project, foreign=foreign,
                          document=document, hidden_doc=hidden_doc)
    session.close()
    engine.dispose()


def payload(env, **overrides):
    return {"project_id": str(env.project.id), "title": "  订单提交  ", "folder": "订单 / 提交",
            "preconditions": "  用户已登录\n购物车有商品  ", "steps": ["  打开购物车  ", "提交订单"],
            "expected_result": "  返回订单编号  ", "tags": [" 冒烟 ", "冒烟", "订单"],
            "requirement_doc_id": str(env.document.id), "requirement_ref": "REQ-102", **overrides}


@pytest.mark.asyncio
async def test_manual_case_persists_ordered_content_version_and_requirement(manual_env):
    env = manual_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test") as client:
        response = await client.post("/api/cases", json=payload(env))
    assert response.status_code == 200, response.text
    asset = response.json()["data"]
    assert asset["title"] == "订单提交"
    assert asset["source"] == "manual" and asset["execution_kind"] == "manual"
    assert asset["review_state"] == "draft" and asset["status"] == "draft"
    assert asset["tags"] == ["冒烟", "订单"]
    assert asset["request_data"]["steps"] == ["打开购物车", "提交订单"]
    assert asset["request_data"]["preconditions"] == "用户已登录\n购物车有商品"
    assert asset["request_data"]["requirement_doc_id"] == str(env.document.id)
    assert asset["expected_result"] == {"text": "返回订单编号"}
    version = env.db.session.scalar(select(m.TestCaseAssetVersion))
    assert version.version == 1 and version.change_type == "created"
    assert version.snapshot["request_data"] == asset["request_data"]
    assert version.changed_by == env.user.id


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"title": "  "}, {"steps": []}, {"steps": ["正常步骤", " "]},
    {"steps": ["x" * 5001]}, {"expected_result": "\n "},
    {"priority": "P9"}, {"case_type": "unknown"}, {"tags": ["x" * 41]},
    {"project_id": "invalid"}, {"folder": "x" * 201},
])
async def test_invalid_input_never_writes_assets(manual_env, overrides):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=manual_env.app), base_url="http://test") as client:
        response = await client.post("/api/cases", json=payload(manual_env, **overrides))
    assert response.status_code == 422
    assert manual_env.db.session.scalar(select(func.count()).select_from(m.TestCaseAsset)) == 0


@pytest.mark.asyncio
async def test_duplicate_requires_confirmation_and_preserves_existing_case(manual_env):
    env = manual_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test") as client:
        first = await client.post("/api/cases", json=payload(env))
        duplicate = await client.post("/api/cases", json=payload(env, title="订单提交"))
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "CASE_DUPLICATE"
        assert duplicate.json()["detail"]["duplicates"][0]["id"] == first.json()["data"]["id"]
        assert env.db.session.scalar(select(func.count()).select_from(m.TestCaseAsset)) == 1
        confirmed = await client.post("/api/cases", json=payload(env, allow_duplicate=True))
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["id"] != first.json()["data"]["id"]
    assert env.db.session.scalar(select(func.count()).select_from(m.TestCaseAssetVersion)) == 2


@pytest.mark.asyncio
async def test_cross_project_requirement_and_project_writes_are_rejected(manual_env):
    env = manual_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test") as client:
        foreign_doc = await client.post("/api/cases", json=payload(env, requirement_doc_id=str(env.hidden_doc.id)))
        foreign_project = await client.post("/api/cases", json=payload(env, project_id=str(env.foreign.id)))
    # 全局项目边界先于业务校验执行，不向调用者泄露外部需求文档是否存在。
    assert foreign_doc.status_code == 404
    assert foreign_project.status_code == 403
    assert env.db.session.scalar(select(func.count()).select_from(m.TestCaseAsset)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [m.UserRole.VIEWER, m.UserRole.DEVELOPER, m.UserRole.AUDITOR])
async def test_non_editor_roles_cannot_create(manual_env, role):
    manual_env.user.role = role
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=manual_env.app), base_url="http://test") as client:
        response = await client.post("/api/cases", json=payload(manual_env))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_options_and_traceability_return_current_project_content(manual_env):
    env = manual_env
    asset = (await api.create_manual_case(CreateManualCaseRequest(**payload(env)), env.user, env.db))["data"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test") as client:
        options = await client.get("/api/cases/manual/options", params={"project_id": str(env.project.id)})
        denied = await client.get("/api/cases/manual/options", params={"project_id": str(env.foreign.id)})
    assert options.status_code == 200
    assert options.json()["data"]["folders"] == ["订单 / 提交"]
    assert options.json()["data"]["requirements"] == [{"id": str(env.document.id), "filename": "订单需求.md"}]
    assert denied.status_code == 403
    from uuid import UUID
    trace = await api.get_case_traceability(UUID(asset["id"]), env.user, env.db)
    assert trace["data"]["source"]["requirement"]["filename"] == "订单需求.md"
    assert trace["data"]["source"]["created_by_name"] == "manual-tester"
    assert trace["data"]["source"]["generation_context"] == {"channel": "manual_entry"}
    assert trace["data"]["recent_runs"] == []
