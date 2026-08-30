"""知识文档切片器 — 章节感知切片（文档中心化 P0）。

替代通用 chunker 的固定字符窗口：先按 Markdown 标题 / 中文编号标题切出章节，
每个切片继承所在章节标题作为语义锚点；超长章节内部再退化为字符窗口滑动。
纯函数，无 IO。
"""
import re
from typing import Any

# 标题行模式（按优先级）：
#   Markdown：1-6 个 # 开头
#   中文编号：一、二、... / 第X章 / 第X节
#   阿拉伯编号：1. / 1.1 / 1.1.1 开头的短行（限 60 字内，避免把"1. 参数说明详见附录"这种普通句子误判）
_HEADING_RE = re.compile(
    r"^(?:"
    r"(?P<md>#{1,6}\s+\S.+)"
    r"|(?P<cn>(?:[一二三四五六七八九十百]+、|第[一二三四五六七八九十百\d]+[章节]).{0,80})"
    r"|(?P<num>\d+(?:\.\d+)*\.?\s+\S.{0,58})"
    r")\s*$"
)

# 超长章节内部切片参数
_MAX_CHARS = 1200
_OVERLAP = 150


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按标题行切分文本为 [(章节标题, 章节正文)]；无任何标题时返回 [("", 全文)]。"""
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    cur_title = ""
    cur_body: list[str] = []
    found_heading = False

    for line in lines:
        stripped = line.strip()
        m = _HEADING_RE.match(stripped)
        if m:
            found_heading = True
            if cur_title or any(s.strip() for s in cur_body):
                sections.append((cur_title, "\n".join(cur_body).strip()))
            cur_title = stripped.lstrip("#").strip()
            cur_body = []
        else:
            cur_body.append(line)

    if cur_title or any(s.strip() for s in cur_body):
        sections.append((cur_title, "\n".join(cur_body).strip()))

    if not found_heading:
        body = text.strip()
        return [("", body)] if body else []
    return sections


def _slide_window(body: str, max_chars: int, overlap: int) -> list[str]:
    """章节内超长正文滑窗切片（与通用 chunker 同语义，内联实现保持自包含）。"""
    step = max(1, max_chars - overlap)
    pieces: list[str] = []
    start = 0
    while start < len(body):
        end = min(start + max_chars, len(body))
        piece = body[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(body):
            break
        start += step
    return pieces


def chunk_document(
    text: str,
    *,
    max_chars: int = _MAX_CHARS,
    overlap: int = _OVERLAP,
) -> list[dict[str, Any]]:
    """章节感知切片。返回 [{"content": str, "title": str}]（title 为所在章节标题，可为空串）。

    - 先按标题切章节；无标题文档整体作为一个章节
    - 章节正文超过 max_chars 时在章节内滑窗续切（每片继承同一章节标题）
    - 过滤纯空白切片
    """
    if not text or not text.strip():
        return []

    out: list[dict[str, Any]] = []
    for title, body in _split_sections(text):
        if not body:
            # 只有标题没有正文：标题本身也可作为极短知识（如空目录章节），跳过
            continue
        pieces = [body] if len(body) <= max_chars else _slide_window(body, max_chars, overlap)
        for piece in pieces:
            piece = piece.strip()
            if piece:
                out.append({"content": piece, "title": title})
    return out
