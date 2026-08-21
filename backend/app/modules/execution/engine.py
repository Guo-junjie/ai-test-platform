"""
测试执行引擎 — Celery 任务链调度

使用 Celery chain + group 实现测试并行执行：
1. prepare_environment: 启动被测服务
2. group(run_api_tests, run_performance_tests, run_integration_tests): 并行执行三类测试
3. aggregate_results: 汇总结果

Celery 任务是同步的，内部通过 asyncio.run() 调用异步测试器。
"""

import asyncio
import json
import uuid
from typing import Any

from celery import chain, group

from app.celery_app import celery_app as app
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 同步 Redis 客户端（Celery 任务中使用）
_sync_redis = None


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

    _set_task_status_sync(test_run_id, "executing", {"step": "preparing_environment"})
    _set_task_progress_sync(test_run_id, 55, "启动被测服务")

    tech_stack = analysis_result.get("tech_stack", {})
    stack_name = tech_stack.get("stack", "unknown")
    repo_path = analysis_result.get("repo_path", "/app/data/repos")

    from app.modules.execution.env_adapters import (
        AUTO_COVERAGE,
        EnvironmentAdapterFactory,
    )

    adapter = EnvironmentAdapterFactory.get_adapter(stack_name)
    # 能力11：AUTO_COVERAGE=1 时启动带覆盖率探针的 SUT；否则普通启动
    service_url = adapter.start_service(repo_path, coverage=AUTO_COVERAGE)

    # 等待服务就绪
    ready = adapter.wait_for_ready(service_url, timeout=120)

    # 暂存覆盖率采集元数据（供 aggregate 阶段自动采集；未启用则无副作用）
    if AUTO_COVERAGE and getattr(adapter, "_coverage_meta", None):
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

    _set_task_status_sync(test_run_id, "executing", {"step": "aggregating_results"})
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

    return summary
