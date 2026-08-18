"""
pdf_parser — pdfplumber 抽取全文（含表格转 markdown）

- 页数上限（默认 200，超出截断并标记）
- 扫描版 PDF（extract_text 为空）由调用方判定为 FAILED（本版本不支持 OCR）
"""

from typing import Any


def _table_from_rows(rows: list) -> str:
    """pdfplumber extract_tables 返回的是二维 list（含 None），转 markdown。"""
    cleaned = [r for r in rows if any(c is not None for c in r)]
    if not cleaned:
        return ""
    out: list[str] = []
    header = [" " if c is None else str(c).strip() for c in cleaned[0]]
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * len(header)) + " |")
    for row in cleaned[1:]:
        cells = [" " if c is None else str(c).strip() for c in row]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def extract_text_pdf(path: str, max_pages: int = 200) -> str:
    """抽取 PDF 全文。返回空字符串表示扫描版（无文本层）。"""
    import pdfplumber

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            txt = page.extract_text() or ""
            for table in page.extract_tables():
                md = _table_from_rows(table)
                if md:
                    txt = (txt + "\n" + md).strip()
            chunks.append(txt)
    return "\n\n".join(c for c in chunks if c).strip()
