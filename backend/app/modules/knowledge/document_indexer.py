"""知识文档索引管线 — 解析 → 章节切片 → 嵌入 → 入库（文档中心化 P0）。

被 Celery 任务（tasks.process_knowledge_document）调用；也可同步调用（小文档测试）。
文档类切片 kb_type=document，project_id 必填（项目隔离铁律）。
"""
import hashlib
import os
import uuid
from datetime import datetime

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import KnowledgeChunk, KnowledgeDocument, KBChunkType
from app.modules.knowledge.chunker import build_chunk_records
from app.modules.knowledge.document_chunker import chunk_document
from app.modules.knowledge.embedder import embed_texts

# 支持的文件类型（扩展名 → file_type）
SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".txt": "txt"}
# 上传大小上限（字节）：20MB
MAX_FILE_SIZE = 20 * 1024 * 1024


def parse_document_file(storage_key: str, file_type: str) -> str:
    """按文件类型解析出全文。md/txt 直接读；docx/pdf 复用 doc_parser。

    返回空字符串视为解析失败（如扫描版 PDF 无文本层），由调用方置 failed。
    """
    if file_type in ("md", "txt"):
        with open(storage_key, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    if file_type == "docx":
        from app.modules.doc_parser.docx_parser import extract_text_docx

        return extract_text_docx(storage_key)
    if file_type == "pdf":
        from app.modules.doc_parser.pdf_parser import extract_text_pdf

        return extract_text_pdf(storage_key)
    raise ValueError(f"Unsupported file_type: {file_type}")


def detect_file_type(filename: str) -> str | None:
    """从文件名识别支持的类型；不支持返回 None。"""
    ext = os.path.splitext(filename or "")[1].lower()
    return SUPPORTED_EXTENSIONS.get(ext)


async def remove_document_chunks(db: AsyncSession, doc_id: uuid.UUID) -> int:
    """删除某文档的全部切片（source_ref 前缀匹配，限定 kb_type 防误删）。"""
    prefix = f"document:{doc_id}"
    result = await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.kb_type == KBChunkType.DOCUMENT,
            KnowledgeChunk.source_ref.like(f"{prefix}%"),
        )
    )
    return result.rowcount or 0


async def index_document(db: AsyncSession, doc_id: uuid.UUID) -> dict:
    """索引一个知识文档：解析（或用 raw_text 缓存）→ 章节切片 → 嵌入 → 覆盖式入库。

    成功：更新 status=indexed / chunk_count / raw_text；失败：status=failed + error。
    返回 {"status": "indexed"|"failed", "chunks": n, "error": str|None}。
    """
    doc = (
        await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))
    ).scalar_one_or_none()
    if doc is None:
        return {"status": "failed", "chunks": 0, "error": f"document not found: {doc_id}"}

    try:
        text = (doc.raw_text or "").strip()
        if not text:
            text = parse_document_file(doc.storage_key, doc.file_type)
        if not text:
            raise ValueError(
                "未能从文件解析出任何文本（扫描版 PDF 需 OCR，当前版本不支持）"
            )

        pieces = chunk_document(text)
        if not pieces:
            raise ValueError("切片结果为空")

        # 章节切片 → chunk 记录（复用 build_chunk_records 保证 _src_hash/增量兼容）
        records: list[dict] = []
        doc_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        for i, piece in enumerate(pieces):
            meta = {
                "document_id": str(doc.id),
                "doc_title": doc.title,
                "filename": doc.filename,
                "category": doc.category,
                "chunk_title": piece.get("title") or "",
                "chunk_index": i,
                "_src_hash": doc_sha,
            }
            records.extend(
                build_chunk_records(
                    piece["content"],
                    "document",
                    f"document:{doc.id}:{i}",
                    meta,
                    src_hash=doc_sha,
                )
            )

        # 嵌入（无模型 → None，关键词检索兜底）
        texts = [r["content"] for r in records]
        embeddings = await embed_texts(texts)
        if embeddings is not None:
            for i, r in enumerate(records):
                r["embedding"] = embeddings[i] if i < len(embeddings) else None

        # 覆盖式入库：先清该文档旧切片
        await remove_document_chunks(db, doc.id)

        from app.modules.knowledge.embedder import upsert_chunks

        count = 0
        for rec in records:
            rec["project_id"] = doc.project_id  # 项目隔离铁律：文档切片必填
        count = await upsert_chunks_with_project(db, records)

        doc.status = "indexed"
        doc.chunk_count = count
        doc.raw_text = text
        doc.error = None
        await db.commit()
        logger.info(
            f"[KB doc] indexed document {doc.id} ({doc.title}): {count} chunks, "
            f"embedding={'yes' if embeddings is not None else 'no(keyword fallback)'}"
        )
        return {"status": "indexed", "chunks": count, "error": None}

    except Exception as exc:  # noqa: BLE001 - 单文档失败不拖垮其他文档
        logger.exception(f"[KB doc] index failed for {doc_id}: {exc}")
        await db.rollback()
        doc = (
            await db.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
            )
        ).scalar_one_or_none()
        if doc is not None:
            doc.status = "failed"
            doc.error = str(exc)[:500]
            await db.commit()
        return {"status": "failed", "chunks": 0, "error": str(exc)[:500]}


async def upsert_chunks_with_project(db: AsyncSession, records: list[dict]) -> int:
    """与 embedder.upsert_chunks 相同，但额外写入 project_id。"""
    count = 0
    for rec in records:
        if not rec.get("content"):
            continue
        chunk = KnowledgeChunk(
            id=rec.get("id") or uuid.uuid4(),
            kb_type=rec["kb_type"],
            project_id=rec.get("project_id"),
            source_ref=rec.get("source_ref"),
            content=rec["content"],
            embedding=rec.get("embedding"),
            meta=rec.get("meta") or {},
            created_at=rec.get("created_at") or datetime.utcnow(),
        )
        db.add(chunk)
        count += 1
    await db.flush()
    return count
