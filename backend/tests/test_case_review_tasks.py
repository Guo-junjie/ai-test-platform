"""用例评审任务的版本冻结、多人结论聚合、权限和留痕回归。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models import database as m
from app.modules.case_reviews import (
    cancel_pending_review_tasks,
    create_review_task,
    decide_review_task,
    reviewer_options,
    task_to_dict,
)


@compiles(JSONB, "sqlite")
def sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@compiles(PGUUID, "sqlite")
def sqlite_uuid(element, compiler, **kw):
    return "CHAR(32)"


class AsyncSessionAdapter:
    def __init__(self, session: Session):
        self.session = session
        self.info = session.info

    async def execute(self, statement):
        return self.session.execute(statement)

    async def flush(self):
        self.session.flush()

    async def get(self, model, identifier):
        return self.session.get(model, identifier)

    def add(self, item):
        self.session.add(item)


@pytest.fixture
def review_env():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for table in m.Base.metadata.tables.values():
        table.to_metadata(metadata)
    models = [
        m.User, m.Project, m.ProjectMember, m.TestCaseAsset, m.TestCaseAssetVersion,
        m.CaseReviewTask, m.CaseReviewAssignment, m.CaseReviewEvent, m.Notification,
    ]
    for model in models:
        for column in metadata.tables[model.__tablename__].columns:
            if column.server_default is not None:
                column.server_default = None
    metadata.create_all(engine, tables=[metadata.tables[model.__tablename__] for model in models])
    session = Session(engine)
    author = m.User(id=uuid4(), username="qa-author", email="author@example.test",
                    hashed_password="unused", role=m.UserRole.TESTER, is_active=True)
    reviewer_a = m.User(id=uuid4(), username="reviewer-a", email="a@example.test",
                        hashed_password="unused", role=m.UserRole.TEST_MANAGER, is_active=True)
    reviewer_b = m.User(id=uuid4(), username="reviewer-b", email="b@example.test",
                        hashed_password="unused", role=m.UserRole.TEST_MANAGER, is_active=True)
    outsider = m.User(id=uuid4(), username="outsider", email="out@example.test",
                      hashed_password="unused", role=m.UserRole.TEST_MANAGER, is_active=True)
    project = m.Project(id=uuid4(), name="订单平台", owner_id=author.id, source_type=m.SourceType.UPLOAD)
    asset = m.TestCaseAsset(
        id=uuid4(), project_id=project.id, case_type="functional", execution_kind="manual",
        title="提交订单", description="覆盖订单主流程",
        request_data={"preconditions": "用户已登录", "steps": ["提交订单"]},
        expected_result={"text": "生成订单编号"}, priority="P1", folder="订单",
        tags=["冒烟"], version=1, status=m.CaseAssetStatus.DRAFT,
        review_state="draft", source=m.CaseSource.MANUAL, created_by=author.id,
    )
    version = m.TestCaseAssetVersion(
        id=uuid4(), case_asset_id=asset.id, version=1,
        snapshot={
            "title": asset.title, "description": asset.description,
            "execution_kind": "manual", "case_type": "functional",
            "request_data": asset.request_data, "expected_result": asset.expected_result,
            "priority": "P1", "folder": "订单", "tags": ["冒烟"],
            "pre_script": "", "post_script": "", "sql_script": "",
        },
        change_type="created", changed_by=author.id,
    )
    session.add_all([
        author, reviewer_a, reviewer_b, outsider, project,
        m.ProjectMember(project_id=project.id, user_id=reviewer_a.id, access="write"),
        m.ProjectMember(project_id=project.id, user_id=reviewer_b.id, access="write"),
        asset, version,
    ])
    session.commit()
    env = SimpleNamespace(
        session=session, db=AsyncSessionAdapter(session), author=author, reviewer_a=reviewer_a,
        reviewer_b=reviewer_b, outsider=outsider, project=project, asset=asset, version=version,
    )
    yield env
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_task_freezes_version_assigns_reviewers_and_notifies(review_env):
    env = review_env
    task = await create_review_task(
        env.db, case_id=env.asset.id, reviewer_ids=[env.reviewer_a.id, env.reviewer_b.id],
        comment="重点核对金额计算", due_at=None, actor=env.author,
    )
    payload = await task_to_dict(env.db, task, env.reviewer_a.id)

    assert task.case_version_id == env.version.id and task.case_version == 1 and task.round == 1
    assert env.asset.review_state == "pending"
    assert payload["version"]["snapshot"]["title"] == "提交订单"
    assert payload["reviewer_count"] == 2 and payload["approved_count"] == 0
    assert payload["can_review"] is True and payload["my_assignment_status"] == "pending"
    assert env.session.query(m.Notification).count() == 2
    event = env.session.scalar(select(m.CaseReviewEvent))
    assert event.task_id == task.id and event.case_version_id == env.version.id and event.case_version == 1


@pytest.mark.asyncio
async def test_all_reviewers_must_approve_and_unassigned_user_is_rejected(review_env):
    env = review_env
    task = await create_review_task(
        env.db, case_id=env.asset.id, reviewer_ids=[env.reviewer_a.id, env.reviewer_b.id],
        comment="", due_at=None, actor=env.author,
    )
    with pytest.raises(HTTPException) as denied:
        await decide_review_task(
            env.db, task_id=task.id, decision="approve", comment="", actor=env.outsider,
        )
    assert denied.value.status_code == 403

    await decide_review_task(
        env.db, task_id=task.id, decision="approve", comment="第一位通过", actor=env.reviewer_a,
    )
    assert task.status == "pending" and env.asset.review_state == "pending"
    await decide_review_task(
        env.db, task_id=task.id, decision="approve", comment="第二位通过", actor=env.reviewer_b,
    )
    assert task.status == "approved" and env.asset.review_state == "approved"
    assert env.asset.status == m.CaseAssetStatus.ADOPTED
    assert env.session.query(m.Notification).filter(m.Notification.user_id == env.author.id).count() == 1


@pytest.mark.asyncio
async def test_rejection_closes_round_and_resubmission_binds_new_version(review_env):
    env = review_env
    first = await create_review_task(
        env.db, case_id=env.asset.id, reviewer_ids=[env.reviewer_a.id, env.reviewer_b.id],
        comment="第一轮", due_at=None, actor=env.author,
    )
    await decide_review_task(
        env.db, task_id=first.id, decision="changes_requested",
        comment="补充库存不足场景", actor=env.reviewer_a,
    )
    assignments = env.session.scalars(select(m.CaseReviewAssignment).where(
        m.CaseReviewAssignment.task_id == first.id,
    )).all()
    assert first.status == "changes_requested"
    assert {row.status for row in assignments} == {"changes_requested", "cancelled"}
    assert env.asset.review_state == "changes_requested"

    env.asset.title = "提交订单（含库存校验）"
    env.asset.version = 2
    env.asset.review_state = "draft"
    second_version = m.TestCaseAssetVersion(
        id=uuid4(), case_asset_id=env.asset.id, version=2,
        snapshot={**env.version.snapshot, "title": env.asset.title},
        change_type="edit", changed_by=env.author.id,
    )
    env.session.add(second_version)
    await env.db.flush()
    second = await create_review_task(
        env.db, case_id=env.asset.id, reviewer_ids=[env.reviewer_b.id],
        comment="已补充场景", due_at=None, actor=env.author,
    )
    assert second.round == 2 and second.case_version == 2 and second.case_version_id == second_version.id
    assert first.case_version_id == env.version.id


@pytest.mark.asyncio
async def test_edit_cancels_pending_task_and_reviewer_options_respect_project(review_env):
    env = review_env
    task = await create_review_task(
        env.db, case_id=env.asset.id, reviewer_ids=[env.reviewer_a.id, env.reviewer_b.id],
        comment="", due_at=None, actor=env.author,
    )
    count = await cancel_pending_review_tasks(
        env.db, item=env.asset, actor_id=env.author.id, reason="内容已修改",
    )
    assignments = env.session.scalars(select(m.CaseReviewAssignment).where(
        m.CaseReviewAssignment.task_id == task.id,
    )).all()
    assert count == 1 and task.status == "cancelled"
    assert {row.status for row in assignments} == {"cancelled"}

    options = await reviewer_options(env.db, env.project.id)
    ids = {row["id"] for row in options}
    assert str(env.reviewer_a.id) in ids and str(env.reviewer_b.id) in ids
    assert str(env.outsider.id) not in ids
