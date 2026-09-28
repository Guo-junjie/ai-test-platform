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
import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.case_library import (
    GenerateRequest,
    UpdateCaseRequest,
    AdoptBatchRequest,
    BatchUpdateCaseRequest,
    CaseAssetResponse,
    CaseImportCommitRequest,
)
from app.schemas.script import BindScriptRequest
from app.models.database import (
    ApiEndpoint,
    CaseAssetStatus,
    CaseReviewEvent,
    Defect,
    InterfaceDoc,
    RequirementDoc,
    TestCase,
    TestCaseAsset,
    TestCaseAssetVersion,
    TestPlan,
    TestPlanCase,
    TestPlanRevision,
    TestPlanRevisionCase,
    TestResult,
    TestRun,
    User,
    UserRole,
)
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.runs.case_readiness import api_case_errors
from app.utils.database import get_db_session

router = APIRouter()
case_editor = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER, UserRole.TESTER)
case_reviewer = require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)


class ReviewDecisionRequest(BaseModel):
    decision: str  # approve / changes_requested
    comment: str = Field(default="", max_length=2000)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _normalize_tags(tags: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in tags or []:
        tag = str(value).strip()[:40]
        if tag and tag not in result:
            result.append(tag)
    return result[:20]


def _case_snapshot(item: TestCaseAsset) -> dict[str, Any]:
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
    }


def _add_case_version(
    db: AsyncSession,
    item: TestCaseAsset,
    actor_id: uuid.UUID | None,
    change_type: str,
    *,
    snapshot: dict[str, Any] | None = None,
    version: int | None = None,
) -> None:
    db.add(TestCaseAssetVersion(
        case_asset_id=item.id,
        version=version or int(item.version or 1),
        snapshot=snapshot or _case_snapshot(item),
        change_type=change_type,
        changed_by=actor_id,
    ))


def _case_to_dict(item: TestCaseAsset) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "endpoint_id": str(item.endpoint_id) if item.endpoint_id else None,
        "case_type": item.case_type,
        "title": item.title,
        "description": item.description or "",
        "request_data": item.request_data or {},
        "expected_result": item.expected_result,
        "priority": item.priority,
        "status": _enum_value(item.status),
        "execution_kind": item.execution_kind,
        "review_state": item.review_state,
        "source": _enum_value(item.source),
        "folder": item.folder or "",
        "tags": list(item.tags or []),
        "version": int(item.version or 1),
        "generation_context": item.generation_context or {},
        "created_by": str(item.created_by) if item.created_by else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


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
            endpoint_id=(uuid.UUID(case["endpoint_id"]) if case.get("endpoint_id") else None),
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
            version=1,
            generation_context={
                "channel": "api_document",
                "endpoint_id": case.get("endpoint_id"),
                "generator": "ai_case_generator",
            },
            created_by=current_user.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(asset)
        saved.append(asset)

    await db.flush()
    for asset in saved:
        _add_case_version(db, asset, current_user.id, "generated")
    await db.flush()

    return {
        "code": 0,
        "data": {
            "cases": [
                {
                    "id": a.id,
                    "endpoint_id": a.endpoint_id,
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
        "endpoint_id": str(ep.id),
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
    review_state: str | None = None,
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
    if review_state:
        query = query.where(TestCaseAsset.review_state == review_state)
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
            "items": [_case_to_dict(item) for item in items],
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
        "data": _case_to_dict(item),
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
        select(TestCaseAsset).where(TestCaseAsset.id == case_id).with_for_update()
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found")

    current_version = int(item.version or 1)
    prior_snapshot = _case_snapshot(item)
    has_current_version = (await db.execute(
        select(func.count()).select_from(TestCaseAssetVersion).where(
            TestCaseAssetVersion.case_asset_id == item.id,
            TestCaseAssetVersion.version == current_version,
        )
    )).scalar_one() > 0
    if not has_current_version:
        _add_case_version(
            db, item, item.created_by, "baseline",
            snapshot=prior_snapshot, version=current_version,
        )

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
    if req.folder is not None:
        item.folder = req.folder.strip() or None
    if req.tags is not None:
        item.tags = _normalize_tags(req.tags)

    if item.review_state in {"pending", "approved", "changes_requested"}:
        item.review_state = "draft"
        item.status = CaseAssetStatus.DRAFT
        _record_review(db, item, current_user, "edit", "内容变更，重新进入草稿")
    item.updated_at = datetime.utcnow()
    item.version = current_version + 1
    _add_case_version(db, item, current_user.id, "edit")
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/batch-update")
async def batch_update_cases(
    req: BatchUpdateCaseRequest,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """批量归类和追加标签，不改变评审状态。"""
    try:
        ids = list(dict.fromkeys(uuid.UUID(value) for value in req.ids))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "用例 ID 格式错误") from exc
    items = (await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id.in_(ids)).with_for_update()
    )).scalars().all()
    if len(items) != len(ids):
        raise HTTPException(404, "部分用例不存在")

    existing_versions = {(row[0], row[1]) for row in (await db.execute(
        select(TestCaseAssetVersion.case_asset_id, TestCaseAssetVersion.version).where(
            TestCaseAssetVersion.case_asset_id.in_(ids)
        )
    )).all()}
    add_tags = _normalize_tags(req.add_tags)
    for item in items:
        current_version = int(item.version or 1)
        if (item.id, current_version) not in existing_versions:
            _add_case_version(db, item, item.created_by, "baseline", version=current_version)
        if req.folder is not None:
            item.folder = req.folder.strip() or None
        item.tags = _normalize_tags([*(item.tags or []), *add_tags])
        item.version = current_version + 1
        item.updated_at = datetime.utcnow()
        _add_case_version(db, item, current_user.id, "classify")
    await db.flush()
    return {"code": 0, "data": {"count": len(items)}, "message": "批量更新完成"}


@router.post("/{case_id}/copy")
async def copy_case(
    case_id: str,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """复制为新的草稿用例，保留来源链路但重新进入评审。"""
    source = (await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id)
    )).scalar_one_or_none()
    if source is None:
        raise HTTPException(404, "用例不存在")
    generation_context = dict(source.generation_context or {})
    generation_context.update({"channel": "copy", "copied_from": str(source.id), "copied_from_version": int(source.version or 1)})
    copied = TestCaseAsset(
        project_id=source.project_id,
        endpoint_id=source.endpoint_id,
        case_type=source.case_type,
        execution_kind=source.execution_kind,
        design_type=source.design_type,
        title=f"{source.title}（副本）"[:500],
        description=source.description,
        request_data=dict(source.request_data or {}),
        expected_result=dict(source.expected_result or {}),
        priority=source.priority,
        folder=source.folder,
        tags=list(source.tags or []),
        version=1,
        generation_context=generation_context,
        status=CaseAssetStatus.DRAFT,
        review_state="draft",
        source="manual",
        created_by=current_user.id,
    )
    db.add(copied)
    await db.flush()
    _add_case_version(db, copied, current_user.id, "copied")
    await db.flush()
    return {"code": 0, "data": _case_to_dict(copied), "message": "用例已复制为草稿"}


@router.get("/{case_id}/versions")
async def list_case_versions(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    item = (await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == case_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")
    rows = (await db.execute(
        select(TestCaseAssetVersion, User.username)
        .outerjoin(User, User.id == TestCaseAssetVersion.changed_by)
        .where(TestCaseAssetVersion.case_asset_id == item.id)
        .order_by(TestCaseAssetVersion.version.desc())
    )).all()
    versions = [{
        "id": str(version.id),
        "version": version.version,
        "snapshot": version.snapshot or {},
        "change_type": version.change_type,
        "changed_by": str(version.changed_by) if version.changed_by else None,
        "changed_by_name": username,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    } for version, username in rows]
    if not versions:
        versions.append({
            "id": None,
            "version": int(item.version or 1),
            "snapshot": _case_snapshot(item),
            "change_type": "baseline",
            "changed_by": str(item.created_by) if item.created_by else None,
            "changed_by_name": None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })
    return {"code": 0, "data": {"items": versions}, "message": "ok"}


@router.get("/{case_id}/traceability")
async def get_case_traceability(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    item = (await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == case_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")

    plan_rows = (await db.execute(
        select(TestPlanCase, TestPlan)
        .join(TestPlan, TestPlan.id == TestPlanCase.plan_id)
        .where(TestPlanCase.case_asset_id == item.id)
        .order_by(TestPlan.updated_at.desc())
    )).all()
    revision_rows = (await db.execute(
        select(TestPlanRevisionCase, TestPlanRevision, TestPlan)
        .join(TestPlanRevision, TestPlanRevision.id == TestPlanRevisionCase.revision_id)
        .join(TestPlan, TestPlan.id == TestPlanRevision.plan_id)
        .where(TestPlanRevisionCase.case_asset_id == item.id)
        .order_by(TestPlanRevision.published_at.desc())
        .limit(50)
    )).all()
    run_rows = (await db.execute(
        select(TestCase, TestResult, TestRun)
        .join(TestRun, TestRun.id == TestCase.test_run_id)
        .outerjoin(TestResult, TestResult.test_case_id == TestCase.id)
        .where(TestCase.case_asset_id == item.id)
        .order_by(TestCase.created_at.desc())
        .limit(10)
    )).all()
    defect_rows = (await db.execute(
        select(Defect, TestCase)
        .join(TestCase, TestCase.id == Defect.test_case_id)
        .where(TestCase.case_asset_id == item.id)
        .order_by(Defect.created_at.desc())
        .limit(20)
    )).all()

    source_trace: dict[str, Any] = {
        "source": _enum_value(item.source),
        "generation_context": item.generation_context or {},
        "created_by": str(item.created_by) if item.created_by else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _json_cell(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _normalize_import_row(raw: dict[str, Any], row_no: int) -> dict[str, Any]:
    title = str(raw.get("title") or raw.get("用例名称") or raw.get("名称") or "").strip()
    kind = str(raw.get("execution_kind") or raw.get("执行类型") or "api").strip().lower()
    method = str(raw.get("method") or raw.get("请求方法") or "GET").upper()
    url = str(raw.get("url") or raw.get("请求地址") or "").strip()
    request_data = _json_cell(raw.get("request_data") or raw.get("请求数据"), {})
    if not request_data:
        request_data = {
            "method": method, "url": url,
            "params": _json_cell(raw.get("params") or raw.get("查询参数"), {}),
            "headers": _json_cell(raw.get("headers") or raw.get("请求头"), {}),
            "body": _json_cell(raw.get("body") or raw.get("请求体"), None),
        }
    expected = _json_cell(raw.get("expected_result") or raw.get("预期结果"), {})
    if not expected and raw.get("status_code"):
        expected = {"status_code": int(raw["status_code"]), "assertions": []}
    tags_raw = raw.get("tags") or raw.get("标签") or []
    tags = tags_raw if isinstance(tags_raw, list) else [v.strip() for v in str(tags_raw).split(",") if v.strip()]
    errors: list[str] = []
    if not title:
        errors.append("用例名称不能为空")
    if kind not in {"api", "manual"}:
        errors.append("执行类型只支持 api 或 manual")
    if kind == "api" and not url:
        errors.append("API 用例必须填写请求地址")
    return {
        "row_no": row_no,
        "valid": not errors,
        "errors": errors,
        "data": {
            "title": title, "description": str(raw.get("description") or raw.get("描述") or ""),
            "execution_kind": kind, "case_type": str(raw.get("case_type") or raw.get("设计类型") or "positive"),
            "priority": str(raw.get("priority") or raw.get("优先级") or "P2").upper(),
            "folder": str(raw.get("folder") or raw.get("目录") or ""), "tags": tags,
            "request_data": request_data, "expected_result": expected,
        },
    }


@router.post("/import/preview")
async def preview_case_import(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(case_editor),
) -> dict[str, Any]:
    """解析 CSV/JSON/XLSX，并返回逐行错误；预检不写入数据库。"""
    content = await file.read()
    suffix = (file.filename or "").lower().rsplit(".", 1)[-1]
    try:
        if suffix == "csv":
            text = content.decode("utf-8-sig")
            raw_rows = list(csv.DictReader(io.StringIO(text)))
        elif suffix == "json":
            parsed = json.loads(content.decode("utf-8-sig"))
            raw_rows = parsed if isinstance(parsed, list) else parsed.get("rows", [])
        elif suffix in {"xlsx", "xlsm"}:
            from openpyxl import load_workbook
            sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
            values = list(sheet.iter_rows(values_only=True))
            headers = [str(v or "").strip() for v in (values[0] if values else [])]
            raw_rows = [dict(zip(headers, row)) for row in values[1:]]
        else:
            raise HTTPException(415, "仅支持 CSV、JSON、XLSX 文件")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"文件解析失败：{exc}") from exc
    if len(raw_rows) > 2000:
        raise HTTPException(422, "单次最多导入 2000 条用例")
    rows = [_normalize_import_row(row, index + 2) for index, row in enumerate(raw_rows)]
    return {"code": 0, "data": {
        "project_id": project_id, "filename": file.filename, "rows": rows,
        "success_count": sum(1 for row in rows if row["valid"]),
        "failed_count": sum(1 for row in rows if not row["valid"]),
    }, "message": "预检完成"}


@router.post("/import/commit")
async def commit_case_import(
    req: CaseImportCommitRequest,
    current_user: User = Depends(case_editor),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """提交已通过预检的标准行，原子写入用例资产与首个版本。"""
    try:
        project_id = uuid.UUID(req.project_id)
    except ValueError as exc:
        raise HTTPException(400, "项目 ID 格式错误") from exc
    from app.models.database import Project
    if not (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none():
        raise HTTPException(404, "项目不存在")
    assets: list[TestCaseAsset] = []
    for row in req.rows:
        data = row.model_dump()
        asset = TestCaseAsset(
            project_id=project_id, title=data["title"], description=data["description"],
            execution_kind=data["execution_kind"], case_type=data["case_type"], design_type=data["case_type"],
            priority=data["priority"], folder=data["folder"] or None,
            tags=_normalize_tags(data["tags"]), request_data=data["request_data"],
            expected_result=data["expected_result"], status=CaseAssetStatus.DRAFT,
            review_state="draft", source="manual", version=1,
            generation_context={"channel": "file_import"}, created_by=current_user.id,
        )
        db.add(asset)
        assets.append(asset)
    await db.flush()
    for asset in assets:
        _add_case_version(db, asset, current_user.id, "imported")
    await db.flush()
    return {"code": 0, "data": {"imported": len(assets), "asset_ids": [str(a.id) for a in assets]}, "message": "导入完成"}


@router.get("/import/template")
async def download_case_import_template(
    current_user: User = Depends(get_current_user),
):
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "用例导入"
    sheet.append(["用例名称", "描述", "执行类型", "设计类型", "优先级", "目录", "标签", "请求方法", "请求地址", "查询参数", "请求头", "请求体", "预期结果"])
    sheet.append(["查询商品列表", "正常查询", "api", "positive", "P1", "商品", "冒烟,回归", "GET", "/api/products", "{}", "{}", "", '{"status_code":200,"assertions":[]}'])
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="case-import-template.xlsx"'}
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)
    if item.created_by:
        creator = (await db.execute(select(User.username).where(User.id == item.created_by))).scalar_one_or_none()
        source_trace["created_by_name"] = creator
    if item.endpoint_id:
        endpoint_row = (await db.execute(
            select(ApiEndpoint, InterfaceDoc)
            .outerjoin(InterfaceDoc, InterfaceDoc.id == ApiEndpoint.doc_id)
            .where(ApiEndpoint.id == item.endpoint_id)
        )).first()
        if endpoint_row:
            endpoint, document = endpoint_row
            source_trace["endpoint"] = {
                "id": str(endpoint.id), "method": endpoint.method, "path": endpoint.path,
                "version": endpoint.version, "document_id": str(document.id) if document else None,
                "document_name": document.filename if document else None,
            }
    requirement_doc_id = (item.request_data or {}).get("requirement_doc_id")
    if requirement_doc_id:
        requirement = (await db.execute(
            select(RequirementDoc).where(RequirementDoc.id == requirement_doc_id)
        )).scalar_one_or_none()
        if requirement:
            source_trace["requirement"] = {
                "id": str(requirement.id), "filename": requirement.filename,
                "parse_engine": requirement.parse_engine,
            }

    return {
        "code": 0,
        "data": {
            "source": source_trace,
            "plans": [{
                "id": str(plan.id), "name": plan.name, "status": plan.status,
                "enabled": bool(link.enabled), "added_at": link.added_at.isoformat() if link.added_at else None,
            } for link, plan in plan_rows],
            "plan_revisions": [{
                "plan_id": str(plan.id), "plan_name": plan.name,
                "revision": revision.revision, "revision_status": revision.status,
                "enabled": bool(link.enabled),
                "published_at": revision.published_at.isoformat() if revision.published_at else None,
            } for link, revision, plan in revision_rows],
            "recent_runs": [{
                "run_id": str(run.id), "run_status": _enum_value(run.status),
                "passed": result.is_passed if result else None,
                "status_code": result.status_code if result else None,
                "response_time_ms": result.response_time_ms if result else None,
                "executed_at": result.executed_at.isoformat() if result and result.executed_at else None,
            } for _case, result, run in run_rows],
            "defects": [{
                "id": str(defect.id), "title": defect.title,
                "severity": _enum_value(defect.severity),
                "status": defect.status or ("closed" if defect.is_resolved else "open"),
                "created_at": defect.created_at.isoformat() if defect.created_at else None,
            } for defect, _case in defect_rows],
        },
        "message": "ok",
    }


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


@router.post("/{case_id}/restore")
async def restore_case(
    case_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """将归档用例恢复为草稿，恢复后必须重新提交评审。"""
    item = (await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id == case_id).with_for_update()
    )).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "用例不存在")
    if item.status != CaseAssetStatus.DEPRECATED:
        raise HTTPException(409, "只有已归档用例可以恢复")
    item.status = CaseAssetStatus.DRAFT
    item.review_state = "draft"
    item.updated_at = datetime.utcnow()
    _record_review(db, item, current_user, "restore", "从归档恢复为草稿")
    await db.flush()
    return {"code": 0, "data": {"review_state": "draft"}, "message": "已恢复为草稿"}


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
