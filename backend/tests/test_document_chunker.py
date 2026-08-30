"""知识文档章节感知切片器测试（KB P0 核心，纯函数无 IO）。"""
from app.modules.knowledge.document_chunker import chunk_document

SAMPLE = """# SNMP 测试规范
## 3 SNMP Trap 测试
### 3.1 Trap 丢失
网络抖动时 Trap 可能丢失，需验证重传机制。
### 3.2 Trap 重复
重复 Trap 需按 oid + 时间窗去重。
一、故障排查
设备离线先检查心跳。
2.1 升级前检查
升级前备份配置。普通正文归入上一节。
"""


class TestChunkDocument:
    def test_markdown_headings_split(self):
        out = chunk_document(SAMPLE)
        titles = [o["title"] for o in out]
        assert any("3.1" in t for t in titles)
        assert any("3.2" in t for t in titles)
        # 每片都带 content
        assert all(o["content"].strip() for o in out)

    def test_chinese_numbered_heading(self):
        titles = [o["title"] for o in chunk_document(SAMPLE)]
        assert any("故障排查" in t for t in titles)

    def test_arabic_numbered_heading(self):
        titles = [o["title"] for o in chunk_document(SAMPLE)]
        assert any("2.1" in t for t in titles)

    def test_plain_text_single_chunk(self):
        out = chunk_document("没有标题的普通文本内容。")
        assert len(out) == 1
        assert out[0]["title"] == ""

    def test_empty_and_whitespace(self):
        assert chunk_document("") == []
        assert chunk_document("   \n\t  ") == []

    def test_long_section_slides_window(self):
        body = "# 章节\n" + ("很长的正文内容。" * 500)  # > 1200 字符
        out = chunk_document(body)
        assert len(out) > 1
        # 每片继承章节标题
        assert all("章节" in o["title"] for o in out)
        # 每片不超过上限
        assert all(len(o["content"]) <= 1200 for o in out)

    def test_heading_only_section_skipped(self):
        out = chunk_document("# 标题A\n## 标题B\n正文内容在这里。")
        titles = [o["title"] for o in out]
        assert "标题B" in titles
        # 无正文的"标题A"不产出空切片
        assert all(o["content"] for o in out)
