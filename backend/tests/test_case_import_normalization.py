"""统一用例导入格式的字段转换与校验回归。"""

from uuid import uuid4

import pytest
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.case_library import _normalize_import_row
from app.api.case_library import commit_case_import
from app.models import database as m
from app.schemas.case_library import CaseImportCommitRequest


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


def test_manual_import_keeps_detailed_fields_and_plain_expected_text():
    row = _normalize_import_row({
        "用例名称": "未登录用户无法提交订单",
        "执行类型": "手工",
        "设计类型": "异常",
        "优先级": "p1",
        "目录": "订单/提交",
        "标签": "冒烟，权限",
        "前置条件": "购物车中已有商品",
        "操作步骤": '["点击提交订单", "观察页面提示"]',
        "需求编号/链接": "REQ-102",
        "预期结果": "跳转登录页，订单未创建",
    }, 2)

    assert row["valid"] is True
    assert row["data"]["execution_kind"] == "manual"
    assert row["data"]["case_type"] == "exception"
    assert row["data"]["tags"] == ["冒烟", "权限"]
    assert row["data"]["request_data"] == {
        "preconditions": "购物车中已有商品",
        "steps": ["点击提交订单", "观察页面提示"],
        "requirement_ref": "REQ-102",
    }
    assert row["data"]["expected_result"] == {"text": "跳转登录页，订单未创建"}


def test_manual_import_rejects_missing_steps_and_expected_result():
    row = _normalize_import_row({"用例名称": "空手工用例", "执行类型": "manual"}, 3)

    assert row["valid"] is False
    assert "手工用例至少需要一个操作步骤" in row["errors"]
    assert "手工用例必须填写预期结果" in row["errors"]


def test_api_import_builds_executable_request_and_assertion():
    row = _normalize_import_row({
        "用例名称": "查询商品列表",
        "执行类型": "api",
        "请求方法": "get",
        "请求地址": "/api/products",
        "查询参数": '{"page": 1}',
        "期望状态码": 200,
    }, 4)

    assert row["valid"] is True
    assert row["data"]["request_data"]["method"] == "GET"
    assert row["data"]["request_data"]["params"] == {"page": 1}
    assert row["data"]["expected_result"]["status_code"] == 200


def test_commit_schema_revalidates_preview_rows_and_duplicate_strategy():
    request = CaseImportCommitRequest.model_validate({
        "project_id": "4e8a514a-9d14-43d9-af64-3e926a3b777a",
        "duplicate_strategy": "skip",
        "rows": [{
            "title": "手工回归",
            "execution_kind": "manual",
            "case_type": "functional",
            "priority": "P2",
            "request_data": {"steps": ["  打开页面  "]},
            "expected_result": {"text": "  页面加载成功  "},
        }],
    })

    assert request.rows[0].request_data["steps"] == ["打开页面"]
    assert request.rows[0].expected_result["text"] == "页面加载成功"


@pytest.mark.asyncio
async def test_commit_skips_project_duplicates_and_persists_first_version():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for table in m.Base.metadata.tables.values():
        table.to_metadata(metadata)
    models = [m.User, m.Project, m.TestCaseAsset, m.TestCaseAssetVersion]
    for model in models:
        for column in metadata.tables[model.__tablename__].columns:
            if column.server_default is not None:
                column.server_default = None
    metadata.create_all(engine, tables=[metadata.tables[model.__tablename__] for model in models])
    session = Session(engine)
    user = m.User(id=uuid4(), username="importer", email="importer@example.test",
                  hashed_password="unused", role=m.UserRole.TESTER)
    project = m.Project(id=uuid4(), name="订单", owner_id=user.id, source_type=m.SourceType.UPLOAD)
    existing = m.TestCaseAsset(
        id=uuid4(), project_id=project.id, title="已有用例", execution_kind="manual",
        case_type="functional", design_type="functional", request_data={"steps": ["已有步骤"]},
        expected_result={"text": "已有结果"}, status=m.CaseAssetStatus.DRAFT,
        review_state="draft", source=m.CaseSource.MANUAL,
    )
    session.add_all([user, project, existing])
    session.commit()
    db = AsyncSessionAdapter(session)
    request = CaseImportCommitRequest.model_validate({
        "project_id": str(project.id),
        "duplicate_strategy": "skip",
        "rows": [
            {"title": " 已有用例 ", "execution_kind": "manual", "case_type": "functional",
             "request_data": {"steps": ["重复步骤"]}, "expected_result": {"text": "重复结果"}},
            {"title": "新增用例", "execution_kind": "manual", "case_type": "functional",
             "request_data": {"preconditions": "已登录", "steps": ["提交订单"]},
             "expected_result": {"text": "创建成功"}},
        ],
    })

    result = await commit_case_import(request, user, db)

    assert result["data"]["imported"] == 1
    assert result["data"]["skipped"] == 1
    created = session.scalar(select(m.TestCaseAsset).where(m.TestCaseAsset.title == "新增用例"))
    assert created.request_data == {"preconditions": "已登录", "steps": ["提交订单"]}
    version = session.scalar(select(m.TestCaseAssetVersion).where(m.TestCaseAssetVersion.case_asset_id == created.id))
    assert version.version == 1 and version.change_type == "imported"
    session.close()
    engine.dispose()
