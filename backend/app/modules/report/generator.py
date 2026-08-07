"""
报告生成器 — 生成在线 HTML 报告和 PDF 报告

使用 Jinja2 渲染模板，weasyprint 转换 PDF，
上传到 MinIO 对象存储，保存记录到 TestReport 表。
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.models.database import TestReport, TestRun, TestStatus
from app.modules.report.charts import ChartBuilder
from app.utils.logger import get_logger
from app.utils.database import AsyncSessionLocal
from sqlalchemy import select

logger = get_logger(__name__)

# 模板目录
_TEMPLATES_DIR = Path(__file__).parent / "templates"
# 报告输出目录
_REPORT_OUTPUT_DIR = Path(settings.REPORT_DIR) if hasattr(settings, "REPORT_DIR") else Path("/app/data/reports")


class ReportGenerator:
    """
    报告生成器。

    生成在线交互式 HTML 报告和 PDF 报告，
    上传到 MinIO 并保存到数据库。
    """

    def __init__(self) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # 确保输出目录存在
        _REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        test_run_id: str,
        test_results: dict[str, Any],
        defects: dict[str, Any],
    ) -> dict[str, Any]:
        """
        主方法 — 生成完整测试报告。

        Args:
            test_run_id: 测试任务 ID。
            test_results: 测试执行结果。
            defects: 缺陷分析结果。

        Returns:
            {
                "report_data": dict,
                "html_path": str,
                "pdf_path": str | None,
                "online_url": str,
                "quality_score": int,
                "overall_pass": bool,
            }
        """
        logger.info(f"Generating report for test_run: {test_run_id}")

        # 1. 构建摘要
        summary = self._build_summary(test_results, defects)

        # 2. 构建报告数据
        report_data: dict[str, Any] = {
            "test_run_id": test_run_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "summary": summary,
            "test_results": test_results,
            "defects": defects,
        }

        # 3. 构建图表数据
        charts = ChartBuilder.build_all_charts(report_data)
        report_data["charts"] = charts

        # 4. 渲染 HTML
        html_content = self._render_html(report_data)
        html_filename = f"report_{test_run_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        html_local_path = str(_REPORT_OUTPUT_DIR / html_filename)
        with open(html_local_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"HTML report saved: {html_local_path}")

        # 5. 渲染 PDF (尝试 weasyprint)
        pdf_local_path: str | None = None
        try:
            pdf_content = self._render_pdf(report_data)
            if pdf_content:
                pdf_filename = html_filename.replace(".html", ".pdf")
                pdf_local_path = str(_REPORT_OUTPUT_DIR / pdf_filename)
                with open(pdf_local_path, "wb") as f:
                    f.write(pdf_content)
                logger.info(f"PDF report saved: {pdf_local_path}")
        except Exception as e:
            logger.warning(f"PDF generation failed (weasyprint may not be installed): {e}")

        # 6. 上传到 MinIO
        html_object_name = f"reports/{test_run_id}/{html_filename}"
        pdf_object_name = f"reports/{test_run_id}/{html_filename.replace('.html', '.pdf')}" if pdf_local_path else None

        online_url = ""
        try:
            from app.utils.storage import upload_file, get_presigned_url

            upload_file(html_local_path, html_object_name)
            if pdf_local_path:
                upload_file(pdf_local_path, pdf_object_name)
            online_url = get_presigned_url(html_object_name, expires_hours=7 * 24)
            logger.info(f"Report uploaded to MinIO: {html_object_name}")
        except Exception as e:
            logger.warning(f"MinIO upload failed: {e}, report saved locally only")

        # 7. 保存到数据库
        await self._save_to_db(
            test_run_id=test_run_id,
            report_data=report_data,
            html_path=html_object_name,
            pdf_path=pdf_object_name,
            quality_score=summary["quality_score"],
            overall_pass=summary["overall_pass"],
        )

        return {
            "report_data": report_data,
            "html_path": html_object_name,
            "pdf_path": pdf_object_name,
            "online_url": online_url,
            "quality_score": summary["quality_score"],
            "overall_pass": summary["overall_pass"],
        }

    def _build_summary(
        self, test_results: dict[str, Any], defects: dict[str, Any]
    ) -> dict[str, Any]:
        """
        构建报告摘要数据。

        Args:
            test_results: 测试执行结果。
            defects: 缺陷分析结果。

        Returns:
            摘要字典。
        """
        # API 测试摘要
        api_data = test_results.get("api_tests", test_results.get("api_results", []))
        if isinstance(api_data, dict):
            api_summary = {
                "total": api_data.get("total", len(api_data.get("results", []))),
                "passed": api_data.get("passed", 0),
                "failed": api_data.get("failed", 0),
            }
        else:
            total = len(api_data)
            passed = sum(1 for r in api_data if r.get("passed"))
            api_summary = {"total": total, "passed": passed, "failed": total - passed}

        # 性能测试摘要
        perf_data = test_results.get("performance_tests", test_results.get("performance_results", []))
        if isinstance(perf_data, dict):
            perf_summary = {
                "total": perf_data.get("total", len(perf_data.get("results", []))),
                "passed": perf_data.get("passed", 0),
                "failed": perf_data.get("failed", 0),
            }
        else:
            total = len(perf_data)
            passed = sum(1 for r in perf_data if not r.get("bottlenecks"))
            perf_summary = {"total": total, "passed": passed, "failed": total - passed}

        # 集成测试摘要
        integ_data = test_results.get("integration_tests", test_results.get("integration_results", []))
        if isinstance(integ_data, dict):
            integ_summary = {
                "total": integ_data.get("total", len(integ_data.get("results", []))),
                "passed": integ_data.get("passed", 0),
                "failed": integ_data.get("failed", 0),
            }
        else:
            total = len(integ_data)
            passed = sum(1 for r in integ_data if r.get("passed"))
            integ_summary = {"total": total, "passed": passed, "failed": total - passed}

        # 缺陷摘要
        defect_summary = defects.get("summary", {"total": 0, "by_severity": {}, "by_category": {}})

        # 质量评分
        quality_score = self._calculate_quality_score(api_summary, perf_summary, integ_summary, defect_summary)

        # 质量门禁
        overall_pass = quality_score >= 60 and defect_summary.get("by_severity", {}).get("P0", 0) == 0

        return {
            "quality_score": quality_score,
            "overall_pass": overall_pass,
            "api_summary": api_summary,
            "performance_summary": perf_summary,
            "integration_summary": integ_summary,
            "defect_summary": defect_summary,
            "basic_info": {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "platform": "AI 自动化测试平台",
                "version": "1.0.0",
            },
        }

    def _calculate_quality_score(
        self,
        api: dict[str, Any],
        perf: dict[str, Any],
        integ: dict[str, Any],
        defects: dict[str, Any],
    ) -> int:
        """
        计算质量评分 (0-100)。

        基准分 100，按以下规则扣分：
        - API 通过率扣分: (1 - pass_rate) × 40
        - 性能瓶颈扣分: bottleneck_count × 5
        - 集成测试扣分: (1 - pass_rate) × 30
        - 缺陷扣分: P0×15 + P1×8 + P2×3 + P3×1
        """
        score = 100.0

        # API 通过率扣分
        api_total = api.get("total", 0)
        api_passed = api.get("passed", 0)
        if api_total > 0:
            api_pass_rate = api_passed / api_total
            score -= (1 - api_pass_rate) * 40

        # 性能瓶颈扣分
        perf_failed = perf.get("failed", 0)
        score -= perf_failed * 5

        # 集成测试扣分
        integ_total = integ.get("total", 0)
        integ_passed = integ.get("passed", 0)
        if integ_total > 0:
            integ_pass_rate = integ_passed / integ_total
            score -= (1 - integ_pass_rate) * 30

        # 缺陷扣分
        by_severity = defects.get("by_severity", {})
        score += (
            by_severity.get("P0", 0) * (-15)
            + by_severity.get("P1", 0) * (-8)
            + by_severity.get("P2", 0) * (-3)
            + by_severity.get("P3", 0) * (-1)
        )

        return max(0, min(100, int(score)))

    def _render_html(self, report_data: dict[str, Any]) -> str:
        """渲染在线交互式 HTML 报告。"""
        template = self.env.get_template("report_interactive.html")
        return template.render(
            summary=report_data["summary"],
            test_results=report_data.get("test_results", {}),
            defects=report_data.get("defects", {}),
            charts=report_data.get("charts", {}),
            report_data_json=json.dumps(report_data, ensure_ascii=False, default=str),
        )

    def _render_pdf(self, report_data: dict[str, Any]) -> bytes | None:
        """渲染 PDF 报告（使用 weasyprint）。"""
        try:
            from weasyprint import HTML

            template = self.env.get_template("report_pdf.html")
            html_content = template.render(
                summary=report_data["summary"],
                test_results=report_data.get("test_results", {}),
                defects=report_data.get("defects", {}),
                report_data_json=json.dumps(report_data, ensure_ascii=False, default=str),
            )

            pdf_bytes = HTML(string=html_content).write_pdf()
            return pdf_bytes
        except ImportError:
            logger.warning("weasyprint not installed, skipping PDF generation")
            return None
        except Exception as e:
            logger.warning(f"PDF rendering failed: {e}")
            return None

    async def _save_to_db(
        self,
        test_run_id: str,
        report_data: dict[str, Any],
        html_path: str,
        pdf_path: str | None,
        quality_score: int,
        overall_pass: bool,
    ) -> None:
        """保存报告记录到 TestReport 表。"""
        try:
            async with AsyncSessionLocal() as session:
                # 检查是否已有报告
                result = await session.execute(
                    select(TestReport).where(
                        TestReport.test_run_id == uuid.UUID(test_run_id)
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # 更新已有记录
                    existing.report_data = report_data
                    existing.html_path = html_path
                    existing.pdf_path = pdf_path
                    existing.quality_score = quality_score
                    existing.gate_passed = overall_pass
                    existing.gate_details = {
                        "quality_score": quality_score,
                        "overall_pass": overall_pass,
                    }
                else:
                    # 创建新记录
                    report = TestReport(
                        id=uuid.uuid4(),
                        test_run_id=uuid.UUID(test_run_id),
                        report_data=report_data,
                        html_path=html_path,
                        pdf_path=pdf_path,
                        share_token=uuid.uuid4().hex,
                        quality_score=quality_score,
                        gate_passed=overall_pass,
                        gate_details={
                            "quality_score": quality_score,
                            "overall_pass": overall_pass,
                        },
                    )
                    session.add(report)

                # 更新 TestRun 状态为 COMPLETED
                run_result = await session.execute(
                    select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
                )
                run = run_result.scalar_one_or_none()
                if run:
                    run.status = TestStatus.COMPLETED
                    run.progress = 100
                    run.completed_at = datetime.utcnow()

                await session.commit()
                logger.info(f"Report saved to DB for test_run: {test_run_id}")
        except Exception as e:
            logger.error(f"Failed to save report to DB: {e}")
