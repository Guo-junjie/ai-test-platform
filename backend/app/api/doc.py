"""
接口文档资产 API（能力1：AI 解析接口文档导入 / 能力2：AI 评审接口文档）

统一返回 {"code": 0, "data": ..., "message": "..."}。
router 不带 prefix，由 main.py 以 prefix="/api/docs" 注册。

⚠️ 路由声明顺序：/endpoints、/reviews、/reviews/{id} 必须声明在 /{doc_id} 之前，
否则会被当成 doc_id 吞掉并抛 UUID 解析错误。
"""

import hashlib
import os
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.models.database import (
    ApiEndpoint,
    AuditLog,
    DocFormat,
    DocReview,
    DocStatus,
    EndpointSource,
    InterfaceDoc,
    Project,
    ReviewEngine,
    User,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.doc_parser import parse_document, ApiSpec
from app.modules.doc_review import review as review_service
from app.utils.database import get_db_session
from app.utils.logger import get_logger
from app.utils.storage import upload_file

logger = get_logger(__name__)

router = APIRouter()

# 本地卷文档目录（已挂载 ./data:/app/data）
DOCS_DIR = os.path.join("/app", "data", "uploads", "docs")
os.makedirs(DOCS_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
CHUNK_SIZE = 1024 * 1024
ALLOWED_EXT = {".json", ".yaml", ".yml", ".har", ".docx", ".pdf", ".txt"}


# ==================== 请求模型 ====================


class ParseRequest(BaseModel):
    use_ai: bool = True
    max_endpoints: int = 200


class ImportRequest(BaseModel):
    endpoint_keys: list[str] = []  # ["GET /api/v1/users", ...]；空 = 导入全部
    import_all: bool = False
    overwrite: bool = True


class ReviewRequest(BaseModel):
    doc_id: str | None = None
    endpoint_id: str | None = None
    endpoint_ids: list[str] = []  # 指定多个接口评审（空 = 全量/单接口）
    project_id: str
    use_ai: bool = True


# ==================== 内部工具 ====================


def _audit(db, user: User, action: str, rtype: str, rid: str, details: dict | None = None):
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            resource_type=rtype,
            resource_id=rid,
            details=details,
        )
    )


def _normalize_path(path: str) -> str:
    """路径归一化：以 / 开头、去尾部 /、:id / <id> 统一转 {id}。"""
    if not path:
        return "/"
    p = path.strip()
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/")
    if not p:
        p = "/"
    p = re.sub(r"(:|<)\w+(>)?", "{id}", p)
    return p


def detect_doc_type(path: str, ext: str) -> str:
    """根据扩展名 + 内容探测文档格式。"""
    if ext in (".har",):
        return "har"
    if ext in (".docx",):
        return "docx"
    if ext in (".pdf",):
        return "pdf"
    if ext in (".txt",):
        return "txt"
    if ext in (".yaml", ".yml"):
        return "openapi"
    if ext == ".json":
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(4096)
        except Exception:
            return "openapi"
        low = head.lower()
        if '"log"' in low and '"entries"' in low:
            return "har"
        if "swagger" in low or "openapi" in low:
            return "openapi"
        return "openapi"
    return "txt"


def _spec_endpoints(doc: InterfaceDoc) -> list[dict]:
    spec = doc.api_spec_json or {}
    if isinstance(spec, dict):
        return spec.get("endpoints", []) or []
    return []


async def _upsert_endpoint(
    db, project_id: uuid.UUID, doc_id: uuid.UUID, e: dict, overwrite: bool
) -> tuple[ApiEndpoint, str]:
    """api_endpoints 幂等 upsert。返回 (endpoint, action)。"""
    method = (e.get("method") or "GET").upper()
    path = _normalize_path(e.get("path") or "/")
    existing = (
        await db.execute(
            select(ApiEndpoint).where(
                ApiEndpoint.project_id == project_id,
                ApiEndpoint.method == method,
                ApiEndpoint.path == path,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if not overwrite:
            return existing, "skipped"
        existing.summary = e.get("summary")
        existing.description = e.get("description")
        existing.params = e.get("params", []) or []
        existing.request_body = e.get("request_body") or {}
        existing.responses = e.get("responses", []) or []
        existing.auth_required = bool(e.get("auth_required", False))
        existing.version = (existing.version or 1) + 1
        existing.is_active = True
        existing.source = EndpointSource.DOC_IMPORT
        existing.doc_id = doc_id
        await db.flush()
        return existing, "updated"

    ep = ApiEndpoint(
        id=uuid.uuid4(),
        project_id=project_id,
        doc_id=doc_id,
        method=method,
        path=path,
        summary=e.get("summary"),
        description=e.get("description"),
        params=e.get("params", []) or [],
        request_body=e.get("request_body") or {},
        responses=e.get("responses", []) or [],
        auth_required=bool(e.get("auth_required", False)),
        version=1,
        is_active=True,
        source=EndpointSource.DOC_IMPORT,
    )
    db.add(ep)
    await db.flush()
    return ep, "inserted"


# ==================== 端点（注意声明顺序） ====================


@router.post("/upload")
async def upload_doc(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    doc_type: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """上传接口文档：落本地卷 + MinIO 镜像（best-effort），创建 interface_docs（status=PARSING）。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    proj = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, "project not found")

    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported format: {ext}")

    fmt = (doc_type or "").lower() or detect_doc_type("", ext)
    try:
        DocFormat(fmt)
    except ValueError:
        fmt = "txt"

    doc_id = uuid.uuid4()
    save_path = os.path.join(DOCS_DIR, f"{doc_id}{ext}")

    total = 0
    sha = hashlib.sha256()
    try:
        with open(save_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    f.close()
                    os.unlink(save_path)
                    raise HTTPException(413, "file too large (max 20MB)")
                sha.update(chunk)
                f.write(chunk)
    finally:
        await file.close()

    # 内容探测（json 需看内容）
    if ext == ".json":
        fmt = detect_doc_type(save_path, ext)
        try:
            DocFormat(fmt)
        except ValueError:
            fmt = "openapi"

    digest = sha.hexdigest()
    dup = (
        await db.execute(
            select(InterfaceDoc).where(
                InterfaceDoc.project_id == pid, InterfaceDoc.sha256 == digest
            )
        )
    ).scalar_one_or_none()

    minio_key = None
    try:
        minio_key = upload_file(save_path, f"docs/{project_id}/{doc_id}{ext}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"MinIO mirror failed for {doc_id}: {e}")

    doc = InterfaceDoc(
        id=doc_id,
        project_id=pid,
        uploader_id=current_user.id,
        filename=filename,
        format=DocFormat(fmt),
        storage_key=save_path,
        minio_key=minio_key,
        status=DocStatus.PARSING,
        file_size=total,
        sha256=digest,
    )
    db.add(doc)
    await db.flush()
    _audit(db, current_user, "doc_upload", "interface_doc", str(doc_id))

    return {
        "code": 0,
        "data": {
            "doc_id": str(doc_id),
            "filename": filename,
            "doc_type": fmt,
            "file_size": total,
            "sha256": digest,
            "status": DocStatus.PARSING.value,
            "duplicated": dup is not None,
        },
        "message": "uploaded",
    }


@router.get("/endpoints")
async def list_endpoints(
    project_id: str,
    doc_id: str | None = None,
    method: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """接口资产列表，project_id 过滤，可选 doc_id / method / keyword。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    q = select(ApiEndpoint).where(ApiEndpoint.project_id == pid)
    if doc_id:
        try:
            q = q.where(ApiEndpoint.doc_id == uuid.UUID(doc_id))
        except ValueError:
            pass
    if method:
        q = q.where(ApiEndpoint.method == method.upper())
    if keyword:
        like = f"%{keyword}%"
        q = q.where(
            (ApiEndpoint.path.ilike(like)) | (ApiEndpoint.summary.ilike(like))
        )

    all_rows = (await db.execute(q.order_by(ApiEndpoint.path))).scalars().all()
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
            "items": [
                {
                    "id": str(e.id),
                    "project_id": str(e.project_id),
                    "doc_id": str(e.doc_id) if e.doc_id else None,
                    "method": e.method,
                    "path": e.path,
                    "summary": e.summary,
                    "description": e.description,
                    "params": e.params or [],
                    "request_body": e.request_body or {},
                    "responses": e.responses or [],
                    "auth_required": bool(e.auth_required),
                    "version": e.version or 1,
                    "is_active": bool(e.is_active),
                    "source": e.source.value if e.source else None,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in items
            ],
        },
        "message": "success",
    }


@router.get("/endpoints/{endpoint_id}")
async def get_endpoint(
    endpoint_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """单个接口资产全字段。"""
    try:
        eid = uuid.UUID(endpoint_id)
    except ValueError:
        raise HTTPException(400, "invalid endpoint_id")
    e = (
        await db.execute(select(ApiEndpoint).where(ApiEndpoint.id == eid))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(404, "endpoint not found")
    return {
        "code": 0,
        "data": {
            "id": str(e.id),
            "project_id": str(e.project_id),
            "doc_id": str(e.doc_id) if e.doc_id else None,
            "method": e.method,
            "path": e.path,
            "summary": e.summary,
            "description": e.description,
            "params": e.params or [],
            "request_body": e.request_body or {},
            "responses": e.responses or [],
            "auth_required": bool(e.auth_required),
            "version": e.version or 1,
            "is_active": bool(e.is_active),
            "source": e.source.value if e.source else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None,
        },
        "message": "success",
    }


@router.post("/reviews")
async def create_review(
    req: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """评审：输入 doc_id 或 endpoint_id + project_id；裁剪 ApiSpec 喂 AI(doc_review)，后端复算总分。"""
    try:
        pid = uuid.UUID(req.project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    endpoints: list[dict] = []
    target_doc_id: uuid.UUID | None = None
    target_endpoint_id: uuid.UUID | None = None

    if req.endpoint_ids:
        # 指定多个接口（来自 api_endpoints 资产）
        valid_ids = []
        for sid in req.endpoint_ids:
            try:
                valid_ids.append(uuid.UUID(sid))
            except ValueError:
                continue
        rows = (
            await db.execute(select(ApiEndpoint).where(ApiEndpoint.id.in_(valid_ids)))
        ).scalars().all()
        for ep in rows:
            if target_doc_id is None:
                target_doc_id = ep.doc_id
            endpoints.append(
                {
                    "method": ep.method,
                    "path": ep.path,
                    "summary": ep.summary,
                    "description": ep.description,
                    "params": ep.params or [],
                    "request_body": ep.request_body or {},
                    "responses": ep.responses or [],
                    "auth_required": bool(ep.auth_required),
                    "auth_type": None,
                }
            )
        if not endpoints:
            raise HTTPException(404, "endpoints not found")
    elif req.endpoint_id:
        try:
            eid = uuid.UUID(req.endpoint_id)
        except ValueError:
            raise HTTPException(400, "invalid endpoint_id")
        ep = (
            await db.execute(select(ApiEndpoint).where(ApiEndpoint.id == eid))
        ).scalar_one_or_none()
        if ep is None:
            raise HTTPException(404, "endpoint not found")
        target_endpoint_id = ep.id
        target_doc_id = ep.doc_id
        endpoints = [
            {
                "method": ep.method,
                "path": ep.path,
                "summary": ep.summary,
                "description": ep.description,
                "params": ep.params or [],
                "request_body": ep.request_body or {},
                "responses": ep.responses or [],
                "auth_required": bool(ep.auth_required),
                "auth_type": ep.auth_type if hasattr(ep, "auth_type") else None,
            }
        ]
    elif req.doc_id:
        try:
            did = uuid.UUID(req.doc_id)
        except ValueError:
            raise HTTPException(400, "invalid doc_id")
        doc = (
            await db.execute(select(InterfaceDoc).where(InterfaceDoc.id == did))
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(404, "doc not found")
        target_doc_id = doc.id
        endpoints = _spec_endpoints(doc)
        if not endpoints:
            # 文档未解析出接口时，回退到已导入的 api_endpoints
            rows = (
                await db.execute(
                    select(ApiEndpoint).where(
                        ApiEndpoint.project_id == pid, ApiEndpoint.doc_id == did
                    )
                )
            ).scalars().all()
            endpoints = [
                {
                    "method": r.method,
                    "path": r.path,
                    "summary": r.summary,
                    "description": r.description,
                    "params": r.params or [],
                    "request_body": r.request_body or {},
                    "responses": r.responses or [],
                    "auth_required": bool(r.auth_required),
                    "auth_type": None,
                }
                for r in rows
            ]
    else:
        raise HTTPException(400, "doc_id or endpoint_id is required")

    result = await review_service(endpoints, use_ai=req.use_ai)

    review = DocReview(
        id=uuid.uuid4(),
        doc_id=target_doc_id,  # 接口级评审时 doc_id 可能为 None（来源 doc 已删除），允许其存 None
        endpoint_id=target_endpoint_id,
        project_id=pid,
        reviewer_id=current_user.id,
        score=int(round(result["overall_score"])),
        scores_json=result["dimension_scores"],
        dimensions=result["dimensions"],
        suggestions=result["issues"],
        engine=ReviewEngine(result["engine"]),
    )
    db.add(review)
    await db.flush()
    _audit(db, current_user, "doc_review", "interface_doc", str(review.id))

    return {
        "code": 0,
        "data": {
            "review_id": str(review.id),
            "status": "completed",
            "review_engine": result["engine"],
            "overall_score": result["overall_score"],
            "score": review.score,
            "dimension_scores": result["dimension_scores"],
            "dimensions": result["dimensions"],
            "issues": result["issues"],
            "summary": result["summary"],
        },
        "message": "reviewed",
    }


@router.get("/reviews")
async def list_reviews(
    doc_id: str | None = None,
    project_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """评审列表，按 doc_id 或 project_id 过滤。"""
    q = select(DocReview)
    if doc_id:
        try:
            q = q.where(DocReview.doc_id == uuid.UUID(doc_id))
        except ValueError:
            pass
    elif project_id:
        try:
            q = q.where(DocReview.project_id == uuid.UUID(project_id))
        except ValueError:
            pass

    all_rows = (await db.execute(q.order_by(DocReview.created_at.desc()))).scalars().all()
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
            "items": [
                {
                    "review_id": str(r.id),
                    "doc_id": str(r.doc_id) if r.doc_id else None,
                    "endpoint_id": str(r.endpoint_id) if r.endpoint_id else None,
                    "overall_score": r.score,
                    "dimension_scores": r.scores_json or {},
                    "issue_count": len(r.suggestions or []),
                    "review_engine": r.engine.value if r.engine else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in items
            ],
        },
        "message": "success",
    }


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """评审详情全文（含 issues）。"""
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(400, "invalid review_id")
    r = (
        await db.execute(select(DocReview).where(DocReview.id == rid))
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "review not found")
    return {
        "code": 0,
        "data": {
            "review_id": str(r.id),
            "doc_id": str(r.doc_id) if r.doc_id else None,
            "endpoint_id": str(r.endpoint_id) if r.endpoint_id else None,
            "project_id": str(r.project_id),
            "reviewer_id": str(r.reviewer_id) if r.reviewer_id else None,
            "overall_score": r.score,
            "dimension_scores": r.scores_json or {},
            "dimensions": r.dimensions or [],
            "issues": r.suggestions or [],
            "review_engine": r.engine.value if r.engine else None,
            "summary": "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        },
        "message": "success",
    }


@router.post("/{doc_id}/parse")
async def parse_doc(
    doc_id: str,
    req: ParseRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """触发解析：openapi/har 规则直出；docx/pdf 抽文本后 AI 结构化，无 AI 则 rule_degraded。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id")
    doc = (
        await db.execute(select(InterfaceDoc).where(InterfaceDoc.id == did))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "doc not found")

    doc.status = DocStatus.PARSING
    await db.flush()

    result = await parse_document(
        doc.format.value,
        doc.storage_key,
        use_ai=req.use_ai,
        max_endpoints=req.max_endpoints,
    )

    api_spec: Optional[ApiSpec] = result.get("api_spec")
    spec_dict = api_spec.model_dump(by_alias=True, exclude_none=True) if api_spec else {}
    doc.api_spec_json = spec_dict
    doc.raw_text = result.get("raw_text") or doc.raw_text
    doc.parse_engine = result.get("parse_engine")
    if api_spec is not None and (spec_dict.get("endpoints") or []):
        doc.status = DocStatus.PARSED
        doc.error = None
    else:
        doc.status = DocStatus.FAILED
        doc.error = (result.get("unparsed_notes") or ["解析未产出接口"])[0]
    await db.flush()
    _audit(db, current_user, "doc_parse", "interface_doc", doc_id)

    endpoints = spec_dict.get("endpoints", []) if spec_dict else []
    return {
        "code": 0,
        "data": {
            "doc_id": doc_id,
            "status": doc.status.value,
            "doc_type": doc.format.value,
            "parse_engine": doc.parse_engine,
            "degraded": result.get("degraded", False),
            "scanned": result.get("scanned", False),
            "endpoint_count": len(endpoints),
            "endpoints": endpoints,
            "unparsed_notes": result.get("unparsed_notes", []),
            "meta": result.get("meta", {}),
        },
        "message": "parsed",
    }


@router.get("/")
async def list_docs(
    project_id: str,
    status: str | None = None,
    doc_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """文档列表，project_id 过滤。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(400, "invalid project_id")

    q = select(InterfaceDoc).where(InterfaceDoc.project_id == pid)
    if status:
        try:
            q = q.where(InterfaceDoc.status == DocStatus(status))
        except ValueError:
            pass
    if doc_type:
        try:
            q = q.where(InterfaceDoc.format == DocFormat(doc_type))
        except ValueError:
            pass
    if keyword:
        q = q.where(InterfaceDoc.filename.ilike(f"%{keyword}%"))

    all_rows = (await db.execute(q.order_by(InterfaceDoc.created_at.desc()))).scalars().all()
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
            "items": [
                {
                    "doc_id": str(d.id),
                    "filename": d.filename,
                    "doc_type": d.format.value if d.format else None,
                    "status": d.status.value if d.status else None,
                    "parse_engine": d.parse_engine,
                    "endpoint_count": len(_spec_endpoints(d)),
                    "file_size": d.file_size,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                }
                for d in items
            ],
        },
        "message": "success",
    }


@router.get("/{doc_id}")
async def get_doc(
    doc_id: str,
    include_raw_text: bool = False,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """文档详情 + api_spec（默认不含 raw_text）。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id")
    doc = (
        await db.execute(select(InterfaceDoc).where(InterfaceDoc.id == did))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "doc not found")

    spec = doc.api_spec_json or {}
    return {
        "code": 0,
        "data": {
            "doc_id": str(doc.id),
            "project_id": str(doc.project_id),
            "filename": doc.filename,
            "doc_type": doc.format.value if doc.format else None,
            "status": doc.status.value if doc.status else None,
            "parse_engine": doc.parse_engine,
            "api_spec": spec,
            "endpoint_count": len(_spec_endpoints(doc)),
            "raw_text": doc.raw_text if include_raw_text else None,
            "error": doc.error,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        },
        "message": "success",
    }


@router.delete("/{doc_id}")
async def delete_doc(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """删除文档记录 + 本地文件；已导入的 api_endpoints.doc_id 置空保留资产。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id")
    doc = (
        await db.execute(select(InterfaceDoc).where(InterfaceDoc.id == did))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "doc not found")

    # 已导入资产 doc_id 置空保留
    imported_rows = (
        await db.execute(select(ApiEndpoint).where(ApiEndpoint.doc_id == did))
    ).scalars().all()
    for ep in imported_rows:
        ep.doc_id = None
    await db.flush()

    # 删除本地文件
    try:
        if doc.storage_key and os.path.exists(doc.storage_key):
            os.unlink(doc.storage_key)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Delete local file failed: {e}")

    await db.delete(doc)
    await db.flush()
    _audit(db, current_user, "doc_delete", "interface_doc", str(did))

    return {
        "code": 0,
        "data": {"doc_id": doc_id, "endpoints_kept": len(imported_rows)},
        "message": "deleted",
    }


@router.post("/{doc_id}/import")
async def import_endpoints(
    doc_id: str,
    req: ImportRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
):
    """一键导入：遍历 api_spec.endpoints，按 (project_id, method, path) upsert 进 api_endpoints。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid doc_id")
    doc = (
        await db.execute(select(InterfaceDoc).where(InterfaceDoc.id == did))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "doc not found")

    all_eps = _spec_endpoints(doc)
    if req.endpoint_keys:
        key_set = set(req.endpoint_keys)
        selected = [
            e
            for e in all_eps
            if f"{str(e.get('method', '')).upper()} {e.get('path', '')}" in key_set
        ]
    else:
        selected = all_eps

    imported = updated = skipped = failed = 0
    endpoint_ids: list[str] = []
    for e in selected:
        try:
            ep, action = await _upsert_endpoint(db, doc.project_id, did, e, req.overwrite)
            if action == "inserted":
                imported += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1
            endpoint_ids.append(str(ep.id))
        except Exception as ex:  # noqa: BLE001
            failed += 1
            logger.warning(f"Import endpoint failed: {ex}")

    _audit(
        db,
        current_user,
        "doc_import",
        "interface_doc",
        str(did),
        {"imported": imported, "updated": updated, "skipped": skipped, "failed": failed},
    )

    return {
        "code": 0,
        "data": {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "endpoint_ids": endpoint_ids,
        },
        "message": "imported",
    }
