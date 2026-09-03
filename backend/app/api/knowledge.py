"""
知识库 RAG 管理 API（能力12）

路径前缀由 main.py 以 prefix="/api/knowledge" 注册；本文件 APIRouter() 不带 prefix；
索引状态路由使用 @router.get("")（绝不写 "/"，避免 307 重定向砍掉 POST 请求体）。

统一响应：{"code":0,"data":...,"message":"success"}，业务冲突返回 {"code":1,...} 且 HTTP 恒 200；
鉴权失败由依赖（require_admin / require_role）返回 403/401（符合权限验收标准）。
"""
import hashlib
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeFeedback,
    KnowledgeTerm,
    KBChunkType,
    User,
    UserRole,
    Defect,
    TestCase,
    ApiEndpoint,
)
from app.modules.auth.dependencies import (
    get_current_user,
    require_admin,
    require_role,
)
from app.utils.database import get_db_session
from app.modules.knowledge.retriever import (
    search_terms,
    retrieve_chunks,
    get_rebuild_state,
    set_rebuild_state,
    _source_label,
)
from app.modules.knowledge.runtime_config import (
    get_kb_rag_enabled,
    set_kb_rag_enabled,
)
from app.modules.knowledge.tasks import (
    rebuild_knowledge_base,
    process_knowledge_document,
)
from app.modules.knowledge.document_indexer import (
    MAX_FILE_SIZE,
    detect_file_type,
    remove_document_chunks,
)

router = APIRouter()

# 术语 CRUD 权限：super_admin / admin / test_manager
require_kb_term_admin = require_role(
    UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER
)

# 知识文档上传/重建索引权限：可操作的Biz角色（viewer/auditor 只读）
require_kb_doc_writer = require_role(
    UserRole.SUPER_ADMIN,
    UserRole.ADMIN,
    UserRole.TEST_MANAGER,
    UserRole.TESTER,
    UserRole.DEVELOPER,
)

_KB_TYPES = ("defect", "case", "doc", "term")

# 知识文档本地存储目录（与 interface_docs 的 /app/data/uploads/docs 同模式）
KNOWLEDGE_DOCS_DIR = os.path.join("/app", "data", "uploads", "knowledge")

# 重建状态卡死阈值（小时）：state==running 且 updated_at 超过此值视为卡死
_REBUILD_STUCK_HOURS = 1
_REBUILD_STUCK_SECONDS = _REBUILD_STUCK_HOURS * 3600


# ==================== 请求模型 ====================


class TermCreate(BaseModel):
    term: str
    technical_meaning: str
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    meta: dict = Field(default_factory=dict)


class TermUpdate(BaseModel):
    term: str | None = None
    technical_meaning: str | None = None
    aliases: list[str] | None = None
    domain: str | None = None
    meta: dict | None = None


class SearchRequest(BaseModel):
    query: str
    kb_type: str
    top_k: int = 5
    # 项目隔离：提供时只返回该项目的文档切片 + 全局切片（NULL）
    project_id: str | None = None


class RebuildRequest(BaseModel):
    kb_type: str | None = None
    force_full: bool = False  # 默认增量；True 走全量清空重插


class ConfigUpdate(BaseModel):
    """运行时配置更新（前端开关切换）。"""

    kb_rag_enabled: bool


class AskRequest(BaseModel):
    """知识问答请求。"""

    question: str
    project_id: str | None = None  # 提供时按项目过滤（文档类切片）
    top_k: int = Field(default=5, ge=1, le=10)


class FeedbackCreate(BaseModel):
    """知识问答反馈提交。"""

    question: str
    answer: str | None = None
    rating: str  # up / down
    comment: str | None = None
    retrieved: list[dict] = Field(default_factory=list)  # 当次召回明细


# ==================== 内部工具 ====================


def _term_to_dict(t: KnowledgeTerm) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "term": t.term,
        "aliases": t.aliases or [],
        "technical_meaning": t.technical_meaning,
        "domain": t.domain,
        "meta": t.meta or {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _escape_like(s: str) -> str:
    """转义 LIKE 通配符，避免搜索词中的 %/_ 干扰匹配。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _get_term_or_404(term_id: str, db: AsyncSession) -> KnowledgeTerm | None:
    try:
        tid = uuid.UUID(term_id)
    except Exception:
        return None
    result = await db.execute(select(KnowledgeTerm).where(KnowledgeTerm.id == tid))
    return result.scalar_one_or_none()


# ==================== 状态 ====================


@router.get("")
async def get_kb_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """知识库概览：开关状态 / 四分类切片计数 / 术语数 / 嵌入模型 / 重建状态。"""
    chunk_counts = {t.value: 0 for t in KBChunkType}
    try:
        res = await db.execute(
            select(KnowledgeChunk.kb_type, func.count()).group_by(
                KnowledgeChunk.kb_type
            )
        )
        for kt, cnt in res.all():
            key = kt.value if hasattr(kt, "value") else str(kt)
            chunk_counts[key] = cnt
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"KB status count failed: {exc}")
    total = sum(chunk_counts.values())

    term_count = 0
    try:
        term_count = (
            await db.execute(select(func.count()).select_from(KnowledgeTerm))
        ).scalar() or 0
    except Exception:
        term_count = 0

    embedding_model_id = None
    try:
        from app.modules.ai.model_router import get_model_router

        embedding_model_id = get_model_router().routing.embedding_model_id
    except Exception:
        embedding_model_id = None

    # 运行时开关（DB 表优先，env 兜底；前端可切换）
    try:
        kb_enabled = await get_kb_rag_enabled(db)
    except Exception:
        kb_enabled = bool(settings.KB_RAG_ENABLED)

    # 语义就绪信号：开关开 且 已配置嵌入模型；不做实时 probe（避免烧嵌入配额/延迟/崩溃）
    embedding_ready = bool(kb_enabled) and bool(embedding_model_id)
    retrieval_mode = "semantic" if embedding_ready else "keyword"

    state_info = {"state": "idle", "last_rebuild": None, "updated_at": None}
    try:
        state_info = await get_rebuild_state(db)
    except Exception:
        pass

    # 卡死判定：state==running 且 updated_at 超过 1 小时视为卡死。
    # 前端据此展示「⚠ 卡死 —强制重置」按钮 + 提示检查 celery-worker 容器。
    is_stuck = False
    if state_info.get("state") == "running":
        updated_str = state_info.get("updated_at")
        if updated_str:
            try:
                upd = datetime.fromisoformat(updated_str)
                is_stuck = (
                    datetime.utcnow() - upd
                ).total_seconds() > _REBUILD_STUCK_SECONDS
            except Exception:
                pass

    return {
        "code": 0,
        "data": {
            "enabled": kb_enabled,
            "chunk_count": total,
            "chunk_counts": chunk_counts,
            "term_count": term_count,
            "embedding_model_id": embedding_model_id,
            "embedding_ready": embedding_ready,
            "retrieval_mode": retrieval_mode,
            "state": state_info.get("state", "idle"),
            "last_rebuild": state_info.get("last_rebuild"),
            "is_stuck": is_stuck,
        },
        "message": "success",
    }


@router.post("/rebuild")
async def rebuild_knowledge(
    req: RebuildRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """触发 Celery 全量重建（仅 super_admin/admin）。返回 task_id。"""
    if req.kb_type == "document":
        return {
            "code": 1,
            "data": None,
            "message": "文档类知识不走全量重建，请在「知识文档」列表中对单个文档执行「重新索引」",
        }
    if req.kb_type is not None and req.kb_type not in _KB_TYPES:
        return {"code": 1, "data": None, "message": f"无效的 kb_type: {req.kb_type}"}

    # 空库友好提示：4 类源表全部为空时，重建结果必然是 0，立即告知用户避免无意义等待。
    # 若用户指定了具体 kb_type，则只检查该类型对应的源表（如 term 类型只需查 knowledge_terms）。
    async def _count(model) -> int:
        try:
            return (
                await db.execute(select(func.count()).select_from(model))
            ).scalar() or 0
        except Exception:
            return 0

    scope = req.kb_type
    counts: dict[str, int] = {}
    if scope is None or scope == "defect":
        counts["defect"] = await _count(Defect)
    if scope is None or scope == "case":
        counts["case"] = await _count(TestCase)
    if scope is None or scope == "doc":
        counts["doc"] = await _count(ApiEndpoint)
    if scope is None or scope == "term":
        counts["term"] = await _count(KnowledgeTerm)

    if counts and all(v == 0 for v in counts.values()):
        detail = " / ".join(
            f"{'缺陷' if k == 'defect' else '用例' if k == 'case' else '接口' if k == 'doc' else '术语'} {v} 条"
            for k, v in counts.items()
        )
        return {
            "code": 1,
            "data": {"counts": counts},
            "message": (
                f"当前数据库为空（{detail}），重建结果将全部为 0。"
                f"请先运行测试任务累积缺陷/用例，解析接口文档，或在「术语表」中维护术语。"
            ),
        }

    state = await get_rebuild_state(db)
    # 防重复提交：running 且更新时间在 1 小时内视为进行中（超时则视为卡死可重触发）。
    # 卡死路径自动把状态推回 idle，再提交新任务；同时在响应里提示用户。
    is_stuck_reset = False
    if state.get("state") == "running":
        updated = state.get("updated_at")
        recent = True
        if updated:
            try:
                upd = datetime.fromisoformat(updated)
                if (datetime.utcnow() - upd).total_seconds() > _REBUILD_STUCK_SECONDS:
                    recent = False
            except Exception:
                recent = True
        if recent:
            return {"code": 1, "data": None, "message": "重建任务进行中，请勿重复提交"}
        # 卡死：先重置再继续
        await set_rebuild_state(
            db, "idle",
            updated_at=datetime.utcnow(),
            error="自动重置：上次任务疑似卡死（>1h 无响应），请检查 celery-worker 容器",
        )
        is_stuck_reset = True

    await set_rebuild_state(
        db, "running", updated_at=datetime.utcnow(), error=None
    )
    try:
        task = rebuild_knowledge_base.delay(req.kb_type, req.force_full)
    except Exception as exc:  # noqa: BLE001
        await set_rebuild_state(db, "idle", error=f"队列不可用: {exc}")
        return {"code": 1, "data": None, "message": f"重建任务提交失败: {exc}"}

    message = "success"
    if is_stuck_reset:
        message = (
            "已自动重置上次卡死任务并提交新任务，请检查 celery-worker 容器是否正常运行"
        )
    return {"code": 0, "data": {"task_id": task.id, "stuck_reset": is_stuck_reset}, "message": message}


@router.post("/reset")
async def reset_rebuild_state(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """强制把重建状态机改回 idle（仅 super_admin/admin）。

    用于：状态卡死无法自愈、worker 已修好但 DB 状态未更新等场景。
    """
    await set_rebuild_state(
        db, "idle",
        updated_at=datetime.utcnow(),
        error="管理员手动重置",
    )
    return {"code": 0, "data": {"state": "idle"}, "message": "已强制重置"}


@router.put("/config")
async def update_kb_config(
    req: ConfigUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """运行时切换 KB_RAG_ENABLED（仅 super_admin/admin），无需重启。"""
    await set_kb_rag_enabled(db, req.kb_rag_enabled)
    return {
        "code": 0,
        "data": {"kb_rag_enabled": req.kb_rag_enabled},
        "message": "已切换，立即生效（5s 内全进程可见）",
    }


@router.get("/terms")
async def list_terms(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    q: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """术语列表（分页 + 关键词模糊搜索）。"""
    stmt = select(KnowledgeTerm)
    count_stmt = select(func.count()).select_from(KnowledgeTerm)
    if q:
        like = f"%{_escape_like(q)}%"
        condition = KnowledgeTerm.term.ilike(like, escape="\\")
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await db.execute(count_stmt)).scalar() or 0
    result = await db.execute(
        stmt.order_by(KnowledgeTerm.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = result.scalars().all()
    return {
        "code": 0,
        "data": {"list": [_term_to_dict(t) for t in items], "total": total},
        "message": "success",
    }


@router.post("/terms")
async def create_term(
    req: TermCreate,
    current_user: User = Depends(require_kb_term_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """新建术语（super_admin/admin/test_manager）。术语重名拒绝。"""
    existing = (
        await db.execute(
            select(KnowledgeTerm).where(KnowledgeTerm.term == req.term)
        )
    ).scalar_one_or_none()
    if existing:
        return {"code": 1, "data": None, "message": "术语已存在"}

    term = KnowledgeTerm(
        id=uuid.uuid4(),
        term=req.term,
        technical_meaning=req.technical_meaning,
        aliases=req.aliases or [],
        domain=req.domain,
        meta=req.meta or {},
    )
    db.add(term)
    await db.flush()
    await db.refresh(term)
    return {"code": 0, "data": _term_to_dict(term), "message": "success"}


@router.get("/terms/{term_id}")
async def get_term(
    term_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """术语详情。"""
    term = await _get_term_or_404(term_id, db)
    if term is None:
        return {"code": 1, "data": None, "message": "术语不存在"}
    return {"code": 0, "data": _term_to_dict(term), "message": "success"}


@router.put("/terms/{term_id}")
async def update_term(
    term_id: str,
    req: TermUpdate,
    current_user: User = Depends(require_kb_term_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """更新术语（字段全可选，重名拒绝）。"""
    term = await _get_term_or_404(term_id, db)
    if term is None:
        return {"code": 1, "data": None, "message": "术语不存在"}

    if req.term is not None and req.term != term.term:
        dup = (
            await db.execute(
                select(KnowledgeTerm).where(KnowledgeTerm.term == req.term)
            )
        ).scalar_one_or_none()
        if dup is not None and str(dup.id) != str(term.id):
            return {"code": 1, "data": None, "message": "术语已存在"}

    if req.term is not None:
        term.term = req.term
    if req.technical_meaning is not None:
        term.technical_meaning = req.technical_meaning
    if req.aliases is not None:
        term.aliases = req.aliases
    if req.domain is not None:
        term.domain = req.domain
    if req.meta is not None:
        term.meta = req.meta

    await db.flush()
    await db.refresh(term)
    return {"code": 0, "data": _term_to_dict(term), "message": "success"}


@router.delete("/terms/{term_id}")
async def delete_term(
    term_id: str,
    current_user: User = Depends(require_kb_term_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """删除术语。"""
    term = await _get_term_or_404(term_id, db)
    if term is None:
        return {"code": 1, "data": None, "message": "术语不存在"}
    await db.delete(term)
    await db.flush()
    return {"code": 0, "data": {"deleted": True}, "message": "success"}


@router.post("/search")
async def search_knowledge(
    req: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """检索预览（调试/前端展示）。project_id 提供时按项目过滤文档类切片。

    kb_type='all' 时遍历全部类型合并结果（此前 'all' 会因 KBChunkType 枚举
    ValueError 直接返回空，属既有 bug，顺带修复）。
    """
    if not req.query or not req.query.strip():
        return {"code": 1, "data": {"chunks": []}, "message": "query 不能为空"}

    def _chunk_dict(h) -> dict:
        return {
            "content": h.chunk.content,
            "kb_type": h.chunk.kb_type.value
            if hasattr(h.chunk.kb_type, "value")
            else str(h.chunk.kb_type),
            "score": round(h.score, 4),
            "source_ref": h.chunk.source_ref,
            "source": _source_label(h.chunk),
        }

    if req.kb_type == "all":
        chunks: list[dict] = []
        terms = await search_terms(db, req.query, top_k=req.top_k)
        for t in terms:
            chunks.append(
                {
                    "content": f"{t.term}：{t.technical_meaning}",
                    "kb_type": "term",
                    "score": 0.0,
                    "source_ref": f"term:{t.id}",
                    "source": t.term,
                }
            )
        for t in ("document", "defect", "case", "doc"):
            hits = await retrieve_chunks(
                db, req.query, t, top_k=req.top_k, project_id=req.project_id
            )
            chunks.extend(_chunk_dict(h) for h in hits)
        chunks.sort(key=lambda c: c["score"] or 0.0, reverse=True)
        return {"code": 0, "data": {"chunks": chunks[: req.top_k]}, "message": "success"}

    if req.kb_type == "term":
        terms = await search_terms(db, req.query, top_k=req.top_k)
        chunks = [
            {
                "content": f"{t.term}：{t.technical_meaning}",
                "kb_type": "term",
                "score": None,
                "source_ref": f"term:{t.id}",
                "source": t.term,
            }
            for t in terms
        ]
        return {"code": 0, "data": {"chunks": chunks}, "message": "success"}

    hits = await retrieve_chunks(
        db, req.query, req.kb_type, top_k=req.top_k, project_id=req.project_id
    )
    return {"code": 0, "data": {"chunks": [_chunk_dict(h) for h in hits]}, "message": "success"}


# ==================== 知识文档（P0：文档中心化） ====================


def _doc_to_dict(d: KnowledgeDocument) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "project_id": str(d.project_id),
        "title": d.title,
        "filename": d.filename,
        "file_type": d.file_type,
        "category": d.category,
        "description": d.description,
        "file_size": d.file_size,
        "version": d.version,
        "status": d.status,
        "chunk_count": d.chunk_count,
        "error": d.error,
        "uploader_id": str(d.uploader_id) if d.uploader_id else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


@router.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    title: str | None = Form(None),
    category: str | None = Form(None),
    description: str | None = Form(None),
    current_user: User = Depends(require_kb_doc_writer),
    db: AsyncSession = Depends(get_db_session),
):
    """上传知识文档并派发异步索引任务（解析→章节切片→嵌入→入库）。

    支持 pdf / docx / md / txt，≤20MB。状态流转 parsing→indexed/failed，
    前端通过列表轮询。文档切片强制携带 project_id（项目隔离）。
    """
    from app.models.database import Project

    # 校验项目存在（避免 FK 违反）
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        return {"code": 1, "data": None, "message": f"无效的 project_id: {project_id}"}
    project = (
        await db.execute(select(Project).where(Project.id == pid))
    ).scalar_one_or_none()
    if project is None:
        return {"code": 1, "data": None, "message": f"项目不存在: {project_id}"}

    # 校验文件类型
    file_type = detect_file_type(file.filename or "")
    if file_type is None:
        return {
            "code": 1,
            "data": None,
            "message": "不支持的文件类型，仅支持 pdf / docx / md / txt",
        }

    content = await file.read()
    if len(content) == 0:
        return {"code": 1, "data": None, "message": "文件为空"}
    if len(content) > MAX_FILE_SIZE:
        return {"code": 1, "data": None, "message": "文件超过 20MB 上限"}

    # 落盘（本地卷；MinIO 镜像 best-effort）
    os.makedirs(KNOWLEDGE_DOCS_DIR, exist_ok=True)
    doc_id = uuid.uuid4()
    ext = os.path.splitext(file.filename or "")[1].lower()
    save_path = os.path.join(KNOWLEDGE_DOCS_DIR, f"{doc_id}{ext}")
    with open(save_path, "wb") as f:
        f.write(content)

    minio_key = None
    try:
        from app.utils.storage import upload_file

        minio_key = upload_file(save_path, f"knowledge/{project_id}/{doc_id}{ext}")
    except Exception as exc:  # noqa: BLE001 - MinIO 不可用不阻塞索引
        logger.warning(f"[KB doc] MinIO mirror failed (non-fatal): {exc}")

    doc = KnowledgeDocument(
        id=doc_id,
        project_id=pid,
        uploader_id=current_user.id,
        title=(title or "").strip() or os.path.splitext(file.filename or "")[0],
        filename=file.filename or f"{doc_id}{ext}",
        file_type=file_type,
        category=(category or "").strip() or None,
        description=(description or "").strip() or None,
        storage_key=save_path,
        minio_key=minio_key,
        file_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status="parsing",
        version=1,
    )
    db.add(doc)
    await db.commit()

    # 派发异步索引任务
    try:
        process_knowledge_document.delay(str(doc_id))
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.error = f"索引任务提交失败（请检查 celery-worker）: {exc}"
        await db.commit()
        return {"code": 1, "data": _doc_to_dict(doc), "message": doc.error}

    return {
        "code": 0,
        "data": _doc_to_dict(doc),
        "message": "上传成功，正在解析索引",
    }


@router.get("/documents")
async def list_documents(
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """知识文档列表（分页 + 项目/状态/标题关键词过滤）。"""
    stmt = select(KnowledgeDocument)
    count_stmt = select(func.count()).select_from(KnowledgeDocument)
    conditions = []
    if project_id:
        try:
            conditions.append(KnowledgeDocument.project_id == uuid.UUID(project_id))
        except ValueError:
            return {"code": 1, "data": None, "message": f"无效的 project_id: {project_id}"}
    if status:
        conditions.append(KnowledgeDocument.status == status)
    if q:
        like = f"%{_escape_like(q)}%"
        conditions.append(KnowledgeDocument.title.ilike(like, escape="\\"))
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = (await db.execute(count_stmt)).scalar() or 0
    result = await db.execute(
        stmt.order_by(KnowledgeDocument.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = result.scalars().all()
    return {
        "code": 0,
        "data": {"list": [_doc_to_dict(d) for d in items], "total": total},
        "message": "success",
    }


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """知识文档详情。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        return {"code": 1, "data": None, "message": f"无效的文档 ID: {doc_id}"}
    doc = (
        await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == did))
    ).scalar_one_or_none()
    if doc is None:
        return {"code": 1, "data": None, "message": "文档不存在"}
    return {"code": 0, "data": _doc_to_dict(doc), "message": "success"}


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(require_kb_term_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """删除知识文档（文件 + MinIO 对象 + 全部切片）。仅 super_admin/admin/test_manager。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        return {"code": 1, "data": None, "message": f"无效的文档 ID: {doc_id}"}
    doc = (
        await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == did))
    ).scalar_one_or_none()
    if doc is None:
        return {"code": 1, "data": None, "message": "文档不存在"}

    # 先清切片（失败不阻塞文件删除）
    try:
        await remove_document_chunks(db, did)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[KB doc] delete chunks failed for {did}: {exc}")

    # 本地文件与 MinIO 镜像 best-effort 清理
    try:
        if doc.storage_key and os.path.exists(doc.storage_key):
            os.unlink(doc.storage_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[KB doc] delete local file failed: {exc}")

    await db.delete(doc)
    await db.commit()
    return {"code": 0, "data": {"deleted": True}, "message": "已删除（含全部切片）"}


@router.post("/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    current_user: User = Depends(require_kb_doc_writer),
    db: AsyncSession = Depends(get_db_session),
):
    """重新索引知识文档（如更换嵌入模型后；有 raw_text 缓存时无需重新解析文件）。"""
    try:
        did = uuid.UUID(doc_id)
    except ValueError:
        return {"code": 1, "data": None, "message": f"无效的文档 ID: {doc_id}"}
    doc = (
        await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == did))
    ).scalar_one_or_none()
    if doc is None:
        return {"code": 1, "data": None, "message": "文档不存在"}

    doc.status = "parsing"
    doc.error = None
    await db.commit()
    try:
        process_knowledge_document.delay(str(did))
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.error = f"任务提交失败: {exc}"
        await db.commit()
        return {"code": 1, "data": _doc_to_dict(doc), "message": doc.error}
    return {"code": 0, "data": _doc_to_dict(doc), "message": "已派发重新索引任务"}


# ==================== 知识问答（RAG Chat）与反馈 ====================


@router.post("/ask")
async def ask_knowledge_qa(
    req: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """知识问答：多类型检索 → 编号引用上下文 → LLM 带来源回答。

    零命中直接礼貌拒答（不调 LLM）；命中但未配置对话模型时抛 409 引导配置。
    """
    from app.modules.knowledge.qa import ask_knowledge

    result = await ask_knowledge(
        db, req.question, project_id=req.project_id, top_k=req.top_k
    )
    return {"code": 0, "data": result, "message": "success"}


@router.post("/feedback")
async def submit_knowledge_feedback(
    req: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """提交问答反馈（点赞/点踩 + 可选评论），记录当次召回明细供质量分析。"""
    if req.rating not in ("up", "down"):
        return {"code": 1, "data": None, "message": "rating 仅支持 up / down"}
    fb = KnowledgeFeedback(
        id=uuid.uuid4(),
        user_id=current_user.id,
        question=req.question,
        answer=req.answer,
        rating=req.rating,
        comment=(req.comment or "").strip() or None,
        retrieved=req.retrieved,
    )
    db.add(fb)
    await db.commit()
    return {"code": 0, "data": {"id": str(fb.id)}, "message": "感谢反馈"}


@router.get("/feedback")
async def list_knowledge_feedback(
    rating: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_kb_term_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """反馈列表与统计（仅 super_admin/admin/test_manager），用于检索质量分析。"""
    stmt = select(KnowledgeFeedback)
    count_stmt = select(func.count()).select_from(KnowledgeFeedback)
    if rating in ("up", "down"):
        stmt = stmt.where(KnowledgeFeedback.rating == rating)
        count_stmt = count_stmt.where(KnowledgeFeedback.rating == rating)

    total = (await db.execute(count_stmt)).scalar() or 0
    up_count = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeFeedback)
            .where(KnowledgeFeedback.rating == "up")
        )
    ).scalar() or 0
    down_count = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeFeedback)
            .where(KnowledgeFeedback.rating == "down")
        )
    ).scalar() or 0

    result = await db.execute(
        stmt.order_by(KnowledgeFeedback.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = result.scalars().all()
    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "id": str(f.id),
                    "user_id": str(f.user_id) if f.user_id else None,
                    "question": f.question,
                    "answer": (f.answer or "")[:200],
                    "rating": f.rating,
                    "comment": f.comment,
                    "retrieved": f.retrieved or [],
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in items
            ],
            "total": total,
            "up_count": up_count,
            "down_count": down_count,
        },
        "message": "success",
    }
