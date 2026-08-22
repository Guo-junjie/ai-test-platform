"""检索 + 注入。所有注入点只调用 retrieve_and_inject / search_terms。"""
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.config import settings
from app.utils.database import AsyncSessionLocal
from app.models.database import (
    KnowledgeChunk,
    KnowledgeTerm,
    KBChunkType,
    KBRebuildState,
)
from app.modules.knowledge.embedder import embed_query


@dataclass
class RetrievalHit:
    """一次检索命中。"""
    chunk: KnowledgeChunk
    score: float


def _tokenize(text: str) -> list[str]:
    """小写并切词：ASCII 词 + 单个 CJK 汉字（中文按字重叠，粗粒度但零配置可用）。"""
    text = (text or "").lower()
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度；维度不一致或零向量返回 0.0（避免除零）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def keyword_score(query: str, content: str) -> float:
    """token 重叠打分（BM25-lite 简化版）；返回 >0 表示命中。"""
    if not query or not content:
        return 0.0
    q_tokens = _tokenize(query)
    c_tokens = _tokenize(content)
    if not q_tokens or not c_tokens:
        return 0.0
    q_set = set(q_tokens)
    hits = sum(1 for t in c_tokens if t in q_set)
    if hits == 0:
        return 0.0
    precision = hits / len(c_tokens)
    recall = hits / len(q_set)
    return precision * recall


async def search_terms(
    db: AsyncSession, query: str, top_k: int = 10
) -> list[KnowledgeTerm]:
    """业务术语表检索（零配置必可用）：对所有 term 做 token 重叠打分取 top_k。"""
    if not query or not query.strip():
        return []
    try:
        result = await db.execute(select(KnowledgeTerm))
        terms = result.scalars().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"search_terms failed: {exc}")
        return []
    scored = []
    for t in terms:
        text = " ".join(
            [str(t.term or ""), " ".join(t.aliases or []), str(t.technical_meaning or "")]
        )
        sc = keyword_score(query, text)
        if sc > 0:
            scored.append((t, sc))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:top_k]]


async def retrieve_chunks(
    db: AsyncSession,
    query: str,
    kb_type: str,
    top_k: int = 5,
    candidate_limit: int = 5000,
) -> list[RetrievalHit]:
    """候选集 SELECT ... WHERE kb_type ORDER BY created_at DESC LIMIT 5000。

    有 query 向量且候选有 embedding → 余弦排序取 top_k；
    否则 → 关键词打分(token 重叠) 取 top_k。
    仅保留正向得分命中，避免注入无关内容。
    """
    try:
        kb_enum = KBChunkType(kb_type)
    except ValueError:
        return []
    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.kb_type == kb_enum)
        .order_by(KnowledgeChunk.created_at.desc())
        .limit(candidate_limit)
    )
    candidates = result.scalars().all()
    if not candidates:
        return []

    query_vec = None
    try:
        query_vec = await embed_query(query)
    except Exception:  # noqa: BLE001
        query_vec = None

    has_emb = query_vec is not None and any(
        isinstance(c.embedding, list) and c.embedding for c in candidates
    )

    scored = []
    if has_emb:
        for c in candidates:
            if isinstance(c.embedding, list) and c.embedding:
                sc = cosine(query_vec, c.embedding)
            else:
                sc = 0.0
            scored.append((c, sc))
    else:
        for c in candidates:
            sc = keyword_score(query, c.content or "")
            scored.append((c, sc))

    # 只保留有正向得分的命中，避免注入无关内容
    scored = [(c, s) for c, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [RetrievalHit(chunk=c, score=s) for c, s in scored[:top_k]]


# ===== 重建状态机（DB 级，跨 API / Celery Worker 进程可见）=====


async def get_rebuild_state(db: AsyncSession) -> dict:
    """读取重建状态；无记录则初始化一行（state=idle）。"""
    row = (
        await db.execute(select(KBRebuildState).order_by(KBRebuildState.id).limit(1))
    ).scalar_one_or_none()
    if row is None:
        row = KBRebuildState(id=1, state="idle")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return {
        "state": row.state,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_rebuild": row.last_rebuild.isoformat() if row.last_rebuild else None,
        "last_rebuild_chunks": row.last_rebuild_chunks,
        "error": row.error,
    }


async def set_rebuild_state(db: AsyncSession, state: str, **fields: Any) -> None:
    """设置重建状态（单行表，id=1）。"""
    row = (
        await db.execute(select(KBRebuildState).order_by(KBRebuildState.id).limit(1))
    ).scalar_one_or_none()
    if row is None:
        row = KBRebuildState(id=1, state="idle")
        db.add(row)
        await db.flush()
    row.state = state
    for k, v in fields.items():
        setattr(row, k, v)
    await db.commit()


async def retrieve_and_inject(
    db: AsyncSession | None,
    query: str,
    kb_type: str,
    top_k: int = 5,
) -> str:
    """统一注入入口（所有注入点唯一调用）。

    - KB_RAG_ENABLED=False → 直接 return ""（零开销，不改变原行为）
    - query 空 → return ""
    - db 为 None 时自行开短生命周期 AsyncSessionLocal() 并在 finally 关闭
    - kb_type=='term' → 调 search_terms 拼【业务术语参考】
    - 其他 → retrieve_chunks 拼【历史经验参考】
    - 任何异常 → 记日志并 return ""（绝不抛出，不阻塞主流程）
    返回可直接拼到 prompt 顶部的字符串。
    """
    # 铁律：开关关闭 → 直接返回空字符串，零开销且不改变原行为
    if not settings.KB_RAG_ENABLED:
        return ""
    if not query or not query.strip():
        return ""

    own_session = False
    if db is None:
        db = AsyncSessionLocal()
        own_session = True

    start = time.monotonic()
    try:
        if kb_type == "term":
            terms = await search_terms(db, query, top_k=top_k)
            if not terms:
                return ""
            lines = []
            for t in terms:
                aliases = ", ".join(t.aliases or []) if t.aliases else ""
                line = (
                    f"- {t.term}"
                    + (f"（别名：{aliases}）" if aliases else "")
                    + f"：{t.technical_meaning}"
                )
                lines.append(line)
            kb = "【业务术语参考】\n" + "\n".join(lines)
            logger.info(
                json.dumps(
                    {
                        "event": "kb_inject",
                        "kb_inject": True,
                        "kb_type": kb_type,
                        "query": query[:50],
                        "hit_count": len(terms),
                        "top_score": None,
                        "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                    },
                    ensure_ascii=False,
                )
            )
            return kb
        else:
            hits = await retrieve_chunks(db, query, kb_type, top_k=top_k)
            if not hits:
                return ""
            lines = []
            for h in hits:
                ref = h.chunk.source_ref or ""
                lines.append(f"【{ref}】{h.chunk.content}")
            kb = "【历史经验参考】\n" + "\n".join(lines)
            top_score = hits[0].score if hits else 0.0
            logger.info(
                json.dumps(
                    {
                        "event": "kb_inject",
                        "kb_inject": True,
                        "kb_type": kb_type,
                        "query": query[:50],
                        "hit_count": len(hits),
                        "top_score": round(top_score, 4),
                        "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                    },
                    ensure_ascii=False,
                )
            )
            return kb
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"retrieve_and_inject degraded to empty (non-blocking): {exc}")
        return ""
    finally:
        if own_session:
            await db.close()
