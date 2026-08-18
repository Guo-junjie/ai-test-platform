"""
能力3（AI 生成单接口用例·接纳闭环）API。

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/cases" 注册。

⚠️ 路由声明顺序（关键，否则被 UUID 路由吞掉）：
    /generate、/adopt-batch 必须声明在 /{case_id} 之前。
"""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.models.database import (
    ApiEndpoint,
    CaseAssetStatus,
    CaseSource,
    Project,
    TestCaseAsset,
    User,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.case_generator.case_generator import TestCaseGenerator
from app.schemas.case_library import (
    AdoptBatchRequest,
    GenerateRequest,
    UpdateCaseRequest,
)
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 并发调用 AI 生成用例的上限（对齐 TestCaseGenerator 内部并发）
_MAX_CONCURRENT_GENERATE = 5


# ==================== 序列化与工具 ====================


def _asset_to_dict(asset: TestCaseAsset) -> dict[str, Any]:
    """将用例资产行序列化为响应字典。"""
    return {
        "id": str(asset.id),
        "project_id": str(asset.project_id),
        "endpoint_id": str(asset.endpoint_id) if asset.endpoint_id else None,
        "case_type": asset.case_type,
        "title": asset.title,
        "description": asset.description,
        "request_data": asset.request_data or {},
        "expected_result": asset.expected_result,
        "priority": asset.priority or "P2",
        "status": asset.status.value if asset.status else None,
        "source": asset.source.value if asset.source else None,
        "created_by": str(asset.created_by) if asset.created_by else None,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }


def _light_business_analysis(ep: ApiEndpoint) -> dict[str, Any]:
    """
    轻量业务分析（MVP，不额外调 AI）。

    直接从接口资产的 summary / params / auth_required / request_body 推导：
    - business_purpose：接口摘要或路径
    - business_rules：必填参数清单
    - risk_points：鉴权要求 + 是否含请求体
    """
    params = ep.params or []
    required = [
        p.get("name") for p in params if isinstance(p, dict) and p.get("required")
    ]
    return {
        "business_purpose": ep.summary or ep.path,
        "business_rules": (
            [f"必填参数: {', '.join(required)}"] if required else ["无显式必填参数"]
        ),
        "risk_points": (
            (["需要鉴权"] if ep.auth_required else [])
            + (["包含请求体"] if ep.request_body else [])
        ),
    }


def _build_api_info(ep: ApiEndpoint) -> dict[str, Any]:
    """把 ApiEndpoint 适配为 TestCaseGenerator 所需的 api_info 结构。"""
    return {
        "path": ep.path,
        "http_method": ep.method,
        "params": ep.params or [],
        "request_body": ep.request_body or {},
        "responses": ep.responses or [],
        "auth_required": bool(ep.auth_required),
        "summary": ep.summary,
    }


# ==================== 端点（注意声明顺序） ====================


@router.post("/generate")
async def generate_cases(
    req: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """
    生成用例并落库（DRAFT）。

    支持三粒度：
    - 整项目：不传 endpoint_id / endpoint_ids
    - 多接口：传 endpoint_ids
    - 单接口：传 endpoint_id
    """
    try:
        pid = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    proj = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, "project not found")

    # 1. 解析待生成的接口资产集合
    q = select(ApiEndpoint).where(ApiEndpoint.project_id == pid)
    if req.endpoint_id:
        try:
            eid = uuid.UUID(req.endpoint_id)
        except ValueError:
            raise HTTPException(400, "invalid endpoint_id")
        q = q.where(ApiEndpoint.id == eid)
    elif req.endpoint_ids:
        valid_ids = []
        for sid in req.endpoint_ids:
            try:
                valid_ids.append(uuid.UUID(sid))
            except ValueError:
                continue
        if not valid_ids:
            raise HTTPException(400, "no valid endpoint_ids")
        q = q.where(ApiEndpoint.id.in_(valid_ids))

    endpoints = (await db.execute(q.order_by(ApiEndpoint.path))).scalars().all()
    if not endpoints:
        raise HTTPException(404, "no endpoints found for the given scope")

    # 2. 逐接口并发生成用例（AI 失败自动走 fallback，不会 500）
    generator = TestCaseGenerator()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_GENERATE)

    async def _generate_one(ep: ApiEndpoint):
        api_info = _build_api_info(ep)
        business_analysis = _light_business_analysis(ep)
        async with semaphore:
            try:
                cases = await generator.generate_api_cases(api_info, business_analysis)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Case generation failed for {ep.method} {ep.path}: {e}")
                cases = []
            return ep, cases

    pairs = await asyncio.gather(*[_generate_one(ep) for ep in endpoints])

    # 3. 批量落库
    inserted = 0
    case_ids: list[str] = []
    for ep, cases in pairs:
        for case in cases:
            asset = TestCaseAsset(
                id=uuid.uuid4(),
                project_id=pid,
                endpoint_id=ep.id,
                case_type=case.get("case_type", "positive"),
                title=case.get("case_name", f"{case.get('case_type', 'positive')}_case"),
                description=case.get("description"),
                request_data=case.get("request", {}),
                expected_result=case.get("expected"),
                priority=case.get("priority", "P2"),
                status=CaseAssetStatus.DRAFT,
                source=CaseSource.AI_GENERATED,
                created_by=current_user.id,
            )
            db.add(asset)
            case_ids.append(str(asset.id))
            inserted += 1

    await db.flush()

    return {
        "code": 0,
        "data": {
            "generated": inserted,
            "inserted": inserted,
            "project_id": str(pid),
            "endpoint_count": len(endpoints),
            "case_ids": case_ids,
        },
        "message": "generated",
    }


@router.post("/adopt-batch")
async def adopt_batch(
    req: AdoptBatchRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """批量接纳用例资产（status -> ADOPTED）。"""
    if not req.ids:
        return {"code": 0, "data": {"updated": 0}, "message": "no ids provided"}

    valid_ids = []
    for sid in req.ids:
        try:
            valid_ids.append(uuid.UUID(sid))
        except ValueError:
            continue

    if not valid_ids:
        raise HTTPException(400, "no valid ids")

    rows = (
        await db.execute(select(TestCaseAsset).where(TestCaseAsset.id.in_(valid_ids)))
    ).scalars().all()

    updated = 0
    for asset in rows:
        asset.status = CaseAssetStatus.ADOPTED
        updated += 1

    await db.flush()

    return {
        "code": 0,
        "data": {"updated": updated},
        "message": "adopted",
    }


@router.get("/")
async def list_cases(
    project_id: str,
    endpoint_id: str | None = None,
    case_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """用例资产列表，project_id 必填，可选 endpoint_id / case_type / status / keyword。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    q = select(TestCaseAsset).where(TestCaseAsset.project_id == pid)
    if endpoint_id:
        try:
            q = q.where(TestCaseAsset.endpoint_id == uuid.UUID(endpoint_id))
        except ValueError:
            pass
    if case_type:
        q = q.where(TestCaseAsset.case_type == case_type)
    if status:
        try:
            q = q.where(TestCaseAsset.status == CaseAssetStatus(status))
        except ValueError:
            pass
    if keyword:
        like = f"%{keyword}%"
        q = q.where(
            (TestCaseAsset.title.ilike(like)) | (TestCaseAsset.description.ilike(like))
        )

    all_rows = (await db.execute(q.order_by(TestCaseAsset.created_at.desc()))).scalars().all()
    total = len(all_rows)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    items = all_rows[start : start + page_size]

    return {
        "code": 0,
        "data": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_asset_to_dict(a) for a in items],
        },
        "message": "success",
    }


@router.get("/{case_id}")
async def get_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """用例资产详情（全字段）。"""
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, "invalid case_id")
    asset = (
        await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == cid))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(404, "case asset not found")
    return {
        "code": 0,
        "data": _asset_to_dict(asset),
        "message": "success",
    }


@router.put("/{case_id}")
async def update_case(
    case_id: str,
    req: UpdateCaseRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """编辑用例资产（标题/描述/请求/预期/优先级/类型）。status 不由此接口变更。"""
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, "invalid case_id")
    asset = (
        await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == cid))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(404, "case asset not found")

    if req.title is not None:
        asset.title = req.title
    if req.description is not None:
        asset.description = req.description
    if req.request_data is not None:
        asset.request_data = req.request_data
    if req.expected_result is not None:
        asset.expected_result = req.expected_result
    if req.priority is not None:
        asset.priority = req.priority
    if req.case_type is not None:
        asset.case_type = req.case_type

    await db.flush()
    await db.refresh(asset)

    return {
        "code": 0,
        "data": _asset_to_dict(asset),
        "message": "updated",
    }


@router.delete("/{case_id}")
async def delete_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """删除用例资产（物理删除，资产未绑定执行实例）。"""
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, "invalid case_id")
    asset = (
        await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == cid))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(404, "case asset not found")

    await db.delete(asset)
    await db.flush()

    return {
        "code": 0,
        "data": {"id": str(cid)},
        "message": "deleted",
    }


@router.post("/{case_id}/adopt")
async def adopt_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """接纳用例资产（status -> ADOPTED）。"""
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, "invalid case_id")
    asset = (
        await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == cid))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(404, "case asset not found")

    asset.status = CaseAssetStatus.ADOPTED
    await db.flush()
    await db.refresh(asset)

    return {
        "code": 0,
        "data": _asset_to_dict(asset),
        "message": "adopted",
    }


@router.post("/{case_id}/deprecate")
async def deprecate_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """废弃用例资产（status -> DEPRECATED）。"""
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(400, "invalid case_id")
    asset = (
        await db.execute(select(TestCaseAsset).where(TestCaseAsset.id == cid))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(404, "case asset not found")

    asset.status = CaseAssetStatus.DEPRECATED
    await db.flush()
    await db.refresh(asset)

    return {
        "code": 0,
        "data": _asset_to_dict(asset),
        "message": "deprecated",
    }
