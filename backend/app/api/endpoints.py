"""接口资产的运行时证据查询。"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import ApiEndpoint, TestCase, TestCaseAsset, TestResult, User
from app.modules.auth.dependencies import get_current_user
from app.utils.database import get_db_session

router = APIRouter()


@router.get("/{endpoint_id}/last-response")
async def get_last_response(
    endpoint_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """返回该接口最近一次真实执行响应，供断言编辑器一键取样。"""
    try:
        eid = uuid.UUID(endpoint_id)
    except ValueError as exc:
        raise HTTPException(400, "接口 ID 格式错误") from exc
    if not (await db.execute(select(ApiEndpoint.id).where(ApiEndpoint.id == eid))).scalar_one_or_none():
        raise HTTPException(404, "接口不存在")
    row = (await db.execute(
        select(TestResult)
        .join(TestCase, TestCase.id == TestResult.test_case_id)
        .where(TestCase.case_asset_id.in_(
            select(TestCaseAsset.id).where(TestCaseAsset.endpoint_id == eid)
        ))
        .order_by(desc(TestResult.executed_at))
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"code": 0, "data": None, "message": "该接口暂无执行响应"}
    return {"code": 0, "data": {
        "status_code": row.status_code,
        "body": row.response_body,
        "headers": {},
        "elapsed_ms": row.response_time_ms,
        "captured_at": row.executed_at.isoformat() if row.executed_at else None,
    }, "message": "ok"}
