"""
需求文档 API（能力10：需求文档解析）

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/requirements" 注册。

提供：
- POST /upload                  上传并解析需求文档（docx/pdf/txt）
- GET  /                        按项目列出需求文档
- GET  /{doc_id}                需求文档详情（含解析出的需求条目）
- DELETE /{doc_id}              删除需求文档
- POST /{doc_id}/generate-cases 基于需求一键生成测试用例（可选落库到指定 test_run）

⚠ 历史 Bug：5 个端点原本误用 ``async with get_db_session() as db:``，
``get_db_session`` 是 FastAPI Depends 注入函数（AsyncGenerator）不是
async-context-manager，会抛 ``TypeError: 'async_generator' object does
not support the asynchronous context manager protocol``。全部改为：
``db: AsyncSession = Depends(get_db_session)``。
"""

import hashlib
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AuditLog,
    CaseAssetStatus,
    CaseSource,
    DocFormat,
    DocStatus,
    Project,
    RequirementDoc,
    TestCaseAsset,
    User,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.doc_parser.docx_parser import extract_text_docx
from app.modules.doc_parser.pdf_parser import extract_text_pdf
from app.modules.doc_parser.requirement_parser import parse_requirements
from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.utils.database import get_db_session
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

REQ_DIR = os.path.join("/app", "data", "uploads", "requirements")
os.makedirs(REQ_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_EXT = {".docx", ".pdf", ".txt", ".md", ".markdown"}
EXT_TO_FORMAT = {
    ".docx": DocFormat.DOCX,
    ".pdf": DocFormat.PDF,
    ".txt": DocFormat.TXT,
    # Markdown 是纯文本超集，等同 .txt（下游解析统一按 UTF-8 读）
    ".md": DocFormat.TXT,
    ".markdown": DocFormat.TXT,
}


# ==================== 请求模型 ====================


class GenerateCasesRequest(BaseModel):
    use_ai: bool = True
    test_run_id: str | None = None  # 兼容旧客户端；禁止向运行中的任务追加未评审实例


# ==================== 内部工具 ====================


def _audit(db, user: User, action: str, rid: str, details: dict | None = None):
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            resource_type="requirement_doc",
            resource_id=rid,
            details=details,
        )
    )


def _detect_format(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return None, ext
    return EXT_TO_FORMAT[ext], ext


# ==================== 接口 ====================


@router.post("")
async def upload_requirement(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    use_ai: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """上传需求文档并解析（支持 .docx / .pdf / .txt / .md）。"""
    # 校验项目
    proj = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "项目不存在")

    fmt, ext = _detect_format(file.filename or "")
    if fmt is None:
        raise HTTPException(400, f"不支持的格式: {ext}（仅支持 .docx/.pdf/.txt/.md）")

    # 落盘
    stored_name = f"{uuid.uuid4()}{ext}"
    storage_path = os.path.join(REQ_DIR, stored_name)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "文件超过 20MB 限制")
    with open(storage_path, "wb") as f:
        f.write(content)
    sha = hashlib.sha256(content).hexdigest()

    # 抽取文本
    try:
        if fmt == DocFormat.DOCX:
            raw_text = extract_text_docx(storage_path)
        elif fmt == DocFormat.PDF:
            raw_text = extract_text_pdf(storage_path)
        else:
            raw_text = content.decode("utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001
        raw_text = ""
        logger.warning(f"Extract text failed for {file.filename}: {e}")

    # 解析需求
    try:
        items, engine = await parse_requirements(raw_text or "", use_ai=use_ai)
    except ModelNotConfiguredError:
        os.remove(storage_path)
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Requirement parse failed: {e}")
        os.remove(storage_path)
        raise HTTPException(502, str(e)) from e

    req_doc = RequirementDoc(
        project_id=uuid.UUID(project_id),
        uploader_id=current_user.id,
        filename=file.filename or stored_name,
        format=fmt,
        storage_key=storage_path,
        raw_text=raw_text,
        status=DocStatus.PARSED if items else DocStatus.FAILED,
        parse_engine=engine,
        requirements_json={
            "title": file.filename or "",
            "total": len(items),
            "items": [i.model_dump() for i in items],
        },
        file_size=len(content),
        sha256=sha,
    )
    db.add(req_doc)
    await db.commit()
    await db.refresh(req_doc)
    _audit(db, current_user, "upload_requirement", str(req_doc.id))
    await db.commit()

    return {
        "code": 0,
        "data": {
            "id": str(req_doc.id),
            "filename": req_doc.filename,
            "status": req_doc.status.value,
            "parse_engine": engine,
            "total": len(items),
            "requirements": [i.model_dump() for i in items],
        },
        "message": "解析完成" if items else "未解析到需求（已降级）",
    }


@router.get("")
async def list_requirements(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """按项目列出需求文档。"""
    rows = (
        await db.execute(
            select(RequirementDoc)
            .where(RequirementDoc.project_id == project_id)
            .order_by(RequirementDoc.created_at.desc())
        )
    ).scalars().all()
    return {
        "code": 0,
        "data": [
            {
                "id": str(r.id),
                "filename": r.filename,
                "format": r.format.value,
                "status": r.status.value,
                "parse_engine": r.parse_engine,
                "total": (r.requirements_json or {}).get("total", 0),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "message": "success",
    }


@router.get("/{doc_id}")
async def get_requirement(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """需求文档详情。"""
    r = (
        await db.execute(select(RequirementDoc).where(RequirementDoc.id == doc_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "需求文档不存在")
    return {
        "code": 0,
        "data": {
            "id": str(r.id),
            "filename": r.filename,
            "format": r.format.value,
            "status": r.status.value,
            "parse_engine": r.parse_engine,
            "requirements": r.requirements_json or {},
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        },
        "message": "success",
    }


@router.delete("/{doc_id}")
async def delete_requirement(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """删除需求文档。"""
    r = (
        await db.execute(select(RequirementDoc).where(RequirementDoc.id == doc_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "需求文档不存在")
    linked = (await db.execute(select(TestCaseAsset.id).where(
        TestCaseAsset.request_data["requirement_doc_id"].astext == str(r.id)
    ).limit(1))).scalar_one_or_none()
    if linked:
        raise HTTPException(409, "该需求文档已有用例资产引用，不能删除；请保留追溯记录")
    await db.delete(r)
    await db.commit()
    # 清理本地文件
    try:
        if r.storage_key and os.path.exists(r.storage_key):
            os.remove(r.storage_key)
    except Exception:  # noqa: BLE001
        pass
    return {"code": 0, "data": None, "message": "已删除"}


# ==================== 一键生成测试用例 ====================


_SYSTEM_PROMPT_GEN = """你是一名资深测试工程师。根据下面给出的需求条目，为每条需求设计测试用例。
输出严格 JSON：
{
  "cases": [
    {"title":"","description":"","priority":"P1","related_requirement":"FR-1",
     "steps":["步骤1","步骤2"],"expected":"预期结果","type":"functional"}
  ]
}
type 取值：functional(功能) / boundary(边界) / negative(异常) / performance(性能)。
只从给定需求推导，不臆造需求外的用例。"""

_PROMPT_GEN = """需求条目如下（JSON）：
{reqs}
=====
请基于上述需求生成测试用例，输出 JSON。"""


@router.post("/{doc_id}/generate-cases")
async def generate_cases(
    doc_id: str,
    req: GenerateCasesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """需求只生成可追溯的手工用例草稿；不伪造 HTTP 请求和成功断言。"""
    if req.test_run_id:
        raise HTTPException(400, "需求草稿不能直接加入运行中任务；请评审并加入测试计划")
    r = (
        await db.execute(select(RequirementDoc).where(RequirementDoc.id == doc_id))
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "需求文档不存在")
    items = (r.requirements_json or {}).get("items", [])
    if not items:
        raise HTTPException(400, "该需求文档未解析出任何需求，无法生成用例")

    existing = (await db.execute(select(TestCaseAsset).where(
        TestCaseAsset.project_id == r.project_id,
        TestCaseAsset.request_data["requirement_doc_id"].astext == str(r.id),
    ))).scalars().all()
    if existing:
        return {"code": 0, "data": {"total": len(existing), "assets_created": 0,
                "instances_created": 0, "existing_asset_ids": [str(a.id) for a in existing]},
                "message": "该文档的用例草稿已生成，请到用例库评审"}

    cases: list[dict] = []
    if req.use_ai:
        try:
            router_ai = get_model_router()
            resp = await router_ai.call(
                use_case="doc_parse",
                messages=[
                    {
                        "role": "user",
                        "content": _PROMPT_GEN.format(
                            reqs=str(
                                [
                                    {
                                        "rid": i.get("rid"),
                                        "title": i.get("title"),
                                        "acceptance_criteria": i.get("acceptance_criteria", []),
                                    }
                                    for i in items
                                ]
                            )
                        ),
                    }
                ],
                response_format_json=True,
                temperature=0.2,
            )
            import json as _json
            import re as _re

            def _extract(text: str):
                try:
                    return _json.loads(text)
                except Exception:
                    m = _re.search(r"\{.*\}", text, _re.DOTALL)
                    return _json.loads(m.group(0)) if m else {}

            parsed = _extract(resp or "")
            cases = parsed.get("cases", []) or []
            if not isinstance(cases, list):
                raise ValueError("AI 返回的 cases 不是列表")
        except ModelNotConfiguredError:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"AI 用例生成失败: {e}") from e

    if not req.use_ai:
        # 显式规则模式：只把现有验收标准转为草稿，不补造断言或接口。
        for it in items:
            cases.append(
                {
                    "title": f"验证需求：{it.get('title','')}",
                    "description": it.get("description", ""),
                    "priority": it.get("priority", "P2"),
                    "related_requirement": it.get("rid", ""),
                    "steps": it.get("test_points", []) or [],
                    "expected": "；".join(it.get("acceptance_criteria", []) or []),
                    "type": "functional",
                }
            )

    known_requirements = {str(it.get("rid")): it for it in items}
    normalized = [c for c in cases if isinstance(c, dict)
                  and str(c.get("title") or "").strip()
                  and str(c.get("related_requirement", "")) in known_requirements]
    if not normalized:
        raise HTTPException(502 if req.use_ai else 422,
                            "未生成可追溯的用例：需要有效标题和已有需求编号")

    assets = []
    for c in normalized:
        priority = str(c.get("priority", "P2")).upper()[:2]
        if priority not in {"P0", "P1", "P2", "P3"}:
            priority = "P2"
        steps = c.get("steps") if isinstance(c.get("steps"), list) else []
        design_type = c.get("type") if c.get("type") in {"functional", "boundary", "negative", "performance"} else "functional"
        asset = TestCaseAsset(
            project_id=r.project_id,
            case_type=design_type,
            design_type=design_type,
            execution_kind="manual",
            title=str(c.get("title") or "")[:500],
            description=str(c.get("description") or ""),
            request_data={
                "steps": [str(step) for step in steps[:30]],
                "related_requirement": str(c.get("related_requirement", "")),
                "requirement_doc_id": str(r.id),
            },
            expected_result={"text": str(c.get("expected") or "")},
            priority=priority,
            status=CaseAssetStatus.DRAFT,
            source=CaseSource.REQUIREMENT,
            created_by=current_user.id,
        )
        db.add(asset)
        assets.append(asset)
    await db.commit()

    return {
        "code": 0,
        "data": {
            "total": len(assets),
            "assets_created": len(assets),
            "instances_created": 0,
            "case_ids": [str(a.id) for a in assets],
        },
        "message": f"生成 {len(assets)} 条手工用例草稿，请到用例库评审",
    }
