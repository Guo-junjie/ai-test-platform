"""
覆盖率优化器

分析已有测试用例的覆盖率，识别未覆盖的代码路径和用例类型，
调用 AI 生成补充用例以提升覆盖率。
"""

import json
import re
from typing import Any

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CoverageOptimizer:
    """
    覆盖率优化器。

    分析已有用例覆盖情况，为缺失的路径和用例类型生成补充用例。
    """

    # 必须覆盖的用例类型
    REQUIRED_CASE_TYPES = {"positive", "negative", "boundary", "exception"}

    def __init__(self) -> None:
        self.router = get_model_router()

    def optimize(
        self,
        cases: list[dict[str, Any]],
        code_paths: list[str],
    ) -> list[dict[str, Any]]:
        """
        分析覆盖率，补充未覆盖路径的用例。

        Args:
            cases: 已有测试用例列表。
            code_paths: 代码中所有 API 路径列表。

        Returns:
            补充的测试用例列表（原有用例不修改）。
        """
        if not code_paths:
            logger.info("No code paths provided, skipping coverage optimization")
            return []

        # 1. 分析已覆盖的路径
        covered_paths: set[str] = set()
        for case in cases:
            url = case.get("request", {}).get("url", "") if "request" in case else case.get("api_path", "")
            if url:
                covered_paths.add(url)

        # 2. 找出未覆盖的路径
        uncovered_paths = [p for p in code_paths if p not in covered_paths]

        if not uncovered_paths:
            logger.info("All paths are covered, no additional cases needed")
            return []

        logger.info(
            f"Coverage analysis: {len(covered_paths)}/{len(code_paths)} paths covered, "
            f"{len(uncovered_paths)} uncovered"
        )

        # 3. 分析已有用例的类型覆盖情况
        existing_types: set[str] = set()
        for case in cases:
            existing_types.add(case.get("case_type", ""))

        missing_types = self.REQUIRED_CASE_TYPES - existing_types

        # 4. 为未覆盖的路径生成补充用例
        supplementary_cases: list[dict[str, Any]] = []

        # 限制补充路径数量，避免过多 AI 调用
        for path in uncovered_paths[:5]:
            try:
                new_cases = self._generate_supplementary_cases(
                    path, missing_types
                )
                supplementary_cases.extend(new_cases)
            except Exception as e:
                logger.warning(
                    f"Failed to generate supplementary cases for {path}: {e}"
                )
                # 生成 fallback 用例
                supplementary_cases.extend(
                    self._generate_fallback_for_path(path)
                )

        logger.info(
            f"Coverage optimization: generated {len(supplementary_cases)} "
            f"supplementary cases for {len(uncovered_paths[:5])} uncovered paths"
        )

        return supplementary_cases

    def _generate_supplementary_cases(
        self, path: str, missing_types: set[str]
    ) -> list[dict[str, Any]]:
        """为未覆盖路径调用 AI 生成补充用例。"""
        import asyncio

        types_to_generate = missing_types if missing_types else {"positive"}
        types_str = ", ".join(types_to_generate)

        prompt = f"""为以下未覆盖的 API 路径生成补充测试用例。

API 路径: {path}
需要生成的用例类型: {types_str}

输出 JSON 格式:
{{
    "cases": [
        {{
            "case_type": "positive|negative|boundary|exception",
            "case_name": "用例名称",
            "description": "用例描述",
            "request": {{
                "method": "GET|POST",
                "url": "{path}",
                "headers": {{}},
                "body": {{}},
                "params": {{}}
            }},
            "expected": {{
                "status_code": 200,
                "assertions": [{{"type": "status_code", "expected": 200}}]
            }}
        }}
    ]
}}
请只输出 JSON。"""

        async def _call_ai() -> list[dict[str, Any]]:
            try:
                response = await self.router.call(
                    use_case="case_generation",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                parsed = self._parse_json_response(response)
                cases_data = parsed.get("cases", [])

                result: list[dict[str, Any]] = []
                for case_data in cases_data:
                    import uuid
                    case_type = case_data.get("case_type", "positive")
                    result.append({
                        "case_id": f"case_{uuid.uuid4().hex[:8]}",
                        "case_type": case_type,
                        "case_name": case_data.get("case_name", f"supplementary_{case_type}"),
                        "description": case_data.get("description", ""),
                        "request": case_data.get("request", {"method": "GET", "url": path}),
                        "expected": case_data.get("expected", {"status_code": 200, "assertions": []}),
                        "priority": "P1" if case_type in ("negative", "boundary") else "P2",
                        "api_path": path,
                        "http_method": case_data.get("request", {}).get("method", "GET"),
                    })
                return result
            except ModelNotConfiguredError:
                raise
            except Exception as e:
                logger.warning(f"AI supplementary case generation failed: {e}")
                return self._generate_fallback_for_path(path)

        return asyncio.run(_call_ai())

    def _generate_fallback_for_path(self, path: str) -> list[dict[str, Any]]:
        """为路径生成 fallback 补充用例。"""
        import uuid

        return [
            {
                "case_id": f"case_{uuid.uuid4().hex[:8]}",
                "case_type": "positive",
                "case_name": f"补充正向用例 - {path}",
                "description": f"覆盖率补充: {path}",
                "request": {"method": "GET", "url": path, "headers": {}, "body": {}, "params": {}},
                "expected": {"status_code": 200, "assertions": [{"type": "status_code", "expected": 200}]},
                "priority": "P0",
                "api_path": path,
                "http_method": "GET",
            }
        ]

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """从 LLM 响应中解析 JSON。"""
        if not response or not response.strip():
            return {}

        text = response.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return {}
