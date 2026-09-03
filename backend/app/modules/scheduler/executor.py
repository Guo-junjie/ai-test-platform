"""定时任务真实执行链（能力8 补全）。

目标语义：
- CASE_COLLECTION：执行项目下全部「已采纳」用例资产（target_config.asset_ids 可指定子集），
  经 APITester 并发执行；
- SCENARIO：执行指定测试场景的多步串联（Scenario.steps → IntegrationTester）。

被测环境：env_config.service_url 必填（定时执行不负责启动 SUT——与流水线不同，
场景/用例资产针对的是已部署环境）。

落库：创建独立 TestRun（source_ref=scheduled:<task_id>）→ 用例入库 test_cases →
执行结果入库 test_results（复用 engine 的持久化助手）→ ScheduledTaskRun 关联 test_run_id。
"""
import uuid
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.models.database import (
    Project,
    Scenario,
    ScheduledTask,
    TestCaseAsset,
    CaseAssetStatus,
    TestRun,
    TestStatus,
    SourceType,
)
from app.utils.database import AsyncSessionLocal


def _asset_to_api_case(asset: TestCaseAsset) -> dict[str, Any]:
    """用例资产 → APITester 用例格式 {case_id, case_name, request, expected}。"""
    return {
        "case_id": str(asset.id),
        "case_name": asset.title,
        "request": asset.request_data or {},
        "expected": asset.expected_result or {},
    }


def _scenario_to_integration(scenario: Scenario) -> dict[str, Any]:
    """Scenario.steps → IntegrationTester 场景格式。

    orchestrator 产出步骤字段：{step_order, method, url, request:{headers,body,params}, extract}；
    IntegrationTester 消费：{step, method, url, headers, body, extract}。
    """
    steps = []
    for s in scenario.steps or []:
        if not isinstance(s, dict):
            continue
        req = s.get("request") or {}
        steps.append(
            {
                "step": s.get("step_order") or len(steps) + 1,
                "method": (s.get("method") or "GET").upper(),
                "url": s.get("url") or "",
                "headers": req.get("headers") or {},
                "body": req.get("body") or {},
                "params": req.get("params") or {},
                "extract": s.get("extract") or {},
            }
        )
    return {
        "case_id": str(scenario.id),
        "case_name": scenario.name,
        "steps": steps,
    }


async def execute_scheduled_chain(task_id: str) -> dict[str, Any]:
    """真实执行一个定时任务目标，返回执行概要。

    Returns:
        {"test_run_id": str|None, "total": int, "passed": int, "failed": int,
         "status": "success"|"failed", "error": str|None}
    """
    from app.modules.execution.api_tester import APITester
    from app.modules.execution.engine import _persist_test_results_async
    from app.modules.pipeline import _persist_test_cases_async

    async with AsyncSessionLocal() as session:
        task = (
            await session.execute(
                select(ScheduledTask).where(ScheduledTask.id == uuid.UUID(task_id))
            )
        ).scalar_one_or_none()
        if task is None:
            return {"status": "failed", "error": f"ScheduledTask {task_id} not found",
                    "test_run_id": None, "total": 0, "passed": 0, "failed": 0}

        project = (
            await session.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one_or_none()
        owner_id = (project.owner_id if project else None) or task.created_by

        service_url = (task.env_config or {}).get("service_url") or ""
        if not service_url:
            return {
                "status": "failed",
                "error": "env_config.service_url 未配置（定时执行不负责启动被测服务，请在定时任务的环境配置中填写被测服务地址）",
                "test_run_id": None, "total": 0, "passed": 0, "failed": 0,
            }

        # 准备用例（两类目标统一为 (persist_format, runner)）
        persist_cases: dict[str, list[dict]] = {}
        run_async = None

        if task.target_type.value == "case_collection":
            asset_ids = (task.target_config or {}).get("asset_ids") or []
            stmt = (
                select(TestCaseAsset)
                .where(
                    TestCaseAsset.project_id == task.project_id,
                    TestCaseAsset.status == CaseAssetStatus.ADOPTED,
                )
                .order_by(TestCaseAsset.priority, TestCaseAsset.created_at)
            )
            assets = (await session.execute(stmt)).scalars().all()
            if asset_ids:
                allow = {str(a) for a in asset_ids}
                assets = [a for a in assets if str(a.id) in allow]
            if not assets:
                return {
                    "status": "failed",
                    "error": "项目下没有已采纳的用例资产（请先在用例库采纳用例）",
                    "test_run_id": None, "total": 0, "passed": 0, "failed": 0,
                }
            cases = [_asset_to_api_case(a) for a in assets]
            persist_cases = {"api": cases}

            async def run_api():
                return await APITester().run_tests(cases, service_url)

            run_async = run_api
            test_type = "api"

        elif task.target_type.value == "scenario":
            if not task.target_id:
                return {"status": "failed", "error": "未绑定场景 ID",
                        "test_run_id": None, "total": 0, "passed": 0, "failed": 0}
            scenario = (
                await session.execute(
                    select(Scenario).where(Scenario.id == task.target_id)
                )
            ).scalar_one_or_none()
            if scenario is None:
                return {"status": "failed", "error": f"场景不存在: {task.target_id}",
                        "test_run_id": None, "total": 0, "passed": 0, "failed": 0}
            scenarios = [_scenario_to_integration(scenario)]
            persist_cases = {"integration": [
                {"name": scenarios[0]["case_name"], "description": scenario.description or "",
                 "request_data": {}, "expected_result": {}, "validation_rules": {},
                 "priority": "P2", "api_path": "", "http_method": ""}
            ]}

            async def run_scenario():
                from app.modules.execution.integration_tester import IntegrationTester

                return await IntegrationTester().run_tests(scenarios, service_url)

            run_async = run_scenario
            test_type = "integration"

        else:
            return {"status": "failed", "error": f"未知目标类型: {task.target_type}",
                    "test_run_id": None, "total": 0, "passed": 0, "failed": 0}

        # 创建独立 TestRun
        run = TestRun(
            id=uuid.uuid4(),
            project_id=task.project_id,
            user_id=owner_id,
            source_type=SourceType.UPLOAD,
            source_ref=f"scheduled:{task.id}",
            branch=None,
            status=TestStatus.EXECUTING,
            progress=10,
            started_at=datetime.utcnow(),
        )
        session.add(run)
        await session.flush()
        await session.commit()  # 必须显式提交：async with 退出不自动 commit，丢失 TestRun 行
        run_id = str(run.id)

    logger.info(f"[sched:{task_id}] TestRun {run_id} created, target={task.target_type.value}")

    # 用例入库（供结果外键挂载）+ 真实执行（worker 进程内 asyncio.run）
    import asyncio

    await _persist_test_cases_async(run_id, persist_cases)
    try:
        results = await run_async()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[sched:{task_id}] execution failed: {exc}")
        await _finish_run(run_id, TestStatus.FAILED, error=str(exc)[:500])
        return {"status": "failed", "error": str(exc)[:300], "test_run_id": run_id,
                "total": 0, "passed": 0, "failed": 0}

    # 结果入库（复用 engine 持久化助手：结果格式 [{"test_type": ..., "results": [...]}]）
    await _persist_test_results_async(run_id, [{"test_type": test_type, "results": results}])

    total = len(results)
    if test_type == "performance":
        passed = sum(1 for r in results if not r.get("bottlenecks"))
    else:
        passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed

    await _finish_run(
        run_id, TestStatus.COMPLETED,
        analysis_result={"trigger": "scheduled", "scheduled_task_id": task_id,
                         "total": total, "passed": passed, "failed": failed},
    )
    logger.info(f"[sched:{task_id}] executed: total={total} passed={passed} failed={failed}")
    return {"status": "success", "test_run_id": run_id, "total": total,
            "passed": passed, "failed": failed, "error": None}


async def _finish_run(run_id: str, status: TestStatus, error: str | None = None,
                      analysis_result: dict | None = None) -> None:
    async with AsyncSessionLocal() as session:
        run = (
            await session.execute(select(TestRun).where(TestRun.id == uuid.UUID(run_id)))
        ).scalar_one_or_none()
        if run is not None:
            run.status = status
            run.progress = 100
            run.completed_at = datetime.utcnow()
            if error:
                run.error_message = error
            if analysis_result:
                run.analysis_result = analysis_result
            await session.commit()
