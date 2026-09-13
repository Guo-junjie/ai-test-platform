"""
coverage/parser — 把覆盖率工具产出的 XML 报告归一化为统一结构

支持：
- Cobertura XML：coverage.py (`coverage xml`)、istanbul/nyc (`--reporter=cobertura`)、
  JaCoCo 也可导出 Cobertura 格式
- JaCoCo XML：Maven/Gradle 插件原生 `jacoco.xml`（<report><counter type=LINE/BRANCH>）

输出统一 dict：
{
  "line_rate": 85.0,        # 行覆盖率 %
  "branch_rate": 70.0,      # 分支覆盖率 %
  "total_lines": 1000, "covered_lines": 850,
  "total_branches": 100, "covered_branches": 70,
  "files": [
    {
      "path": "src/main.py",
      "line_rate": 80.0,
      "branch_rate": 50.0,
      "total_lines": 100, "covered_lines": 80,
      "lines": [
        {"number": 10, "hits": 5, "branch": false, "covered_branches": 0, "total_branches": 0},
        ...
      ]
    }
  ]
}

注：
- `lines` 元素按行号升序；hits>0 视为覆盖
- Cobertura branch 属性：<line branch="true|false" condition-coverage="x% (a/b)">
- JaCoCo 行级：<line nr="N" mi="M" ci="C" mb="0" cb="0">，ci+mi>0 视为有指令
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from loguru import logger


def _to_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100.0, 2)


def _parse_cobertura(root: ET.Element) -> dict[str, Any]:
    """解析 Cobertura 格式（coverage.py / istanbul / JaCoCo-cobertura）。"""
    cov = root
    # 顶层已有聚合指标（coverage.py 直接给）
    line_rate_attr = cov.get("line-rate")
    branch_rate_attr = cov.get("branch-rate")
    lines_valid = cov.get("lines-valid")
    lines_covered = cov.get("lines-covered")
    branches_valid = cov.get("branches-valid")
    branches_covered = cov.get("branches-covered")

    total_lines = int(float(lines_valid)) if lines_valid else 0
    covered_lines = int(float(lines_covered)) if lines_covered else 0
    total_branches = int(float(branches_valid)) if branches_valid else 0
    covered_branches = int(float(branches_covered)) if branches_covered else 0

    if line_rate_attr is not None:
        line_rate = round(float(line_rate_attr) * 100.0, 2)
    else:
        line_rate = _to_pct(covered_lines, total_lines)
    if branch_rate_attr is not None:
        branch_rate = round(float(branch_rate_attr) * 100.0, 2)
    else:
        branch_rate = _to_pct(covered_branches, total_branches)

    files: list[dict[str, Any]] = []
    for cls in cov.iter("class"):
        fname = cls.get("filename") or cls.get("name") or ""
        if not fname:
            continue
        lines_el = cls.find("lines")
        f_total = 0
        f_covered = 0
        f_cb = 0  # covered branches
        f_mb = 0  # missed branches
        f_lines: list[dict[str, Any]] = []
        if lines_el is not None:
            for ln in lines_el.findall("line"):
                f_total += 1
                try:
                    hits = int(ln.get("hits", "0"))
                except (ValueError, TypeError):
                    hits = 0
                if hits > 0:
                    f_covered += 1
                # branch info：condition-coverage="100% (2/2)" 解析 a/b
                cb, mb = 0, 0
                is_branch = (ln.get("branch") or "").lower() == "true"
                cond = ln.get("condition-coverage") or ""
                if "(" in cond and "/" in cond and ")" in cond:
                    try:
                        a, b = cond.split("(")[1].split(")")[0].split("/")
                        cb, mb = int(a), int(b) - int(a)
                    except (ValueError, TypeError, IndexError):
                        pass
                f_cb += cb
                f_mb += mb
                f_lines.append({
                    "number": int(ln.get("number", "0") or 0),
                    "hits": hits,
                    "branch": is_branch,
                    "covered_branches": cb,
                    "total_branches": cb + mb,
                })
        files.append(
            {
                "path": fname,
                "line_rate": _to_pct(f_covered, f_total),
                "branch_rate": _to_pct(f_cb, f_cb + f_mb) if (f_cb + f_mb) > 0 else None,
                "total_lines": f_total,
                "covered_lines": f_covered,
                "lines": f_lines,
            }
        )
    if not total_lines and files:
        total_lines = sum(f["total_lines"] for f in files)
        covered_lines = sum(f["covered_lines"] for f in files)
        line_rate = _to_pct(covered_lines, total_lines)
    if not total_branches and files:
        total_branches = sum(
            line["total_branches"] for f in files for line in f["lines"]
        )
        covered_branches = sum(
            line["covered_branches"] for f in files for line in f["lines"]
        )
        branch_rate = _to_pct(covered_branches, total_branches) if total_branches else None
    return {
        "line_rate": line_rate,
        "branch_rate": branch_rate,
        "total_lines": total_lines,
        "covered_lines": covered_lines,
        "total_branches": total_branches,
        "covered_branches": covered_branches,
        "files": files,
    }


def _parse_jacoco(root: ET.Element) -> dict[str, Any]:
    """解析 JaCoCo 原生格式（<report><counter type=LINE/BRANCH>）。"""
    total_lines = total_branches = covered_lines = covered_branches = 0
    for counter in root.findall("counter"):
        ctype = (counter.get("type") or "").upper()
        try:
            missed = int(counter.get("missed", "0"))
            covered = int(counter.get("covered", "0"))
        except (ValueError, TypeError):
            continue
        if ctype == "LINE":
            total_lines = missed + covered
            covered_lines = covered
        elif ctype == "BRANCH":
            total_branches = missed + covered
            covered_branches = covered

    files: list[dict[str, Any]] = []
    # 按 sourcefile 汇总行/分支
    for pkg in root.iter("package"):
        pkg_name = pkg.get("name", "")
        for sf in pkg.iter("sourcefile"):
            sf_name = sf.get("name", "")
            f_total = f_covered = f_mb = f_cb = 0
            f_lines: list[dict[str, Any]] = []
            for ln in sf.findall("line"):
                f_total += 1
                try:
                    nr = int(ln.get("nr", "0"))
                    ci = int(ln.get("ci", "0"))
                    mi = int(ln.get("mi", "0"))
                    cb = int(ln.get("cb", "0"))
                    mb = int(ln.get("mb", "0"))
                except (ValueError, TypeError):
                    nr, ci, mi, cb, mb = 0, 0, 0, 0, 0
                hits = ci  # JaCoCo 用 covered instructions 数代表 hits
                # 修正：仅当 ci>0 视为覆盖（ci+mi>0 是"有指令"≠"已覆盖"）
                if ci > 0:
                    f_covered += 1
                f_mb += mb
                f_cb += cb
                f_lines.append({
                    "number": nr,
                    "hits": hits,
                    "branch": (cb + mb) > 0,
                    "covered_branches": cb,
                    "total_branches": cb + mb,
                })
            path = f"{pkg_name}/{sf_name}" if pkg_name else sf_name
            files.append(
                {
                    "path": path,
                    "line_rate": _to_pct(f_covered, f_total),
                    "branch_rate": _to_pct(f_cb, f_cb + f_mb) if (f_cb + f_mb) > 0 else None,
                    "total_lines": f_total,
                    "covered_lines": f_covered,
                    "lines": f_lines,
                }
            )

    return {
        "line_rate": _to_pct(covered_lines, total_lines),
        "branch_rate": _to_pct(covered_branches, total_branches),
        "total_lines": total_lines,
        "covered_lines": covered_lines,
        "total_branches": total_branches,
        "covered_branches": covered_branches,
        "files": files,
    }


def parse_coverage_report(tool: str, raw_xml: str) -> dict[str, Any]:
    """
    解析覆盖率 XML 为统一结构。

    Args:
        tool: "coverage.py" | "jacoco" | "istanbul" | "cobertura"
        raw_xml: 报告文本内容
    Returns:
        统一结构 dict（见模块 docstring）；解析失败抛出 ValueError。
    """
    if not raw_xml or not raw_xml.strip():
        raise ValueError("覆盖率报告内容为空")

    if raw_xml.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError("返回的是网页 HTML，不是覆盖率报告；请配置专门的报告地址或上传报告文件")

    if raw_xml.lstrip().startswith("mode:"):
        return _parse_go_coverprofile(raw_xml)

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        raise ValueError(f"覆盖率 XML 解析失败: {e}")

    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag == "report" and root.find(".//counter[@type='LINE']") is not None:
        result = _parse_jacoco(root)
    elif tag == "coverage":
        result = _parse_cobertura(root)
    else:
        raise ValueError("无法识别的覆盖率报告格式：需要 JaCoCo/Cobertura XML 或 Go coverprofile")
    if result["total_lines"] <= 0 or not result["files"]:
        raise ValueError("报告没有有效的文件和代码行，请检查生成命令或报告格式")
    return result


def _parse_go_coverprofile(raw_text: str) -> dict[str, Any]:
    """解析 go test -coverprofile 输出；语句块按 numStmt 加权，避免把块数冒充代码行。"""
    import re

    rows = raw_text.splitlines()
    if not rows or rows[0].strip() not in {"mode: set", "mode: count", "mode: atomic"}:
        raise ValueError("无效的 Go coverprofile 模式")
    pattern = re.compile(r"^(.+):(\d+)\.(\d+),(\d+)\.(\d+)\s+(\d+)\s+(\d+)$")
    grouped: dict[str, dict[int, dict[str, Any]]] = {}
    total = covered = 0
    for row in rows[1:]:
        match = pattern.match(row.strip())
        if not match:
            raise ValueError(f"无效的 Go coverprofile 数据行: {row[:120]}")
        path, start, _start_col, end, _end_col, statements, hits = match.groups()
        start, end, statements, hits = map(int, (start, end, statements, hits))
        if end < start or statements < 0:
            raise ValueError("Go coverprofile 行范围或语句数无效")
        total += statements
        covered += statements if hits > 0 else 0
        lines = grouped.setdefault(path, {})
        for number in range(start, end + 1):
            if number not in lines or hits > lines[number]["hits"]:
                lines[number] = {"number": number, "hits": hits, "branch": False,
                                 "covered_branches": 0, "total_branches": 0}
    if total <= 0:
        raise ValueError("Go coverprofile 没有有效的语句块")
    files = []
    for path, line_map in grouped.items():
        lines = sorted(line_map.values(), key=lambda item: item["number"])
        count = sum(line["hits"] > 0 for line in lines)
        files.append({"path": path, "line_rate": _to_pct(count, len(lines)),
                      "branch_rate": None, "total_lines": len(lines),
                      "covered_lines": count, "lines": lines})
    return {"line_rate": _to_pct(covered, total), "branch_rate": None,
            "total_lines": total, "covered_lines": covered,
            "total_branches": 0, "covered_branches": 0, "files": files}
