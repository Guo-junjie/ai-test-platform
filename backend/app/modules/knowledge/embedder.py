"""嵌入层：复用 ModelRouter 的 'embedding' use_case；无模型时返回 None 降级。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.config import settings
from app.modules.ai.model_router import get_model_router, ModelNotConfiguredError
from app.modules.knowledge.chunker import build_chunk_records
from app.models.database import (
    KnowledgeChunk,
    KnowledgeTerm,
    Defect,
    TestCase,
    ApiEndpoint,
    KBChunkType,
)


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """批量嵌入。返回 list[float[]]；无嵌入模型 / provider 不支持 → 返回 None 降级。"""
    if not texts:
        return []
    try:
        router = get_model_router()
        client = router.get_client("embedding")
    except Exception as exc:  # noqa: BLE001
        logger.info(f"Embedding model unavailable, degrade to keyword search: {exc}")
        return None
    try:
        return await client.embed(texts)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"Embedding failed, degrade to keyword search: {exc}")
        return None


async def embed_query(text: str) -> list[float] | None:
    """单条查询嵌入；无模型返回 None。"""
    if not text or not text.strip():
        return None
    vectors = await embed_texts([text])
    if not vectors:
        return None
    return vectors[0]


async def upsert_chunks(db: AsyncSession, records: list[dict]) -> int:
    """将 build_chunk_records 产出的 dict 列表写入 knowledge_chunks。返回写入条数。"""
    count = 0
    for rec in records:
        if not rec.get("content"):
            continue
        chunk = KnowledgeChunk(
            id=rec.get("id") or uuid.uuid4(),
            kb_type=rec["kb_type"],
            source_ref=rec.get("source_ref"),
            content=rec["content"],
            embedding=rec.get("embedding"),
            meta=rec.get("meta") or {},
            created_at=rec.get("created_at") or datetime.now(timezone.utc),
        )
        db.add(chunk)
        count += 1
    await db.flush()
    return count


async def _fetch_source_rows(
    db: AsyncSession, kb_type: str
) -> list[tuple[str, str, dict]]:
    """按 kb_type 从对应源表取 (source_ref, content, meta)。

    各源表字段以 app/models/database.py 真实列名为准；JSONB 列统一 or {} / or [] 防 None，
    拼串前统一 str() / json.dumps(..., ensure_ascii=False)，避免 None 进 +。
    """
    import json

    rows: list[tuple[str, str, dict]] = []

    if kb_type == "defect":
        result = await db.execute(select(Defect))
        for d in result.scalars().all():
            content = " ".join(
                str(x) for x in [d.title, d.description, d.root_cause, d.fix_suggestion] if x
            ).strip()
            if not content:
                continue
            meta = {
                "defect_type": d.defect_type.value if d.defect_type else None,
                "severity": d.severity.value if d.severity else None,
            }
            rows.append((f"defect:{d.id}", content, meta))

    elif kb_type == "case":
        result = await db.execute(select(TestCase))
        for c in result.scalars().all():
            expected = c.expected_result or {}
            expected_summary = json.dumps(expected, ensure_ascii=False) if expected else ""
            content = " ".join(
                str(x)
                for x in [
                    c.case_name,
                    c.description,
                    c.http_method,
                    c.api_path,
                    expected_summary,
                ]
                if x
            ).strip()
            if not content:
                continue
            meta = {"case_type": c.case_type, "priority": c.priority}
            rows.append((f"case:{c.id}", content, meta))

    elif kb_type == "doc":
        result = await db.execute(select(ApiEndpoint))
        for e in result.scalars().all():
            params = e.params or []
            param_parts = []
            for p in params:
                if isinstance(p, dict):
                    param_parts.append(f"{p.get('name', '')} {p.get('description', '')}")
            param_str = " ".join(param_parts)
            content = " ".join(
                str(x)
                for x in [e.method, e.path, e.summary, e.description, param_str]
                if x
            ).strip()
            if not content:
                continue
            meta = {"method": e.method, "path": e.path}
            rows.append((f"doc:{e.id}", content, meta))

    elif kb_type == "term":
        result = await db.execute(select(KnowledgeTerm))
        for t in result.scalars().all():
            aliases = t.aliases or []
            content = " ".join(
                str(x) for x in [t.term, " ".join(aliases), t.technical_meaning] if x
            ).strip()
            if not content:
                continue
            meta = {"domain": t.domain}
            rows.append((f"term:{t.id}", content, meta))

    return rows


async def rebuild_kb_type(db: AsyncSession, kb_type: str) -> int:
    """对一个 kb_type 执行全量重建。

    1) 按 kb_type 从对应源表取数据
    2) build_chunk_records 切片
    3) embed_texts 嵌入（None 安全）
    4) 先 DELETE 该 kb_type 旧 chunks，再批量插入
    返回总切片数。
    """
    rows = await _fetch_source_rows(db, kb_type)
    records: list[dict] = []
    for source_ref, content, meta in rows:
        records.extend(build_chunk_records(content, kb_type, source_ref, meta))

    if records:
        texts = [r["content"] for r in records]
        embeddings = await embed_texts(texts)
        if embeddings is not None:
            for i, r in enumerate(records):
                r["embedding"] = embeddings[i] if i < len(embeddings) else None

    # 先清后写（全量覆盖式，避免脏数据累积）
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.kb_type == KBChunkType(kb_type)
        )
    )
    count = await upsert_chunks(db, records)
    return count
