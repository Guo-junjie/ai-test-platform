"""
知识库 RAG 管理 API（能力12）

路径前缀由 main.py 以 prefix="/api/knowledge" 注册；本文件 APIRouter() 不带 prefix；
索引状态路由使用 @router.get("")（绝不写 "/"，避免 307 重定向砍掉 POST 请求体）。

统一响应：{"code":0,"data":...,"message":"success"}，业务冲突返回 {"code":1,...} 且 HTTP 恒 200；
鉴权失败由依赖（require_admin / require_role）返回 403/401（符合权限验收标准）。
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    KnowledgeChunk,
    KnowledgeTerm,
    KBChunkType,
    User,
    UserRole,
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
)
from app.modules.knowledge.tasks import rebuild_knowledge_base

router = APIRouter()

# 术语 CRUD 权限：super_admin / admin / test_manager
require_kb_term_admin = require_role(
    UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.TEST_MANAGER
)

_KB_TYPES = ("defect", "case", "doc", "term")


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


class RebuildRequest(BaseModel):
    kb_type: str | None = None
    force_full: bool = False  # 默认增量；True 走全量清空重插


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

    # 语义就绪信号：开关开 且 已配置嵌入模型；不做实时 probe（避免烧嵌入配额/延迟/崩溃）
    embedding_ready = bool(settings.KB_RAG_ENABLED) and bool(embedding_model_id)
    retrieval_mode = "semantic" if embedding_ready else "keyword"

    state_info = {"state": "idle", "last_rebuild": None}
    try:
        state_info = await get_rebuild_state(db)
    except Exception:
        pass

    return {
        "code": 0,
        "data": {
            "enabled": bool(settings.KB_RAG_ENABLED),
            "chunk_count": total,
            "chunk_counts": chunk_counts,
            "term_count": term_count,
            "embedding_model_id": embedding_model_id,
            "embedding_ready": embedding_ready,
            "retrieval_mode": retrieval_mode,
            "state": state_info.get("state", "idle"),
            "last_rebuild": state_info.get("last_rebuild"),
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
    if req.kb_type is not None and req.kb_type not in _KB_TYPES:
        return {"code": 1, "data": None, "message": f"无效的 kb_type: {req.kb_type}"}

    state = await get_rebuild_state(db)
    # 防重复提交：running 且更新时间在 1 小时内视为进行中（超时则视为卡死可重触发）
    if state.get("state") == "running":
        updated = state.get("updated_at")
        recent = True
        if updated:
            try:
                upd = datetime.fromisoformat(updated)
                if (datetime.now(timezone.utc) - upd).total_seconds() > 3600:
                    recent = False
            except Exception:
                recent = True
        if recent:
            return {"code": 1, "data": None, "message": "重建任务进行中，请勿重复提交"}

    await set_rebuild_state(
        db, "running", updated_at=datetime.now(timezone.utc), error=None
    )
    try:
        task = rebuild_knowledge_base.delay(req.kb_type, req.force_full)
    except Exception as exc:  # noqa: BLE001
        await set_rebuild_state(db, "idle", error=f"队列不可用: {exc}")
        return {"code": 1, "data": None, "message": f"重建任务提交失败: {exc}"}

    return {"code": 0, "data": {"task_id": task.id}, "message": "success"}


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
    """检索预览（调试/前端展示）。"""
    if not req.query or not req.query.strip():
        return {"code": 1, "data": {"chunks": []}, "message": "query 不能为空"}
    if req.kb_type == "term":
        terms = await search_terms(db, req.query, top_k=req.top_k)
        chunks = [
            {
                "content": f"{t.term}：{t.technical_meaning}",
                "kb_type": "term",
                "score": None,
                "source_ref": f"term:{t.id}",
            }
            for t in terms
        ]
        return {"code": 0, "data": {"chunks": chunks}, "message": "success"}

    hits = await retrieve_chunks(db, req.query, req.kb_type, top_k=req.top_k)
    chunks = [
        {
            "content": h.chunk.content,
            "kb_type": h.chunk.kb_type.value
            if hasattr(h.chunk.kb_type, "value")
            else str(h.chunk.kb_type),
            "score": round(h.score, 4),
            "source_ref": h.chunk.source_ref,
        }
        for h in hits
    ]
    return {"code": 0, "data": {"chunks": chunks}, "message": "success"}
