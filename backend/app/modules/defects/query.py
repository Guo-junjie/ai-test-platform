"""列表、报告入口、详情共享的缺陷字段与筛选口径。"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models.database import Defect, DefectAffectedRelease, DefectReference, DefectSeverity, DefectType, DefectWatcher, DefectWorkflowRevision, EnvironmentProfile, Project, ProjectModule, ProjectIteration, ProjectRelease, User, TestRun
from .permissions import can_edit, context_for
from .service import core_dict, json_value, transition_options
from .workflow import PRIORITY_LABELS, STATES


def filter_conditions(*, project_id=None, test_run_id=None, severity=None, defect_type=None, status_code=None,
                      workflow_states=None, priority=None, assignee_id=None, reporter_id=None, module_id=None,
                      iteration_id=None, environment_profile_id=None, label=None, source=None, q=None,
                      verifier_id=None, created_from=None, created_to=None, updated_from=None, updated_to=None,
                      overdue=None, watching=None, view=None, user_id=None, include_deleted=False):
    conditions = [] if include_deleted else [Defect.deleted_at.is_(None)]
    effective_project = func.coalesce(Defect.project_id, TestRun.project_id)
    for value, column in ((project_id, effective_project), (test_run_id, Defect.test_run_id),
                          (assignee_id, Defect.assignee_id), (reporter_id, Defect.reporter_id),
                          (verifier_id, Defect.verifier_id),
                          (module_id, Defect.module_id), (iteration_id, Defect.iteration_id),
                          (environment_profile_id, Defect.environment_profile_id)):
        if value:
            conditions.append(column == value)
    for value, enum, column in ((severity, DefectSeverity, Defect.severity), (defect_type, DefectType, Defect.defect_type)):
        if value:
            try:
                conditions.append(column == enum(value))
            except ValueError:
                raise HTTPException(422, "无效的缺陷分类或严重程度")
    if status_code:
        if status_code not in {state["legacy_status"] for state in STATES.values()}:
            raise HTTPException(422, "无效的旧状态筛选值")
        conditions.append(Defect.status == status_code)
    if workflow_states:
        if any(not isinstance(value, str) or not value or len(value) > 64 for value in workflow_states):
            raise HTTPException(422, "无效的工作流状态")
        conditions.append(Defect.workflow_state.in_(workflow_states))
    if priority:
        if priority not in PRIORITY_LABELS:
            raise HTTPException(422, "无效的优先级")
        conditions.append(Defect.priority == priority)
    if source:
        if source not in {"manual", "pipeline", "import"}:
            raise HTTPException(422, "无效的缺陷来源")
        conditions.append(Defect.source == source)
    if label:
        conditions.append(Defect.labels.contains([label]))
    for value, column, operator in ((created_from, Defect.created_at, "from"), (created_to, Defect.created_at, "to"),
                                    (updated_from, Defect.updated_at, "from"), (updated_to, Defect.updated_at, "to")):
        if value:
            conditions.append(column >= value if operator == "from" else column < value)
    if overdue:
        conditions.extend([Defect.due_at < datetime.now(timezone.utc), Defect.is_resolved.is_(False)])
    if watching:
        conditions.append(Defect.id.in_(select(DefectWatcher.defect_id).where(DefectWatcher.user_id == user_id)))
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(or_(Defect.title.ilike("%" + escaped + "%", escape="\\"),
                               Defect.description.ilike("%" + escaped + "%", escape="\\"),
                               Defect.defect_key.ilike("%" + escaped + "%", escape="\\")))
    if view == "assigned_to_me":
        conditions.append(Defect.assignee_id == user_id)
    elif view == "reported_by_me":
        conditions.append(Defect.reporter_id == user_id)
    elif view == "verify_by_me":
        conditions.extend([Defect.verifier_id == user_id, Defect.workflow_state == "pending_verification"])
    elif view == "triage":
        conditions.append(Defect.workflow_state.in_(["new", "unassigned"]))
    elif view == "overdue":
        conditions.extend([Defect.due_at < datetime.now(timezone.utc), Defect.workflow_state.in_(
            [key for key, value in STATES.items() if value["is_backlog"]])])
    elif view not in (None, "", "all"):
        raise HTTPException(422, "未知的缺陷视图")
    return conditions


async def enrich_list(db, defects):
    user_ids = {value for defect in defects for value in (defect.assignee_id, defect.reporter_id, defect.verifier_id) if value}
    names = dict((await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))).all()) if user_ids else {}
    module_ids = {defect.module_id for defect in defects if defect.module_id}
    modules = dict((await db.execute(select(ProjectModule.id, ProjectModule.path).where(ProjectModule.id.in_(module_ids)))).all()) if module_ids else {}
    project_ids = {defect.project_id for defect in defects if defect.project_id}
    projects = dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all()) if project_ids else {}
    revision_ids = {defect.workflow_revision_id for defect in defects if defect.workflow_revision_id}
    definitions = {item.id: item.definition_json for item in (await db.execute(select(DefectWorkflowRevision).where(
        DefectWorkflowRevision.id.in_(revision_ids)))).scalars().all()} if revision_ids else {}
    result = []
    for defect in defects:
        item = core_dict(defect, projects.get(defect.project_id), definitions.get(defect.workflow_revision_id))
        item.update({"assignee_name": names.get(defect.assignee_id), "reporter_name": names.get(defect.reporter_id),
                     "verifier_name": names.get(defect.verifier_id), "module_name": modules.get(defect.module_id)})
        result.append(item)
    return result


async def display_event_changes(db, items):
    """保留审计原值，另外批量解析人名与业务目录，避免活动列表显示裸 UUID。"""
    models = {"reporter_id": User, "assignee_id": User, "verifier_id": User,
              "fix_submitted_by_id": User, "resolved_by_id": User, "closed_by_id": User,
              "module_id": ProjectModule, "iteration_id": ProjectIteration,
              "fix_release_id": ProjectRelease, "verified_release_id": ProjectRelease,
              "environment_profile_id": EnvironmentProfile, "duplicate_of_id": Defect}
    identifiers = {}
    for item in items:
        for key, change in (item.get("changes") or {}).items():
            if key not in models or not isinstance(change, dict):
                continue
            for value in (change.get("before"), change.get("after")):
                try:
                    identifiers.setdefault(models[key], set()).add(UUID(str(value)))
                except (ValueError, TypeError):
                    pass
    names = {}
    for model, values in identifiers.items():
        name_column = model.username if model is User else model.path if model is ProjectModule else model.defect_key if model is Defect else model.name
        names[model] = {str(identifier): label for identifier, label in (await db.execute(select(model.id, name_column).where(model.id.in_(values)))).all()}
    enums = {"workflow_state": {key: value["label"] for key, value in STATES.items()},
             "priority": PRIORITY_LABELS,
             "resolution": {"fixed": "已修复", "not_a_bug": "非缺陷", "duplicate": "重复缺陷", "cannot_reproduce": "无法复现", "wont_fix": "暂不修复", "legacy_unknown": "历史未记录"}}
    for item in items:
        display = {}
        for key, change in (item.get("changes") or {}).items():
            if not isinstance(change, dict) or "before" not in change:
                continue
            mapping = names.get(models.get(key), enums.get(key, {}))
            display[key] = {side: mapping.get(str(change.get(side)), change.get(side)) for side in ("before", "after")}
        item["display_changes"] = display


async def detail_dict(db, defect, user):
    result = (await enrich_list(db, [defect]))[0]
    result["permissions"] = {"edit": False, "assign": False, "delete": False, "restore": False}
    result["transitions"] = []
    if defect.project_id:
        context = await context_for(db, user, defect.project_id)
        result["permissions"] = {"edit": can_edit(context, defect) and not defect.deleted_at,
                                  "assign": context.privileged and not defect.deleted_at and defect.workflow_state in {"new", "unassigned", "in_progress", "pending_verification", "reopened"},
                                  "delete": context.privileged and not defect.deleted_at,
                                  "restore": context.privileged and bool(defect.deleted_at)}
        result["transitions"] = await transition_options(db, context, defect)
    releases = (await db.execute(select(ProjectRelease).join(DefectAffectedRelease,
                    DefectAffectedRelease.release_id == ProjectRelease.id).where(DefectAffectedRelease.defect_id == defect.id))).scalars().all()
    result["affected_release_ids"] = [str(item.id) for item in releases]
    result["affected_releases"] = [{"id": str(item.id), "name": item.name} for item in releases]
    references = (await db.execute(select(DefectReference).where(DefectReference.defect_id == defect.id))).scalars().all()
    result["references"] = [{column.name: json_value(getattr(item, column.name)) for column in DefectReference.__table__.columns} for item in references]
    if defect.iteration_id:
        iteration = (await db.execute(select(ProjectIteration).where(ProjectIteration.id == defect.iteration_id))).scalar_one_or_none()
        result["iteration_name"] = iteration.name if iteration else None
    release_ids = [value for value in (defect.fix_release_id, defect.verified_release_id) if value]
    names = dict((await db.execute(select(ProjectRelease.id, ProjectRelease.name).where(ProjectRelease.id.in_(release_ids)))).all()) if release_ids else {}
    result["fix_release_name"] = names.get(defect.fix_release_id)
    result["verified_release_name"] = names.get(defect.verified_release_id)
    result["legacy_information"] = "历史数据缺少部分责任人或过程时间；迁移未补造记录" if (defect.source_metadata or {}).get("legacy_snapshot") else None
    return result
