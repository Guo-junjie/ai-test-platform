"""用例评审任务 API：评审人候选、版本化提交、待办与个人结论。"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CaseReviewAssignment, CaseReviewTask, TestCaseAsset, User, UserRole
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.case_reviews import (
    create_review_task,
    decide_review_task,
    reviewer_options,
    task_to_dict,
    tasks_to_dict,
)
from app.schemas.case_library import CaseReviewTaskDecisionRequest, CreateCaseReviewTaskRequest
from app.utils.database import get_db_session


router = APIRouter()
case_editor = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)
case_reviewer = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)


@router.get("/reviewers")
async def list_case_reviewers(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    return {"code": 0, "data": await reviewer_options(db, project_id), "message": "ok"}


@router.get("/review-tasks")
async def list_review_tasks(
    project_id: uuid.UUID,
    scope: Literal["mine", "all", "submitted_by_me"] = "mine",
    status: Literal["pending", "approved", "changes_requested", "cancelled"] | None = None,
    case_id: uuid.UUID | None = None,
    keyword: str | None = Query(default=None, max_length=200),
    case_type: str | None = Query(default=None, max_length=50),
    source: Literal["requirement", "ai_generated", "manual"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    query = select(CaseReviewTask).where(CaseReviewTask.project_id == project_id)
    if scope == "mine":
        query = query.join(CaseReviewAssignment).where(CaseReviewAssignment.reviewer_id == current_user.id)
    elif scope == "submitted_by_me":
        query = query.where(CaseReviewTask.submitted_by == current_user.id)
    if status:
        query = query.where(CaseReviewTask.status == status)
    if case_id:
        query = query.where(CaseReviewTask.case_asset_id == case_id)
    if keyword or case_type or source:
        query = query.join(TestCaseAsset, TestCaseAsset.id == CaseReviewTask.case_asset_id)
    if keyword:
        query = query.where(TestCaseAsset.title.ilike(f"%{keyword.strip()}%"))
    if case_type:
        query = query.where(TestCaseAsset.case_type == case_type)
    if source:
        query = query.where(TestCaseAsset.source == source)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    tasks = (await db.execute(query.order_by(
        CaseReviewTask.status.asc(), CaseReviewTask.submitted_at.desc(),
    ).offset((page - 1) * page_size).limit(page_size))).scalars().unique().all()
    return {"code": 0, "data": {
        "items": await tasks_to_dict(db, tasks, current_user.id),
        "total": total, "page": page, "page_size": page_size,
    }, "message": "ok"}


@router.get("/review-tasks/{task_id}")
async def get_review_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    task = await db.get(CaseReviewTask, task_id)
    if task is None:
        raise HTTPException(404, "评审任务不存在")
    return {"code": 0, "data": await task_to_dict(db, task, current_user.id), "message": "ok"}


@router.post("/review-tasks/{task_id}/decision")
async def decide_case_review_task(
    task_id: uuid.UUID,
    req: CaseReviewTaskDecisionRequest,
    current_user: User = Depends(case_reviewer),
    db: AsyncSession = Depends(get_db_session),
):
    task = await decide_review_task(
        db, task_id=task_id, decision=req.decision, comment=req.comment, actor=current_user,
    )
    return {"code": 0, "data": await task_to_dict(db, task, current_user.id), "message": "评审结论已记录"}


@router.post("/{case_id}/review-tasks")
async def submit_case_review_task(
    case_id: uuid.UUID,
    req: CreateCaseReviewTaskRequest,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
):
    task = await create_review_task(
        db,
        case_id=case_id,
        reviewer_ids=req.reviewer_ids,
        comment=req.comment,
        due_at=req.due_at,
        actor=current_user,
    )
    return {"code": 0, "data": await task_to_dict(db, task, current_user.id), "message": "评审任务已创建"}


@router.get("/{case_id}/review-tasks")
async def list_case_review_tasks(
    case_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    exists = (await db.execute(select(TestCaseAsset.id).where(TestCaseAsset.id == case_id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(404, "用例不存在")
    tasks = (await db.execute(select(CaseReviewTask).where(
        CaseReviewTask.case_asset_id == case_id,
    ).order_by(CaseReviewTask.round.desc()))).scalars().all()
    return {"code": 0, "data": await tasks_to_dict(db, tasks, current_user.id), "message": "ok"}
