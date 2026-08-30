"""
测试执行引擎 — Celery 任务链调度

使用 Celery chain + group 实现测试并行执行：
1. prepare_environment: 启动被测服务
2. group(run_api_tests, run_performance_tests, run_integration_tests): 并行执行三类测试
3. aggregate_results: 汇总结果 + 持久化 TestResult

Celery 任务是同步的，内部通过 asyncio.run() 调用异步测试器。
"""

import asyncio
import json
import uuid as _uuid
from typing import Any

from celery import chain, group

from app.celery_app import celery_app as app
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 同步 Redis 客户端（Celery 任务中使用）
_sync_redis = None


class RunCancelled(Exception):
    """测试任务被用户取消 — 各阶段检查点抛出，上层据此标记 CANCELLED 而非 FAILED。"""


def _is_cancelled(test_run_id: str) -> bool:
    """检查取消标志（cancel API 写入 Redis；7 天过期与任务状态键一致）。"""
    try:
        return bool(_get_sync_redis().get(f"task:cancel:{test_run_id}"))
    except Exception:  # noqa: BLE001 - Redis 异常时按未取消处理，不阻塞执行
        return False


def _check_cancelled(test_run_id: str) -> None:
    """阶段检查点：已取消则抛 RunCancelled（Celery 任务随即终止）。"""
    if _is_cancelled(test_run_id):
        _set_task_status_sync(test_run_id, "cancelled", {"step": "cancelled_by_user"})
        _set_task_progress_sync(test_run_id, 0, "已取消")
        logger.info(f"[{test_run_id}] cancellation flag detected, aborting stage")
        raise RunCancelled(test_run_id)


def _get_sync_redis():
    """获取同步 Redis 客户端（惰性初始化）。"""
    global _sync_redis
    if _sync_redis is None:
        from app.utils.redis_client import get_redis

        _sync_redis = get_redis()
    return _sync_redis


def _set_task_status_sync(task_id: str, status: str, extra: dict[str, Any] | None = None) -> None:
    """同步设置任务状态到 Redis。"""
    data: dict[str, Any] = {"status": status}
    if extra:
        data.update(extra)
    _get_sync_redis().set(
        f"task:status:{task_id}",
        json.dumps(data, ensure_ascii=False),
        ex=7 * 24 * 3600,
    )


def _set_task_progress_sync(task_id: str, progress: int, step: str = "") -> None:
    """同步设置任务进度到 Redis。"""
    _get_sync_redis().set(
        f"task:progress:{task_id}",
        json.dumps({"progress": progress, "step": step}, ensure_ascii=False),
        ex=7 * 24 * 3600,
    )


def _persist_test_results(test_run_id: str, test_results: list[dict[str, Any]]) -> int:
    """同步包装（Celery 同步任务用）；async 上下文请直接 await _persist_test_results_async。"""
    try:
        count = asyncio.run(_persist_test_results_async(test_run_id, test_results))
        if count:
            logger.info(f"[{test_run_id}] Persisted {count} TestResult rows to DB")
        return count
    except Exception as db_err:  # pragma: no cover - 兜底，不阻塞汇总
        logger.warning(f"[{test_run_id}] persist_test_results failed (non-fatal): {db_err}")
        return 0


async def _persist_test_results_async(test_run_id: str, test_results: list[dict[str, Any]]) -> int:
    """
    把 aggregate 阶段汇聚到的「逐条用例执行结果」入库到 test_results 表。

    数据流修复：
    - pipeline 生成用例 → _persist_test_cases 已经入库 test_cases（真实 id）
    - engine 跑用例 → api_tester / performance_tester / integration_tester 产出 results[]
    - aggregate 阶段 → 原来只写 Redis `task:result:{run_id}` 汇总结果，
      现在同时把 results[] 拆开逐条 INSERT 到 test_results 表

    结果 detail 字段对齐 TestResult 模型：
    - test_run_id / test_case_id（FK）/ is_passed / status_code / response_body /
      response_time_ms / tps / qps / error_rate / concurrent_users /
      error_message / error_trace / executed_at

    Args:
        test_run_id: 测试任务 ID（字符串 UUID）。
        test_results: 从 group 收集到的 3 类子任务结果列表。

    Returns:
        实际入库的 TestResult 条数（logging 用）。
    """
    from app.models.database import TestCase, TestResult
    from app.utils.database import AsyncSessionLocal

    try:
        run_uuid = _uuid.UUID(test_run_id)
    except (ValueError, TypeError):
        logger.warning(f"[{test_run_id}] invalid uuid, skip persist_test_results")
        return 0

    from sqlalchemy import select as sa_select
    from sqlalchemy import insert as sa_insert

    async def _do_persist() -> int:
        async with AsyncSessionLocal() as session:
            # 1. 查出该 run 下所有 TestCase（用于 case_id 反查 + 冗余写入 case_type/case_name）
            cases_rows = (
                await session.execute(
                    sa_select(TestCase.id, TestCase.case_type, TestCase.case_name).where(
                        TestCase.test_run_id == run_uuid
                    )
                )
            ).all()
            if not cases_rows:
                logger.warning(
                    f"[{test_run_id}] No TestCase rows for run, skip TestResult persist"
                )
                return 0

            # 构建 case_id -> (case_type, case_name) 映射（反查用）
            # 同时建 (case_type, case_name) -> case_id 映射
            case_meta: dict[_uuid.UUID, tuple[str, str]] = {
                row.id: (row.case_type, row.case_name) for row in cases_rows
            }
            case_key_to_id: dict[tuple[str, str], _uuid.UUID] = {
                (row.case_type, row.case_name): row.id for row in cases_rows
            }

            # 2. 遍历 3 类子任务结果，把 results[] 逐条映射并 INSERT
            rows: list[dict[str, Any]] = []
            for sub in test_results:
                if not isinstance(sub, dict):
                    continue
                test_type = sub.get("test_type", "unknown")
                for result in sub.get("results", []) or []:
                    case_name = result.get("case_name") or result.get("name") or ""
                    case_id = case_key_to_id.get((test_type, case_name))
                    if case_id is None:
                        # 找不到对应 TestCase（孤立 result，跳过并打 warning）
                        logger.warning(
                            f"[{test_run_id}] skip orphan result: "
                            f"type={test_type} name={case_name[:80]}"
                        )
                        continue

                    is_passed = bool(result.get("passed", False))
                    # 性能测试的「失败」判定：bottlenecks 非空
                    if test_type == "performance":
                        if result.get("bottlenecks"):
                            is_passed = False
                        else:
                            is_passed = bool(result.get("passed", True))

                    rows.append({
                        "id": _uuid.uuid4(),
                        "test_run_id": run_uuid,
                        "test_case_id": case_id,
                        # 冗余字段：避免 _load_test_results 时 join TestCase
                        "case_type": test_type,
                        "case_name": case_name[:500] if case_name else None,
                        "is_passed": is_passed,
                        "status_code": result.get("status_code")
                            or result.get("actual_status_code")
                            or result.get("http_status"),
                        "response_body": result.get("response_body")
                            or result.get("actual_response"),
                        "response_time_ms": result.get("response_time_ms")
                            or result.get("elapsed_ms"),
                        "tps": result.get("tps"),
                        "qps": result.get("qps"),
                        "error_rate": result.get("error_rate"),
                        "concurrent_users": result.get("concurrent_users"),
                        "error_message": (result.get("error_message") or "")[:1000] if not is_passed else None,
                        "error_trace": (result.get("error_trace") or "")[:2000] if not is_passed else None,
                        "executed_at": datetime_module_utcnow(),
                    })
            if not rows:
                return 0
            await session.execute(sa_insert(TestResult), rows)
            await session.commit()
            return len(rows)

    count = await _do_persist()
    if count:
        logger.info(f"[{test_run_id}] Persisted {count} TestResult rows to DB")
    return count



# 避免 top-level 导入 datetime 与 db 模型耦合（worker 进程冷启动更快）
def datetime_module_utcnow():
    from datetime import datetime
    return datetime.utcnow()


class TestExecutionEngine:
    """
    测试执行引擎。

    调度 Celery 任务链执行完整测试流程。
    """

    def execute_all(
        self,
        test_run_id: str,
        analysis_result: dict[str, Any],
        test_cases: dict[str, list[dict[str, Any]]],
    ) -> str:
        """
        调度全部测试。

        使用 Celery chain + group 编排：
        prepare_environment → group(api_tests, perf_tests, integ_tests) → aggregate_results

        Args:
            test_run_id: 测试任务 ID。
            analysis_result: 代码分析结果。
            test_cases: 三类测试用例 {api: [...], performance: [...], integration: [...]}。

        Returns:
            Celery 任务组 ID。
        """
        logger.info(f"Dispatching test execution chain for run: {test_run_id}")

        _set_task_status_sync(test_run_id, "executing", {"step": "preparing_environment"})
        _set_task_progress_sync(test_run_id, 50, "准备测试环境")

        # 构建 Celery 任务链
        workflow = chain(
            prepare_environment.s(test_run_id, analysis_result),
            group(
                run_api_tests.s(test_run_id, test_cases.get("api", [])),
                run_performance_tests.s(
                    test_run_id,
                    test_cases.get("performance", []),
                    analysis_result,
                ),
                run_integration_tests.s(
                    test_run_id,
                    test_cases.get("integration", []),
                    analysis_result,
                ),
            ),
            aggregate_results.s(test_run_id),
        )

        result = workflow.apply_async()
        logger.info(f"Test execution chain dispatched: {result.id}")
        return result.id


# ==================== Celery 任务定义 ====================


@app.task(bind=True, max_retries=3)
def prepare_environment(
    self,
    test_run_id: str,
    analysis_result: dict[str, Any],
) -> dict[str, Any]:
    """
    准备测试环境 — 根据技术栈启动被测服务。

    Args:
        test_run_id: 测试任务 ID。
        analysis_result: 代码分析结果（含 tech_stack 信息）。

    Returns:
        包含 service_url 和 analysis_result 的字典。
    """
    logger.info(f"[{test_run_id}] Preparing test environment...")
    try:
        _check_cancelled(test_run_id)
    except RunCancelled:
        return {"service_url": "", "analysis_result": analysis_result, "cancelled": True}

    _set_task_status_sync(test_run_id, "executing", {"step": "preparing_environment"})
    _set_task_progress_sync(test_run_id, 55, "启动被测服务")

    tech_stack = analysis_result.get("tech_stack", {})
    stack_name = tech_stack.get("stack", "unknown")
    repo_path = analysis_result.get("repo_path", "/app/data/repos")

    from app.modules.execution.env_adapters import (
        AUTO_COVERAGE,
        EnvironmentAdapterFactory,
    )

    # 项目级开关：平台 AUTO_COVERAGE=1 且本项目未显式关闭时才注入探针
    # （项目配置存 projects.quality_gate_config.auto_coverage，未设置默认采集）
    coverage_enabled = AUTO_COVERAGE
    try:
        from sqlalchemy import select as _select

        from app.models.database import Project as _Project
        from app.utils.database import AsyncSessionLocal as _S

        async def _proj_cov() -> bool:
            async with _S() as s:
                pid_row = (
                    await s.execute(
                        _select(TestRun.project_id).where(TestRun.id == test_run_id)
                    )
                ).scalar_one_or_none()
                if not pid_row:
                    return True
                proj = (
                    await s.execute(_select(_Project).where(_Project.id == pid_row))
                ).scalar_one_or_none()
                cfg = (proj.quality_gate_config or {}) if proj else {}
                return bool(cfg.get("auto_coverage", True))

        import asyncio as _aio
        coverage_enabled = AUTO_COVERAGE and _aio.run(_proj_cov())
    except Exception as e:  # noqa: BLE001 - 配置读取失败按默认采集，不阻塞
        logger.warning(f"[{test_run_id}] resolve project auto_coverage failed: {e}")

    adapter = EnvironmentAdapterFactory.get_adapter(stack_name)
    # 能力11：coverage_enabled 时启动带覆盖率探针的 SUT；否则普通启动
    service_url = adapter.start_service(repo_path, coverage=coverage_enabled)

    # 等待服务就绪
    ready = adapter.wait_for_ready(service_url, timeout=120)

    # 暂存覆盖率采集元数据（供 aggregate 阶段自动采集；未启用则无副作用）
    if coverage_enabled and getattr(adapter, "_coverage_meta", None):
        meta = dict(adapter._coverage_meta)
        meta["test_run_id"] = test_run_id
        # 解析 project_id 一并暂存
        try:
            from app.utils.database import AsyncSessionLocal
            from sqlalchemy import select

            from app.models.database import TestRun

            async def _pid():
                async with AsyncSessionLocal() as s:
                    r = (
                        await s.execute(select(TestRun.project_id).where(TestRun.id == test_run_id))
                    ).scalar_one_or_none()
                    return str(r) if r else None

            import asyncio

            pid = asyncio.run(_pid())
            if pid:
                meta["project_id"] = pid
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[coverage] resolve project_id failed: {e}")
        _get_sync_redis().set(
            f"coverage:meta:{test_run_id}",
            json.dumps(meta, ensure_ascii=False),
            ex=7 * 24 * 3600,
        )
        logger.info(f"[{test_run_id}] coverage auto-collect armed")
    if not ready:
        logger.warning(
            f"[{test_run_id}] Service not ready, proceeding anyway with {service_url}"
        )

    _set_task_progress_sync(test_run_id, 60, "测试环境就绪")

    return {
        "service_url": service_url,
        "analysis_result": analysis_result,
    }


@app.task(bind=True, max_retries=2)
def run_api_tests(
    self,
    env_result: dict[str, Any],
    test_run_id: str,
    api_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    执行接口测试。

    Args:
        env_result: prepare_environment 的返回值。
        test_run_id: 测试任务 ID。
        api_cases: 接口测试用例列表。

    Returns:
        接口测试结果。
    """
    try:
        _check_cancelled(test_run_id)
    except RunCancelled:
        return {"test_type": "api", "total": 0, "passed": 0, "failed": 0, "results": [], "cancelled": True}
    service_url = env_result.get("service_url", "http://localhost:8000")
    logger.info(f"[{test_run_id}] Running API tests: {len(api_cases)} cases")

    _set_task_progress_sync(test_run_id, 65, f"执行接口测试 ({len(api_cases)} 用例)")

    from app.modules.execution.api_tester import APITester

    async def _run():
        tester = APITester()
        return await tester.run_tests(api_cases, service_url)

    try:
        results = asyncio.run(_run())
    except Exception as e:
        logger.error(f"[{test_run_id}] API tests failed: {e}")
        results = []

    passed = sum(1 for r in results if r.get("passed"))
    logger.info(f"[{test_run_id}] API tests: {passed}/{len(results)} passed")

    _set_task_progress_sync(test_run_id, 75, f"接口测试完成 ({passed}/{len(results)})")

    return {
        "test_type": "api",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


@app.task(bind=True, max_retries=1)
def run_performance_tests(
    self,
    env_result: dict[str, Any],
    test_run_id: str,
    perf_cases: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    执行性能测试。

    Args:
        env_result: prepare_environment 的返回值。
        test_run_id: 测试任务 ID。
        perf_cases: 性能测试用例列表。
        analysis: 代码分析结果。

    Returns:
        性能测试结果。
    """
    try:
        _check_cancelled(test_run_id)
    except RunCancelled:
        return {"test_type": "performance", "total": 0, "passed": 0, "failed": 0, "results": [], "cancelled": True}
    service_url = env_result.get("service_url", "http://localhost:8000")
    logger.info(f"[{test_run_id}] Running performance tests: {len(perf_cases)} scenarios")

    _set_task_progress_sync(test_run_id, 80, f"执行性能测试 ({len(perf_cases)} 场景)")

    if not perf_cases:
        logger.info(f"[{test_run_id}] No performance test cases, skipping")
        return {"test_type": "performance", "total": 0, "passed": 0, "failed": 0, "results": []}

    from app.modules.execution.performance_tester import PerformanceTester

    async def _run():
        tester = PerformanceTester()
        return await tester.run_tests(perf_cases, service_url)

    try:
        results = asyncio.run(_run())
    except Exception as e:
        logger.error(f"[{test_run_id}] Performance tests failed: {e}")
        results = []

    # 性能测试结果中 bottlenecks 非空视为失败
    passed = sum(1 for r in results if not r.get("bottlenecks"))
    logger.info(f"[{test_run_id}] Performance tests: {passed}/{len(results)} passed")

    _set_task_progress_sync(test_run_id, 85, f"性能测试完成 ({passed}/{len(results)})")

    return {
        "test_type": "performance",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


@app.task(bind=True, max_retries=2)
def run_integration_tests(
    self,
    env_result: dict[str, Any],
    test_run_id: str,
    integration_cases: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    执行集成测试。

    Args:
        env_result: prepare_environment 的返回值。
        test_run_id: 测试任务 ID。
        integration_cases: 集成测试用例列表。
        analysis: 代码分析结果。

    Returns:
        集成测试结果。
    """
    try:
        _check_cancelled(test_run_id)
    except RunCancelled:
        return {"test_type": "integration", "total": 0, "passed": 0, "failed": 0, "results": [], "cancelled": True}
    service_url = env_result.get("service_url", "http://localhost:8000")
    logger.info(f"[{test_run_id}] Running integration tests: {len(integration_cases)} scenarios")

    _set_task_progress_sync(test_run_id, 88, f"执行集成测试 ({len(integration_cases)} 场景)")

    if not integration_cases:
        logger.info(f"[{test_run_id}] No integration test cases, skipping")
        return {"test_type": "integration", "total": 0, "passed": 0, "failed": 0, "results": []}

    from app.modules.execution.integration_tester import IntegrationTester

    async def _run():
        tester = IntegrationTester()
        return await tester.run_tests(integration_cases, service_url)

    try:
        results = asyncio.run(_run())
    except Exception as e:
        logger.error(f"[{test_run_id}] Integration tests failed: {e}")
        results = []

    passed = sum(1 for r in results if r.get("passed"))
    logger.info(f"[{test_run_id}] Integration tests: {passed}/{len(results)} passed")

    _set_task_progress_sync(test_run_id, 92, f"集成测试完成 ({passed}/{len(results)})")

    return {
        "test_type": "integration",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


@app.task(bind=True)
def aggregate_results(
    self,
    test_results: list[dict[str, Any]],
    test_run_id: str,
) -> dict[str, Any]:
    """
    汇总所有测试结果。

    Args:
        test_results: group 中三个测试任务的返回值列表。
        test_run_id: 测试任务 ID。

    Returns:
        汇总结果。
    """
    logger.info(f"[{test_run_id}] Aggregating test results...")
    try:
        _check_cancelled(test_run_id)
    except RunCancelled:
        logger.info(f"[{test_run_id}] aggregate aborted: run cancelled")
        return {"cancelled": True}
    _set_task_progress_sync(test_run_id, 95, "汇总测试结果")

    # test_results 是 group 的结果列表
    summary: dict[str, Any] = {
        "total_tests": 0,
        "total_passed": 0,
        "total_failed": 0,
        "api_tests": None,
        "performance_tests": None,
        "integration_tests": None,
    }

    for result in test_results:
        if not isinstance(result, dict):
            continue

        test_type = result.get("test_type", "unknown")
        total = result.get("total", 0)
        passed = result.get("passed", 0)
        failed = result.get("failed", 0)

        summary["total_tests"] += total
        summary["total_passed"] += passed
        summary["total_failed"] += failed

        if test_type == "api":
            summary["api_tests"] = result
        elif test_type == "performance":
            summary["performance_tests"] = result
        elif test_type == "integration":
            summary["integration_tests"] = result

    # 存储结果到 Redis
    _get_sync_redis().set(
        f"task:result:{test_run_id}",
        json.dumps(summary, ensure_ascii=False, default=str),
        ex=7 * 24 * 3600,
    )

    # 把逐条用例执行结果持久化到 DB（修复报告补生成 4 端点 404 的根因：
    #   Redis 摘要数据是有，但「逐条用例明细」本来没有，导致 test_results 表空）
    _persist_test_results(test_run_id, test_results)

    _set_task_status_sync(test_run_id, "completed", {"summary": {
        "total": summary["total_tests"],
        "passed": summary["total_passed"],
        "failed": summary["total_failed"],
    }})
    _set_task_progress_sync(test_run_id, 100, "测试完成")

    logger.info(
        f"[{test_run_id}] Test execution completed: "
        f"total={summary['total_tests']}, "
        f"passed={summary['total_passed']}, "
        f"failed={summary['total_failed']}"
    )

    # 能力11：若启用自动覆盖率，测试完成后采集并入库
    try:
        import asyncio
        import json as _json

        cov_meta_raw = _get_sync_redis().get(f"coverage:meta:{test_run_id}")
        if cov_meta_raw:
            meta = _json.loads(cov_meta_raw)
            _get_sync_redis().delete(f"coverage:meta:{test_run_id}")
            pid = meta.get("project_id")
            if pid:
                from app.modules.coverage.collector import collect_and_store

                rid = asyncio.run(collect_and_store(test_run_id, meta, pid))
                if rid:
                    logger.info(f"[{test_run_id}] auto coverage report {rid} stored")
                else:
                    logger.warning(
                        f"[{test_run_id}] auto coverage collect failed; 请改用手动上传报告"
                    )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[coverage] aggregate auto-collect error: {e}")

    # 自动生成测试报告（有结果才生成；异步任务，不阻塞本阶段）
    if summary.get("total_tests", 0) > 0:
        try:
            from app.modules.report.tasks import auto_generate_report

            auto_generate_report.delay(test_run_id)
            logger.info(f"[{test_run_id}] auto report generation dispatched")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{test_run_id}] auto report dispatch failed (non-fatal): {e}")

    # CI/CD 集成：项目配置了回调地址时推送结果摘要（best-effort，不阻塞、不重试）
    try:
        import asyncio as _aio

        from app.utils.database import AsyncSessionLocal as _S
        from sqlalchemy import select as _sel

        from app.models.database import Project as _P

        async def _callback():
            async with _S() as s:
                pid = (
                    await s.execute(
                        _sel(TestRun.project_id).where(TestRun.id == _uuid.UUID(test_run_id))
                    )
                ).scalar_one_or_none()
                if not pid:
                    return
                proj = (await s.execute(_sel(_P).where(_P.id == pid))).scalar_one_or_none()
                url = ((proj.source_config or {}).get("ci_callback_url") or "") if proj else ""
                if not url:
                    return
            payload = {
                "test_run_id": test_run_id,
                "status": "completed",
                "total": summary.get("total_tests", 0),
                "passed": summary.get("total_passed", 0),
                "failed": summary.get("total_failed", 0),
                "ci_result_url": f"/api/webhook/ci-result/{test_run_id}",
            }
            import httpx as _hx

            async with _hx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json=payload)
            logger.info(f"[{test_run_id}] CI callback sent to {url}")

        _aio.run(_callback())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[{test_run_id}] CI callback failed (non-fatal): {e}")

    return summary
