"""
AI 测试用例生成器

使用 LLM (通过 ModelRouter) 为每个 API 接口生成四类测试用例：
- 正向用例 (positive)：验证正常业务流程
- 反向用例 (negative)：验证异常输入和非法操作
- 边界值用例 (boundary)：验证边界条件
- 异常用例 (exception)：验证异常场景和错误处理

支持批量生成，使用 asyncio.Semaphore 限制并发。
"""

import asyncio
import json
import re
import uuid
from typing import Any

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 并发调用 AI 的最大并发数
_MAX_CONCURRENT_AI_CALLS = 5


class TestCaseGenerator:
    """
    AI 测试用例生成器。

    通过 ModelRouter 调用 LLM，为每个 API 接口生成标准化的测试用例。
    """

    def __init__(self) -> None:
        self.router = get_model_router()

    async def generate_api_cases(
        self, api_info: dict[str, Any], business_analysis: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        为单个 API 生成四类测试用例。

        生成正反向、边界值、异常四类用例，每类至少生成指定数量。

        Args:
            api_info: API 接口信息（含 path, http_method, params 等）。
            business_analysis: AI 分析结果（含 business_purpose, business_rules 等）。

        Returns:
            测试用例列表，每个用例包含 case_id, case_type, case_name,
            request, expected, priority, description。
        """
        prompt = self._build_prompt(api_info, business_analysis)

        try:
            response = await self.router.call(
                use_case="case_generation",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.error(
                f"AI case generation failed for {api_info.get('path', 'unknown')}: {e}"
            )
            return self._generate_fallback_cases(api_info)

        parsed = self._parse_json_response(response)
        if not parsed or "cases" not in parsed:
            logger.warning(
                f"AI response parsing failed for {api_info.get('path')}, "
                f"using fallback cases"
            )
            return self._generate_fallback_cases(api_info)

        cases: list[dict[str, Any]] = []
        for case_data in parsed.get("cases", []):
            case = self._normalize_case(case_data, api_info)
            cases.append(case)

        # 确保每类用例数量满足最低要求
        cases = self._ensure_minimum_cases(cases, api_info)

        logger.info(
            f"Generated {len(cases)} cases for API: "
            f"{api_info.get('http_method', '')} {api_info.get('path', '')}"
        )
        return cases

    async def generate_all(
        self, apis: list[dict[str, Any]], ai_analysis: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        """
        批量生成所有 API 的测试用例。

        并发生成（限制并发数为 5），汇总为三类：
        - api: 接口测试用例
        - performance: 性能测试用例（从正向用例中选取）
        - integration: 集成测试用例（跨 API 串联场景）

        Args:
            apis: API 接口列表。
            ai_analysis: AI 分析结果。

        Returns:
            包含 api / performance / integration 三类用例的字典。
        """
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_AI_CALLS)
        api_analyses = ai_analysis.get("api_analyses", [])

        # 构建 API path -> business analysis 映射
        analysis_map: dict[str, dict[str, Any]] = {}
        for analysis in api_analyses:
            key = f"{analysis.get('http_method', '')} {analysis.get('path', '')}"
            analysis_map[key] = analysis

        async def generate_with_semaphore(
            api: dict[str, Any],
        ) -> list[dict[str, Any]]:
            async with semaphore:
                key = f"{api.get('http_method', '')} {api.get('path', '')}"
                business_analysis = analysis_map.get(key, {})
                try:
                    return await self.generate_api_cases(api, business_analysis)
                except ModelNotConfiguredError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Case generation failed for {key}: {e}, using fallback"
                    )
                    return self._generate_fallback_cases(api)

        tasks = [generate_with_semaphore(api) for api in apis]
        results = await asyncio.gather(*tasks)

        # 汇总所有接口测试用例
        all_api_cases: list[dict[str, Any]] = []
        for api, cases in zip(apis, results):
            for case in cases:
                case["api_path"] = api.get("path", "")
                case["http_method"] = api.get("http_method", "")
                all_api_cases.append(case)

        # 生成性能测试用例（从正向用例中选取代表性用例）
        performance_cases = self._generate_performance_cases(all_api_cases)

        # 生成集成测试用例（跨 API 串联场景）
        integration_cases = self._generate_integration_cases(
            all_api_cases, ai_analysis
        )

        logger.info(
            f"Total cases generated: api={len(all_api_cases)}, "
            f"performance={len(performance_cases)}, "
            f"integration={len(integration_cases)}"
        )

        return {
            "api": all_api_cases,
            "performance": performance_cases,
            "integration": integration_cases,
        }

    def _build_prompt(
        self, api_info: dict[str, Any], business_analysis: dict[str, Any]
    ) -> str:
        """构建 AI 用例生成 prompt。"""
        params_str = json.dumps(api_info.get("params", []), ensure_ascii=False)
        business_purpose = business_analysis.get("business_purpose", "未知")
        business_rules = business_analysis.get("business_rules", [])
        risk_points = business_analysis.get("risk_points", [])

        return f"""为以下 API 接口生成测试用例。

接口信息:
- 路径: {api_info.get('path', 'N/A')}
- HTTP 方法: {api_info.get('http_method', 'N/A')}
- 参数: {params_str}
- 是否需要认证: {api_info.get('auth_required', False)}

业务分析:
- 业务目的: {business_purpose}
- 业务规则: {json.dumps(business_rules, ensure_ascii=False)}
- 风险点: {json.dumps(risk_points, ensure_ascii=False)}

请生成以下四类测试用例:
1. 正向用例 (positive): 至少 3 个，验证正常业务流程
2. 反向用例 (negative): 至少 5 个，验证异常输入和非法操作
3. 边界值用例 (boundary): 至少 4 个，验证边界条件
4. 异常用例 (exception): 至少 3 个，验证异常场景和错误处理

输出 JSON 格式:
{{
    "cases": [
        {{
            "case_type": "positive|negative|boundary|exception",
            "case_name": "用例名称",
            "description": "用例描述",
            "request": {{
                "method": "GET|POST|PUT|DELETE",
                "url": "/api/path",
                "headers": {{"Content-Type": "application/json"}},
                "body": {{}},
                "params": {{}}
            }},
            "expected": {{
                "status_code": 200,
                "assertions": [
                    {{"type": "status_code", "expected": 200}},
                    {{"type": "json_path", "path": "$.code", "expected": 0}}
                ]
            }}
        }}
    ]
}}

变量占位符使用 {{{{variable_name}}}} 格式，如 {{{{token}}}}、{{{{user_id}}}}。
请只输出 JSON，不要包含其他文字。"""

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """从 LLM 响应中解析 JSON（兼容 markdown code block）。"""
        if not response or not response.strip():
            return {}

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

        # 3. 提取 { ... } 块
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse JSON from AI response: {text[:200]}...")
        return {}

    def _normalize_case(
        self, case_data: dict[str, Any], api_info: dict[str, Any]
    ) -> dict[str, Any]:
        """将 AI 生成的用例数据标准化。"""
        case_type = case_data.get("case_type", "positive")
        return {
            "case_id": f"case_{uuid.uuid4().hex[:8]}",
            "case_type": case_type,
            "case_name": case_data.get("case_name", f"{case_type}_case"),
            "description": case_data.get("description", ""),
            "request": {
                "method": case_data.get("request", {}).get(
                    "method", api_info.get("http_method", "GET")
                ),
                "url": case_data.get("request", {}).get(
                    "url", api_info.get("path", "/")
                ),
                "headers": case_data.get("request", {}).get("headers", {}),
                "body": case_data.get("request", {}).get("body", {}),
                "params": case_data.get("request", {}).get("params", {}),
            },
            "expected": {
                "status_code": case_data.get("expected", {}).get("status_code", 200),
                "assertions": case_data.get("expected", {}).get("assertions", []),
            },
            "priority": self._infer_priority(case_type),
        }

    def _infer_priority(self, case_type: str) -> str:
        """根据用例类型推断优先级。"""
        priority_map = {
            "positive": "P0",
            "negative": "P1",
            "boundary": "P1",
            "exception": "P2",
        }
        return priority_map.get(case_type, "P2")

    def _ensure_minimum_cases(
        self, cases: list[dict[str, Any]], api_info: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """确保每类用例数量满足最低要求，不足则补充 fallback 用例。"""
        min_counts = {"positive": 3, "negative": 5, "boundary": 4, "exception": 3}
        type_counts: dict[str, int] = {}
        for case in cases:
            ct = case.get("case_type", "positive")
            type_counts[ct] = type_counts.get(ct, 0) + 1

        for case_type, min_count in min_counts.items():
            current = type_counts.get(case_type, 0)
            if current < min_count:
                needed = min_count - current
                fallback = self._generate_fallback_cases(api_info, case_type, needed)
                cases.extend(fallback)

        return cases

    def _generate_fallback_cases(
        self,
        api_info: dict[str, Any],
        case_type: str | None = None,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """生成 fallback 用例（AI 调用失败时使用）。"""
        path = api_info.get("path", "/")
        method = api_info.get("http_method", "GET")

        templates: dict[str, list[dict[str, Any]]] = {
            "positive": [
                {
                    "case_type": "positive",
                    "case_name": f"正常请求 - {method} {path}",
                    "description": "验证接口正常响应",
                    "request": {"method": method, "url": path, "headers": {}, "body": {}, "params": {}},
                    "expected": {"status_code": 200, "assertions": [{"type": "status_code", "expected": 200}]},
                }
            ],
            "negative": [
                {
                    "case_type": "negative",
                    "case_name": f"缺少必填参数 - {path}",
                    "description": "不传必填参数，验证错误处理",
                    "request": {"method": method, "url": path, "headers": {}, "body": {}, "params": {}},
                    "expected": {"status_code": 400, "assertions": [{"type": "status_code", "expected": 400}]},
                },
                {
                    "case_type": "negative",
                    "case_name": f"无效认证 - {path}",
                    "description": "使用无效 token 访问",
                    "request": {"method": method, "url": path, "headers": {"Authorization": "Bearer invalid"}, "body": {}, "params": {}},
                    "expected": {"status_code": 401, "assertions": [{"type": "status_code", "expected": 401}]},
                },
            ],
            "boundary": [
                {
                    "case_type": "boundary",
                    "case_name": f"空字符串参数 - {path}",
                    "description": "参数传空字符串",
                    "request": {"method": method, "url": path, "headers": {}, "body": {"param": ""}, "params": {}},
                    "expected": {"status_code": 200, "assertions": []},
                },
                {
                    "case_type": "boundary",
                    "case_name": f"超长字符串参数 - {path}",
                    "description": "参数传超长字符串",
                    "request": {"method": method, "url": path, "headers": {}, "body": {"param": "A" * 10000}, "params": {}},
                    "expected": {"status_code": 200, "assertions": []},
                },
            ],
            "exception": [
                {
                    "case_type": "exception",
                    "case_name": f"服务端异常 - {path}",
                    "description": "触发服务端异常场景",
                    "request": {"method": method, "url": path, "headers": {}, "body": {"trigger_error": True}, "params": {}},
                    "expected": {"status_code": 500, "assertions": [{"type": "status_code", "expected": 500}]},
                },
            ],
        }

        if case_type and count:
            templates_to_use = templates.get(case_type, [])
            result = []
            for i in range(count):
                template = templates_to_use[i % len(templates_to_use)].copy()
                template["case_name"] = f"{template['case_name']} (#{i + 1})"
                result.append(self._normalize_case(template, api_info))
            return result

        # 生成所有类型的 fallback 用例
        all_cases: list[dict[str, Any]] = []
        for ct, templates_list in templates.items():
            for template in templates_list:
                all_cases.append(self._normalize_case(template, api_info))
        return all_cases

    def _generate_performance_cases(
        self, all_api_cases: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """从正向用例中选取性能测试用例。"""
        positive_cases = [c for c in all_api_cases if c.get("case_type") == "positive"]
        # 最多取 5 个性能测试用例
        selected = positive_cases[:5]
        perf_cases: list[dict[str, Any]] = []
        for case in selected:
            perf_case = case.copy()
            perf_case["case_id"] = f"perf_{uuid.uuid4().hex[:8]}"
            perf_case["case_type"] = "performance"
            perf_case["case_name"] = f"[性能] {case.get('case_name', '')}"
            perf_case["description"] = f"性能压测: {case.get('request', {}).get('method', '')} {case.get('request', {}).get('url', '')}"
            perf_case["load_config"] = {
                "concurrent_users": [10, 50, 100, 200],
                "duration_seconds": 30,
            }
            perf_cases.append(perf_case)
        return perf_cases

    def _generate_integration_cases(
        self, all_api_cases: list[dict[str, Any]], ai_analysis: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """生成集成测试用例（跨 API 串联场景）。"""
        modules = ai_analysis.get("business_modules", [])
        data_flow = ai_analysis.get("data_flow", {})
        edges = data_flow.get("edges", []) if isinstance(data_flow, dict) else []

        integration_cases: list[dict[str, Any]] = []

        # 为每条依赖边生成一个集成测试场景
        for edge in edges[:5]:  # 最多 5 个集成测试场景
            source = edge.get("source", "")
            target = edge.get("target", "")

            # 找到 source 和 target 模块下的正向用例
            source_cases = [
                c for c in all_api_cases
                if c.get("case_type") == "positive" and source in c.get("api_path", "")
            ][:1]
            target_cases = [
                c for c in all_api_cases
                if c.get("case_type") == "positive" and target in c.get("api_path", "")
            ][:1]

            if source_cases and target_cases:
                steps = []
                for i, case in enumerate(source_cases + target_cases):
                    steps.append({
                        "step": i + 1,
                        "case_id": case.get("case_id", ""),
                        "method": case.get("request", {}).get("method", "GET"),
                        "url": case.get("request", {}).get("url", "/"),
                        "headers": case.get("request", {}).get("headers", {}),
                        "body": case.get("request", {}).get("body", {}),
                        "extract": {"token": "$.data.token", "id": "$.data.id"} if i == 0 else {},
                    })

                integration_cases.append({
                    "case_id": f"integ_{uuid.uuid4().hex[:8]}",
                    "case_type": "integration",
                    "case_name": f"[集成] {source} → {target}",
                    "description": f"验证 {source} 模块到 {target} 模块的业务链路",
                    "steps": steps,
                    "priority": "P1",
                })

        # 如果没有依赖边，生成一个基础集成测试
        if not integration_cases and all_api_cases:
            positive_cases = [c for c in all_api_cases if c.get("case_type") == "positive"][:2]
            if len(positive_cases) >= 2:
                steps = []
                for i, case in enumerate(positive_cases):
                    steps.append({
                        "step": i + 1,
                        "case_id": case.get("case_id", ""),
                        "method": case.get("request", {}).get("method", "GET"),
                        "url": case.get("request", {}).get("url", "/"),
                        "headers": case.get("request", {}).get("headers", {}),
                        "body": case.get("request", {}).get("body", {}),
                        "extract": {"token": "$.data.token"} if i == 0 else {},
                    })
                integration_cases.append({
                    "case_id": f"integ_{uuid.uuid4().hex[:8]}",
                    "case_type": "integration",
                    "case_name": "[集成] 基础业务链路",
                    "description": "验证多接口串联的基础业务流程",
                    "steps": steps,
                    "priority": "P1",
                })

        return integration_cases
