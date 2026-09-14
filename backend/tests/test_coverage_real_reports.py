"""真实代码覆盖率报告解析与 HTTP 来源校验回归。"""

import pytest

from app.modules.coverage.parser import parse_coverage_report


def test_jacoco_uses_report_totals_not_last_nested_counter():
    xml = """<report name="demo"><package name="demo"><sourcefile name="A.java">
      <line nr="1" mi="0" ci="1" mb="0" cb="0"/>
      <counter type="LINE" missed="0" covered="1"/>
    </sourcefile></package>
    <counter type="LINE" missed="3" covered="7"/>
    <counter type="BRANCH" missed="1" covered="3"/></report>"""
    report = parse_coverage_report("jacoco", xml)
    assert (report["total_lines"], report["covered_lines"], report["line_rate"]) == (10, 7, 70)
    assert (report["total_branches"], report["covered_branches"]) == (4, 3)


def test_cobertura_without_root_counts_aggregates_files():
    xml = """<coverage><packages><package><classes><class filename="a.py">
      <lines><line number="1" hits="1"/><line number="2" hits="0"/></lines>
    </class></classes></package></packages></coverage>"""
    report = parse_coverage_report("jacoco", xml)  # 上传时工具选错也应按内容解析
    assert (report["total_lines"], report["covered_lines"], report["line_rate"]) == (2, 1, 50)


def test_go_coverprofile_uses_statement_weights_and_no_fake_branch_rate():
    profile = """mode: set
example.com/demo/a.go:1.1,3.2 8 1
example.com/demo/a.go:4.1,6.2 2 0
"""
    report = parse_coverage_report("go_cover", profile)
    assert (report["total_lines"], report["covered_lines"], report["line_rate"]) == (10, 8, 80)
    assert report["branch_rate"] is None
    assert report["files"][0]["path"] == "example.com/demo/a.go"
    assert (report["files"][0]["total_lines"], report["files"][0]["covered_lines"],
            report["files"][0]["line_rate"]) == (10, 8, 80)
    assert report["files"][0]["lines"][-1]["hits"] == 0


@pytest.mark.parametrize("content", ["<html>app</html>", "<!DOCTYPE html><html>app</html>", "<report/>", "mode: set\n"])
def test_non_reports_are_rejected(content):
    with pytest.raises(ValueError):
        parse_coverage_report("jacoco", content)


@pytest.mark.asyncio
async def test_http_probe_rejects_frontend_html(monkeypatch):
    from app.modules.coverage import collector

    class FakeResponse:
        status_code = 200
        text = "<html><body>IoTFast</body></html>"
        content = text.encode()

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(collector.httpx, "AsyncClient", FakeClient)
    assert await collector.fetch_http_coverage("http://example.test/report") is None
    probe = await collector.probe_coverage_target(strategy="http_dump", dump_url="http://example.test/report")
    assert probe["ok"] is False
