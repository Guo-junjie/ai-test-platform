"""
图表构建器 — 生成 ECharts 配置 dict

所有方法返回 ECharts option 字典，前端可直接传入 echarts.setOption() 渲染。
用于在线交互式报告。
"""

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ChartBuilder:
    """
    图表构建器。

    为测试报告生成各类 ECharts 图表配置。
    """

    @staticmethod
    def build_quality_gauge(score: int) -> dict[str, Any]:
        """
        构建质量评分仪表盘。

        Args:
            score: 质量评分 (0-100)。

        Returns:
            ECharts Gauge option dict。
        """
        if score >= 80:
            color = "#67c23a"
        elif score >= 60:
            color = "#e6a23c"
        else:
            color = "#f56c6c"

        return {
            "title": {
                "text": "质量评分",
                "left": "center",
                "top": "10%",
                "textStyle": {"fontSize": 16, "fontWeight": "bold"},
            },
            "series": [
                {
                    "type": "gauge",
                    "min": 0,
                    "max": 100,
                    "splitNumber": 10,
                    "axisLine": {
                        "lineStyle": {
                            "width": 20,
                            "color": [
                                [0.6, "#f56c6c"],
                                [0.8, "#e6a23c"],
                                [1, "#67c23a"],
                            ],
                        }
                    },
                    "pointer": {"width": 5},
                    "detail": {
                        "valueAnimation": True,
                        "formatter": "{value}",
                        "fontSize": 32,
                        "color": color,
                        "offsetCenter": [0, "70%"],
                    },
                    "data": [{"value": score}],
                }
            ],
        }

    @staticmethod
    def build_defect_pie(defects: dict[str, Any]) -> dict[str, Any]:
        """
        构建缺陷严重等级分布饼图。

        Args:
            defects: 缺陷分析结果，含 summary.by_severity。

        Returns:
            ECharts Pie option dict。
        """
        by_severity = defects.get("summary", {}).get("by_severity", {})
        color_map = {
            "P0": "#f56c6c",
            "P1": "#e6a23c",
            "P2": "#409eff",
            "P3": "#909399",
        }

        data = []
        for sev in ["P0", "P1", "P2", "P3"]:
            count = by_severity.get(sev, 0)
            if count > 0:
                data.append({
                    "name": f"{sev} ({_severity_label(sev)})",
                    "value": count,
                    "itemStyle": {"color": color_map.get(sev, "#909399")},
                })

        if not data:
            data.append({"name": "无缺陷", "value": 1, "itemStyle": {"color": "#67c23a"}})

        return {
            "title": {
                "text": "缺陷严重等级分布",
                "left": "center",
                "textStyle": {"fontSize": 14, "fontWeight": "bold"},
            },
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {
                "orient": "vertical",
                "left": "left",
                "top": "middle",
            },
            "series": [
                {
                    "type": "pie",
                    "radius": ["40%", "70%"],
                    "center": ["55%", "55%"],
                    "avoidLabelOverlap": False,
                    "label": {
                        "show": True,
                        "formatter": "{b}\n{c}个",
                    },
                    "labelLine": {"show": True},
                    "data": data,
                }
            ],
        }

    @staticmethod
    def build_defect_category_pie(defects: dict[str, Any]) -> dict[str, Any]:
        """
        构建缺陷类别分布饼图。

        Args:
            defects: 缺陷分析结果，含 summary.by_category。

        Returns:
            ECharts Pie option dict。
        """
        by_category = defects.get("summary", {}).get("by_category", {})
        category_labels = {
            "business_exception": "业务异常",
            "program_bug": "程序缺陷",
            "performance_issue": "性能问题",
            "integration_failure": "集成失败",
            "security_vulnerability": "安全漏洞",
        }
        color_list = ["#f56c6c", "#e6a23c", "#409eff", "#67c23a", "#909399"]

        data = []
        for i, (cat, count) in enumerate(by_category.items()):
            if count > 0:
                data.append({
                    "name": category_labels.get(cat, cat),
                    "value": count,
                    "itemStyle": {"color": color_list[i % len(color_list)]},
                })

        if not data:
            data.append({"name": "无缺陷", "value": 1, "itemStyle": {"color": "#67c23a"}})

        return {
            "title": {
                "text": "缺陷类别分布",
                "left": "center",
                "textStyle": {"fontSize": 14, "fontWeight": "bold"},
            },
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {
                "orient": "vertical",
                "left": "left",
                "top": "middle",
            },
            "series": [
                {
                    "type": "pie",
                    "radius": "60%",
                    "center": ["55%", "55%"],
                    "label": {"formatter": "{b}\n{c}个"},
                    "data": data,
                }
            ],
        }

    @staticmethod
    def build_pass_rate_bar(
        api_summary: dict[str, Any],
        perf_summary: dict[str, Any],
        integ_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """
        构建三类测试通过率对比柱状图。

        Args:
            api_summary: API 测试摘要 {total, passed, failed}。
            perf_summary: 性能测试摘要。
            integ_summary: 集成测试摘要。

        Returns:
            ECharts Bar option dict。
        """
        categories = ["接口测试", "性能测试", "集成测试"]
        summaries = [api_summary, perf_summary, integ_summary]

        pass_rates = []
        passed_counts = []
        failed_counts = []

        for s in summaries:
            total = s.get("total", 0)
            passed = s.get("passed", 0)
            failed = s.get("failed", 0)
            rate = round(passed / total * 100, 1) if total > 0 else 0
            pass_rates.append(rate)
            passed_counts.append(passed)
            failed_counts.append(failed)

        return {
            "title": {
                "text": "测试通过率对比",
                "left": "center",
                "textStyle": {"fontSize": 14, "fontWeight": "bold"},
            },
            "tooltip": {
                "trigger": "axis",
                "formatter": lambda params: "",  # 前端会覆盖
            },
            "legend": {"data": ["通过数", "失败数", "通过率(%)"], "top": "bottom"},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": [
                {"type": "value", "name": "用例数"},
                {"type": "value", "name": "通过率(%)", "max": 100},
            ],
            "series": [
                {
                    "name": "通过数",
                    "type": "bar",
                    "data": passed_counts,
                    "itemStyle": {"color": "#67c23a"},
                },
                {
                    "name": "失败数",
                    "type": "bar",
                    "data": failed_counts,
                    "itemStyle": {"color": "#f56c6c"},
                },
                {
                    "name": "通过率(%)",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": pass_rates,
                    "itemStyle": {"color": "#409eff"},
                    "label": {"show": True, "formatter": "{c}%"},
                },
            ],
        }

    @staticmethod
    def build_performance_line(perf_results: list[dict[str, Any]]) -> dict[str, Any]:
        """
        构建性能趋势折线图（TPS 和响应时间）。

        Args:
            perf_results: 性能测试结果列表。

        Returns:
            ECharts Line option dict。
        """
        case_names = []
        tps_values = []
        avg_rt_values = []
        p95_values = []

        for r in perf_results:
            name = r.get("case_name", "").replace("[性能] ", "")
            case_names.append(name[:20])
            tps_values.append(r.get("tps", 0))
            avg_rt_values.append(round(r.get("avg_response_time", 0), 1))
            p95_values.append(round(r.get("p95", 0), 1))

        return {
            "title": {
                "text": "性能指标趋势",
                "left": "center",
                "textStyle": {"fontSize": 14, "fontWeight": "bold"},
            },
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["TPS", "平均响应时间(ms)", "P95(ms)"], "top": "bottom"},
            "xAxis": {"type": "category", "data": case_names, "axisLabel": {"rotate": 30}},
            "yAxis": [
                {"type": "value", "name": "TPS"},
                {"type": "value", "name": "响应时间(ms)"},
            ],
            "series": [
                {
                    "name": "TPS",
                    "type": "line",
                    "data": tps_values,
                    "itemStyle": {"color": "#409eff"},
                    "smooth": True,
                },
                {
                    "name": "平均响应时间(ms)",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": avg_rt_values,
                    "itemStyle": {"color": "#e6a23c"},
                    "smooth": True,
                },
                {
                    "name": "P95(ms)",
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": p95_values,
                    "itemStyle": {"color": "#f56c6c"},
                    "smooth": True,
                },
            ],
        }

    @staticmethod
    def build_all_charts(report_data: dict[str, Any]) -> dict[str, Any]:
        """
        汇总构建所有图表数据。

        Args:
            report_data: 完整报告数据，含 summary / defects / test_results。

        Returns:
            包含所有图表配置的字典。
        """
        summary = report_data.get("summary", {})
        defects = report_data.get("defects", {})
        test_results = report_data.get("test_results", {})

        quality_score = summary.get("quality_score", 0)

        api_summary = summary.get("api_summary", {})
        perf_summary = summary.get("performance_summary", {})
        integ_summary = summary.get("integration_summary", {})

        perf_results = test_results.get("performance_results", [])
        if not perf_results:
            perf_data = test_results.get("performance_tests", {})
            perf_results = perf_data.get("results", []) if isinstance(perf_data, dict) else []

        charts = {
            "quality_gauge": ChartBuilder.build_quality_gauge(quality_score),
            "defect_severity_pie": ChartBuilder.build_defect_pie(defects),
            "defect_category_pie": ChartBuilder.build_defect_category_pie(defects),
            "pass_rate_bar": ChartBuilder.build_pass_rate_bar(
                api_summary, perf_summary, integ_summary
            ),
            "performance_line": ChartBuilder.build_performance_line(perf_results),
        }

        logger.info(f"Built {len(charts)} charts for report")
        return charts


def _severity_label(severity: str) -> str:
    """获取严重等级中文标签。"""
    labels = {"P0": "阻断", "P1": "严重", "P2": "一般", "P3": "轻微"}
    return labels.get(severity, severity)
