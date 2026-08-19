"""
能力9：报告 AI 分析器

对测试结果/报告进行 AI 分析：
- analyze_failure: 单用例失败深度分析（根因 + 修复建议）
- analyze_summary: 报告摘要分析
- analyze_compare: 两次执行结果对比分析

分析结果落 ai_analysis_results 表。
"""

import json
import uuid
import logging
from typing import Any

from app.modules.ai.model_router import ModelNotConfiguredError, get_model_router

logger = logging.getLogger(__name__)


class ReportAnalyzer:
    """
    AI 报告分析器。

    通过 ModelRouter 调用 LLM 对测试结果进行深度分析。
    支持三种分析类型：失败分析、报告摘要、对比分析。
    """

    def __init__(self) -> None:
        self.router = get_model_router()

    # ==================== 公开接口 ====================

    async def analyze_failure(
        self,
        result_id: str,
        project_id: str,
        db_session: Any = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        单用例失败深度分析。

        读取测试结果，调用 LLM 分析失败原因并给出修复建议。

        Args:
            result_id: 测试结果 ID。
            project_id: 项目 ID。
            db_session: 数据库会话。
            user_id: 操作用户 ID。

        Returns:
            分析结果字典。
        """
        # 读取测试结果
        from sqlalchemy import select
        from app.models.database import TestResult, TestCase

        rid = uuid.UUID(result_id)
        result = (
            await db_session.execute(
                select(TestResult).where(TestResult.id == rid)
            )
        ).scalar_one_or_none()
        if result is None:
            raise ValueError(f"Test result not found: {result_id}")

        # 读取关联的测试用例
        test_case = (
            await db_session.execute(
                select(TestCase).where(TestCase.id == result.test_case_id)
            )
        ).scalar_one_or_none()

        # 组装 prompt
        case_info = {
            "case_name": test_case.case_name if test_case else "unknown",
            "case_type": test_case.case_type if test_case else "unknown",
            "request_data": test_case.request_data if test_case else {},
            "expected_result": test_case.expected_result if test_case else {},
        }
        result_info = {
            "is_passed": result.is_passed,
            "status_code": result.status_code,
            "response_body": result.response_body,
            "response_time_ms": result.response_time_ms,
            "error_message": result.error_message,
            "error_trace": result.error_trace,
        }

        prompt = self._build_failure_prompt(case_info, result_info)

        # 调用 LLM
        try:
            model_response = await self.router.call(
                use_case="report_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            analysis = self._parse_json_response(model_response)
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI failure analysis failed: {e}, using fallback")
            analysis = self._fallback_failure_analysis(result_info)

        # 落库
        await self._save_analysis(
            project_id=project_id,
            analysis_type="failure",
            test_result_id=result_id,
            test_run_id=str(result.test_run_id) if result.test_run_id else None,
            analysis_json=analysis,
            model_used=None,
            db_session=db_session,
            user_id=user_id,
        )

        return analysis

    async def analyze_summary(
        self,
        report_id: str,
        project_id: str,
        db_session: Any = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        报告摘要 AI 分析。

        读取测试报告，调用 LLM 生成摘要和质量评估。

        Args:
            report_id: 报告 ID。
            project_id: 项目 ID。
            db_session: 数据库会话。
            user_id: 操作用户 ID。

        Returns:
            分析结果字典。
        """
        from sqlalchemy import select
        from app.models.database import TestReport

        rid = uuid.UUID(report_id)
        report = (
            await db_session.execute(
                select(TestReport).where(TestReport.id == rid)
            )
        ).scalar_one_or_none()
        if report is None:
            raise ValueError(f"Report not found: {report_id}")

        report_data = report.report_data or {}

        prompt = self._build_summary_prompt(report_data)

        try:
            model_response = await self.router.call(
                use_case="report_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            analysis = self._parse_json_response(model_response)
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI summary analysis failed: {e}, using fallback")
            analysis = self._fallback_summary_analysis(report_data)

        await self._save_analysis(
            project_id=project_id,
            analysis_type="report_summary",
            test_run_id=str(report.test_run_id) if report.test_run_id else None,
            analysis_json=analysis,
            model_used=None,
            db_session=db_session,
            user_id=user_id,
        )

        return analysis

    async def analyze_compare(
        self,
        result_id: str,
        compare_run_id: str,
        project_id: str,
        db_session: Any = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        两次执行结果对比分析。

        读取当前结果和对比 run 的对应结果，调用 LLM 分析差异。

        Args:
            result_id: 当前测试结果 ID。
            compare_run_id: 对比的测试运行 ID。
            project_id: 项目 ID。
            db_session: 数据库会话。
            user_id: 操作用户 ID。

        Returns:
            分析结果字典。
        """
        from sqlalchemy import select
        from app.models.database import TestResult, TestCase

        rid = uuid.UUID(result_id)
        current_result = (
            await db_session.execute(
                select(TestResult).where(TestResult.id == rid)
            )
        ).scalar_one_or_none()
        if current_result is None:
            raise ValueError(f"Test result not found: {result_id}")

        # 查找对比 run 中的对应结果（相同 test_case_id）
        compare_rid = uuid.UUID(compare_run_id)
        compare_result = (
            await db_session.execute(
                select(TestResult).where(
                    TestResult.test_run_id == compare_rid,
                    TestResult.test_case_id == current_result.test_case_id,
                )
            )
        ).scalar_one_or_none()

        current_info = {
            "is_passed": current_result.is_passed,
            "status_code": current_result.status_code,
            "response_body": current_result.response_body,
            "response_time_ms": current_result.response_time_ms,
            "error_message": current_result.error_message,
        }
        compare_info = (
            {
                "is_passed": compare_result.is_passed,
                "status_code": compare_result.status_code,
                "response_body": compare_result.response_body,
                "response_time_ms": compare_result.response_time_ms,
                "error_message": compare_result.error_message,
            }
            if compare_result
            else None
        )

        prompt = self._build_compare_prompt(current_info, compare_info)

        try:
            model_response = await self.router.call(
                use_case="report_analysis",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            analysis = self._parse_json_response(model_response)
        except ModelNotConfiguredError:
            raise
        except Exception as e:
            logger.warning(f"AI compare analysis failed: {e}, using fallback")
            analysis = self._fallback_compare_analysis(current_info, compare_info)

        await self._save_analysis(
            project_id=project_id,
            analysis_type="compare",
            test_result_id=result_id,
            test_run_id=str(current_result.test_run_id),
            analysis_json=analysis,
            model_used=None,
            db_session=db_session,
            user_id=user_id,
        )

        return analysis

    # ==================== Prompt 构建 ====================

    @staticmethod
    def _build_failure_prompt(case_info: dict[str, Any], result_info: dict[str, Any]) -> str:
        """构建失败分析 prompt。"""
        return f"""请对以下测试失败进行深度分析，找出根因并给出修复建议。

测试用例信息：
{json.dumps(case_info, ensure_ascii=False, indent=2)}

测试结果：
{json.dumps(result_info, ensure_ascii=False, indent=2)}

请以 JSON 格式输出分析结果：
{{
    "root_cause": "根因分析（用中文描述失败的根本原因）",
    "category": "失败类别：business_logic / data_issue / environment / timeout / assertion / unknown",
    "severity": "严重程度：P0 / P1 / P2 / P3",
    "fix_suggestion": "具体的修复建议（用中文描述）",
    "confidence": 0.0-1.0
}}

只输出 JSON，不要包含其他文字。"""

    @staticmethod
    def _build_summary_prompt(report_data: dict[str, Any]) -> str:
        """构建报告摘要 prompt。"""
        # 提取关键统计信息
        summary = report_data.get("summary", {})
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        pass_rate = (passed / total * 100) if total > 0 else 0

        return f"""请对以下测试报告进行 AI 分析，生成摘要和质量评估。

报告统计：
- 总用例数：{total}
- 通过数：{passed}
- 失败数：{failed}
- 通过率：{pass_rate:.1f}%
- 质量评分：{report_data.get('quality_score', 'N/A')}

报告详情：
{json.dumps(report_data, ensure_ascii=False, indent=2)[:4000]}

请以 JSON 格式输出分析结果：
{{
    "summary": "报告摘要（2-3句中文字描述）",
    "quality_assessment": "质量评估：excellent / good / fair / poor",
    "key_findings": ["关键发现1", "关键发现2", ...],
    "recommendations": ["改进建议1", "改进建议2", ...],
    "risk_level": "风险等级：low / medium / high / critical"
}}

只输出 JSON，不要包含其他文字。"""

    @staticmethod
    def _build_compare_prompt(
        current_info: dict[str, Any],
        compare_info: dict[str, Any] | None,
    ) -> str:
        """构建对比分析 prompt。"""
        return f"""请对比以下两次测试执行的结果，分析差异。

当前执行结果：
{json.dumps(current_info, ensure_ascii=False, indent=2)}

对比执行结果：
{json.dumps(compare_info, ensure_ascii=False, indent=2) if compare_info else "无对比数据（该用例在对比执行中不存在）"}

请以 JSON 格式输出分析结果：
{{
    "comparison": "对比结论（用中文描述两次执行的差异）",
    "regression": true/false（是否出现回归）,
    "improvement": true/false（是否有改进）,
    "response_time_diff": "响应时间变化描述",
    "status_diff": "状态码/通过状态变化描述",
    "details": "详细差异说明"
}}

只输出 JSON，不要包含其他文字。"""

    # ==================== 响应解析 ====================

    @staticmethod
    def _parse_json_response(response: str) -> dict[str, Any]:
        """从 LLM 响应中解析 JSON。"""
        if not response:
            return {}

        text = response.strip()

        # 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 提取 markdown code block
        import re
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        return {"raw_response": text}

    # ==================== 降级分析 ====================

    @staticmethod
    def _fallback_failure_analysis(result_info: dict[str, Any]) -> dict[str, Any]:
        """失败分析降级规则。"""
        error_msg = result_info.get("error_message", "")
        status_code = result_info.get("status_code", 0)

        category = "unknown"
        if status_code and status_code >= 500:
            category = "environment"
        elif status_code == 404:
            category = "data_issue"
        elif status_code == 401 or status_code == 403:
            category = "environment"
        elif status_code and status_code >= 400:
            category = "business_logic"
        elif "timeout" in str(error_msg).lower():
            category = "timeout"

        return {
            "root_cause": f"规则分析：HTTP {status_code} — {error_msg or '未知错误'}",
            "category": category,
            "severity": "P2",
            "fix_suggestion": "请检查 API 服务和数据状态，确认环境配置正确",
            "confidence": 0.5,
        }

    @staticmethod
    def _fallback_summary_analysis(report_data: dict[str, Any]) -> dict[str, Any]:
        """报告摘要降级规则。"""
        summary = report_data.get("summary", {})
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        pass_rate = (passed / total * 100) if total > 0 else 0

        if pass_rate >= 95:
            quality = "excellent"
            risk = "low"
        elif pass_rate >= 80:
            quality = "good"
            risk = "medium"
        elif pass_rate >= 60:
            quality = "fair"
            risk = "high"
        else:
            quality = "poor"
            risk = "critical"

        return {
            "summary": f"本次测试共 {total} 个用例，通过 {passed} 个，失败 {failed} 个，通过率 {pass_rate:.1f}%",
            "quality_assessment": quality,
            "key_findings": [f"通过率 {pass_rate:.1f}%", f"失败用例数 {failed}"],
            "recommendations": ["建议关注失败用例并排查根因"] if failed > 0 else [],
            "risk_level": risk,
        }

    @staticmethod
    def _fallback_compare_analysis(
        current_info: dict[str, Any],
        compare_info: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """对比分析降级规则。"""
        if compare_info is None:
            return {
                "comparison": "对比执行中无对应结果，无法进行自动对比",
                "regression": False,
                "improvement": False,
                "response_time_diff": "N/A",
                "status_diff": "N/A",
                "details": "对比数据缺失",
            }

        current_rt = current_info.get("response_time_ms", 0)
        compare_rt = compare_info.get("response_time_ms", 0)
        rt_diff = current_rt - compare_rt if current_rt and compare_rt else 0

        current_passed = current_info.get("is_passed", False)
        compare_passed = compare_info.get("is_passed", False)

        regression = compare_passed and not current_passed
        improvement = not compare_passed and current_passed

        return {
            "comparison": (
                f"响应时间：当前 {current_rt}ms vs 对比 {compare_rt}ms（差异 {rt_diff:+d}ms）"
            ),
            "regression": regression,
            "improvement": improvement,
            "response_time_diff": f"{rt_diff:+d}ms",
            "status_diff": (
                f"当前：{'通过' if current_passed else '失败'}，"
                f"对比：{'通过' if compare_passed else '失败'}"
            ),
            "details": "基于规则引擎的对比分析（AI 分析不可用时的降级结果）",
        }

    # ==================== 落库 ====================

    async def _save_analysis(
        self,
        project_id: str,
        analysis_type: str,
        analysis_json: dict[str, Any],
        test_result_id: str | None = None,
        test_run_id: str | None = None,
        model_used: str | None = None,
        db_session: Any = None,
        user_id: str | None = None,
    ) -> None:
        """将分析结果写入 ai_analysis_results 表。"""
        if db_session is None:
            return

        try:
            from app.models.database import AIAnalysisResult, AnalysisType

            atype = AnalysisType(analysis_type)

            record = AIAnalysisResult(
                id=uuid.uuid4(),
                project_id=uuid.UUID(project_id),
                analysis_type=atype,
                test_run_id=uuid.UUID(test_run_id) if test_run_id else None,
                test_result_id=uuid.UUID(test_result_id) if test_result_id else None,
                input_summary={},
                analysis_json=analysis_json,
                model_used=model_used,
                created_by=uuid.UUID(user_id) if user_id else None,
            )
            db_session.add(record)
            await db_session.flush()
        except Exception as e:
            logger.warning(f"Failed to save AI analysis result: {e}")