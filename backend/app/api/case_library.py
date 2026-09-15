"""
能力3（用例资产）API 路由 + 能力5/6/7 脚本绑定扩展

提供：
- POST /generate:       AI 生成并落库
- GET  /:               列表
- GET  /{id}:           详情
- PUT  /{id}:           编辑
- DELETE /{id}:         删除
- POST /{id}/adopt:     单条接纳
- POST /{id}/deprecate: 单条废弃
- POST /adopt-batch:    批量接纳
- PUT  /{id}/scripts:   绑定脚本（能力5/6/7 扩展）
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.case_library import (
    GenerateRequest,
    UpdateCaseRequest,
    AdoptBatchRequest,
    CaseAssetResponse,
)
from app.schemas.script import BindScriptRequest
from app.models.database import CaseAssetStatus, CaseReviewEvent, TestCaseAsset, User, UserRole
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.runs.case_readiness import api_case_errors
from app.utils.database import get_db_session

router = APIRouter()
case_editor = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)
case_reviewer = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.AUDITOR)


class ReviewDecisionRequest(BaseModel):
    decision: str  # approve / changes_requested
    comment: str = Field(default="", max_length=2000)


def _record_review(db: AsyncSession, item: TestCaseAsset, actor: User,
                   action: str, comment: str = "") -> None:
    content = {"title": item.title, "description": item.description,
               "execution_kind": item.execution_kind, "case_type": item.case_type,
               "request_data": item.request_data, "expected_result": item.expected_result,
               "priority": item.priority, "pre_script": item.pre_script,
               "post_script": item.post_script, "sql_script": item.sql_script}
    fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                             default=str).encode("utf-8")).hexdigest()
    db.add(CaseReviewEvent(case_asset_id=item.id, project_id=item.project_id,
                           actor_id=actor.id, action=action, comment=comment,
                           content_hash=fingerprint))


def _review_errors(item: TestCaseAsset) -> list[str]:
    errors = [] if (item.title or "").strip() else ["用例标题不能为空"]
    if item.execution_kind == "api":
        errors.extend(api_case_errors(item.request_data, item.expected_result))
    elif item.execution_kind == "manual":
        expected = item.expected_result if isinstance(item.expected_result, dict) else {}
        if not isinstance(expected.get("text"), str) or not expected["text"].strip():
            errors.append("手工用例需要明确预期结果")
    return errors


@router.post("/generate")
async def generate_cases(
    req: GenerateRequest,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """AI 生成测试用例并落库（DRAFT 状态）。

    支持三粒度：
      - 整项目（req.endpoint_ids / endpoint_id 均空）：自动取 project 下全部 active 接口
      - 多接口（req.endpoint_ids）：指定待生成的接口资产 id 列表
      - 单接口（req.endpoint_id）：指定单个接口资产 id
    """
    from app.models.database import TestCaseAsset, ApiEndpoint
    from app.modules.case_generator.case_generator import TestCaseGenerator

    # 校验 project_id 合法 UUID
    try:
        pid = uuid.UUID(req.project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid project_id (must be UUID)")

    generator = TestCaseGenerator()

    # 构建 API 列表
    apis = []
    if req.endpoint_ids:
        # 多接口粒度
        for eid in req.endpoint_ids:
            try:
                ep_uuid = uuid.UUID(eid)
            except (ValueError, TypeError):
                continue
            result = await db.execute(
                select(ApiEndpoint).where(ApiEndpoint.id == ep_uuid)
            )
            ep = result.scalar_one_or_none()
            if ep and ep.project_id == pid:
                apis.append(_ep_to_dict(ep))
    elif req.endpoint_id:
        # 单接口粒度
        try:
            ep_uuid = uuid.UUID(req.endpoint_id)
        except (ValueError, TypeError):
            pass
        else:
            result = await db.execute(
                select(ApiEndpoint).where(ApiEndpoint.id == ep_uuid)
            )
            ep = result.scalar_one_or_none()
            if ep and ep.project_id == pid:
                apis.append(_ep_to_dict(ep))
    else:
        # 整项目粒度：自动取 project 下所有 active 接口（上限 30，避免一次生成过大）
        result = await db.execute(
            select(ApiEndpoint)
            .where(ApiEndpoint.project_id == pid, ApiEndpoint.is_active == True)
            .order_by(ApiEndpoint.method, ApiEndpoint.path)
            .limit(30)
        )
        for ep in result.scalars().all():
            apis.append(_ep_to_dict(ep))

    if not apis:
        raise HTTPException(
            status_code=400,
            detail="未找到可用接口：请确认项目下已有解析出的接口资产（数据源→接口文档），或在弹窗中勾选接口后再生成",
        )

    # 生成用例（能力12 P1：传项目 ID，知识库注入按项目过滤）
    cases = await generator.generate_all(apis, {}, project_id=str(pid))

    # 落库
    saved = []
    for case in cases.get("api", []):
        asset = TestCaseAsset(
            id=str(uuid.uuid4()),
            project_id=req.project_id,
            case_type=case.get("case_type", "positive"),
            # M2：语义拆分——AI 接口用例 execution_kind=api，设计类型沿用 case_type
            execution_kind="api",
            design_type=case.get("case_type", "positive"),
            title=case.get("case_name", ""),
            description=case.get("description", ""),
            request_data=case.get("request", {}),
            expected_result=case.get("expected"),
            priority=case.get("priority", "P2"),
            status="DRAFT",
            source="ai_generated",
            created_by=current_user.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(asset)
        saved.append(asset)

    await db.flush()

    return {
        "code": 0,
        "data": {
            "cases": [
                {
                    "id": a.id,
                    "case_type": a.case_type,
                    "title": a.title,
                    "status": a.status,
                }
                for a in saved
            ],
            "total": len(saved),
            "inserted": len(saved),  # 兼容前端 caseApi.generate 返回字段（成功提示用）
        },
        "message": "ok",
    }


def _ep_to_dict(ep) -> dict[str, Any]:
    """ApiEndpoint ORM → 生成器所需 dict 的标准化映射（前后端字段名统一）。"""
    return {
        "path": ep.path,
        "http_method": ep.method,  # ApiEndpoint 列名是 method，前端/生成器期望 http_method
        "params": ep.params or [],
        "auth_required": bool(ep.auth_required),
        "summary": ep.summary or "",
    }


@router.get("")
async def list_cases(
    project_id: str | None = None,
    endpoint_id: str | None = None,
    case_type: str | None = None,
    status: str | None = None,
    source: str | None = None,  # 新增：ai_generated / requirement / manual
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取用例列表。"""
    from app.models.database import TestCaseAsset

    query = select(TestCaseAsset).order_by(TestCaseAsset.created_at.desc())
    if project_id:
        query = query.where(TestCaseAsset.project_id == project_id)
    if endpoint_id:
        query = query.where(TestCaseAsset.endpoint_id == endpoint_id)
    if case_type:
        query = query.where(TestCaseAsset.case_type == case_type)
    if status:
        query = query.where(TestCaseAsset.status == status)
    if source:
        query = query.where(TestCaseAsset.source == source)
    if keyword:
        query = query.where(
            TestCaseAsset.title.ilike(f"%{keyword}%")
        )

    total = (await db.execute(select(func.count()).select_from(
        query.order_by(None).subquery()))).scalar_one()

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "code": 0,
        "data": {
            "items": [
                {
                    "id": item.id,
                    "project_id": item.project_id,
                    "endpoint_id": getattr(item, "endpoint_id", None),
                    "case_type": item.case_type,
                    "title": item.title,
                    "description": getattr(item, "description", ""),
                    "request_data": getattr(item, "request_data", {}),
                    "expected_result": getattr(item, "expected_result", None),
                    "priority": item.priority,
                    "status": item.status,
                    "execution_kind": item.execution_kind,
                    "review_state": item.review_state,
                    "source": getattr(item, "source", ""),
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                }
                for item in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "message": "ok",
    }


@router.get("/{case_id}")
async def get_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取用例详情。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    return {
        "code": 0,
        "data": {
            "id": item.id,
            "project_id": item.project_id,
            "endpoint_id": getattr(item, "endpoint_id", None),
            "case_type": item.case_type,
            "title": item.title,
            "description": getattr(item, "description", ""),
            "request_data": getattr(item, "request_data", {}),
            "expected_result": getattr(item, "expected_result", None),
            "priority": item.priority,
            "status": item.status,
            "execution_kind": item.execution_kind,
            "review_state": item.review_state,
            "source": getattr(item, "source", ""),
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        },
        "message": "ok",
    }


@router.put("/{case_id}")
async def update_case(
    case_id: str,
    req: UpdateCaseRequest,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """编辑用例资产。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if req.title is not None:
        item.title = req.title
    if req.description is not None:
        item.description = req.description
    if req.request_data is not None:
        source_doc = (item.request_data or {}).get("requirement_doc_id")
        updated_request = dict(req.request_data)
        if source_doc:
            updated_request["requirement_doc_id"] = source_doc
        item.request_data = updated_request
    if req.expected_result is not None:
        item.expected_result = req.expected_result
    if req.priority is not None:
        item.priority = req.priority
    if req.case_type is not None:
        item.case_type = req.case_type
        item.design_type = req.case_type  # M2：设计类型同步
    if req.execution_kind is not None:
        if req.execution_kind not in {"manual", "api"}:
            raise HTTPException(422, "当前用例库只允许手工或 API 执行类型")
        item.execution_kind = req.execution_kind

    if item.review_state in {"pending", "approved", "changes_requested"}:
        item.review_state = "draft"
        item.status = CaseAssetStatus.DRAFT
        _record_review(db, item, current_user, "edit", "内容变更，重新进入草稿")
    item.updated_at = datetime.utcnow()
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.delete("/{case_id}")
async def delete_case(
    case_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """删除用例资产。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if item.review_state != "draft" or item.status == CaseAssetStatus.ADOPTED:
        raise HTTPException(409, "已进入评审或计划流程的用例不能物理删除，请废弃")
    await db.delete(item)
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{case_id}/submit-review")
async def submit_case_review(
    case_id: str,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    item = (await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == case_id)
                             .with_for_update())).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")
    if item.status == CaseAssetStatus.DEPRECATED or item.review_state not in {"draft", "changes_requested"}:
        raise HTTPException(409, "只有草稿或退回用例可以提交评审")
    errors = _review_errors(item)
    if errors:
        raise HTTPException(422, "；".join(errors))
    item.review_state = "pending"
    _record_review(db, item, current_user, "submit")
    await db.flush()
    return {"code": 0, "data": {"review_state": "pending"}, "message": "已提交评审"}


@router.post("/{case_id}/review")
async def review_case(
    case_id: str,
    req: ReviewDecisionRequest,
    current_user: User = Depends(case_reviewer),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    item = (await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == case_id)
                             .with_for_update())).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")
    if item.review_state != "pending":
        raise HTTPException(409, "用例尚未提交评审")
    if req.decision not in {"approve", "changes_requested"}:
        raise HTTPException(422, "评审结论必须是 approve 或 changes_requested")
    if req.decision == "changes_requested" and not req.comment.strip():
        raise HTTPException(422, "退回时必须填写修改意见")
    if req.decision == "approve":
        errors = _review_errors(item)
        if errors:
            raise HTTPException(422, "；".join(errors))
        item.status = CaseAssetStatus.ADOPTED
        item.review_state = "approved"
    else:
        item.status = CaseAssetStatus.DRAFT
        item.review_state = "changes_requested"
    item.updated_at = datetime.utcnow()
    _record_review(db, item, current_user, req.decision, req.comment.strip())
    await db.flush()
    return {"code": 0, "data": {"review_state": item.review_state}, "message": "评审已记录"}


@router.get("/{case_id}/review-events")
async def get_case_review_events(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    item = (await db.execute(select(TestCaseAsset.id).where(TestCaseAsset.id == case_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")
    rows = (await db.execute(select(CaseReviewEvent, User.username)
                             .join(User, User.id == CaseReviewEvent.actor_id)
                             .where(CaseReviewEvent.case_asset_id == item)
                             .order_by(CaseReviewEvent.created_at.asc()))).all()
    return {"code": 0, "data": [{"id": str(row.id), "actor_id": str(row.actor_id),
                                   "actor_name": username, "action": row.action,
                                   "comment": row.comment, "content_hash": row.content_hash,
                                   "created_at": row.created_at.isoformat() if row.created_at else None}
                                  for row, username in rows], "message": "ok"}


@router.post("/{case_id}/adopt")
async def adopt_case(
    case_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """单条接纳用例。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if item.review_state != "pending":
        raise HTTPException(409, "请先提交评审，再批准用例")
    errors = _review_errors(item)
    if errors:
        raise HTTPException(422, "；".join(errors))
    item.status = CaseAssetStatus.ADOPTED
    item.review_state = "approved"
    item.updated_at = datetime.utcnow()
    _record_review(db, item, current_user, "approve")
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{case_id}/deprecate")
async def deprecate_case(
    case_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """单条废弃用例。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    item.status = CaseAssetStatus.DEPRECATED
    item.review_state = "changes_requested"
    item.updated_at = datetime.utcnow()
    _record_review(db, item, current_user, "deprecate")
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/adopt-batch")
async def adopt_batch(
    req: AdoptBatchRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """批量接纳用例。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id.in_(req.ids))
    )
    items = result.scalars().all()

    if len(items) != len(set(req.ids)):
        raise HTTPException(404, "部分用例不存在")
    invalid = [item.title for item in items if item.review_state != "pending" or _review_errors(item)]
    if invalid:
        raise HTTPException(409, f"以下用例未通过提交评审或内容校验：{', '.join(invalid[:5])}")
    for item in items:
        item.status = CaseAssetStatus.ADOPTED
        item.review_state = "approved"
        item.updated_at = datetime.utcnow()
        _record_review(db, item, current_user, "approve")

    await db.flush()

    return {"code": 0, "data": {"count": len(items)}, "message": "ok"}


# ============ 能力5/6/7 扩展：脚本绑定 ============

@router.put("/{case_id}/scripts")
async def bind_scripts(
    case_id: str,
    req: BindScriptRequest,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    绑定脚本到用例资产（能力5/6/7 扩展）。

    将生成的前置/后置/SQL 脚本绑定到 TestCaseAsset 的 pre_script/post_script/sql_script 字段。
    """
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if req.pre_script is not None:
        item.pre_script = req.pre_script
    if req.post_script is not None:
        item.post_script = req.post_script
    if req.sql_script is not None:
        item.sql_script = req.sql_script

    if item.review_state in {"pending", "approved", "changes_requested"}:
        item.review_state = "draft"
        item.status = CaseAssetStatus.DRAFT
        _record_review(db, item, current_user, "edit", "脚本变更，重新进入草稿")
    item.updated_at = datetime.utcnow()
    await db.flush()

    return {
        "code": 0,
        "data": {
            "id": item.id,
            "has_pre_script": bool(item.pre_script),
            "has_post_script": bool(item.post_script),
            "has_sql_script": bool(item.sql_script),
        },
        "message": "ok",
    }
