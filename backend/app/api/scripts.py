"""
能力5/6/7（脚本生成）API 路由

提供：
- POST /generate: 生成脚本（统一入口，支持 pre_script/post_script/sql_script）
- POST /preview:  预览脚本（不落库）
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.script_gen.script_generator import ScriptGenerator
from app.schemas.script import GenerateScriptRequest, GenerateScriptResponse, BindScriptRequest
from app.utils.database import get_db_session

router = APIRouter()


@router.post("/generate")
async def generate_script(
    req: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    生成脚本（统一入口）。

    支持三种脚本类型：
    - pre_script: 前置脚本（Python），数据准备/环境初始化
    - post_script: 后置脚本（Python），数据清理/结果校验
    - sql_script: SQL 脚本，数据库状态验证
    """
    generator = ScriptGenerator()
    result = await generator.generate(
        script_type=req.script_type,
        context=req.context,
        project_id=req.project_id or 0,
        db_session=db,
    )
    return {"code": 0, "data": result, "message": "ok"}


@router.post("/preview")
async def preview_script(
    req: GenerateScriptRequest,
) -> dict[str, Any]:
    """
    预览脚本（不落库，仅返回生成结果）。
    """
    generator = ScriptGenerator()
    result = await generator.preview(
        script_type=req.script_type,
        context=req.context,
    )
    return {"code": 0, "data": result, "message": "ok"}