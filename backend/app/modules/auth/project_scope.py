"""请求级项目隔离。后台任务使用独立服务会话，不继承 HTTP 会话权限。

列表、聚合、关联查询和 ORM 批量更新统一加范围；写入检查关联资源。
此处仅为项目边界，不宣称提供组织/租户管理。
"""
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, event, inspect, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import database as models

ADMIN_ROLES = {models.UserRole.SUPER_ADMIN, models.UserRole.ADMIN}


@dataclass(frozen=True)
class ProjectScope:
    user_id: UUID
    project_ids: tuple[UUID, ...]
    writable_ids: tuple[UUID, ...]


async def load_project_scope(db, user):
    owned = tuple((await db.execute(select(models.Project.id).where(
        models.Project.owner_id == user.id
    ))).scalars().all())
    members = (await db.execute(select(models.ProjectMember.project_id, models.ProjectMember.access).where(
        models.ProjectMember.user_id == user.id
    ))).all()
    readable = tuple(set(owned) | {row[0] for row in members})
    writable = tuple(set(owned) | {row[0] for row in members if row[1] == "write"})
    if user.role in {models.UserRole.VIEWER, models.UserRole.AUDITOR}:
        writable = ()
    return ProjectScope(user.id, readable, writable)


# Tables without their own project_id: traverse only the authoritative parent.
PARENTS = {
    "test_cases": ("test_run_id", "test_runs"),
    "test_results": ("test_run_id", "test_runs"),
    "test_reports": ("test_run_id", "test_runs"),
    "coverage_services": ("coverage_run_id", "coverage_runs"),
    "test_plan_cases": ("plan_id", "test_plans"),
    "test_plan_executions": ("plan_id", "test_plans"),
    "test_plan_revisions": ("plan_id", "test_plans"),
    "test_plan_revision_cases": ("revision_id", "test_plan_revisions"),
    "run_snapshots": ("test_run_id", "test_runs"),
    "run_events": ("test_run_id", "test_runs"),
    "scheduled_task_runs": ("task_id", "scheduled_tasks"),
    "environment_profile_revisions": ("profile_id", "environment_profiles"),
    "knowledge_messages": ("conversation_id", "knowledge_conversations"),
}


def table_predicate(table, scope, *, write=False):
    """使用 Core 子查询，防止 ORM loader criteria 在父级子查询中递归注入。"""
    ids = scope.writable_ids if write else scope.project_ids
    name = table.name
    if name == "projects":
        return table.c.id.in_(ids)
    if name == "knowledge_conversations":
        return and_(table.c.user_id == scope.user_id,
                    or_(table.c.project_id.is_(None), table.c.project_id.in_(scope.project_ids)))
    if name in {"knowledge_feedback", "notifications"}:
        return table.c.user_id == scope.user_id
    if "project_id" in table.c:
        predicate = table.c.project_id.in_(ids)
        if name == "defects":
            runs = models.TestRun.__table__
            predicate = or_(predicate, and_(table.c.project_id.is_(None),
                table.c.test_run_id.in_(select(runs.c.id).where(runs.c.project_id.in_(ids)))))
        if name == "knowledge_chunks" and not write:
            predicate = or_(predicate, and_(table.c.project_id.is_(None), table.c.kb_type == "term"))
        return predicate
    if name in PARENTS:
        fk, parent_name = PARENTS[name]
        parent = models.Base.metadata.tables[parent_name]
        return table.c[fk].in_(select(parent.c.id).where(table_predicate(parent, scope, write=write)))
    return None


@lru_cache(maxsize=1)
def scoped_models():
    probe = ProjectScope(UUID(int=0), (), ())
    return tuple(mapper.class_ for mapper in models.Base.registry.mappers
                 if table_predicate(mapper.local_table, probe) is not None)


@event.listens_for(Session, "do_orm_execute")
def filter_project_resources(state):
    scope = state.session.info.get("project_scope")
    if scope is None:
        return
    if not state.is_orm_statement:
        raise HTTPException(403, "受限项目会话不允许执行原始数据库语句")
    statement = state.statement
    if state.is_select or state.is_update or state.is_delete:
        for model in scoped_models():
            predicate = table_predicate(model.__table__, scope,
                                        write=state.is_update or state.is_delete)
            statement = statement.options(with_loader_criteria(model, predicate, include_aliases=True))
        state.statement = statement
    else:
        # ORM objects must pass before_flush; raw/bulk INSERT bypasses that check.
        raise HTTPException(403, "受限项目会话不允许批量插入")


@event.listens_for(Session, "before_flush")
def validate_project_writes(session, flush_context, instances):
    scope = session.info.get("project_scope")
    if scope is None:
        return
    connection = session.connection()
    for obj in set(session.new) | set(session.dirty) | set(session.deleted):
        if obj in session.dirty and not session.is_modified(obj, include_collections=False):
            continue
        table = inspect(obj).mapper.local_table
        if table.name == "projects" and obj in session.new:
            if obj.owner_id != scope.user_id:
                raise HTTPException(403, "不能为其他用户创建项目")
            if obj.id is None:
                obj.id = uuid4()
            scope = ProjectScope(scope.user_id, tuple(set(scope.project_ids) | {obj.id}),
                                 tuple(set(scope.writable_ids) | {obj.id}))
            session.info["project_scope"] = scope
            continue
        predicate = table_predicate(table, scope, write=True)
        if predicate is not None and obj not in session.new:
            identity = [column == getattr(obj, column.key) for column in table.primary_key]
            if connection.execute(select(1).select_from(table).where(*identity, predicate)).first() is None:
                raise HTTPException(403, "没有此资源的写入权限")
        if "project_id" in table.c and table.name != "knowledge_conversations":
            if getattr(obj, "project_id") not in scope.writable_ids:
                raise HTTPException(403, "没有此项目的写入权限")
        # Validate references before inserting/repointing resources, including indirect parents.
        for column in table.c:
            value = getattr(obj, column.key, None)
            if value is None:
                continue
            for fk in column.foreign_keys:
                target = fk.column.table
                target_filter = table_predicate(target, scope, write=table.name not in {
                    "knowledge_conversations", "knowledge_messages", "knowledge_feedback"
                })
                if target_filter is None:
                    continue
                pending_parent = next((parent for parent in session.new
                    if inspect(parent).mapper.local_table is target
                    and getattr(parent, fk.column.key, None) == value), None)
                if pending_parent is not None:
                    continue  # Parent itself is checked in this same flush.
                if connection.execute(select(1).select_from(target).where(
                    fk.column == value, target_filter
                )).first() is None:
                    raise HTTPException(403, "关联资源不属于可访问的项目")
