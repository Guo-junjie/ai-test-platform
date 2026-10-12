"""用例评审任务领域服务：版本冻结、多人指派、结论聚合与操作留痕。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    CaseAssetStatus,
    CaseReviewAssignment,
    CaseReviewEvent,
    CaseReviewTask,
    Notification,
    Project,
    ProjectMember,
    TestCaseAsset,
    TestCaseAssetVersion,
    User,
    UserRole,
)
from app.modules.runs.case_readiness import api_case_errors


REVIEWER_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER}


def _snapshot(item: TestCaseAsset) -> dict[str, Any]:
    return {
        "title": item.title,
        "description": item.description or "",
        "execution_kind": item.execution_kind or "api",
        "case_type": item.case_type,
        "request_data": item.request_data or {},
        "expected_result": item.expected_result or {},
        "priority": item.priority or "P2",
        "folder": item.folder or "",
        "tags": list(item.tags or []),
        "pre_script": getattr(item, "pre_script", None) or "",
        "post_script": getattr(item, "post_script", None) or "",
        "sql_script": getattr(item, "sql_script", None) or "",
    }


def _content_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _review_errors(item: TestCaseAsset) -> list[str]:
    errors = [] if (item.title or "").strip() else ["用例标题不能为空"]
    if item.execution_kind == "api":
        errors.extend(api_case_errors(item.request_data, item.expected_result))
    elif item.execution_kind == "manual":
        request = item.request_data if isinstance(item.request_data, dict) else {}
        expected = item.expected_result if isinstance(item.expected_result, dict) else {}
        if not isinstance(request.get("steps"), list) or not request["steps"]:
            errors.append("手工用例至少需要一个操作步骤")
        if not isinstance(expected.get("text"), str) or not expected["text"].strip():
            errors.append("手工用例需要明确预期结果")
    return errors


def _normalise_due_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value <= datetime.utcnow():
        raise HTTPException(422, "截止时间必须晚于当前时间")
    return value


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _ensure_version(db: AsyncSession, item: TestCaseAsset) -> TestCaseAssetVersion:
    version = int(item.version or 1)
    row = (await db.execute(select(TestCaseAssetVersion).where(
        TestCaseAssetVersion.case_asset_id == item.id,
        TestCaseAssetVersion.version == version,
    ))).scalar_one_or_none()
    if row is not None:
        return row
    row = TestCaseAssetVersion(
        case_asset_id=item.id,
        version=version,
        snapshot=_snapshot(item),
        change_type="review_baseline",
        changed_by=item.created_by,
    )
    db.add(row)
    await db.flush()
    return row


async def _record_event(
    db: AsyncSession,
    *,
    item: TestCaseAsset,
    actor_id: uuid.UUID,
    action: str,
    task: CaseReviewTask,
    version: TestCaseAssetVersion,
    comment: str = "",
) -> None:
    db.add(CaseReviewEvent(
        case_asset_id=item.id,
        project_id=item.project_id,
        actor_id=actor_id,
        task_id=task.id,
        case_version_id=version.id,
        case_version=version.version,
        action=action,
        comment=comment or None,
        content_hash=_content_hash(version.snapshot or {}),
    ))


async def reviewer_options(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "项目不存在")
    rows = (await db.execute(
        select(User).outerjoin(
            ProjectMember,
            (ProjectMember.user_id == User.id) & (ProjectMember.project_id == project_id),
        ).where(
            User.is_active.is_(True),
            User.role.in_(list(REVIEWER_ROLES)),
            or_(
                User.id == project.owner_id,
                ProjectMember.project_id == project_id,
                User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]),
            ),
        ).order_by(User.username.asc())
    )).scalars().unique().all()
    return [{"id": str(user.id), "username": user.username, "email": user.email, "role": user.role.value} for user in rows]


async def create_review_task(
    db: AsyncSession,
    *,
    case_id: uuid.UUID,
    reviewer_ids: list[uuid.UUID],
    comment: str,
    due_at: datetime | None,
    actor: User,
) -> CaseReviewTask:
    item = (await db.execute(select(TestCaseAsset).where(
        TestCaseAsset.id == case_id,
    ).with_for_update())).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")
    if item.status == CaseAssetStatus.DEPRECATED or item.review_state not in {"draft", "changes_requested"}:
        raise HTTPException(409, "只有草稿或已退回用例可以创建评审任务")
    errors = _review_errors(item)
    if errors:
        raise HTTPException(422, "；".join(errors))
    active = (await db.execute(select(CaseReviewTask.id).where(
        CaseReviewTask.case_asset_id == item.id,
        CaseReviewTask.status == "pending",
    ))).scalar_one_or_none()
    if active is not None:
        raise HTTPException(409, "该用例已有进行中的评审任务")

    reviewer_ids = list(dict.fromkeys(reviewer_ids))
    allowed = {uuid.UUID(row["id"]) for row in await reviewer_options(db, item.project_id)}
    invalid = [value for value in reviewer_ids if value not in allowed]
    if invalid:
        raise HTTPException(422, "评审人不存在、已停用或不具备当前项目评审权限")

    version = await _ensure_version(db, item)
    next_round = int((await db.execute(select(func.max(CaseReviewTask.round)).where(
        CaseReviewTask.case_asset_id == item.id,
    ))).scalar_one_or_none() or 0) + 1
    now = datetime.utcnow()
    task = CaseReviewTask(
        project_id=item.project_id,
        case_asset_id=item.id,
        case_version_id=version.id,
        case_version=version.version,
        round=next_round,
        status="pending",
        approval_rule="all",
        submission_comment=comment or None,
        submitted_by=actor.id,
        submitted_at=now,
        due_at=_normalise_due_at(due_at),
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()
    for reviewer_id in reviewer_ids:
        db.add(CaseReviewAssignment(task_id=task.id, reviewer_id=reviewer_id, status="pending"))
        db.add(Notification(
            user_id=reviewer_id,
            title=f"待评审用例：{item.title}"[:500],
            content=f"{actor.username} 提交了第 {version.version} 版用例，请完成第 {next_round} 轮评审。",
            type="case_review",
            related_url=f"/case-library?project_id={item.project_id}&case_id={item.id}&review_task_id={task.id}",
            resource_type="case_review_task",
            resource_id=task.id,
            dedupe_key=f"case-review-assigned:{task.id}:{reviewer_id}",
        ))
    item.review_state = "pending"
    item.status = CaseAssetStatus.DRAFT
    item.updated_at = now
    await _record_event(db, item=item, actor_id=actor.id, action="submit", task=task, version=version, comment=comment)
    await db.flush()
    return task


async def cancel_pending_review_tasks(
    db: AsyncSession,
    *,
    item: TestCaseAsset,
    actor_id: uuid.UUID,
    reason: str,
) -> int:
    tasks = (await db.execute(select(CaseReviewTask).where(
        CaseReviewTask.case_asset_id == item.id,
        CaseReviewTask.status == "pending",
    ).with_for_update())).scalars().all()
    if not tasks:
        return 0
    now = datetime.utcnow()
    for task in tasks:
        task.status = "cancelled"
        task.completed_at = now
        task.updated_at = now
        assignments = (await db.execute(select(CaseReviewAssignment).where(
            CaseReviewAssignment.task_id == task.id,
            CaseReviewAssignment.status == "pending",
        ))).scalars().all()
        for assignment in assignments:
            assignment.status = "cancelled"
            assignment.updated_at = now
            if assignment.reviewer_id != actor_id:
                db.add(Notification(
                    user_id=assignment.reviewer_id,
                    title=f"用例评审已取消：{item.title}"[:500],
                    content=reason,
                    type="case_review",
                    related_url=f"/case-library?project_id={item.project_id}&case_id={item.id}&review_task_id={task.id}",
                    resource_type="case_review_task",
                    resource_id=task.id,
                    dedupe_key=f"case-review-cancelled:{task.id}:{assignment.reviewer_id}",
                ))
        version = await db.get(TestCaseAssetVersion, task.case_version_id)
        if version is not None:
            await _record_event(db, item=item, actor_id=actor_id, action="cancel", task=task, version=version, comment=reason)
    return len(tasks)


async def decide_review_task(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    decision: str,
    comment: str,
    actor: User,
) -> CaseReviewTask:
    task = (await db.execute(select(CaseReviewTask).where(
        CaseReviewTask.id == task_id,
    ).with_for_update())).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "评审任务不存在")
    if task.status != "pending":
        raise HTTPException(409, "该评审任务已经结束")
    if decision not in {"approve", "changes_requested"}:
        raise HTTPException(422, "不支持的评审结论")
    comment = comment.strip()
    if decision == "changes_requested" and not comment:
        raise HTTPException(422, "退回时必须填写修改意见")

    item = (await db.execute(select(TestCaseAsset).where(
        TestCaseAsset.id == task.case_asset_id,
    ).with_for_update())).scalar_one()
    version = await db.get(TestCaseAssetVersion, task.case_version_id)
    if version is None:
        raise HTTPException(409, "评审绑定的用例版本不存在")
    if int(item.version or 1) != task.case_version or item.review_state != "pending":
        raise HTTPException(409, "用例版本已变化，请重新创建评审任务")

    assignments = (await db.execute(select(CaseReviewAssignment).where(
        CaseReviewAssignment.task_id == task.id,
    ).with_for_update())).scalars().all()
    assignment = next((row for row in assignments if row.reviewer_id == actor.id), None)
    if assignment is None:
        raise HTTPException(403, "你不是该任务的指定评审人")
    if assignment.status != "pending":
        raise HTTPException(409, "你已经提交过本轮评审结论")

    now = datetime.utcnow()
    assignment.status = "approved" if decision == "approve" else "changes_requested"
    assignment.comment = comment or None
    assignment.decided_at = now
    assignment.updated_at = now
    if decision == "changes_requested":
        task.status = "changes_requested"
        task.completed_at = now
        for other in assignments:
            if other.id != assignment.id and other.status == "pending":
                other.status = "cancelled"
                other.updated_at = now
        item.review_state = "changes_requested"
        item.status = CaseAssetStatus.DRAFT
    elif all(row.status == "approved" for row in assignments):
        errors = _review_errors(item)
        if errors:
            raise HTTPException(422, "；".join(errors))
        task.status = "approved"
        task.completed_at = now
        item.review_state = "approved"
        item.status = CaseAssetStatus.ADOPTED
    task.updated_at = now
    item.updated_at = now
    await _record_event(db, item=item, actor_id=actor.id, action=decision, task=task, version=version, comment=comment)

    if task.status in {"approved", "changes_requested"}:
        label = "已通过" if task.status == "approved" else "需修改"
        db.add(Notification(
            user_id=task.submitted_by,
            title=f"用例评审{label}：{item.title}"[:500],
            content=f"第 {task.case_version} 版用例的第 {task.round} 轮评审结论为“{label}”。",
            type="case_review",
            related_url=f"/case-library?project_id={item.project_id}&case_id={item.id}&review_task_id={task.id}",
            resource_type="case_review_task",
            resource_id=task.id,
            dedupe_key=f"case-review-completed:{task.id}:{task.status}",
        ))
    await db.flush()
    return task


def _task_dict(
    task: CaseReviewTask,
    item: TestCaseAsset | None,
    version: TestCaseAssetVersion | None,
    submitter: User | None,
    rows: list[tuple[CaseReviewAssignment, User]],
    current_user_id: uuid.UUID,
) -> dict[str, Any]:
    reviewers = [{
        "assignment_id": str(assignment.id),
        "reviewer_id": str(assignment.reviewer_id),
        "reviewer_name": reviewer.username,
        "reviewer_role": reviewer.role.value,
        "status": assignment.status,
        "comment": assignment.comment or "",
        "decided_at": _iso_utc(assignment.decided_at),
    } for assignment, reviewer in rows]
    mine = next((row for row in reviewers if row["reviewer_id"] == str(current_user_id)), None)
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "case_asset_id": str(task.case_asset_id),
        "case_version_id": str(task.case_version_id),
        "case_version": task.case_version,
        "round": task.round,
        "status": task.status,
        "approval_rule": task.approval_rule,
        "submission_comment": task.submission_comment or "",
        "submitted_by": str(task.submitted_by),
        "submitter_name": submitter.username if submitter else None,
        "submitted_at": _iso_utc(task.submitted_at),
        "due_at": _iso_utc(task.due_at),
        "completed_at": _iso_utc(task.completed_at),
        "created_at": _iso_utc(task.created_at),
        "reviewers": reviewers,
        "approved_count": sum(row["status"] == "approved" for row in reviewers),
        "reviewer_count": len(reviewers),
        "overdue": bool(task.status == "pending" and task.due_at and task.due_at < datetime.utcnow()),
        "my_assignment_status": mine["status"] if mine else None,
        "can_review": bool(task.status == "pending" and mine and mine["status"] == "pending"),
        "case": {
            "id": str(item.id), "title": item.title, "priority": item.priority,
            "execution_kind": item.execution_kind, "review_state": item.review_state,
            "status": getattr(item.status, "value", item.status),
            "source": getattr(item.source, "value", item.source),
            "current_version": int(item.version or 1),
        } if item else None,
        "version": {
            "id": str(version.id), "version": version.version, "snapshot": version.snapshot or {},
            "change_type": version.change_type,
            "created_at": _iso_utc(version.created_at),
        } if version else None,
    }


async def tasks_to_dict(
    db: AsyncSession,
    tasks: list[CaseReviewTask],
    current_user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """批量装配任务详情，避免任务列表按行查询用例、版本、用户和指派。"""
    if not tasks:
        return []
    task_ids = [task.id for task in tasks]
    asset_ids = list({task.case_asset_id for task in tasks})
    version_ids = list({task.case_version_id for task in tasks})
    submitter_ids = list({task.submitted_by for task in tasks})
    assets = (await db.execute(select(TestCaseAsset).where(TestCaseAsset.id.in_(asset_ids)))).scalars().all()
    versions = (await db.execute(select(TestCaseAssetVersion).where(
        TestCaseAssetVersion.id.in_(version_ids),
    ))).scalars().all()
    submitters = (await db.execute(select(User).where(User.id.in_(submitter_ids)))).scalars().all()
    assignment_rows = (await db.execute(select(CaseReviewAssignment, User).join(
        User, User.id == CaseReviewAssignment.reviewer_id,
    ).where(CaseReviewAssignment.task_id.in_(task_ids)).order_by(User.username.asc()))).all()
    assets_by_id = {row.id: row for row in assets}
    versions_by_id = {row.id: row for row in versions}
    users_by_id = {row.id: row for row in submitters}
    assignments_by_task: dict[uuid.UUID, list[tuple[CaseReviewAssignment, User]]] = {}
    for assignment, reviewer in assignment_rows:
        assignments_by_task.setdefault(assignment.task_id, []).append((assignment, reviewer))
    return [
        _task_dict(
            task,
            assets_by_id.get(task.case_asset_id),
            versions_by_id.get(task.case_version_id),
            users_by_id.get(task.submitted_by),
            assignments_by_task.get(task.id, []),
            current_user_id,
        )
        for task in tasks
    ]


async def task_to_dict(db: AsyncSession, task: CaseReviewTask, current_user_id: uuid.UUID) -> dict[str, Any]:
    return (await tasks_to_dict(db, [task], current_user_id))[0]
