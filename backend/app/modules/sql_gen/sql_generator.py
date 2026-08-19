"""
AI SQL 生成器

使用 LLM (通过 ModelRouter) 为测试用例生成 SQL 验证脚本。
基于表结构上下文生成精准的 SQL 语句，AI 失败时降级为规则模板。
"""

import json
import logging
import re
from typing import Any, Dict, List

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router

logger = logging.getLogger(__name__)


class SqlGenerator:
    """
    AI SQL 生成器。

    通过 ModelRouter 调用 LLM 生成 SQL 语句，支持表结构上下文注入。
    AI 调用失败时降级为规则模板。
    """

    def __init__(self) -> None:
        self.router = get_model_router()

    # ==================== 公开接口 ====================

    async def generate(
        self,
        context: Dict[str, Any],
        schema_context: str = "",
        nl_input: str = "",
    ) -> Dict[str, Any]:
        """
        生成 SQL 验证脚本。

        Args:
            context: 上下文信息（含 api_info, case_info 等）
            schema_context: 表结构上下文（DDL 或描述）
            nl_input: 自然语言描述

        Returns:
            {"sql": str, "explanation": str, "tables": list}
        """
        prompt = self._build_prompt(context, schema_context, nl_input)

        try:
            response = await self.router.call(
                use_case="sql_generation",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            result = self._parse_response(response)
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI SQL generation failed: {e}, using fallback")
            result = self._fallback_sql(context, schema_context)

        return result

    # ==================== Prompt 构建 ====================

    def _build_prompt(
        self,
        context: Dict[str, Any],
        schema_context: str,
        nl_input: str,
    ) -> str:
        """构建 SQL 生成 prompt。"""
        api_info = json.dumps(context.get("api_info", {}), ensure_ascii=False, indent=2)
        case_info = json.dumps(context.get("case_info", {}), ensure_ascii=False, indent=2)

        schema_str = schema_context
        if not schema_str and context.get("tables"):
            schema_str = self._format_tables(context["tables"])

        return f"""请根据以下信息生成 SQL 验证脚本。

API 信息:
{api_info}

测试用例:
{case_info}

表结构:
{schema_str or "无表结构信息，请根据 API 和用例推断"}

自然语言描述: {nl_input or "根据 API 和用例生成合适的 SQL 验证脚本"}

要求：
1. 只使用 SELECT 语句（安全考虑）
2. 每条语句以分号结尾
3. 添加适当的注释
4. 输出 JSON 格式：
{{
    "sql": "SELECT ... FROM ... WHERE ...;",
    "explanation": "这段 SQL 的作用说明",
    "tables": ["table1", "table2"]
}}

请只输出 JSON，不要包含其他文字。"""

    @staticmethod
    def _format_tables(tables: List[Dict[str, Any]]) -> str:
        """格式化表结构列表为可读描述。"""
        lines: List[str] = []
        for table in tables:
            name = table.get("name", "unknown")
            columns = table.get("columns", [])
            col_strs = []
            for col in columns:
                col_name = col.get("name", "")
                col_type = col.get("type", "")
                col_strs.append(f"  {col_name} {col_type}")
            lines.append(f"表 {name}:")
            lines.extend(col_strs)
            lines.append("")
        return "\n".join(lines)

    # ==================== 响应解析 ====================

    @staticmethod
    def _parse_response(response: str) -> Dict[str, Any]:
        """从 LLM 响应中解析 JSON。"""
        if not response:
            return {"sql": "", "explanation": "", "tables": []}

        text = response.strip()

        # 1. 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. markdown code block
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3. SQL 直接输出
        if "SELECT" in text.upper():
            return {
                "sql": text.strip(),
                "explanation": "AI generated SQL",
                "tables": [],
            }

        return {"sql": "", "explanation": "Failed to parse", "tables": []}

    # ==================== 规则降级 ====================

    @staticmethod
    def _fallback_sql(
        context: Dict[str, Any],
        schema_context: str,
    ) -> Dict[str, Any]:
        """SQL 生成降级规则模板。"""
        api_info = context.get("api_info", {})
        path = api_info.get("path", "/api/unknown")
        table_hint = path.replace("/", "_").strip("_").replace("-", "_")

        return {
            "sql": f"-- SQL 验证脚本（降级生成）\n"
                   f"-- 目标 API: {api_info.get('http_method', 'GET')} {path}\n\n"
                   f"-- 查询最近创建的记录\n"
                   f"SELECT * FROM {table_hint} ORDER BY created_at DESC LIMIT 10;\n\n"
                   f"-- 统计记录数\n"
                   f"SELECT COUNT(*) AS total FROM {table_hint};",
            "explanation": f"查询 {table_hint} 表的最新记录和总数，用于验证 API 操作结果",
            "tables": [table_hint],
        }