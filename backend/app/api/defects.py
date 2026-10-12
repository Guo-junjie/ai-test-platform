"""缺陷中心：薄路由，写操作统一由缺陷领域服务校验。"""
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.models.database import (
    AuditLog, Defect, DefectEvent, DefectOccurrence, DefectReference, EnvironmentProfile,
    ProjectMember, RequirementDoc, TestCaseAsset, TestRun, User, UserRole, ProjectDefectSettings, DefectWorkflow, DefectWorkflowRevision,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.defects.permissions import context_for, validate_participant, can_edit
from app.modules.defects.query import filter_conditions, enrich_list, detail_dict, display_event_changes
from app.modules.defects.service import (
    DIRECTORY_MODELS, add_reference, append_event, assign_defect, bump,
    create_defect as create_service, delete_or_restore, edit_defect, json_value,
    locked_defect, requirement_keys, same_project, snapshot, transition_defect,
)
from app.modules.defects.workflow import DEFAULT_WORKFLOW, PRIORITY_LABELS, STATES
from app.schemas.defects import AssignmentRequest, DefectCreate, DefectUpdate, DirectoryInput, LegacyStatusRequest, ReferenceInput, TransitionRequest
from app.utils.database import get_db_session

router = APIRouter()
catalog_router = APIRouter()


def success(data, message="success"):
    return {"code": 0, "data": data, "message": message}


async def read_defect(db, defect_id, user):
    defect = (await db.execute(select(Defect).where(Defect.id == defect_id))).scalar_one_or_none()
    if defect is None:
        raise HTTPException(404, "缺陷不存在或无权访问")
    if defect.project_id:
        await context_for(db, user, defect.project_id)
    elif user.role not in {UserRole.ADMIN, UserRole.SUPER_ADMIN}:
        raise HTTPException(404, "缺陷不存在或无权访问")
    return defect


@router.get("/metadata")
async def metadata(project_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    context = await context_for(db, user, project_id)
    states = DEFAULT_WORKFLOW["states"]
    settings_row = await db.get(ProjectDefectSettings, project_id)
    if settings_row and settings_row.default_workflow_id:
        workflow = await db.get(DefectWorkflow, settings_row.default_workflow_id)
        revision = await db.get(DefectWorkflowRevision, workflow.active_revision_id) if workflow and workflow.active_revision_id else None
        if revision and revision.status == "published": states = revision.definition_json.get("states", states)
    data = {"states": states, "priorities": PRIORITY_LABELS,
            "can_create": context.writable and bool(context.roles), "can_configure": "project_manager" in context.roles,
            "roles": sorted(context.roles)}
    for key, model in DIRECTORY_MODELS.items():
        query = select(model).where(model.project_id == project_id)
        if key == "modules":
            query = query.where(model.is_active.is_(True)).order_by(model.path)
        else:
            query = query.where(model.status != "archived").order_by(model.name)
        items = (await db.execute(query.limit(1000))).scalars().all()
        data[key] = [{column.name: json_value(getattr(item, column.name)) for column in model.__table__.columns} for item in items]
    envs = (await db.execute(select(EnvironmentProfile).where(EnvironmentProfile.project_id == project_id,
                            EnvironmentProfile.status != "archived").order_by(EnvironmentProfile.name))).scalars().all()
    data["environments"] = [{"id": str(item.id), "name": item.name, "status": item.status} for item in envs]
    docs = (await db.execute(select(RequirementDoc).where(RequirementDoc.project_id == project_id).order_by(RequirementDoc.created_at.desc()).limit(200))).scalars().all()
    data["requirements"] = [{"id": str(item.id), "filename": item.filename,
                              "items": [{"key": key, "title": title} for key, title in requirement_keys(item.requirements_json or {}).items()]} for item in docs]
    cases = (await db.execute(select(TestCaseAsset.id, TestCaseAsset.title).where(TestCaseAsset.project_id == project_id)
                              .order_by(TestCaseAsset.updated_at.desc()).limit(200))).all()
    data["cases"] = [{"id": str(item.id), "title": item.title} for item in cases]
    return success(data)


@router.get("/participants")
async def participants(project_id: UUID, purpose: str = "all", q: str = "", db=Depends(get_db_session), user=Depends(get_current_user)):
    context = await context_for(db, user, project_id)
    if purpose not in {"all", "assignee", "verifier"}:
        raise HTTPException(422, "未知的选人用途")
    members = select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    candidates = (await db.execute(select(User).where(User.is_active.is_(True),
                  or_(User.id.in_(members), User.id == context.project.owner_id),
                  User.role.notin_([UserRole.VIEWER, UserRole.AUDITOR]),
                  User.username.ilike("%" + q + "%")).order_by(User.username).limit(200))).scalars().all()
    items = []
    for candidate in candidates:
        if purpose != "all":
            try:
                await validate_participant(db, context.project, candidate.id, purpose)
            except HTTPException:
                continue
        items.append({"id": str(candidate.id), "username": candidate.username, "role": candidate.role.value})
    return success({"items": items})


@router.get("/duplicates")
async def duplicates(project_id: UUID, title: str = Query(..., min_length=2, max_length=500), exclude_defect_id: UUID | None = None,
                     db=Depends(get_db_session), user=Depends(get_current_user)):
    await context_for(db, user, project_id)
    query = select(Defect).where(Defect.project_id == project_id, Defect.deleted_at.is_(None),
                                 func.lower(Defect.title) == title.strip().lower())
    if exclude_defect_id:
        query = query.where(Defect.id != exclude_defect_id)
    rows = (await db.execute(query.order_by(Defect.created_at.desc()).limit(10))).scalars().all()
    return success({"items": await enrich_list(db, rows)})


@router.get("")
async def list_defects(project_id: UUID | None = None, test_run_id: UUID | None = None,
                       severity: str | None = None, defect_type: str | None = None, status_code: str | None = None,
                       workflow_states: list[str] | None = Query(None), priority: str | None = None,
                       assignee_id: UUID | None = None, reporter_id: UUID | None = None,
                       verifier_id: UUID | None = None,
                       module_id: UUID | None = None, iteration_id: UUID | None = None, environment_profile_id: UUID | None = None,
                       label: str | None = None, source: str | None = None, q: str | None = Query(None, max_length=500),
                       created_from: datetime | None = None, created_to: datetime | None = None,
                       updated_from: datetime | None = None, updated_to: datetime | None = None,
                       overdue: bool = False, watching: bool = False,
                       view: str | None = None, include_deleted: bool = False,
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       db=Depends(get_db_session), current_user=Depends(get_current_user)):
    if include_deleted:
        if not project_id or not (await context_for(db, current_user, project_id)).privileged:
            raise HTTPException(403, "回收站需要指定项目且具有管理权限")
    conds = filter_conditions(project_id=project_id, test_run_id=test_run_id, severity=severity, defect_type=defect_type,
          status_code=status_code, workflow_states=workflow_states, priority=priority, assignee_id=assignee_id,
          reporter_id=reporter_id, verifier_id=verifier_id, module_id=module_id, iteration_id=iteration_id,
          environment_profile_id=environment_profile_id, label=label, source=source, q=q, view=view,
          created_from=created_from, created_to=created_to, updated_from=updated_from, updated_to=updated_to,
          overdue=overdue, watching=watching,
          user_id=current_user.id, include_deleted=include_deleted)
    base = select(Defect).outerjoin(TestRun, TestRun.id == Defect.test_run_id).where(*conds)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(Defect.updated_at.desc(), Defect.id.desc())
                            .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    grouped = (await db.execute(select(Defect.severity, Defect.status, Defect.workflow_state, Defect.workflow_revision_id, func.count())
              .outerjoin(TestRun, TestRun.id == Defect.test_run_id).where(*conds)
              .group_by(Defect.severity, Defect.status, Defect.workflow_state, Defect.workflow_revision_id))).all()
    revision_ids = {row[3] for row in grouped if row[3]}
    definitions = {item.id: {state["key"]: state for state in item.definition_json.get("states", [])}
                   for item in (await db.execute(select(DefectWorkflowRevision).where(
                       DefectWorkflowRevision.id.in_(revision_ids)))).scalars().all()} if revision_ids else {}
    stats = {"by_severity": {key: 0 for key in ("P0", "P1", "P2", "P3")},
             "by_status": {key: 0 for key in ("open", "in_fix", "verified", "closed", "rejected")},
             "by_state": {key: 0 for key in STATES}, "backlog": 0, "pending_verification": 0}
    for sev, legacy, state, revision_id, count in grouped:
        stats["by_severity"][sev.value] += count
        stats["by_status"][legacy or "open"] += count
        stats["by_state"][state] = stats["by_state"].get(state, 0) + count
        state_definition = definitions.get(revision_id, STATES).get(state, {})
        if state_definition.get("is_backlog"):
            stats["backlog"] += count
        if state_definition.get("category") == "verification":
            stats["pending_verification"] += count
    return success({"list": await enrich_list(db, rows), "total": total, "page": page, "page_size": page_size, "stats": stats})


@router.post("")
async def create_defect(req: DefectCreate, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect = await create_service(db, user, req)
    await db.commit()
    return success(await detail_dict(db, defect, user), "缺陷已登记")


@router.get("/{defect_id}")
async def get_defect(defect_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    return success(await detail_dict(db, await read_defect(db, defect_id, user), user))


@router.patch("/{defect_id}")
@router.put("/{defect_id}")
async def update_defect(defect_id: UUID, req: DefectUpdate, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect = await edit_defect(db, user, defect_id, req)
    await db.commit()
    return success(await detail_dict(db, defect, user), "缺陷已保存")


@router.post("/{defect_id}/assign")
async def assign(defect_id: UUID, req: AssignmentRequest, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, result = await assign_defect(db, user, defect_id, req)
    await db.commit()
    return success({**result, "detail": await detail_dict(db, defect, user)}, "责任人已更新")


@router.get("/{defect_id}/transitions")
async def transitions(defect_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    return success({"items": (await detail_dict(db, await read_defect(db, defect_id, user), user))["transitions"]})


@router.post("/{defect_id}/transitions")
async def transition(defect_id: UUID, req: TransitionRequest, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, result = await transition_defect(db, user, defect_id, req)
    await db.commit()
    return success({**result, "detail": await detail_dict(db, defect, user)}, "缺陷流转成功")


@router.patch("/{defect_id}/status")
async def legacy_status(defect_id: UUID, req: LegacyStatusRequest, db=Depends(get_db_session), user=Depends(get_current_user)):
    defect = await read_defect(db, defect_id, user)
    actions = {"in_fix": "resume" if defect.workflow_state == "reopened" else "start",
               "verified": "verify_pass", "closed": "close", "rejected": "reject"}
    if req.status == "open":
        action = "reopen" if defect.workflow_state in {"resolved", "closed", "rejected"} else "return_to_queue"
    else:
        action = actions[req.status]
    return await transition(defect_id, TransitionRequest(action_id=action, expected_version=req.expected_version,
                         request_id=req.request_id, note=req.note, fields=req.fields), db, user)


@router.get("/{defect_id}/events")
async def events(defect_id: UUID, after_sequence: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                 db=Depends(get_db_session), user=Depends(get_current_user)):
    await read_defect(db, defect_id, user)
    rows = (await db.execute(select(DefectEvent, User.username).outerjoin(User, User.id == DefectEvent.actor_id)
                             .where(DefectEvent.defect_id == defect_id, DefectEvent.sequence > after_sequence)
                             .order_by(DefectEvent.sequence).limit(limit + 1))).all()
    items = [{"id": str(item.id), "sequence": item.sequence, "event_type": item.event_type,
               "actor_id": str(item.actor_id) if item.actor_id else None, "actor_name": name or "系统",
               "from_state": item.from_state, "to_state": item.to_state, "changes": item.changes_json,
               "note": item.note, "is_legacy": item.is_legacy, "occurred_at": json_value(item.occurred_at)} for item, name in rows[:limit]]
    await display_event_changes(db, items)
    return success({"items": items, "has_more": len(rows) > limit, "next_sequence": items[-1]["sequence"] if items else after_sequence})


@router.get("/{defect_id}/occurrences")
async def occurrences(defect_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
    await read_defect(db, defect_id, user)
    items = (await db.execute(select(DefectOccurrence).where(DefectOccurrence.defect_id == defect_id)
                              .order_by(DefectOccurrence.observed_at.desc()).limit(100))).scalars().all()
    return success({"items": [{column.name: json_value(getattr(item, column.name)) for column in DefectOccurrence.__table__.columns} for item in items]})


@router.post("/{defect_id}/references")
async def reference_add(defect_id: UUID, req: ReferenceInput, expected_version: int = Query(..., ge=1),
                        db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, context, _ = await locked_defect(db, user, defect_id, expected_version)
    if not can_edit(context, defect):
        raise HTTPException(403, "没有修改此缺陷关联的权限")
    before = snapshot(defect)
    await add_reference(db, defect, req)
    bump(defect)
    append_event(db, defect, user, "reference_added", before, extra=req.model_dump(mode="json"))
    await db.commit()
    return success(await detail_dict(db, defect, user))


@router.delete("/{defect_id}/references/{reference_id}")
async def reference_remove(defect_id: UUID, reference_id: UUID, expected_version: int = Query(..., ge=1),
                           db=Depends(get_db_session), user=Depends(get_current_user)):
    defect, context, _ = await locked_defect(db, user, defect_id, expected_version)
    if not can_edit(context, defect):
        raise HTTPException(403, "没有修改此缺陷关联的权限")
    item = (await db.execute(select(DefectReference).where(DefectReference.id == reference_id,
                                                         DefectReference.defect_id == defect_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "关联记录不存在")
    before = snapshot(defect)
    await db.delete(item)
    bump(defect)
    append_event(db, defect, user, "reference_removed", before, extra={"reference_id": str(reference_id), "title": item.title_snapshot})
    await db.commit()
    return success(await detail_dict(db, defect, user))


@router.delete("/{defect_id}")
async def delete_defect(defect_id: UUID, expected_version: int = Query(..., ge=1), db=Depends(get_db_session), user=Depends(get_current_user)):
    defect = await delete_or_restore(db, user, defect_id, expected_version)
    await db.commit()
    return success({"id": str(defect.id), "deleted": True, "row_version": defect.row_version})


@router.post("/{defect_id}/restore")
async def restore_defect(defect_id: UUID, expected_version: int = Query(..., ge=1), db=Depends(get_db_session), user=Depends(get_current_user)):
    defect = await delete_or_restore(db, user, defect_id, expected_version, restore=True)
    await db.commit()
    return success(await detail_dict(db, defect, user), "缺陷已恢复")


async def directory_list(project_id, kind, db, user):
    await context_for(db, user, project_id)
    model = DIRECTORY_MODELS[kind]
    items = (await db.execute(select(model).where(model.project_id == project_id).order_by(model.name).limit(1000))).scalars().all()
    return success({"items": [{column.name: json_value(getattr(item, column.name)) for column in model.__table__.columns} for item in items]})


async def directory_write(project_id, kind, req, db, user, identifier=None):
    context = await context_for(db, user, project_id, write=True)
    if "project_manager" not in context.roles:
        raise HTTPException(403, "项目目录配置仅限项目负责人或管理员")
    model = DIRECTORY_MODELS[kind]
    item = await same_project(db, model, identifier, project_id) if identifier else model(id=uuid4(), project_id=project_id)
    if kind == "modules":
        parent_id = req.parent_id if "parent_id" in req.model_fields_set else item.parent_id
        parent = await same_project(db, model, parent_id, project_id, active=True)
        if identifier and (parent_id != item.parent_id or req.name != item.name):
            children = (await db.execute(select(model.id).where(model.parent_id == item.id))).scalars().all()
            if children:
                raise HTTPException(422, "有子模块时不能改名或调整父目录，请先调整子模块")
        if parent and (parent.id == item.id or (item.path and parent.path.startswith(item.path + "/"))):
            raise HTTPException(422, "模块不能形成父子循环")
        item.parent_id = parent_id
        item.path = (parent.path + "/" if parent else "") + req.name
        if len(item.path) > 500:
            raise HTTPException(422, "模块目录过长")
        if req.is_active is not None:
            item.is_active = req.is_active
    else:
        allowed = {"planned", "active", "completed", "archived"} if kind == "iterations" else {"planned", "released", "archived"}
        if req.status and req.status not in allowed:
            raise HTTPException(422, "无效的目录状态")
        item.status = req.status or getattr(item, "status", None) or "planned"
        for key in (("start_date", "end_date") if kind == "iterations" else ("build_ref", "released_at")):
            if key in req.model_fields_set:
                setattr(item, key, getattr(req, key))
    item.name = req.name
    db.add(item)
    db.add(AuditLog(user_id=user.id, action="defect_directory_updated", resource_type=kind,
                    resource_id=str(item.id), details={"project_id": str(project_id), "name": req.name}))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "目录名称或路径已存在，请检查日期及引用关系")
    return success({column.name: json_value(getattr(item, column.name)) for column in model.__table__.columns})


def register_catalog(kind):
    async def listing(project_id: UUID, db=Depends(get_db_session), user=Depends(get_current_user)):
        return await directory_list(project_id, kind, db, user)
    async def creating(project_id: UUID, req: DirectoryInput, db=Depends(get_db_session), user=Depends(get_current_user)):
        return await directory_write(project_id, kind, req, db, user)
    async def updating(project_id: UUID, directory_id: UUID, req: DirectoryInput, db=Depends(get_db_session), user=Depends(get_current_user)):
        return await directory_write(project_id, kind, req, db, user, directory_id)
    catalog_router.add_api_route("/{project_id}/" + kind, listing, methods=["GET"], name="defect_" + kind + "_list")
    catalog_router.add_api_route("/{project_id}/" + kind, creating, methods=["POST"], name="defect_" + kind + "_create")
    catalog_router.add_api_route("/{project_id}/" + kind + "/{directory_id}", updating, methods=["PATCH"], name="defect_" + kind + "_update")


for _kind in DIRECTORY_MODELS:
    register_catalog(_kind)
