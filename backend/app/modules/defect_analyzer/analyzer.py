"""
缺陷分析器 — AI 驱动的缺陷智能识别、分类与去重

遍历三类测试结果（API / 性能 / 集成），识别失败用例，
调用 LLM 分析根因、给出修复建议和复现步骤。
支持 AI 去重合并同根因缺陷。
"""

import asyncio
import json
import re
import uuid
from typing import Any

from app.modules.ai.model_router import ModelNotConfiguredError, ModelRouter, get_model_router
from app.modules.knowledge.retriever import retrieve_and_inject
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 并发调用 AI 的最大并发数
_MAX_CONCURRENT_AI_CALLS = 5

# 缺陷类别定义
DEFECT_CATEGORIES: dict[str, dict[str, Any]] = {
    "business_exception": {
        "description": "业务异常 — 接口返回了不符合业务规则的响应",
        "severity_base": "P2",
    },
    "program_bug": {
        "description": "程序缺陷 — 代码逻辑错误导致的功能异常",
        "severity_base": "P1",
    },
    "performance_issue": {
        "description": "性能问题 — 响应时间过长或吞吐量不达标",
        "severity_base": "P2",
    },
    "integration_failure": {
        "description": "集成失败 — 多接口串联场景中链路不通",
        "severity_base": "P1",
    },
    "security_vulnerability": {
        "description": "安全漏洞 — 认证缺失或敏感信息泄露",
        "severity_base": "P0",
    },
}

# 严重等级规则
SEVERITY_RULES: dict[str, dict[str, Any]] = {
    "P0": {"label": "阻断", "color": "#f56c6c", "description": "阻断级缺陷，系统不可用"},
    "P1": {"label": "严重", "color": "#e6a23c", "description": "严重缺陷，核心功能受损"},
    "P2": {"label": "一般", "color": "#409eff", "description": "一般缺陷，非核心功能异常"},
    "P3": {"label": "轻微", "color": "#909399", "description": "轻微缺陷，不影响主流程"},
}


class DefectAnalyzer:
    """
    缺陷分析器。

    遍历测试结果，识别失败用例，调用 AI 进行根因分析和分类。
    支持 AI 去重合并同根因缺陷。
    """

    def __init__(self, model_router: ModelRouter | None = None) -> None:
        self.router = model_router or get_model_router()

    async def analyze(
        self, test_results: dict[str, Any], project_id: str | None = None
    ) -> dict[str, Any]:
        """
        主方法 — 分析全部测试结果，输出缺陷列表和统计摘要。

        Args:
            test_results: 测试执行结果，包含 api_results / performance_results / integration_results。
            project_id: 项目 ID（知识库按项目过滤注入；None 走全局回退）。

        Returns:
            {
                "defects": [...],
                "summary": {total, by_severity, by_category},
            }
        """
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_AI_CALLS)
        all_defects: list[dict[str, Any]] = []

        # 1. 分析 API 测试失败
        api_results = test_results.get("api_results", [])
        if not api_results:
            api_data = test_results.get("api_tests", {})
            api_results = api_data.get("results", []) if isinstance(api_data, dict) else []

        api_failures = [r for r in api_results if not r.get("passed", False)]
        logger.info(f"Analyzing {len(api_failures)} API test failures")

        async def analyze_api(failure: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                return await self._analyze_api_failure(failure, project_id=project_id)

        api_tasks = [analyze_api(f) for f in api_failures]
        api_defects = await asyncio.gather(*api_tasks)
        all_defects.extend([d for d in api_defects if d is not None])

        # 2. 分析性能问题
        perf_results = test_results.get("performance_results", [])
        if not perf_results:
            perf_data = test_results.get("performance_tests", {})
            perf_results = perf_data.get("results", []) if isinstance(perf_data, dict) else []

        perf_issues = [r for r in perf_results if r.get("bottlenecks")]
        logger.info(f"Analyzing {len(perf_issues)} performance issues")

        async def analyze_perf(issue: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                return await self._analyze_performance(issue, project_id=project_id)

        perf_tasks = [analyze_perf(i) for i in perf_issues]
        perf_defects = await asyncio.gather(*perf_tasks)
        all_defects.extend([d for d in perf_defects if d is not None])

        # 3. 分析集成测试失败
        integ_results = test_results.get("integration_results", [])
        if not integ_results:
            integ_data = test_results.get("integration_tests", {})
            integ_results = integ_data.get("results", []) if isinstance(integ_data, dict) else []

        integ_failures = [r for r in integ_results if not r.get("passed", False)]
        logger.info(f"Analyzing {len(integ_failures)} integration test failures")

        async def analyze_integ(failure: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                return await self._analyze_integration_failure(failure, project_id=project_id)

        integ_tasks = [analyze_integ(f) for f in integ_failures]
        integ_defects = await asyncio.gather(*integ_tasks)
        all_defects.extend([d for d in integ_defects if d is not None])

        # 4. AI 去重合并
        if len(all_defects) > 1:
            all_defects = await self._deduplicate(all_defects)

        # 5. 构建统计摘要
        summary = {
            "total": len(all_defects),
            "by_severity": self._group_by_severity(all_defects),
            "by_category": self._group_by_category(all_defects),
        }

        logger.info(
            f"Defect analysis completed: {summary['total']} defects, "
            f"P0={summary['by_severity'].get('P0', 0)}, "
            f"P1={summary['by_severity'].get('P1', 0)}, "
            f"P2={summary['by_severity'].get('P2', 0)}, "
            f"P3={summary['by_severity'].get('P3', 0)}"
        )

        return {"defects": all_defects, "summary": summary}

    async def _analyze_api_failure(
        self, result: dict[str, Any], project_id: str | None = None
    ) -> dict[str, Any]:
        """
        AI 分析接口测试失败。

        Args:
            result: 失败的 API 测试结果。

        Returns:
            缺陷字典，包含 category / severity / root_cause / fix_suggestion / reproduction_steps。
        """
        case_name = result.get("case_name", "unknown")
        case_type = result.get("case_type", "unknown")
        error_message = result.get("error_message", "")
        actual_status = result.get("actual_status_code")
        actual_response = result.get("actual_response")
        request_data = result.get("request", {})
        expected = result.get("expected", {})

        # 能力12：注入历史相似缺陷（开关关闭/异常自动为空，不改主流程）
        error_summary = f"{case_name} {case_type} {actual_status} {error_message}"
        kb = ""
        try:
            kb = await retrieve_and_inject(None, error_summary, "defect", top_k=5, project_id=project_id)
        except Exception:
            kb = ""
        prompt = (kb + "\n\n" if kb else "") + f"""分析以下 API 测试失败，判断缺陷类型和根因。

测试用例信息:
- 用例名称: {case_name}
- 用例类型: {case_type}
- 请求方法: {request_data.get('method', 'N/A')}
- 请求路径: {request_data.get('url', 'N/A')}
- 请求体: {json.dumps(request_data.get('body', {}), ensure_ascii=False, default=str)[:500]}
- 预期状态码: {expected.get('status_code', 'N/A')}
- 实际状态码: {actual_status}
- 实际响应: {json.dumps(actual_response, ensure_ascii=False, default=str)[:500]}
- 错误信息: {error_message}

请分析并输出 JSON:
{{
    "category": "business_exception|program_bug|performance_issue|integration_failure|security_vulnerability",
    "severity": "P0|P1|P2|P3",
    "title": "缺陷标题（简短描述）",
    "root_cause": "根因分析（详细说明失败原因）",
    "fix_suggestion": "修复建议（具体可操作的修复方向）",
    "reproduction_steps": ["步骤1", "步骤2", "步骤3"]
}}

分类规则:
- business_exception: 接口返回了不符合业务规则的响应（如参数校验未通过但返回了数据）
- program_bug: 代码逻辑错误导致功能异常（如 500 错误、空指针等）
- performance_issue: 响应超时或性能不达标
- integration_failure: 多接口串联场景中链路不通
- security_vulnerability: 认证缺失或敏感信息泄露

严重等级:
- P0: 阻断级（系统不可用、核心功能完全无法使用）
- P1: 严重（核心功能受损但有规避方案）
- P2: 一般（非核心功能异常）
- P3: 轻微（不影响主流程）

请只输出 JSON。"""

        try:
            response = await self.router.call(
                use_case="defect_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            parsed = self._parse_json_response(response)
            if parsed and "category" in parsed:
                return self._normalize_defect(parsed, result, "api")
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI API failure analysis failed for {case_name}: {e}")

        # Fallback: 基于规则分类
        return self._fallback_api_defect(result)

    async def _analyze_performance(
        self, result: dict[str, Any], project_id: str | None = None
    ) -> dict[str, Any]:
        """
        AI 分析性能问题。

        Args:
            result: 性能测试结果（含 bottlenecks）。

        Returns:
            缺陷字典。
        """
        case_name = result.get("case_name", "unknown")
        bottlenecks = result.get("bottlenecks", [])
        avg_rt = result.get("avg_response_time", 0)
        p95 = result.get("p95", 0)
        p99 = result.get("p99", 0)
        tps = result.get("tps", 0)
        error_rate = result.get("error_rate", 0)
        total_requests = result.get("total_requests", 0)

        # 能力12：注入历史相似性能缺陷（开关关闭/异常自动为空，不改主流程）
        error_summary = f"{case_name} 性能 avg_rt={avg_rt}ms p95={p95}ms 错误率={error_rate}%"
        kb = ""
        try:
            kb = await retrieve_and_inject(None, error_summary, "defect", top_k=5, project_id=project_id)
        except Exception:
            kb = ""
        prompt = (kb + "\n\n" if kb else "") + f"""分析以下性能测试结果，判断性能瓶颈根因。

性能测试信息:
- 场景名称: {case_name}
- 平均响应时间: {avg_rt}ms
- P95 响应时间: {p95}ms
- P99 响应时间: {p99}ms
- TPS: {tps}
- 错误率: {error_rate}%
- 总请求数: {total_requests}
- 识别到的瓶颈: {json.dumps(bottlenecks, ensure_ascii=False)}

请分析并输出 JSON:
{{
    "category": "performance_issue",
    "severity": "P0|P1|P2|P3",
    "title": "性能缺陷标题",
    "root_cause": "性能瓶颈根因分析",
    "fix_suggestion": "性能优化建议",
    "reproduction_steps": ["压测步骤1", "压测步骤2"]
}}

严重等级参考:
- P0: 系统完全不可用（错误率>50%或平均响应时间>5s）
- P1: 严重性能问题（P95>2s 或错误率>10%）
- P2: 一般性能问题（P95>1s 或平均响应时间>500ms）
- P3: 轻微性能问题（有瓶颈但不影响主流程）

请只输出 JSON。"""

        try:
            response = await self.router.call(
                use_case="defect_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            parsed = self._parse_json_response(response)
            if parsed and "category" in parsed:
                return self._normalize_defect(parsed, result, "performance")
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI performance analysis failed for {case_name}: {e}")

        return self._fallback_performance_defect(result)

    async def _analyze_integration_failure(
        self, result: dict[str, Any], project_id: str | None = None
    ) -> dict[str, Any]:
        """
        AI 分析集成测试失败。

        Args:
            result: 失败的集成测试结果。

        Returns:
            缺陷字典。
        """
        case_name = result.get("case_name", "unknown")
        failure_step = result.get("failure_step")
        failure_reason = result.get("failure_reason", "")
        total_steps = result.get("total_steps", 0)
        executed_steps = result.get("executed_steps", 0)
        step_results = result.get("step_results", [])

        # 能力12：注入历史相似集成缺陷（开关关闭/异常自动为空，不改主流程）
        error_summary = f"{case_name} 第{failure_step}步 {failure_reason}"
        kb = ""
        try:
            kb = await retrieve_and_inject(None, error_summary, "defect", top_k=5, project_id=project_id)
        except Exception:
            kb = ""
        prompt = (kb + "\n\n" if kb else "") + f"""分析以下集成测试失败，判断缺陷根因。

集成测试信息:
- 场景名称: {case_name}
- 总步骤数: {total_steps}
- 已执行步骤数: {executed_steps}
- 失败步骤: 第 {failure_step} 步
- 失败原因: {failure_reason}
- 步骤详情: {json.dumps(step_results, ensure_ascii=False, default=str)[:800]}

请分析并输出 JSON:
{{
    "category": "integration_failure|program_bug|business_exception",
    "severity": "P0|P1|P2|P3",
    "title": "集成缺陷标题",
    "root_cause": "集成失败根因分析",
    "fix_suggestion": "修复建议",
    "reproduction_steps": ["步骤1", "步骤2"]
}}

请只输出 JSON。"""

        try:
            response = await self.router.call(
                use_case="defect_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            parsed = self._parse_json_response(response)
            if parsed and "category" in parsed:
                return self._normalize_defect(parsed, result, "integration")
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI integration analysis failed for {case_name}: {e}")

        return self._fallback_integration_defect(result)

    async def _deduplicate(self, defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        AI 去重合并 — 将同根因的缺陷合并为一个。

        Args:
            defects: 缺陷列表。

        Returns:
            去重后的缺陷列表。
        """
        if len(defects) <= 1:
            return defects

        # 构建精简的缺陷摘要用于 AI 判断
        defect_summaries = []
        for i, d in enumerate(defects):
            defect_summaries.append({
                "index": i,
                "title": d.get("title", ""),
                "category": d.get("category", ""),
                "severity": d.get("severity", ""),
                "root_cause": d.get("root_cause", "")[:200],
            })

        prompt = f"""以下是一个测试任务中识别到的缺陷列表。请判断哪些缺陷可以合并（同根因或高度相似）。

缺陷列表:
{json.dumps(defect_summaries, ensure_ascii=False, indent=2)}

请输出 JSON，表示合并方案:
{{
    "merge_groups": [
        {{"indices": [0, 2, 5], "reason": "同根因：数据库连接池耗尽"}},
        {{"indices": [1], "reason": "独立缺陷"}}
    ]
}}

规则:
- 只有根因相同或高度相似的缺陷才合并
- 合并后保留最高严重等级
- 每个缺陷必须出现在某个分组中
请只输出 JSON。"""

        try:
            response = await self.router.call(
                use_case="defect_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            parsed = self._parse_json_response(response)
            merge_groups = parsed.get("merge_groups", [])

            if not merge_groups:
                return defects

            merged: list[dict[str, Any]] = []
            for group in merge_groups:
                indices = group.get("indices", [])
                if not indices:
                    continue

                group_defects = [defects[i] for i in indices if i < len(defects)]
                if not group_defects:
                    continue

                if len(group_defects) == 1:
                    merged.append(group_defects[0])
                else:
                    # 合并：保留最高严重等级的缺陷作为主缺陷，其余追加到 related_cases
                    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
                    group_defects.sort(
                        key=lambda d: severity_order.get(d.get("severity", "P3"), 3)
                    )
                    primary = group_defects[0].copy()
                    related = []
                    for d in group_defects[1:]:
                        related.append({
                            "case_id": d.get("case_id", ""),
                            "case_name": d.get("case_name", ""),
                            "test_type": d.get("test_type", ""),
                        })
                    existing_related = primary.get("related_cases", [])
                    primary["related_cases"] = existing_related + related
                    primary["merge_reason"] = group.get("reason", "")
                    merged.append(primary)

            logger.info(f"Deduplicated: {len(defects)} → {len(merged)} defects")
            return merged

        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI deduplication failed: {e}, keeping original defects")
            return defects

    def _normalize_defect(
        self,
        parsed: dict[str, Any],
        result: dict[str, Any],
        test_type: str,
    ) -> dict[str, Any]:
        """将 AI 分析结果标准化为缺陷字典。"""
        category = parsed.get("category", "program_bug")
        severity = parsed.get("severity", "P2")

        # 验证 category 和 severity 合法性
        if category not in DEFECT_CATEGORIES:
            category = "program_bug"
        if severity not in SEVERITY_RULES:
            severity = "P2"

        return {
            "defect_id": f"defect_{uuid.uuid4().hex[:8]}",
            "case_id": result.get("case_id", ""),
            "case_name": result.get("case_name", ""),
            "test_type": test_type,
            "title": parsed.get("title", f"{test_type} defect: {result.get('case_name', '')}"),
            "category": category,
            "severity": severity,
            "root_cause": parsed.get("root_cause", ""),
            "fix_suggestion": parsed.get("fix_suggestion", ""),
            "reproduction_steps": parsed.get("reproduction_steps", []),
            "related_cases": [],
            "raw_result": {
                "actual_status_code": result.get("actual_status_code"),
                "error_message": result.get("error_message", ""),
                "response_time_ms": result.get("response_time_ms"),
            },
        }

    def _fallback_api_defect(self, result: dict[str, Any]) -> dict[str, Any]:
        """API 失败的规则兜底分类。"""
        status = result.get("actual_status_code")
        error_msg = result.get("error_message", "")

        if status is None and "timeout" in error_msg.lower():
            category = "performance_issue"
            severity = "P2"
        elif status is not None and status >= 500:
            category = "program_bug"
            severity = "P1"
        elif status is not None and 400 <= status < 500:
            if status == 401 or status == 403:
                category = "security_vulnerability"
                severity = "P1"
            else:
                category = "business_exception"
                severity = "P3"
        else:
            category = "program_bug"
            severity = "P2"

        return {
            "defect_id": f"defect_{uuid.uuid4().hex[:8]}",
            "case_id": result.get("case_id", ""),
            "case_name": result.get("case_name", ""),
            "test_type": "api",
            "title": f"[规则分类] {result.get('case_name', 'API failure')}",
            "category": category,
            "severity": severity,
            "root_cause": f"HTTP {status}: {error_msg}",
            "fix_suggestion": "建议检查接口逻辑和异常处理",
            "reproduction_steps": [
                f"发送请求: {result.get('request', {}).get('method', 'GET')} {result.get('request', {}).get('url', '/')}",
                f"预期状态码: {result.get('expected', {}).get('status_code', 'N/A')}",
                f"实际状态码: {status}",
            ],
            "related_cases": [],
            "raw_result": {
                "actual_status_code": status,
                "error_message": error_msg,
                "response_time_ms": result.get("response_time_ms"),
            },
        }

    def _fallback_performance_defect(self, result: dict[str, Any]) -> dict[str, Any]:
        """性能问题的规则兜底分类。"""
        avg_rt = result.get("avg_response_time", 0)
        p95 = result.get("p95", 0)
        error_rate = result.get("error_rate", 0)

        if error_rate > 50 or avg_rt > 5000:
            severity = "P0"
        elif p95 > 2000 or error_rate > 10:
            severity = "P1"
        elif p95 > 1000 or avg_rt > 500:
            severity = "P2"
        else:
            severity = "P3"

        bottlenecks = result.get("bottlenecks", [])

        return {
            "defect_id": f"defect_{uuid.uuid4().hex[:8]}",
            "case_id": result.get("case_id", ""),
            "case_name": result.get("case_name", ""),
            "test_type": "performance",
            "title": f"[性能] {result.get('case_name', 'performance issue')}",
            "category": "performance_issue",
            "severity": severity,
            "root_cause": "; ".join(bottlenecks) if bottlenecks else "性能指标未达标",
            "fix_suggestion": "建议优化数据库查询、缓存策略或接口逻辑",
            "reproduction_steps": [
                f"执行阶梯压测: {result.get('case_name', '')}",
                f"观察平均响应时间: {avg_rt}ms, P95: {p95}ms",
                f"瓶颈: {bottlenecks}",
            ],
            "related_cases": [],
            "raw_result": {
                "avg_response_time": avg_rt,
                "p95": p95,
                "p99": result.get("p99"),
                "tps": result.get("tps"),
                "error_rate": error_rate,
            },
        }

    def _fallback_integration_defect(self, result: dict[str, Any]) -> dict[str, Any]:
        """集成失败的规则兜底分类。"""
        failure_step = result.get("failure_step")
        failure_reason = result.get("failure_reason", "")

        return {
            "defect_id": f"defect_{uuid.uuid4().hex[:8]}",
            "case_id": result.get("case_id", ""),
            "case_name": result.get("case_name", ""),
            "test_type": "integration",
            "title": f"[集成] {result.get('case_name', 'integration failure')}",
            "category": "integration_failure",
            "severity": "P1",
            "root_cause": f"第 {failure_step} 步失败: {failure_reason}",
            "fix_suggestion": "建议检查接口间数据传递和依赖关系",
            "reproduction_steps": [
                f"执行集成场景: {result.get('case_name', '')}",
                f"第 {failure_step} 步失败",
                f"失败原因: {failure_reason}",
            ],
            "related_cases": [],
            "raw_result": {
                "failure_step": failure_step,
                "failure_reason": failure_reason,
                "total_steps": result.get("total_steps"),
                "executed_steps": result.get("executed_steps"),
            },
        }

    def _group_by_severity(self, defects: list[dict[str, Any]]) -> dict[str, int]:
        """按严重等级分组统计。"""
        counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for d in defects:
            sev = d.get("severity", "P3")
            if sev in counts:
                counts[sev] += 1
        return counts

    def _group_by_category(self, defects: list[dict[str, Any]]) -> dict[str, int]:
        """按缺陷类别分组统计。"""
        counts: dict[str, int] = {}
        for d in defects:
            cat = d.get("category", "program_bug")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

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
