"""
报告 API 路由

提供测试报告的完整生命周期管理：
- GET /{run_id} — 获取报告数据 JSON
- GET /{run_id}/html — 返回在线 HTML 报告内容
- GET /{run_id}/pdf — 下载 PDF 报告
- GET /{run_id}/share — 生成分享链接
- GET /history — 查询历史报告列表
- POST /{run_id}/generate — 手动触发报告生成
"""

import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse, FileResponse
from pathlib import Path
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TestReport, TestRun
from app.utils.database import get_db_session
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

router = APIRouter()

# 后端直接对外提供 echarts bundle（避免前端源 / 外网 CDN 依赖，分享链接整页打开也能渲染图表）
_ECHARTS_PATH = (
    Path(__file__).parent.parent / "modules" / "report" / "static" / "echarts.min.js"
)


# ==================== API 路由 ====================


@router.get("/history")
async def get_report_history(
    test_run_id: str | None = Query(None, description="按测试任务ID过滤"),
    project_id: str | None = Query(None, description="按项目ID过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    查询历史报告列表。

    支持按 test_run_id 或 project_id 过滤，分页返回。
    """
    query = select(TestReport).order_by(desc(TestReport.created_at))

    if test_run_id:
        try:
            run_uuid = uuid.UUID(test_run_id)
            query = query.where(TestReport.test_run_id == run_uuid)
        except ValueError:
            raise HTTPException(400, f"Invalid test_run_id: {test_run_id}")

    if project_id:
        # 通过 TestRun 关联查询 project_id
        run_query = select(TestRun.id).where(TestRun.project_id == uuid.UUID(project_id))
        run_result = await db.execute(run_query)
        run_ids = [row[0] for row in run_result.fetchall()]
        if run_ids:
            query = query.where(TestReport.test_run_id.in_(run_ids))
        else:
            return {"code": 0, "data": {"list": [], "total": 0}, "message": "success"}

    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    reports = result.scalars().all()

    return {
        "code": 0,
        "data": {
            "list": [
                {
                    "id": str(r.id),
                    "test_run_id": str(r.test_run_id),
                    "quality_score": r.quality_score,
                    "gate_passed": r.gate_passed,
                    "html_path": r.html_path,
                    "pdf_path": r.pdf_path,
                    "share_token": r.share_token,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in reports
            ],
            "total": len(reports),
            "page": page,
            "page_size": page_size,
        },
        "message": "success",
    }


@router.get("/{run_id}")
async def get_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    获取报告数据 JSON。

    从 TestReport 表查询完整 report_data。若报告尚未生成（TestReport 行不存在），
    返回 404 并提示用户先点击「重新生成报告」。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"报告尚未生成（run_id={run_id}）。请先点击「重新生成报告」按钮。"
            ),
        )

    return {
        "code": 0,
        "data": {
            "id": str(report.id),
            "test_run_id": str(report.test_run_id),
            "report_data": report.report_data,
            "quality_score": report.quality_score,
            "gate_passed": report.gate_passed,
            "gate_details": report.gate_details,
            "html_path": report.html_path,
            "pdf_path": report.pdf_path,
            "share_token": report.share_token,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        },
        "message": "success",
    }


@router.get("/{run_id}/html")
async def get_html_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    返回在线 HTML 报告内容。

    优先从 MinIO 下载，失败时从本地路径读取。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"报告尚未生成（run_id={run_id}）。请先点击「重新生成报告」按钮。",
        )

    html_object_name = report.html_path
    if not html_object_name:
        raise HTTPException(404, "HTML report path not available (请重新生成报告)")

    html_content = await _load_report_html(html_object_name)
    if html_content is None:
        raise HTTPException(500, "Failed to read HTML report (MinIO 与本地均读取失败)")

    return {"code": 0, "data": {"html": html_content}, "message": "success"}


@router.get("/static/echarts.min.js")
async def serve_echarts_bundle():
    """
    后端直接提供 echarts bundle。

    报告 HTML 里的 <script src="/api/reports/static/echarts.min.js"> 会命中此路由：
    - 应用内 iframe（frontend 源）→ nginx 把 /api/ 反代到 backend → 命中
    - 分享链接整页打开（backend 源）→ 同域直接命中
    两种场景都不依赖 frontend 的 /echarts.min.js 或外网 CDN。
    """
    if not _ECHARTS_PATH.exists():
        raise HTTPException(404, "echarts bundle not found (请重新部署后端)")
    return FileResponse(str(_ECHARTS_PATH), media_type="application/javascript")


@router.get("/{run_id}/share-view")
async def share_view(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    整页渲染报告 HTML（text/html），供分享链接在浏览器直接打开。

    与 /{run_id}/html 的区别：后者返回 JSON 包裹（供前端 iframe 取 html 字段），
    本路由直接返回裸 HTML，浏览器打开即整页渲染，图表也能正常显示。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"报告尚未生成（run_id={run_id}）。请先点击「重新生成报告」按钮。",
        )

    html_object_name = report.html_path
    if not html_object_name:
        raise HTTPException(404, "HTML report path not available (请重新生成报告)")

    html_content = await _load_report_html(html_object_name)
    if html_content is None:
        raise HTTPException(500, "Failed to read HTML report")

    return Response(content=html_content, media_type="text/html")


@router.get("/{run_id}/pdf")
async def download_pdf_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    下载 PDF 报告。

    返回 StreamingResponse，media_type=application/pdf。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"报告尚未生成（run_id={run_id}）。请先点击「重新生成报告」按钮。",
        )

    pdf_object_name = report.pdf_path
    if not pdf_object_name:
        # 不再静默 404：把 gate_details.pdf_error 也带回去，方便前端展示根因
        pdf_error = "（无详细原因）"
        if isinstance(report.gate_details, dict):
            pdf_error = report.gate_details.get("pdf_error") or pdf_error
        raise HTTPException(
            status_code=503,
            detail=(
                f"PDF 报告暂不可用：{pdf_error}。"
                f" 请确认 weasyprint 系统依赖（libcairo/libpango/libffi）齐全，"
                f"或重新生成报告。"
            ),
        )

    # 从 MinIO 下载
    try:
        from app.utils.storage import download_file
        import tempfile
        import os

        temp_path = os.path.join(tempfile.gettempdir(), f"report_{run_id}.pdf")
        download_file(pdf_object_name, temp_path)

        with open(temp_path, "rb") as f:
            pdf_bytes = f.read()

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=test_report_{run_id[:8]}.pdf"
            },
        )
    except Exception as e:
        logger.error(f"Failed to download PDF: {e}")
        raise HTTPException(500, f"Failed to download PDF report: {e}")


@router.get("/{run_id}/share")
async def get_share_link(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """
    生成报告分享链接。

    返回指向后端 /api/reports/{run_id}/share-view 的整页 URL（7 天有效，对象本身长期保留）。
    不再返回 MinIO presigned URL —— 因为 MinIO 在 Docker 内网（minio:9000），
    浏览器从外部打开会「代理服务器拒绝连接 / 无法连接到 minio:9000」。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    result = await db.execute(
        select(TestReport).where(TestReport.test_run_id == run_uuid)
    )
    report = result.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"报告尚未生成（run_id={run_id}）。请先点击「重新生成报告」按钮。",
        )

    html_object_name = report.html_path
    if not html_object_name:
        raise HTTPException(404, "HTML report path not available (请重新生成报告)")

    try:
        base = _report_share_base(request)
        share_url = f"{base}/api/reports/{run_id}/share-view"
        return {
            "code": 0,
            "data": {
                "share_url": share_url,
                "share_token": report.share_token,
                "expires_hours": 7 * 24,
            },
            "message": "success",
        }
    except Exception as e:
        logger.error(f"Failed to generate share link: {e}")
        raise HTTPException(500, f"Failed to generate share link: {e}")


@router.post("/{run_id}/generate")
async def generate_report(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    手动触发报告生成。

    加载测试结果（Redis 优先 → DB TestResult 兜底），调用 DefectAnalyzer + ReportGenerator 生成报告。
    """
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, f"Invalid run_id: {run_id}")

    # 查询 TestRun
    result = await db.execute(select(TestRun).where(TestRun.id == run_uuid))
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(404, f"Test run not found: {run_id}")

    # Redis 优先 → DB 兜底
    test_results = await _load_test_results(run_id, db)
    if test_results is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "测试结果不存在（Redis 已过期 / 未执行用例 / TestResult 表为空）。"
                "请先完成测试（执行用例）后再生成报告，或检查 Redis 状态。"
            ),
        )

    # 异步执行报告生成
    import asyncio

    asyncio.create_task(
        _generate_report_async(run_id, test_results)
    )

    source = test_results.get("summary", {}).get("source", "redis")
    return {
        "code": 0,
        "data": {
            "test_run_id": run_id,
            "status": "generating",
            "data_source": source,
            "message": f"Report generation started (data source: {source})",
        },
        "message": "success",
    }


# ==================== 内部函数 ====================


async def _load_report_html(html_object_name: str) -> str | None:
    """
    从 MinIO 或本地路径读取报告 HTML 内容，返回字符串；都失败返回 None。

    MinIO / 本地双降级：MinIO 不可达（如分享链接场景下对象被清理）时回退本地。
    """
    import os
    import tempfile

    # 1. MinIO 优先
    try:
        from app.utils.storage import download_file

        temp_path = os.path.join(tempfile.gettempdir(), f"report_dl_{os.getpid()}.html")
        download_file(html_object_name, temp_path)
        with open(temp_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Failed to download HTML from MinIO: {e}")

    # 2. 本地兜底
    try:
        from app.config import settings

        local_path = os.path.join(settings.REPORT_DIR, html_object_name.split("/")[-1])
        with open(local_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e2:
        logger.error(f"Failed to read HTML report locally: {e2}")
        return None


def _report_share_base(request: Request) -> str:
    """
    推导分享链接对外可访问的基址。

    优先级：
    1) 环境变量 REPORT_PUBLIC_BASE_URL（最可靠，部署时显式配置，如 http://<公网IP>:3000）
    2) 反向代理透传的 Host / X-Forwarded-Proto 头（nginx 已配置透传）
       —— 注意不能直接用 request.base_url，那是 backend:8000 内网地址。
    """
    base = settings.REPORT_PUBLIC_BASE_URL
    if base:
        return base.rstrip("/")

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("host") or request.url.netloc
    if host:
        return f"{proto}://{host}"

    return str(request.base_url).rstrip("/")


async def _load_test_results(
    run_id: str,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """
    加载测试结果，Redis 优先 → DB TestResult 兜底。

    背景：流水线跑完测试后只把结果写到 Redis（set_task_result），TTL 到期 / 容器重启
    / Redis 清理后数据丢失。TestResult 表本应持久化但当前流水线未插入（TODO），先做
    "能读就读、不能读返 None" 的优雅降级。返回结构尽量贴合
    DefectAnalyzer.analyze 期望的 {api_results: [...], summary: {...}}。
    """
    # 1. Redis 优先（完整数据：含 request_body / assertions 等）
    from app.utils.redis_client import get_task_result

    cached = await get_task_result(run_id)
    if cached:
        return cached

    # 2. DB 兜底：从 TestResult 表读（目前流水线未持久化，所以多数情况空，但留兼容）
    from app.models.database import TestResult

    result = await db.execute(
        select(TestResult).where(TestResult.test_run_id == uuid.UUID(run_id))
    )
    rows = result.scalars().all()
    if not rows:
        return None

    api_results: list[dict[str, Any]] = []
    perf_results: list[dict[str, Any]] = []
    integ_results: list[dict[str, Any]] = []

    for r in rows:
        # 优化：case_type / case_name 已经在 TestResult 行上冗余写入
        # 不必再 join TestCase 表。如果旧数据没写（NULL），按 'api' 兜底
        case_type = getattr(r, "case_type", None) or "api"
        case_name = getattr(r, "case_name", None) or "(未知用例)"

        # 字段名按 HTML 模板约定
        item = {
            "case_name": case_name,
            "case_type": case_type,
            "api_path": "",  # 老数据可能缺
            "http_method": "",
            "actual_status_code": r.status_code,
            "actual_response": r.response_body,
            "response_time_ms": r.response_time_ms,
            "passed": bool(r.is_passed),
            "error_message": r.error_message,
            "error_trace": r.error_trace,
            "executed_at": r.executed_at.isoformat() if r.executed_at else None,
            "tps": r.tps,
            "qps": r.qps,
            "error_rate": r.error_rate,
            "concurrent_users": r.concurrent_users,
        }

        # 按 case_type 分桶
        if case_type == "performance":
            item.update({
                "total_requests": None,
                "total_errors": None,
                "avg_response_time": r.response_time_ms,
                "p95": None,
                "p99": None,
                "bottlenecks": [] if r.is_passed else [(r.error_message or "未知瓶颈")[:200]],
            })
            perf_results.append(item)
        elif case_type == "integration":
            item.update({
                "total_steps": None,
                "executed_steps": None,
                "failure_step": 0 if r.is_passed else 1,
                "failure_reason": r.error_message,
                "step_results": [],
            })
            integ_results.append(item)
        else:
            api_results.append(item)

    total_api = len(api_results)
    passed_api = sum(1 for r in api_results if r.get("passed"))
    total_perf = len(perf_results)
    passed_perf = sum(1 for r in perf_results if not r.get("bottlenecks"))
    total_integ = len(integ_results)
    passed_integ = sum(1 for r in integ_results if r.get("passed"))

    # 兼容两种消费方：
    # 1) DefectAnalyzer.analyze 期望 {api_results: [...], summary: {...}}
    # 2) ReportGenerator 期望 {api_tests: {results:[]}, performance_tests: {results:[]}, integration_tests: {results:[]}, summary: {...}}
    return {
        "api_results": api_results,
        "api_tests": {"results": api_results, "total": total_api, "passed": passed_api, "failed": total_api - passed_api},
        "performance_tests": {"results": perf_results, "total": total_perf, "passed": passed_perf, "failed": total_perf - passed_perf},
        "performance_results": perf_results,
        "integration_tests": {"results": integ_results, "total": total_integ, "passed": passed_integ, "failed": total_integ - passed_integ},
        "integration_results": integ_results,
        "summary": {
            "total": total_api + total_perf + total_integ,
            "passed": passed_api + passed_perf + passed_integ,
            "failed": (total_api - passed_api) + (total_perf - passed_perf) + (total_integ - passed_integ),
            "source": "db_fallback",
        },
    }


async def _generate_report_async(
    test_run_id: str,
    test_results: dict[str, Any],
) -> None:
    """异步执行报告生成流程。"""
    from app.utils.redis_client import set_task_status, set_task_progress

    try:
        await set_task_status(test_run_id, "analyzing_defects", {"step": "defect_analysis"})
        await set_task_progress(test_run_id, 90, "缺陷分析")

        # 1. 缺陷分析
        from app.modules.defect_analyzer import DefectAnalyzer

        analyzer = DefectAnalyzer()
        defects = await analyzer.analyze(test_results)

        logger.info(f"[{test_run_id}] Defect analysis completed: {defects['summary']['total']} defects")

        # 2. 报告生成
        await set_task_status(test_run_id, "reporting", {"step": "report_generation"})
        await set_task_progress(test_run_id, 95, "生成报告")

        from app.modules.report import ReportGenerator

        generator = ReportGenerator()
        report_result = await generator.generate(test_run_id, test_results, defects)

        logger.info(
            f"[{test_run_id}] Report generated: score={report_result['quality_score']}, "
            f"pass={report_result['overall_pass']}"
        )

        await set_task_status(test_run_id, "completed", {
            "quality_score": report_result["quality_score"],
            "overall_pass": report_result["overall_pass"],
        })
        await set_task_progress(test_run_id, 100, "报告生成完成")

    except Exception as e:
        logger.error(f"[{test_run_id}] Report generation failed: {e}", exc_info=True)
        await set_task_status(test_run_id, "failed", {"error": str(e)})
        await set_task_progress(test_run_id, 0, f"报告生成失败: {str(e)[:100]}")
