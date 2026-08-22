"""知识库文本切片。纯函数，无 IO。"""
from typing import Any


def chunk_text(
    text: str,
    *,
    max_chars: int = 1000,
    overlap: int = 100,
) -> list[str]:
    """按字符窗口切片，带 overlap 重叠；返回非空片段列表。

    - 文本短于 max_chars 直接整体返回。
    - 否则以 (max_chars - overlap) 为步长滑动窗口切片，避免过多切断语义单元。
    - 过滤掉纯空白片段。
    """
    if not text or not text.strip():
        return []
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    step = max(1, max_chars - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start += step
    return chunks


def build_chunk_records(
    text: str,
    kb_type: str,
    source_ref: str | None,
    meta: dict[str, Any] | None = None,
    *,
    max_chars: int = 1000,
    overlap: int = 100,
    src_hash: str | None = None,
) -> list[dict[str, Any]]:
    """切片并生成 knowledge_chunks 行(dict)列表。

    每条含: {id, kb_type, source_ref, content, embedding(null), meta, created_at}
    embedding 初始为 None，由 embedder 回填。
    meta 统一并入 _src_hash（内容哈希）：用于增量重建的变更检测。
    src_hash 为 None 时不写入该键（全量重建路径保持原行为）。
    """
    import uuid
    from datetime import datetime, timezone

    pieces = chunk_text(text, max_chars=max_chars, overlap=overlap)
    records: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for piece in pieces:
        records.append(
            {
                "id": uuid.uuid4(),
                "kb_type": kb_type,
                "source_ref": source_ref,
                "content": piece,
                "embedding": None,
                "meta": {**(meta or {}), "_src_hash": src_hash},
                "created_at": now,
            }
        )
    return records
