"""
能力8：Cron 表达式解析器

支持自然语言 → Cron 表达式转换，规则引擎 + LLM 辅助。
规则映射覆盖常见中文时间表达，LLM 辅助处理复杂场景。
"""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


# 规则映射表：中文常见时间表达 → Cron 表达式
_RULE_MAP: list[tuple[str, str, str]] = [
    # (正则模式, Cron 表达式, 描述)
    (r"每天\s*(\d{1,2})\s*点", r"0 {hour} * * *", "每天 {hour} 点"),
    (r"每天\s*(\d{1,2})\s*时", r"0 {hour} * * *", "每天 {hour} 点"),
    (r"每(?:个?\s*)?小时", r"0 * * * *", "每小时"),
    (r"每\s*(\d+)\s*小时", r"0 */{n} * * *", "每 {n} 小时"),
    (r"每周一", r"0 0 * * 1", "每周一 00:00"),
    (r"每周二", r"0 0 * * 2", "每周二 00:00"),
    (r"每周三", r"0 0 * * 3", "每周三 00:00"),
    (r"每周四", r"0 0 * * 4", "每周四 00:00"),
    (r"每周五", r"0 0 * * 5", "每周五 00:00"),
    (r"每周六", r"0 0 * * 6", "每周六 00:00"),
    (r"每周日|每周天", r"0 0 * * 0", "每周日 00:00"),
    (r"每(?:个?\s*)?月\s*(\d{1,2})\s*(?:号|日)", r"0 0 {day} * *", "每月 {day} 号 00:00"),
    (r"每月1号|每月1日", r"0 0 1 * *", "每月 1 号 00:00"),
    (r"每月\s*(\d{1,2})\s*(?:号|日)\s*(\d{1,2})\s*点", r"0 {dayhour_1} {dayhour_0} * *", "每月 {day} 号 {hour} 点"),
    (r"每天\s*(\d{1,2})\s*点\s*(\d{1,2})\s*分", r"{min} {hour} * * *", "每天 {hour}:{min}"),
    (r"每天早上", r"0 8 * * *", "每天早上 08:00"),
    (r"每天上午", r"0 9 * * *", "每天上午 09:00"),
    (r"每天下午", r"0 14 * * *", "每天下午 14:00"),
    (r"每天晚上", r"0 20 * * *", "每天晚上 20:00"),
    (r"每天凌晨", r"0 0 * * *", "每天凌晨 00:00"),
    (r"每天中午", r"0 12 * * *", "每天中午 12:00"),
    (r"每\s*(\d+)\s*分钟", r"*/{n} * * * *", "每 {n} 分钟"),
    (r"每\s*(\d+)\s*秒", r"* * * * *", "每 {n} 秒（最小粒度 1 分钟）"),
    (r"工作日", r"0 9 * * 1-5", "工作日（周一至周五）09:00"),
    (r"周末", r"0 10 * * 6,0", "周末（周六、周日）10:00"),
    (r"每(?:个?\s*)?天", r"0 0 * * *", "每天 00:00"),
    (r"每(?:个?\s*)?周", r"0 0 * * 0", "每周日 00:00"),
    (r"每(?:个?\s*)?月", r"0 0 1 * *", "每月 1 号 00:00"),
]


class CronParser:
    """
    Cron 表达式解析器。

    支持规则引擎（快速匹配常见中文表达）+ LLM 辅助（复杂场景）。
    LLM 可用时优先尝试 LLM 解析，失败/不可用时降级为规则引擎。
    """

    def __init__(self) -> None:
        self._rule_map = _RULE_MAP

    async def parse(self, nl_input: str) -> str:
        """
        将自然语言时间描述解析为 Cron 表达式。

        Args:
            nl_input: 自然语言描述，如「每天早上8点」「每周一」「每月1号」

        Returns:
            Cron 表达式字符串（5段：分 时 日 月 周）。
        """
        if not nl_input or not nl_input.strip():
            return "0 0 * * *"

        nl_input = nl_input.strip()

        # 1. 尝试规则引擎匹配
        rule_result = self._rule_parse(nl_input)
        if rule_result:
            logger.info(f"CronParsed (rule): '{nl_input}' -> '{rule_result}'")
            return rule_result

        # 2. 尝试 LLM 辅助解析
        try:
            llm_result = await self._llm_parse(nl_input)
            if llm_result:
                logger.info(f"CronParsed (LLM): '{nl_input}' -> '{llm_result}'")
                return llm_result
        except Exception as e:
            logger.warning(f"LLM cron parse failed: {e}, falling back to default")

        # 3. 降级：默认每天 00:00
        logger.warning(f"CronParsed (fallback): '{nl_input}' -> '0 0 * * *'")
        return "0 0 * * *"

    def _rule_parse(self, nl_input: str) -> str | None:
        """
        基于规则表匹配 Cron 表达式。

        Args:
            nl_input: 自然语言描述。

        Returns:
            匹配到的 Cron 表达式，或 None。
        """
        for pattern, cron_template, _desc in self._rule_map:
            match = re.search(pattern, nl_input)
            if match:
                groups = match.groups()
                cron = cron_template
                # 替换模板变量
                # 单分组「每天8点」：{hour}=groups[0]
                # 单分组「每天8点30分」：{hour}=groups[0], {min}=groups[1]
                # 双分组「每月5号8点」：正则分组顺序为 (day, hour)，模板用
                #   {dayhour_0}=groups[0](day)、{dayhour_1}=groups[1](hour)
                if "{hour}" in cron and groups:
                    cron = cron.replace("{hour}", groups[0])
                if "{dayhour_0}" in cron and groups:
                    cron = cron.replace("{dayhour_0}", groups[0])
                if "{dayhour_1}" in cron and len(groups) > 1:
                    cron = cron.replace("{dayhour_1}", groups[1])
                if "{day}" in cron and len(groups) > 1:
                    cron = cron.replace("{day}", groups[1] if len(groups) > 1 else groups[0])
                if "{min}" in cron and groups:
                    cron = cron.replace("{min}", (groups[-1] if groups else "0"))
                if "{n}" in cron and groups:
                    cron = cron.replace("{n}", groups[0])
                return cron

        return None

    async def _llm_parse(self, nl_input: str) -> str | None:
        """
        使用 LLM 解析 Cron 表达式。

        Args:
            nl_input: 自然语言描述。

        Returns:
            Cron 表达式，或 None。
        """
        from app.modules.ai.model_router import get_model_router

        prompt = f"""请将以下自然语言时间描述转换为标准的 5 段式 Cron 表达式（分 时 日 月 周）。

自然语言描述：{nl_input}

要求：
1. 只输出 Cron 表达式，不要包含其他文字
2. 格式：分 时 日 月 周（5 段，空格分隔）
3. 例如：「每天早上8点」→ 0 8 * * *
4. 例如：「每周一早上10点」→ 0 10 * * 1
5. 例如：「每月1号凌晨」→ 0 0 1 * *

Cron 表达式："""

        router = get_model_router()
        response = await router.call(
            use_case="report_analysis",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        # 提取 Cron 表达式
        if response:
            response = response.strip()
            # 查找 5 段式 Cron 模式
            cron_match = re.search(
                r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
                response,
            )
            if cron_match:
                return cron_match.group(0)

        return None

    def describe(self, cron_expression: str) -> str:
        """
        将 Cron 表达式反向描述为人类可读文本。

        Args:
            cron_expression: 5 段式 Cron 表达式。

        Returns:
            人类可读描述。
        """
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            return f"Cron: {cron_expression}"

        minute, hour, day, month, weekday = parts

        descriptions: list[str] = []

        # 分钟
        if minute == "0":
            pass  # 整点不特别说明
        elif minute == "*":
            descriptions.append("每分钟")
        elif minute.startswith("*/"):
            n = minute[2:]
            descriptions.append(f"每{n}分钟")

        # 小时
        if hour == "*":
            if not descriptions:
                descriptions.append("每小时")
        elif hour == "0":
            if not descriptions:
                descriptions.append("每天凌晨")
        elif hour == "8":
            if not descriptions:
                descriptions.append("每天早上")
        elif hour == "12":
            if not descriptions:
                descriptions.append("每天中午")
        elif hour == "20":
            if not descriptions:
                descriptions.append("每天晚上")
        else:
            if not descriptions:
                descriptions.append(f"每天{hour}点")

        # 日
        if day != "*" and day != "?":
            descriptions.append(f"{day}号")

        # 月
        if month != "*" and month != "?":
            month_names = ["", "1月", "2月", "3月", "4月", "5月", "6月",
                           "7月", "8月", "9月", "10月", "11月", "12月"]
            try:
                descriptions.append(month_names[int(month)])
            except (ValueError, IndexError):
                descriptions.append(f"{month}月")

        # 周
        weekday_map: dict[str, str] = {
            "0": "周日", "1": "周一", "2": "周二", "3": "周三",
            "4": "周四", "5": "周五", "6": "周六", "7": "周日",
        }
        if weekday != "*" and weekday != "?":
            if "," in weekday:
                days = [weekday_map.get(d, d) for d in weekday.split(",")]
                descriptions.append("、".join(days))
            elif "-" in weekday:
                parts_w = weekday.split("-")
                start = weekday_map.get(parts_w[0], parts_w[0])
                end = weekday_map.get(parts_w[1], parts_w[1])
                descriptions.append(f"{start}至{end}")
            else:
                descriptions.append(weekday_map.get(weekday, weekday))

        if not descriptions:
            descriptions.append("按 Cron 调度")

        # 时间
        time_str = ""
        if minute not in ("*", "0") and not minute.startswith("*/"):
            time_str = f"{hour}:{minute.zfill(2)}"
        elif hour not in ("*",):
            time_str = f"{hour}:00"

        result = "".join(descriptions)
        if time_str:
            result += f" {time_str}"

        return result