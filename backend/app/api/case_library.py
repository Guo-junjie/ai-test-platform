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

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.case_library import (
    GenerateRequest,
    UpdateCaseRequest,
    AdoptBatchRequest,
    CaseAssetResponse,
)
from app.schemas.script import BindScriptRequest
from app.utils.database import get_db_session

router = APIRouter()


@router.post("/generate")
async def generate_cases(
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """AI 生成测试用例并落库（DRAFT 状态）。"""
    from app.models.database import TestCaseAsset
    from app.modules.case_generator.case_generator import TestCaseGenerator

    generator = TestCaseGenerator()

    # 构建 API 列表
    apis = []
    if req.endpoint_ids:
        from app.models.database import ApiEndpoint
        for eid in req.endpoint_ids:
            result = await db.execute(
                select(ApiEndpoint).where(ApiEndpoint.id == eid)
            )
            ep = result.scalar_one_or_none()
            if ep:
                apis.append({
                    "path": ep.path,
                    "http_method": ep.http_method,
                    "params": getattr(ep, "params", []),
                    "auth_required": getattr(ep, "auth_required", False),
                })
    elif req.endpoint_id:
        from app.models.database import ApiEndpoint
        result = await db.execute(
            select(ApiEndpoint).where(ApiEndpoint.id == req.endpoint_id)
        )
        ep = result.scalar_one_or_none()
        if ep:
            apis.append({
                "path": ep.path,
                "http_method": ep.http_method,
                "params": getattr(ep, "params", []),
                "auth_required": getattr(ep, "auth_required", False),
            })

    if not apis:
        raise HTTPException(status_code=400, detail="No valid endpoints found")

    # 生成用例
    cases = await generator.generate_all(apis, {})

    # 落库
    saved = []
    for case in cases.get("api", []):
        asset = TestCaseAsset(
            id=str(uuid.uuid4()),
            project_id=req.project_id,
            case_type=case.get("case_type", "positive"),
            title=case.get("case_name", ""),
            description=case.get("description", ""),
            request_data=case.get("request", {}),
            expected_result=case.get("expected"),
            priority=case.get("priority", "P2"),
            status="DRAFT",
            source="ai_generated",
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
        },
        "message": "ok",
    }


@router.get("")
async def list_cases(
    project_id: str | None = None,
    endpoint_id: str | None = None,
    case_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
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
    if keyword:
        query = query.where(
            TestCaseAsset.title.ilike(f"%{keyword}%")
        )

    # Count
    count_result = await db.execute(query)
    all_items = count_result.scalars().all()
    total = len(all_items)

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
        item.request_data = req.request_data
    if req.expected_result is not None:
        item.expected_result = req.expected_result
    if req.priority is not None:
        item.priority = req.priority
    if req.case_type is not None:
        item.case_type = req.case_type

    item.updated_at = datetime.utcnow()
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.delete("/{case_id}")
async def delete_case(
    case_id: str,
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

    await db.delete(item)
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{case_id}/adopt")
async def adopt_case(
    case_id: str,
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

    item.status = "ADOPTED"
    item.updated_at = datetime.utcnow()
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{case_id}/deprecate")
async def deprecate_case(
    case_id: str,
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

    item.status = "DEPRECATED"
    item.updated_at = datetime.utcnow()
    await db.flush()

    return {"code": 0, "data": None, "message": "ok"}


@router.post("/adopt-batch")
async def adopt_batch(
    req: AdoptBatchRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """批量接纳用例。"""
    from app.models.database import TestCaseAsset

    result = await db.execute(
        select(TestCaseAsset).where(TestCaseAsset.id.in_(req.ids))
    )
    items = result.scalars().all()

    for item in items:
        item.status = "ADOPTED"
        item.updated_at = datetime.utcnow()

    await db.flush()

    return {"code": 0, "data": {"count": len(items)}, "message": "ok"}


# ============ 能力5/6/7 扩展：脚本绑定 ============

@router.put("/{case_id}/scripts")
async def bind_scripts(
    case_id: str,
    req: BindScriptRequest,
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