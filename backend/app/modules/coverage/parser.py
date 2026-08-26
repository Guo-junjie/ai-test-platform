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
    for counter in root.iter("counter"):
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

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        raise ValueError(f"覆盖率 XML 解析失败: {e}")

    tool_l = (tool or "").lower()
    tag = root.tag.lower()

    # JaCoCo 原生：根标签 <report> 且含 <counter type=...>
    is_jacoco = tool_l == "jacoco" or (
        tag.endswith("report") and root.find(".//counter[@type='LINE']") is not None
    )
    if is_jacoco:
        try:
            return _parse_jacoco(root)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"JaCoCo parse failed, try cobertura: {e}")

    # Cobertura：根标签 <coverage>
    try:
        return _parse_cobertura(root)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Cobertura parse failed: {e}")
        raise ValueError(f"无法识别的覆盖率报告格式（tool={tool}）: {e}")
