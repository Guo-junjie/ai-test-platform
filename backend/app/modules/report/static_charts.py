"""
静态图表构建器 — 为 PDF 报告生成 matplotlib PNG（base64 data URI）

背景（重要）：
    PDF 由 weasyprint 在**服务端**渲染，它**不执行任何 JavaScript**。
    在线报告用的 ECharts 图表依赖 JS 渲染，因此在 PDF 里必然是空白。
    本模块用 matplotlib 在服务端把同样的图表画成静态图片，内嵌进 PDF 模板。

中文字体：
    matplotlib 默认字体不含中文，画出来的中文全是方块（tofu）。
    容器必须安装中文字体（见 Dockerfile 的 fonts-wqy-zenhei），
    本模块启动时主动 addfont 并配置 font.sans-serif。

降级原则（离线友好 / 双降级链）：
    任何一步失败都只返回空 dict，绝不抛异常中断报告生成。
"""

import base64
import io
import os
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 常见 CJK 字体路径（Debian/Ubuntu 系）。安装任意一个即可正常显示中文。
_CJK_FONT_PATHS = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)

# 与 ECharts 版本保持一致的主题色
_COLOR_PASS = "#67c23a"
_COLOR_WARN = "#e6a23c"
_COLOR_FAIL = "#f56c6c"
_COLOR_INFO = "#409eff"
_COLOR_GRAY = "#909399"

_SEVERITY_COLORS = {"P0": _COLOR_FAIL, "P1": _COLOR_WARN, "P2": _COLOR_INFO, "P3": _COLOR_GRAY}
_SEVERITY_LABELS = {"P0": "阻断", "P1": "严重", "P2": "一般", "P3": "轻微"}

_CATEGORY_LABELS = {
    "business_exception": "业务异常",
    "program_bug": "程序缺陷",
    "performance_issue": "性能问题",
    "integration_failure": "集成失败",
    "security_vulnerability": "安全漏洞",
}

_font_configured = False


def _configure_cjk_font() -> None:
    """配置 matplotlib 使用中文字体（幂等，失败不抛异常）。"""
    global _font_configured
    if _font_configured:
        return
    _font_configured = True

    try:
        import matplotlib

        matplotlib.use("Agg")  # 无 GUI 环境必须
        from matplotlib import font_manager

        # 主动注册容器里存在的中文字体文件
        registered = False
        for path in _CJK_FONT_PATHS:
            if os.path.exists(path):
                try:
                    font_manager.fontManager.addfont(path)
                    registered = True
                    logger.debug(f"Registered CJK font for matplotlib: {path}")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Failed to register font {path}: {e}")

        if not registered:
            logger.warning(
                "未找到任何中文字体，PDF 图表中的中文可能显示为方块。"
                "请在镜像中安装 fonts-wqy-zenhei（见 Dockerfile）。"
            )

        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = [
            "WenQuanYi Zen Hei",
            "WenQuanYi Micro Hei",
            "Noto Sans CJK SC",
            "Noto Sans CJK JP",
            "AR PL UMing CN",
            "DejaVu Sans",
        ]
        # 解决负号显示为方块
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to configure matplotlib CJK font: {e}")


def _fig_to_data_uri(fig: Any) -> str:
    """把 matplotlib Figure 转成 base64 data URI，并释放内存。"""
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def build_severity_pie(defects: dict[str, Any]) -> str | None:
    """缺陷严重等级分布饼图。无缺陷时返回 None。"""
    import matplotlib.pyplot as plt

    by_severity = defects.get("summary", {}).get("by_severity", {}) or {}

    labels: list[str] = []
    sizes: list[int] = []
    colors: list[str] = []

    for sev in ("P0", "P1", "P2", "P3"):
        count = by_severity.get(sev, 0) or 0
        if count > 0:
            labels.append(f"{sev} ({_SEVERITY_LABELS.get(sev, sev)})")
            sizes.append(count)
            colors.append(_SEVERITY_COLORS.get(sev, _COLOR_GRAY))

    if not sizes:
        return None

    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct=lambda p: f"{p * sum(sizes) / 100:.0f}个",
        startangle=90,
        textprops={"fontsize": 9},
    )
    for t in autotexts:
        t.set_fontsize(8)
        t.set_color("white")
    ax.set_title("缺陷严重等级分布", fontsize=12, fontweight="bold")
    ax.axis("equal")
    return _fig_to_data_uri(fig)


def build_pass_rate_bar(
    api_summary: dict[str, Any],
    perf_summary: dict[str, Any],
    integ_summary: dict[str, Any],
) -> str | None:
    """三类测试通过率对比柱状图（柱=通过/失败数，折线=通过率）。"""
    import matplotlib.pyplot as plt
    import numpy as np

    categories = ["接口测试", "性能测试", "集成测试"]
    summaries = [api_summary or {}, perf_summary or {}, integ_summary or {}]

    passed: list[int] = []
    failed: list[int] = []
    rates: list[float] = []

    for s in summaries:
        total = s.get("total", 0) or 0
        p = s.get("passed", 0) or 0
        f = s.get("failed", 0) or 0
        passed.append(p)
        failed.append(f)
        rates.append(round(p / total * 100, 1) if total > 0 else 0.0)

    if sum(passed) + sum(failed) == 0:
        return None

    x = np.arange(len(categories))
    width = 0.32

    fig, ax1 = plt.subplots(figsize=(6.4, 3.4))
    b1 = ax1.bar(x - width / 2, passed, width, label="通过数", color=_COLOR_PASS)
    b2 = ax1.bar(x + width / 2, failed, width, label="失败数", color=_COLOR_FAIL)
    ax1.set_ylabel("用例数", fontsize=10)
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories, fontsize=10)
    ax1.set_ylim(bottom=0)

    # 在柱顶标数字
    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax1.annotate(
                    f"{int(h)}",
                    xy=(bar.get_x() + bar.get_width() / 2, h),
                    xytext=(0, 2),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )

    ax2 = ax1.twinx()
    ax2.plot(x, rates, color=_COLOR_INFO, marker="o", linewidth=2, label="通过率(%)")
    ax2.set_ylabel("通过率(%)", fontsize=10)
    ax2.set_ylim(0, 105)
    for i, r in enumerate(rates):
        ax2.annotate(
            f"{r}%",
            xy=(x[i], r),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=_COLOR_INFO,
        )

    ax1.set_title("测试通过率对比", fontsize=12, fontweight="bold")
    # 合并两个坐标轴的图例
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper right", fontsize=8)

    fig.tight_layout()
    return _fig_to_data_uri(fig)


def build_performance_line(perf_results: list[dict[str, Any]]) -> str | None:
    """性能指标趋势折线图（TPS / 平均RT / P95）。无性能数据返回 None。"""
    import matplotlib.pyplot as plt

    if not perf_results:
        return None

    names: list[str] = []
    tps: list[float] = []
    avg_rt: list[float] = []
    p95: list[float] = []

    for r in perf_results:
        names.append(str(r.get("case_name", "")).replace("[性能] ", "")[:14] or "-")
        tps.append(float(r.get("tps", 0) or 0))
        avg_rt.append(round(float(r.get("avg_response_time", 0) or 0), 1))
        p95.append(round(float(r.get("p95", 0) or 0), 1))

    if not any(tps) and not any(avg_rt) and not any(p95):
        return None

    fig, ax1 = plt.subplots(figsize=(6.4, 3.2))
    xs = list(range(len(names)))

    ax1.plot(xs, tps, marker="o", color=_COLOR_INFO, linewidth=2, label="TPS")
    ax1.set_ylabel("TPS", fontsize=10)
    ax1.set_xticks(xs)
    ax1.set_xticklabels(names, rotation=20, ha="right", fontsize=8)

    ax2 = ax1.twinx()
    ax2.plot(xs, avg_rt, marker="s", color=_COLOR_WARN, linewidth=2, label="平均响应时间(ms)")
    if any(p95):
        ax2.plot(xs, p95, marker="^", color=_COLOR_FAIL, linewidth=2, label="P95(ms)")
    ax2.set_ylabel("响应时间(ms)", fontsize=10)

    ax1.set_title("性能指标趋势", fontsize=12, fontweight="bold")
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)

    fig.tight_layout()
    return _fig_to_data_uri(fig)


def build_defect_category_pie(defects: dict[str, Any]) -> str | None:
    """缺陷类别分布饼图。无缺陷时返回 None。"""
    import matplotlib.pyplot as plt

    by_category = defects.get("summary", {}).get("by_category", {}) or {}

    labels: list[str] = []
    sizes: list[int] = []

    for cat, count in by_category.items():
        if (count or 0) > 0:
            labels.append(_CATEGORY_LABELS.get(cat, str(cat)))
            sizes.append(count)

    if not sizes:
        return None

    palette = [_COLOR_FAIL, _COLOR_WARN, _COLOR_INFO, _COLOR_PASS, _COLOR_GRAY]
    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=[palette[i % len(palette)] for i in range(len(sizes))],
        autopct=lambda p: f"{p * sum(sizes) / 100:.0f}个",
        startangle=90,
        textprops={"fontsize": 9},
    )
    for t in autotexts:
        t.set_fontsize(8)
        t.set_color("white")
    ax.set_title("缺陷类别分布", fontsize=12, fontweight="bold")
    ax.axis("equal")
    return _fig_to_data_uri(fig)


def build_static_charts(report_data: dict[str, Any]) -> dict[str, str]:
    """
    为 PDF 报告构建所有静态图表。

    Args:
        report_data: 完整报告数据（含 summary / defects / test_results）。

    Returns:
        {图表名: base64 data URI}。任一步失败都返回已成功的部分，绝不抛异常。
    """
    charts: dict[str, str] = {}

    try:
        _configure_cjk_font()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Static chart font setup failed, skipping charts: {e}")
        return charts

    summary = report_data.get("summary", {}) or {}
    defects = report_data.get("defects", {}) or {}
    test_results = report_data.get("test_results", {}) or {}

    perf_results = test_results.get("performance_results", [])
    if not perf_results:
        perf_data = test_results.get("performance_tests", {})
        perf_results = perf_data.get("results", []) if isinstance(perf_data, dict) else []

    builders = (
        ("pass_rate_bar", lambda: build_pass_rate_bar(
            summary.get("api_summary", {}),
            summary.get("performance_summary", {}),
            summary.get("integration_summary", {}),
        )),
        ("severity_pie", lambda: build_severity_pie(defects)),
        ("category_pie", lambda: build_defect_category_pie(defects)),
        ("performance_line", lambda: build_performance_line(perf_results)),
    )

    for name, builder in builders:
        try:
            uri = builder()
            if uri:
                charts[name] = uri
        except Exception as e:  # noqa: BLE001
            # 单张图失败不影响其它图与整份报告
            logger.warning(f"Static chart '{name}' failed, skipped: {e}")

    logger.info(f"Built {len(charts)} static charts for PDF report")
    return charts
