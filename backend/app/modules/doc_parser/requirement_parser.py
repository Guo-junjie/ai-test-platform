"""
requirement_parser — 用 AI 把需求/PRD 文本结构化为需求条目（use_case=doc_parse）

- 长文本分块（≤12000 字符，优先在空行切），并发调模型
- JSON 三重容错：裸 JSON / ```json 块 / 抽取首个 {...}
- 失败 / 无模型 → 规则兜底：从文本抽取编号/项目符号条目与“需求/功能”章节
- 输出 RequirementItem 列表，供 API 落库与“一键生成用例”消费

与 ai_enhancer 的区别：抽取目标是“需求/验收标准”而非“HTTP 接口”。
"""

import asyncio
import json
import re
from typing import Optional

from loguru import logger

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.modules.doc_parser.schemas import RequirementItem


_SYSTEM_PROMPT = """你是一名资深需求分析师。任务：从给定文本（产品需求文档 / PRD / 功能规格）中抽取结构化需求，输出严格 JSON。

铁律：
1. 只允许从文本中抽取真实存在的需求，禁止推测、补全不存在的内容。
2. 每条需求尽量回填：编号(rid)、标题(title)、描述(description)、类别(category)、
   优先级(priority)、出处章节(source_section)、验收标准(acceptance_criteria)、
   关联模块(related_modules)、建议测试点(test_points)。
3. category 取值：functional(功能) / non_functional(非功能) / interface(接口) / security(安全)。
4. priority 取值：P0(最高) / P1 / P2 / P3(最低)；无法判定填 P2。
5. 文本未明确的信息留空，不要臆造；找不到明确需求的段落放入 unparsed_notes。
6. confidence 自评：明确编号+验收标准 >=0.8；散落描述 0.4~0.7；仅出现标题 0.3。

输出格式（仅 JSON，不要 markdown 代码块，不要解释文字）：
{
  "requirements": [
    {"rid":"FR-1","title":"用户登录","description":"支持账号密码登录","category":"functional",
     "priority":"P1","source_section":"2.1 登录","acceptance_criteria":["输入正确账号密码可登录","密码错误提示"],
     "related_modules":["认证服务"],"test_points":["正常登录","错误密码","空输入"],"confidence":0.9,"evidence":""}
  ],
  "unparsed_notes": []
}
"""

_PROMPT_TEMPLATE = """请解析以下需求文档文本：

===== 文档开始 =====
{text}
===== 文档结束 =====

按系统要求输出 JSON。"""


def _parse_json_response(text: str) -> Optional[dict]:
    """三重容错解析 LLM 返回的 JSON。"""
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break
    return None


def _split_chunks(text: str, max_chars: int = 12000) -> list[str]:
    """优先在空行处切分，避免切断需求条目。"""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    buf = ""
    for line in text.splitlines():
        if len(buf) + len(line) > max_chars and buf:
            chunks.append(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        chunks.append(buf)
    return chunks


def _coerce_item(item: dict, idx: int) -> RequirementItem:
    """把 AI 返回的 dict 规整为 RequirementItem。"""
    rid = item.get("rid") or f"REQ-{idx:03d}"
    priority = str(item.get("priority") or "P2").upper()
    if priority not in ("P0", "P1", "P2", "P3"):
        priority = "P2"
    category = str(item.get("category") or "functional").lower()
    if category not in ("functional", "non_functional", "interface", "security"):
        category = "functional"
    conf = item.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) else 0.8
    return RequirementItem(
        rid=str(rid),
        title=item.get("title", "") or "",
        description=item.get("description", "") or "",
        category=category,
        priority=priority,
        source_section=item.get("source_section", "") or "",
        acceptance_criteria=list(item.get("acceptance_criteria", []) or []),
        related_modules=list(item.get("related_modules", []) or []),
        test_points=list(item.get("test_points", []) or []),
        confidence=conf,
        evidence=item.get("evidence", "") or "",
    )


def _regex_fallback(raw_text: str, max_requirements: int = 200) -> list[RequirementItem]:
    """
    无 AI 时的规则兜底：抽取编号条目（1. / 1.1 / (一) / 【需求】 / 功能：）与
    “需求/功能”章节标题，退化为低置信度需求骨架。
    """
    items: list[RequirementItem] = []
    seen: set[str] = set()
    # 匹配编号段落开头：数字编号、中文编号、方括号标题、以"需求/功能"开头的行
    patterns = [
        re.compile(r"^\s*(\d+(?:\.\d+)*)\s*[.、)]\s*(.+)$"),
        re.compile(r"^\s*[（(](.+?)[)）]\s*(.+)$"),
        re.compile(r"^\s*【?\s*(需求|功能|特性|规则)\s*】?\s*[:：]?\s*(.+)$"),
    ]
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        for pat in patterns:
            m = pat.match(line)
            if m:
                if pat.groups == 2:
                    rid, title = m.group(1), m.group(2)
                else:
                    rid, title = f"REQ-{len(items)+1:03d}", m.group(1)
                key = f"{rid} {title}"
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    RequirementItem(
                        rid=str(rid),
                        title=title.strip()[:200],
                        description=line[:500],
                        category="functional",
                        priority="P2",
                        confidence=0.3,
                        evidence="regex fallback",
                    )
                )
                break
        if len(items) >= max_requirements:
            break
    return items


async def parse_requirements(
    raw_text: str, use_ai: bool = True, max_requirements: int = 200
) -> tuple[list[RequirementItem], str]:
    """
    解析需求文本，返回 (需求条目列表, parse_engine)。

    parse_engine: "ai" | "rule_degraded"
    无 AI 模型 / 调用失败 → rule_degraded（正则兜底）。
    """
    if not raw_text or not raw_text.strip():
        return [], "rule_degraded"

    if use_ai:
        try:
            router = get_model_router()
            chunks = _split_chunks(raw_text, max_chars=12000)
            sem = asyncio.Semaphore(3)

            async def _one(chunk: str):
                async with sem:
                    prompt = _PROMPT_TEMPLATE.format(text=chunk)
                    try:
                        resp = await router.call(
                            use_case="doc_parse",
                            messages=[{"role": "user", "content": prompt}],
                            response_format_json=True,
                            temperature=0.1,
                        )
                    except ModelNotConfiguredError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"AI requirement parse chunk failed (degrade): {e}")
                        return None
                    return _parse_json_response(resp)

            results = await asyncio.gather(*[_one(c) for c in chunks])
            merged: dict[str, RequirementItem] = {}
            order = 0
            for data in results:
                if not data or "requirements" not in data:
                    continue
                for item in data.get("requirements", []):
                    try:
                        spec = _coerce_item(item, order)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"Skip invalid requirement: {e}")
                        continue
                    key = spec.rid or f"_{order}"
                    if key not in merged:
                        merged[key] = spec
                        order += 1
            if merged:
                items = list(merged.values())[:max_requirements]
                return items, "ai"
        except ModelNotConfiguredError:
            logger.info("doc_parse model not configured, requirement parse -> rule_degraded")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI requirement parse failed, fall back to regex: {e}")

    items = _regex_fallback(raw_text, max_requirements)
    return items, "rule_degraded"
