"""缺陷写操作共享领域校验；事务由 API 或任务提交。"""
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.models.database import (
    AuditLog, Defect, DefectAffectedRelease, DefectEvent, DefectReference,
    DefectSeverity, DefectType, DefectWorkflow, DefectWorkflowRevision,
    EnvironmentProfile, EnvironmentProfileRevision, Project, ProjectDefectSettings,
    ProjectIteration, ProjectModule, ProjectRelease, RequirementDoc, TestCaseAsset,
)
from .permissions import action_denial, can_edit, context_for, validate_participant
from .workflow import DEFAULT_WORKFLOW, LEGACY_LABELS, PRIORITY_LABELS, STATES, action_definition, fingerprint, project_state, validate_action_input

EDIT_FIELDS = {"title", "description", "severity", "defect_type", "priority", "module_id", "iteration_id",
               "environment_profile_id", "preconditions", "expected_result", "actual_result", "reproduce_steps",
               "reproducibility", "assignee_id", "verifier_id", "labels", "due_at"}
CYCLE_FIELDS = ("started_at", "fix_submitted_at", "resolved_at", "closed_at", "fix_release_id", "verified_release_id",
                "fix_build", "verified_build", "fix_submitted_by_id", "resolved_by_id", "closed_by_id",
                "proposed_resolution", "resolution", "resolution_note", "duplicate_of_id")
DIRECTORY_MODELS = {"modules": ProjectModule, "iterations": ProjectIteration, "releases": ProjectRelease}


def utcnow():
    return datetime.now(timezone.utc)


def json_value(value):
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def snapshot(defect):
    return {column.name: json_value(getattr(defect, column.name)) for column in Defect.__table__.columns
            if column.name not in {"source_metadata", "event_sequence"}}


def core_dict(defect, project_name=None, state_definition=None):
    result = snapshot(defect)
    result["project_name"] = project_name
    result["status_code"] = defect.status or "open"
    result["status"] = LEGACY_LABELS.get(defect.status or "open", "待处理")
    states = {item["key"]: item for item in (state_definition or {}).get("states", [])} if state_definition else STATES
    result["workflow_state_label"] = states.get(defect.workflow_state, {}).get("label", defect.workflow_state)
    result["priority_label"] = PRIORITY_LABELS.get(defect.priority, defect.priority)
    result["severity_label"] = {"P0": "致命", "P1": "严重", "P2": "一般", "P3": "轻微"}.get(result["severity"], result["severity"])
    result["defect_type_label"] = {"business": "业务缺陷", "program": "程序缺陷", "performance": "性能缺陷", "integration": "集成缺陷", "security": "安全缺陷"}.get(result["defect_type"], result["defect_type"])
    result["source_metadata"] = {key: json_value(value) for key, value in (defect.source_metadata or {}).items()
                               if key not in {"creation_hash", "legacy_snapshot"}}
    return result


async def ensure_workflow(db, project_id):
    # 为同项目第一次创建流程串行化，也保护新建缺陷的幂等请求。
    project = (await db.execute(select(Project).where(Project.id == project_id).with_for_update())).scalar_one()
    settings = (await db.execute(select(ProjectDefectSettings).where(ProjectDefectSettings.project_id == project_id))).scalar_one_or_none()
    if settings and settings.default_workflow_id:
        workflow = await db.get(DefectWorkflow, settings.default_workflow_id)
        revision = await db.get(DefectWorkflowRevision, workflow.active_revision_id) if workflow and workflow.active_revision_id else None
        if revision is None:
            revision = (await db.execute(select(DefectWorkflowRevision).where(
                DefectWorkflowRevision.workflow_id == settings.default_workflow_id,
                DefectWorkflowRevision.project_id == project_id, DefectWorkflowRevision.status == "published",
            ).order_by(DefectWorkflowRevision.revision.desc()).limit(1))).scalar_one_or_none()
        if revision:
            return revision
    revision_id = uuid4()
    workflow = DefectWorkflow(id=uuid4(), project_id=project_id, name=DEFAULT_WORKFLOW["name"], created_by=project.owner_id)
    revision = DefectWorkflowRevision(id=revision_id, workflow_id=workflow.id, project_id=project_id,
                                     revision=1, status="published", definition_json=deepcopy(DEFAULT_WORKFLOW))
    db.add(workflow)
    await db.flush()
    db.add(revision)
    await db.flush()
    workflow.active_revision_id = revision.id
    if settings is None:
        settings = ProjectDefectSettings(project_id=project_id)
        db.add(settings)
    settings.default_workflow_id = workflow.id
    await db.flush()
    return revision


async def definition_for(db, defect):
    if not defect.workflow_revision_id:
        return DEFAULT_WORKFLOW
    revision = (await db.execute(select(DefectWorkflowRevision).where(
        DefectWorkflowRevision.id == defect.workflow_revision_id,
        DefectWorkflowRevision.project_id == defect.project_id,
    ))).scalar_one_or_none()
    if revision is None or revision.status != "published":
        raise HTTPException(409, "缺陷关联的工作流版本不可用，请联系项目负责人")
    return revision.definition_json


def append_event(db, defect, actor, event_type, before, *, note="", request_id=None, request_hash=None, extra=None):
    after = snapshot(defect)
    changes = {key: {"before": before.get(key), "after": value} for key, value in after.items()
               if value != before.get(key) and key not in {"updated_at", "row_version"}}
    if extra:
        changes["action_input"] = json_value(extra)
    defect.event_sequence = int(defect.event_sequence or 0) + 1
    event = DefectEvent(id=uuid4(), defect_id=defect.id, project_id=defect.project_id,
                        sequence=defect.event_sequence, event_type=event_type,
                        actor_id=actor.id if actor else None, actor_kind="user" if actor else "system",
                        from_state=before.get("workflow_state"), to_state=defect.workflow_state,
                        changes_json=changes, note=note, request_id=request_id, request_hash=request_hash,
                        occurred_at=utcnow(), result_json={
                            "id": str(defect.id), "workflow_state": defect.workflow_state,
                            "row_version": defect.row_version, "event_id": None})
    event.result_json["event_id"] = str(event.id)
    db.add(event)
    db.add(AuditLog(user_id=actor.id if actor else None, action="defect_" + event_type,
                    resource_type="defect", resource_id=str(defect.id), details={
                        "project_id": str(defect.project_id), "event_id": str(event.id), "changes": changes, "note": note}))
    from .notifications import enqueue_event
    enqueue_event(db, defect, event, actor, mention_user_ids=(extra or {}).get("mention_user_ids"))
    return event


def bump(defect):
    defect.row_version = int(defect.row_version or 1) + 1
    defect.updated_at = utcnow()


async def locked_defect(db, user, defect_id, expected_version=None, *, include_deleted=False, request_id=None, request_hash=None):
    defect = (await db.execute(select(Defect).where(Defect.id == defect_id)
                              .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if defect is None or (defect.deleted_at and not include_deleted):
        raise HTTPException(404, "缺陷不存在或已删除")
    if not defect.project_id:
        raise HTTPException(409, "该历史缺陷尚未确定项目归属，请联系管理员")
    context = await context_for(db, user, defect.project_id, write=True)
    if request_id:
        prior = (await db.execute(select(DefectEvent).where(DefectEvent.defect_id == defect.id,
                                                          DefectEvent.request_id == request_id))).scalar_one_or_none()
        if prior:
            if prior.request_hash != request_hash or prior.actor_id != user.id:
                raise HTTPException(409, "该请求编号已用于其他操作，请重新提交")
            return defect, context, prior.result_json
    if expected_version is None or defect.row_version != expected_version:
        raise HTTPException(409, {"error_code": "DEFECT_VERSION_CONFLICT", "message": "缺陷已被其他人更新，请刷新后重新提交",
                                  "current_version": defect.row_version})
    return defect, context, None


async def same_project(db, model, identifier, project_id, *, active=False, fresh=False):
    if identifier is None:
        return None
    item = (await db.execute(select(model).where(model.id == identifier, model.project_id == project_id)
                             .execution_options(populate_existing=fresh))).scalar_one_or_none()
    if item is None or (model is Defect and item.deleted_at):
        raise HTTPException(422, "关联对象不存在或不属于当前项目")
    if active and ((hasattr(item, "is_active") and not item.is_active) or getattr(item, "status", None) == "archived"):
        raise HTTPException(422, "所选目录对象已停用")
    return item


async def prepare_fields(db, context, fields):
    prepared = dict(fields)
    for key, model in (("module_id", ProjectModule), ("iteration_id", ProjectIteration),
                       ("fix_release_id", ProjectRelease), ("verified_release_id", ProjectRelease)):
        if key in prepared:
            await same_project(db, model, prepared[key], context.project.id, active=True)
    for key, purpose in (("assignee_id", "assignee"), ("verifier_id", "verifier")):
        if key in prepared:
            await validate_participant(db, context.project, prepared[key], purpose)
    if "environment_profile_id" in prepared:
        environment = await same_project(db, EnvironmentProfile, prepared["environment_profile_id"], context.project.id)
        prepared["environment_revision_id"] = None
        prepared["environment_snapshot"] = {}
        if environment:
            if environment.status == "archived":
                raise HTTPException(422, "环境已停用")
            revision = None
            if environment.current_revision_id:
                revision = (await db.execute(select(EnvironmentProfileRevision).where(
                    EnvironmentProfileRevision.id == environment.current_revision_id,
                    EnvironmentProfileRevision.profile_id == environment.id))).scalar_one_or_none()
            prepared["environment_revision_id"] = revision.id if revision else None
            config = revision.config_json if revision else {"base_url": environment.base_url}
            parsed = urlsplit(config.get("base_url") or "")
            netloc = parsed.hostname or ""
            if ":" in netloc:
                netloc = "[" + netloc + "]"
            if parsed.port:
                netloc += ":" + str(parsed.port)
            prepared["environment_snapshot"] = {"name": environment.name,
                                                 "base_url": urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))}
    for key, enum in (("severity", DefectSeverity), ("defect_type", DefectType)):
        if key in prepared:
            prepared[key] = enum(prepared[key])
    return prepared


async def replace_affected_releases(db, defect, release_ids):
    ids = list(dict.fromkeys(release_ids))
    for identifier in ids:
        await same_project(db, ProjectRelease, identifier, defect.project_id, active=True)
    existing = (await db.execute(select(DefectAffectedRelease).where(DefectAffectedRelease.defect_id == defect.id))).scalars().all()
    old = [str(item.release_id) for item in existing]
    for item in existing:
        if item.release_id not in ids:
            await db.delete(item)
    present = {item.release_id for item in existing}
    for identifier in ids:
        if identifier not in present:
            db.add(DefectAffectedRelease(defect_id=defect.id, project_id=defect.project_id, release_id=identifier))
    return {"before": old, "after": [str(value) for value in ids]}


def requirement_keys(value):
    found = {}
    if isinstance(value, dict):
        key = value.get("id") or value.get("requirement_id") or value.get("key")
        if isinstance(key, (str, int)):
            found[str(key)] = str(value.get("title") or value.get("name") or value.get("description") or key)[:500]
        for item in value.values():
            found.update(requirement_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(requirement_keys(item))
    return found


async def add_reference(db, defect, reference):
    fields = reference.model_dump(exclude_none=True)
    models = {"requirement": (RequirementDoc, "requirement_doc_id"), "case": (TestCaseAsset, "case_asset_id"), "defect": (Defect, "related_defect_id")}
    model, key = models[reference.kind]
    target = await same_project(db, model, fields[key], defect.project_id)
    if target.id == defect.id:
        raise HTTPException(422, "不能关联缺陷自身")
    title = getattr(target, "title", None) or getattr(target, "filename", "")
    if reference.requirement_item_key:
        items = requirement_keys(target.requirements_json or {})
        if reference.requirement_item_key not in items:
            raise HTTPException(422, "需求条目不存在或文档已变化，请重新选择")
        title = items[reference.requirement_item_key]
    existing = (await db.execute(select(DefectReference).where(DefectReference.defect_id == defect.id,
                                                              DefectReference.kind == reference.kind))).scalars().all()
    for item in existing:
        if all(getattr(item, field) == value for field, value in fields.items()):
            return item
    item = DefectReference(id=uuid4(), defect_id=defect.id, project_id=defect.project_id,
                           title_snapshot=title, **fields)
    db.add(item)
    return item


async def create_defect(db, user, request):
    context = await context_for(db, user, request.project_id, write=True)
    if not context.roles:
        raise HTTPException(403, "没有登记缺陷的项目职责")
    project_settings = await db.get(ProjectDefectSettings, request.project_id)
    required = (project_settings.field_config or {}).get("required_on_create", []) if project_settings else []
    values = request.model_dump()
    missing = [name for name in required if values.get(name) in (None, "", [])]
    if missing:
        raise HTTPException(422, {"message": "请补齐项目要求的新建必填字段", "field_errors": missing})
    revision = await ensure_workflow(db, request.project_id)
    digest = fingerprint(request.model_dump(mode="json", exclude={"creation_request_id"}))
    if request.creation_request_id:
        existing = (await db.execute(select(Defect).where(Defect.project_id == request.project_id,
             Defect.reporter_id == user.id, Defect.creation_request_id == request.creation_request_id))).scalar_one_or_none()
        if existing:
            if (existing.source_metadata or {}).get("creation_hash") != digest:
                raise HTTPException(409, "该登记请求编号已经使用，请重新提交")
            return existing
    raw = request.model_dump(include=EDIT_FIELDS, exclude_unset=True)
    prepared = await prepare_fields(db, context, raw)
    defect = Defect(id=uuid4(), project_id=request.project_id, reporter_id=user.id,
                    title=request.title, description=request.description, severity=DefectSeverity(request.severity),
                    defect_type=DefectType(request.defect_type), priority=request.priority,
                    reproduce_steps=request.reproduce_steps, labels=request.labels,
                    reproducibility=request.reproducibility, source="manual", source_metadata={"creation_hash": digest},
                    workflow_state=revision.definition_json["initial_state"], workflow_revision_id=revision.id,
                    row_version=1, event_sequence=0, reopened_count=0, creation_request_id=request.creation_request_id,
                    updated_at=utcnow())
    for key, value in prepared.items():
        setattr(defect, key, value)
    if defect.assignee_id:
        defect.assigned_at = utcnow()
    project_state(defect, revision.definition_json)
    db.add(defect)
    await db.flush()
    releases = await replace_affected_releases(db, defect, request.affected_release_ids or [])
    for reference in request.references:
        await add_reference(db, defect, reference)
    append_event(db, defect, user, "created", {}, extra={"affected_release_ids": releases["after"]})
    await db.flush()
    return defect


async def edit_defect(db, user, defect_id, request):
    defect, context, _ = await locked_defect(db, user, defect_id, request.expected_version)
    if not can_edit(context, defect):
        raise HTTPException(403, "只能编辑自己报告、负责处理或获授权的缺陷")
    raw = request.model_dump(include=EDIT_FIELDS, exclude_unset=True)
    if any(key in raw for key in ("assignee_id", "verifier_id")) and not context.privileged:
        raise HTTPException(403, "责任人由项目负责人或测试负责人指派")
    if "priority" in raw and raw["priority"] != defect.priority and not context.privileged:
        raise HTTPException(403, "调整优先级需要项目负责人或测试负责人权限")
    if any(key in raw and raw[key] != getattr(defect, key) for key in ("assignee_id", "verifier_id")):
        if defect.workflow_state not in {"new", "unassigned", "reopened"}:
            raise HTTPException(422, "处理中和待验证缺陷请使用指派操作填写转派原因")
    before = snapshot(defect)
    # 编辑器完整提交表单时，不重新绑定未改变的历史环境、停用目录或责任人。
    raw = {key: value for key, value in raw.items() if json_value(value) != before.get(key)}
    prepared = await prepare_fields(db, context, raw)
    for key, value in prepared.items():
        setattr(defect, key, value)
    if "assignee_id" in prepared and json_value(prepared["assignee_id"]) != before.get("assignee_id"):
        defect.assigned_at = utcnow() if defect.assignee_id else None
    extra = {}
    if "affected_release_ids" in request.model_fields_set:
        existing_releases = set((await db.execute(select(DefectAffectedRelease.release_id).where(DefectAffectedRelease.defect_id == defect.id))).scalars().all())
        if existing_releases != set(request.affected_release_ids or []):
            extra["affected_release_ids"] = await replace_affected_releases(db, defect, request.affected_release_ids)
    if snapshot(defect) == before and not extra:
        return defect
    bump(defect)
    append_event(db, defect, user, "updated", before, note=request.note, extra=extra)
    await db.flush()
    return defect


async def assign_defect(db, user, defect_id, request):
    digest = fingerprint({"action": "assign", **request.model_dump(mode="json")})
    defect, context, prior = await locked_defect(db, user, defect_id, request.expected_version,
                                               request_id=request.request_id, request_hash=digest)
    if prior:
        return defect, prior
    if not context.privileged:
        raise HTTPException(403, "指派需要项目负责人或测试负责人权限")
    if defect.workflow_state not in {"new", "unassigned", "in_progress", "pending_verification", "reopened"}:
        raise HTTPException(422, "请先重开已结束的缺陷再指派")
    fields = request.model_dump(include={"assignee_id", "verifier_id"}, exclude_unset=True)
    if not fields:
        raise HTTPException(422, "请选择需要调整的处理人或验证人")
    if defect.workflow_state in {"in_progress", "pending_verification"} and not request.note:
        raise HTTPException(422, "处理中或待验证缺陷转派必须说明原因")
    if defect.workflow_state in {"in_progress", "pending_verification"} and "assignee_id" in fields and fields["assignee_id"] is None:
        raise HTTPException(422, "当前状态不能解除处理人，请先退回待分配")
    if defect.workflow_state == "pending_verification" and "verifier_id" in fields and fields["verifier_id"] is None:
        raise HTTPException(422, "待验证缺陷不能清空验证人")
    before = snapshot(defect)
    for key, value in (await prepare_fields(db, context, fields)).items():
        setattr(defect, key, value)
    if "assignee_id" in fields:
        defect.assigned_at = utcnow() if defect.assignee_id else None
    bump(defect)
    event = append_event(db, defect, user, "assigned", before, note=request.note,
                         request_id=request.request_id, request_hash=digest)
    await db.flush()
    return defect, event.result_json


async def transition_defect(db, user, defect_id, request):
    digest = fingerprint(request.model_dump(mode="json"))
    defect, context, prior = await locked_defect(db, user, defect_id, request.expected_version,
                                               request_id=request.request_id, request_hash=digest)
    if prior:
        return defect, prior
    definition = await definition_for(db, defect)
    action = action_definition(definition, request.action_id, defect.workflow_state)
    denial = action_denial(context, defect, action)
    if denial:
        raise HTTPException(403, denial)
    supplied = request.fields.model_dump(exclude_unset=True)
    validate_action_input(action, snapshot(defect), supplied, request.note)
    if request.action_id == "triage":
        project_settings = await db.get(ProjectDefectSettings, defect.project_id)
        required = (project_settings.field_config or {}).get("required_on_triage", []) if project_settings else []
        current = {**snapshot(defect), **supplied}
        missing = [name for name in required if current.get(name) in (None, "", [])]
        if missing:
            raise HTTPException(422, {"message": "请补齐项目要求的分诊字段", "field_errors": missing})
    override = ((request.action_id in {"start", "resume", "submit_fix"} and defect.assignee_id != user.id)
                or (request.action_id in {"verify_pass", "verify_fail"} and defect.verifier_id != user.id))
    if override and not request.note:
        raise HTTPException(422, "代责任人操作必须填写原因")
    before = snapshot(defect)
    prepared = await prepare_fields(db, context, {key: value for key, value in supplied.items() if key != "fix_available"})
    for key, value in prepared.items():
        setattr(defect, key, value)
    if request.action_id in {"start", "resume", "submit_fix"}:
        await validate_participant(db, context.project, defect.assignee_id, "assignee")
    if request.action_id == "submit_fix":
        await validate_participant(db, context.project, defect.verifier_id, "verifier")
        if defect.verifier_id == user.id and not definition["settings"].get("allow_self_verification"):
            raise HTTPException(422, "默认不允许修复提交人验证自己的修复，请选择其他验证人")
        defect.fix_submitted_at = utcnow()
        defect.fix_submitted_by_id = user.id
        defect.proposed_resolution = "fixed"
    if request.action_id in {"verify_pass", "verify_fail"}:
        if defect.fix_submitted_by_id == user.id and not definition["settings"].get("allow_self_verification"):
            raise HTTPException(403, "不能验证自己提交的修复")
    if request.action_id in {"start", "resume"} and not defect.started_at:
        defect.started_at = utcnow()
    if request.action_id == "verify_pass":
        defect.resolution = "fixed"
        defect.resolution_note = request.note
        defect.resolved_at = utcnow()
        defect.resolved_by_id = user.id
        if not defect.first_resolved_at:
            defect.first_resolved_at = defect.resolved_at
    if request.action_id == "close":
        if defect.resolution != "fixed" or not defect.resolved_at:
            raise HTTPException(422, "该缺陷缺少可信验证结果，请重开并完成验证后再关闭")
        defect.closed_at = utcnow()
        defect.closed_by_id = user.id
    if request.action_id in {"reopen", "verify_fail"}:
        for key in CYCLE_FIELDS:
            setattr(defect, key, None)
        defect.reopened_count += 1
    if request.action_id == "return_to_queue":
        defect.started_at = None
        if "assignee_id" in supplied:
            defect.assigned_at = utcnow() if defect.assignee_id else None
    if request.action_id == "reject":
        if defect.resolution == "duplicate":
            if not defect.duplicate_of_id:
                raise HTTPException(422, "重复缺陷必须指定主缺陷")
            seen = {defect.id}
            target_id = defect.duplicate_of_id
            # 锁项目，防止同时创建 A→B 和 B→A 的重复关系。
            await db.execute(select(Project).where(Project.id == defect.project_id).with_for_update())
            while target_id:
                if target_id in seen:
                    raise HTTPException(422, "重复缺陷关系不能指向自身或形成循环")
                seen.add(target_id)
                target = await same_project(db, Defect, target_id, defect.project_id, fresh=True)
                target_id = target.duplicate_of_id
        else:
            if supplied.get("duplicate_of_id"):
                raise HTTPException(422, "只有重复解决结果可以指定主缺陷")
            defect.duplicate_of_id = None
        defect.resolution_note = request.note
    defect.workflow_state = action["to"]
    project_state(defect, definition)
    bump(defect)
    event = append_event(db, defect, user, request.action_id, before, note=request.note,
                         request_id=request.request_id, request_hash=digest, extra=supplied)
    await db.flush()
    return defect, event.result_json


async def delete_or_restore(db, user, defect_id, expected_version, *, restore=False):
    defect, context, _ = await locked_defect(db, user, defect_id, expected_version, include_deleted=restore)
    if not context.privileged:
        raise HTTPException(403, "删除和恢复需要项目负责人或测试负责人权限")
    if restore and not defect.deleted_at:
        return defect
    before = snapshot(defect)
    defect.deleted_at = None if restore else utcnow()
    defect.deleted_by = None if restore else user.id
    bump(defect)
    append_event(db, defect, user, "restored" if restore else "deleted", before)
    await db.flush()
    return defect


async def transition_options(db, context, defect):
    definition = await definition_for(db, defect)
    options = []
    for action in definition["transitions"]:
        if defect.workflow_state not in action["from"]:
            continue
        reason = "缺陷已删除，请先恢复" if defect.deleted_at else action_denial(context, defect, action)
        if action["action_id"] == "close" and (defect.resolution != "fixed" or not defect.resolved_at):
            reason = "历史缺陷缺少可信验证记录，请重开补验"
        if action["action_id"] in {"verify_pass", "verify_fail"} and defect.fix_submitted_by_id == context.user.id and not definition["settings"].get("allow_self_verification"):
            reason = "不能验证自己提交的修复"
        options.append({**action, "allowed": reason is None, "disabled_reason": reason})
    return options
