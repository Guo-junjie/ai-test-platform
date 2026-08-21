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
"""

import hashlib
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.models.database import (
    AuditLog,
    DocFormat,
    DocStatus,
    Project,
    RequirementDoc,
    TestCase,
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
ALLOWED_EXT = {".docx", ".pdf", ".txt"}
EXT_TO_FORMAT = {".docx": DocFormat.DOCX, ".pdf": DocFormat.PDF, ".txt": DocFormat.TXT}


# ==================== 请求模型 ====================


class GenerateCasesRequest(BaseModel):
    use_ai: bool = True
    test_run_id: str | None = None  # 提供则把生成的用例落库为该测试任务的 TestCase


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
):
    """上传需求文档并解析。"""
    # 校验项目
    async with get_db_session() as db:
        proj = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
        if not proj:
            raise HTTPException(404, "项目不存在")

        fmt, ext = _detect_format(file.filename or "")
        if fmt is None:
            raise HTTPException(400, f"不支持的格式: {ext}（仅支持 .docx/.pdf/.txt）")

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
            items, engine = [], "rule_degraded"
        except Exception as e:  # noqa: BLE001
            logger.error(f"Requirement parse failed: {e}")
            items, engine = [], "rule_degraded"

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
):
    """按项目列出需求文档。"""
    async with get_db_session() as db:
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
):
    """需求文档详情。"""
    async with get_db_session() as db:
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
):
    """删除需求文档。"""
    async with get_db_session() as db:
        r = (
            await db.execute(select(RequirementDoc).where(RequirementDoc.id == doc_id))
        ).scalar_one_or_none()
        if not r:
            raise HTTPException(404, "需求文档不存在")
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
):
    """基于需求文档一键生成测试用例；提供 test_run_id 则落库为 TestCase。"""
    async with get_db_session() as db:
        r = (
            await db.execute(select(RequirementDoc).where(RequirementDoc.id == doc_id))
        ).scalar_one_or_none()
        if not r:
            raise HTTPException(404, "需求文档不存在")
        items = (r.requirements_json or {}).get("items", [])
        if not items:
            raise HTTPException(400, "该需求文档未解析出任何需求，无法生成用例")

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
            except ModelNotConfiguredError:
                cases = []
            except Exception as e:  # noqa: BLE001
                logger.warning(f"AI generate cases failed: {e}")
                cases = []

        if not cases:
            # 兜底：每个需求生成一条基础功能用例
            for it in items:
                cases.append(
                    {
                        "title": f"验证需求：{it.get('title','')}",
                        "description": it.get("description", ""),
                        "priority": it.get("priority", "P2"),
                        "related_requirement": it.get("rid", ""),
                        "steps": it.get("acceptance_criteria", []) or ["执行需求对应操作"],
                        "expected": "行为符合需求描述",
                        "type": "functional",
                    }
                )

        # 落库
        created = 0
        if req.test_run_id:
            try:
                run_uuid = uuid.UUID(req.test_run_id)
            except ValueError:
                raise HTTPException(400, "test_run_id 格式错误")
            for c in cases:
                db.add(
                    TestCase(
                        test_run_id=run_uuid,
                        case_type="requirement",
                        case_name=c.get("title", "")[:500],
                        description=c.get("description", ""),
                        request_data={},
                        expected_result={
                            "expected": c.get("expected", ""),
                            "steps": c.get("steps", []),
                            "related_requirement": c.get("related_requirement", ""),
                        },
                        validation_rules={},
                        priority=str(c.get("priority", "P2")).upper()[:2] or "P2",
                    )
                )
                created += 1
            await db.commit()

        return {
            "code": 0,
            "data": {"total": len(cases), "created": created, "cases": cases},
            "message": f"生成 {len(cases)} 条用例" + (f"，已落库 {created} 条" if created else ""),
        }
