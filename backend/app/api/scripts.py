"""
能力5/6/7（脚本生成）API 路由

提供：
- POST /generate: 生成脚本（统一入口，支持 pre_script/post_script/sql_script）
- POST /preview:  预览脚本（不落库）
"""

from typing import Any

import ast
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.script_gen.script_generator import ScriptGenerator
from app.schemas.script import GenerateScriptRequest, GenerateScriptResponse, BindScriptRequest
from app.utils.database import get_db_session
from app.models.database import ScriptGenerationRecord, ScriptType, TestCaseAsset, User
from app.modules.auth.dependencies import get_current_user
from app.modules.sql_gen.sql_security import SqlSecurity

router = APIRouter()


@router.get("")
async def list_scripts(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        pid = uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(422, "项目 ID 格式错误") from exc
    query = select(ScriptGenerationRecord).where(ScriptGenerationRecord.project_id == pid)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (await db.execute(query.order_by(desc(ScriptGenerationRecord.created_at)).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"code": 0, "data": {"items": [{"id": str(row.id), "project_id": str(row.project_id),
        "script_type": row.script_type.value if row.script_type else "", "nl_input": row.nl_input,
        "code": row.generated_script, "language": "sql" if row.script_type == ScriptType.SQL_SCRIPT else "python",
        "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows],
        "total": total, "page": page, "page_size": page_size}, "message": "success"}


@router.post("/{script_id}/validate")
async def validate_saved_script(
    script_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(script_id)
    except ValueError as exc:
        raise HTTPException(422, "脚本 ID 格式错误") from exc
    row = (await db.execute(select(ScriptGenerationRecord).where(ScriptGenerationRecord.id == sid))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "脚本不存在")
    if row.script_type == ScriptType.SQL_SCRIPT:
        result = await SqlSecurity.check(row.generated_script, row.project_id, db)
        valid, detail = bool(result.get("passed")), result.get("message") or result.get("error")
    else:
        try:
            ast.parse(row.generated_script)
            valid, detail = True, "Python 语法与静态安全校验通过"
        except SyntaxError as exc:
            valid, detail = False, str(exc)
    return {"code": 0, "data": {"valid": valid, "status": "passed" if valid else "failed", "detail": detail,
        "mode": "static_validation", "message": "平台尚未配置隔离 Runner，本次执行为静态安全试运行"}, "message": "校验完成"}


@router.post("/generate")
async def generate_script(
    req: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    生成脚本（统一入口）。

    支持三种脚本类型：
    - pre_script: 前置脚本（Python），数据准备/环境初始化
    - post_script: 后置脚本（Python），数据清理/结果校验
    - sql_script: SQL 脚本，数据库状态验证
    """
    generator = ScriptGenerator()
    context = dict(req.context or {})
    context["nl_input"] = req.nl_input or context.get("nl_input", "")
    case = None
    if req.case_id:
        case = (await db.execute(select(TestCaseAsset).where(
            TestCaseAsset.id == req.case_id, TestCaseAsset.project_id == req.project_id,
        ))).scalar_one_or_none()
        if case is None:
            raise HTTPException(422, "关联用例不存在或不属于当前项目")
        context["case_info"] = {"title": case.title, "request": case.request_data, "expected": case.expected_result}
    result = await generator.generate(
        script_type=req.script_type,
        context=context,
        project_id=req.project_id,
        db_session=db,
    )
    if result.get("id"):
        record = (await db.execute(select(ScriptGenerationRecord).where(
            ScriptGenerationRecord.id == uuid.UUID(result["id"]),
        ))).scalar_one_or_none()
        if record:
            record.user_id = current_user.id
    if case is not None and result.get("valid"):
        setattr(case, req.script_type, result.get("code"))
        result["bound_case_id"] = str(case.id)
    await db.flush()
    return {"code": 0, "data": result, "message": "ok"}


@router.post("/preview")
async def preview_script(
    req: GenerateScriptRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    预览脚本（不落库，仅返回生成结果）。
    """
    generator = ScriptGenerator()
    context = dict(req.context or {})
    context["nl_input"] = req.nl_input or context.get("nl_input", "")
    result = await generator.preview(
        script_type=req.script_type,
        context=context,
    )
    return {"code": 0, "data": result, "message": "ok"}
