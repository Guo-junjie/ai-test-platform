"""嵌入层：复用 ModelRouter 的 'embedding' use_case；无模型时返回 None 降级。"""
import hashlib
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


async def rebuild_kb_type(
    db: AsyncSession, kb_type: str, force_full: bool = False
) -> int:
    """对一个 kb_type 执行重建（增量或全量）。

    force_full=True  → 旧逻辑（DELETE 该 kb_type 全量 + 全插），清空全部旧 chunk；
    force_full=False → 增量：仅对内容哈希变更的 source_ref 重算，并清理孤儿 chunk。
    返回写入 chunk 数。
    """
    if force_full:
        return await _full_rebuild_kb_type(db, kb_type)
    return await _incremental_rebuild_kb_type(db, kb_type)


async def _full_rebuild_kb_type(db: AsyncSession, kb_type: str) -> int:
    """旧的全量重建逻辑（清空该 kb_type 全部 chunk 后重插）。

    保留原行为：build_chunk_records 不写入 _src_hash（首次增量会整体重算，符合预期）。
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


async def _incremental_rebuild_kb_type(db: AsyncSession, kb_type: str) -> int:
    """增量重建：仅对内容哈希变更的 source_ref 重算，并清理孤儿 chunk。

    1) 拉取当前源行 (source_ref -> (content, meta))
    2) 读取已存 chunk 的 _src_hash（按 source_ref 分组取其一）
    3) 计算当前内容哈希 sha256(content)[:16]，哈希不一致 → 视为变更/新增
    4) 孤儿：源表已删但 chunk 仍在的 source_ref
    5) 变更/新增：先删该 ref 旧 chunk，再重插（带新哈希 + 重新 embed，None 安全）
    6) 孤儿：限定 kb_type 批量删除，杜绝跨类型误删
    """
    # 1) 当前源行
    rows = await _fetch_source_rows(db, kb_type)
    current: dict[str, tuple[str, dict]] = {}
    for source_ref, content, meta in rows:
        current[source_ref] = (content, meta)

    # 2) 已存 chunk 的 _src_hash（按 source_ref 分组，取其一）
    existing = (
        await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.kb_type == KBChunkType(kb_type)
            )
        )
    ).scalars().all()
    existing_hash: dict[str, str | None] = {}
    for c in existing:
        h = (c.meta or {}).get("_src_hash") if c.meta else None
        existing_hash.setdefault(c.source_ref, h)

    # 3) 计算当前哈希，判定变更 / 新增
    changed_refs: list[tuple[str, str, dict, str]] = []
    for source_ref, (content, meta) in current.items():
        src_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        if existing_hash.get(source_ref) != src_hash:
            changed_refs.append((source_ref, content, meta, src_hash))

    # 首次增量：老 chunk 无 _src_hash，会触发整体重算（预期行为，仅记日志）
    if existing_hash and any(v is None for v in existing_hash.values()):
        logger.info(
            f"[KB incremental] kb_type={kb_type} 存在无 _src_hash 老 chunk，"
            "将整体重算其所属 source_ref（首次增量预期行为）"
        )

    # 4) 孤儿：源表已无、但 chunk 仍在。
    # 过滤掉 source_ref IS NULL 的历史 chunk（F4）：SQL 三值逻辑下
    # `source_ref IN (NULL)` 永不匹配 NULL，会导致它们静默滞留并每次增量
    # 都白算一遍。如需清理 NULL 另发一条 WHERE source_ref IS NULL。
    orphan_refs = [
        ref
        for ref in existing_hash
        if ref is not None and ref not in current
    ]

    total = 0
    # 5) 变更/新增：先删该 ref 旧 chunk，再重插（带新哈希 + 重新 embed）
    for source_ref, content, meta, src_hash in changed_refs:
        await delete_chunks_by_source_ref(db, kb_type, source_ref)
        records = build_chunk_records(
            content, kb_type, source_ref, meta, src_hash=src_hash
        )
        if records:
            texts = [r["content"] for r in records]
            emb = await embed_texts(texts)  # None 安全 → 关键词兜底
            if emb is not None:
                for i, r in enumerate(records):
                    r["embedding"] = emb[i] if i < len(emb) else None
            total += await upsert_chunks(db, records)

    # 6) 孤儿清理（限定 kb_type，避免跨类型误删）
    if orphan_refs:
        await delete_chunks_by_source_refs(db, kb_type, orphan_refs)

    return total


async def delete_chunks_by_source_ref(
    db: AsyncSession, kb_type: str, source_ref: str
) -> None:
    """删除指定 kb_type 下某个 source_ref 的全部 chunk（源行粒度增量删插）。"""
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.kb_type == KBChunkType(kb_type),
            KnowledgeChunk.source_ref == source_ref,
        )
    )


async def delete_chunks_by_source_refs(
    db: AsyncSession, kb_type: str, refs: list[str]
) -> None:
    """批量删除指定 kb_type 下多个 source_ref 的 chunk（孤儿清理）。

    refs 为空直接返回；限定 kb_type 防止跨类型误删。
    """
    if not refs:
        return
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.kb_type == KBChunkType(kb_type),
            KnowledgeChunk.source_ref.in_(refs),
        )
    )
