"""
测试流水线 Celery 任务

将完整测试流水线（代码拉取 → 代码解析 → 用例生成 → 执行调度）从 API 进程
迁移到 Celery worker 进程执行。

原实现放在 `app/api/test_run.py::_execute_full_pipeline`，使用
`asyncio.create_task` 在 API 事件循环里跑，但其中的 `SourceAdapterFactory.fetch_code()`
是同步阻塞调用，`AICodeAnalyzer.analyze_project` / `TestCaseGenerator.generate_all`
也在同一事件循环里 `await`，会把整个事件循环卡死，导致列表刷新、进度轮询等
后续 API 全部无响应（前端表现为"页面卡死"）。

迁入 Celery 后：API 只负责建 TestRun 记录并 `delay()` 派发，立刻返回；
所有重活在 worker 进程里以同步方式执行，互不干扰。
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text  # noqa: F401  (text 供后续扩展/排错使用)

from app.celery_app import celery_app as app
from app.models.database import TestRun, TestStatus
from app.modules.execution.engine import (
    RunCancelled,
    _is_cancelled,
    _set_task_progress_sync,
    _set_task_status_sync,
)
from app.modules.ai.model_router import ModelNotConfiguredError
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 内部助手 ====================


def _mark_run_failed(test_run_id: str, error: str) -> None:
    """
    将 TestRun 行状态置为 FAILED（在 worker 进程中通过独立事件循环执行）。

    Args:
        test_run_id: 测试任务 ID。
        error: 错误描述，截取前 500 字符写入 error_message。
    """

    async def _update() -> None:
        from app.utils.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
            )
            run = result.scalar_one_or_none()
            if run:
                run.status = TestStatus.FAILED
                run.error_message = error[:500]
                run.completed_at = datetime.utcnow()
                await session.commit()

    try:
        asyncio.run(_update())
    except Exception as db_err:  # pragma: no cover - 兜底日志
        logger.error(f"[{test_run_id}] Failed to update DB status: {db_err}")


def _mark_run_cancelled(test_run_id: str) -> None:
    """将 TestRun 行状态置为 CANCELLED（流水线各阶段检测到取消标志时调用）。"""

    async def _update() -> None:
        from app.utils.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
            )
            run = result.scalar_one_or_none()
            if run:
                run.status = TestStatus.CANCELLED
                run.error_message = "Cancelled by user"
                run.completed_at = datetime.utcnow()
                await session.commit()

    try:
        asyncio.run(_update())
    except Exception as db_err:  # pragma: no cover - 兜底日志
        logger.error(f"[{test_run_id}] Failed to mark cancelled: {db_err}")


def _persist_test_cases(test_run_id: str, test_cases: dict[str, list[dict[str, Any]]]) -> int:
    """同步包装（Celery 同步任务用）；async 上下文请直接 await _persist_test_cases_async。"""
    try:
        total = asyncio.run(_persist_test_cases_async(test_run_id, test_cases))
        logger.info(f"[{test_run_id}] Persisted {total} test_cases to DB")
        return total
    except Exception as db_err:  # pragma: no cover - 兜底日志
        logger.warning(f"[{test_run_id}] persist_test_cases failed (non-fatal): {db_err}")
    return 0


async def _persist_test_cases_async(test_run_id: str, test_cases: dict[str, list[dict[str, Any]]]) -> int:
    """把流水线生成的 3 类测试用例（api / performance / integration）入库到 test_cases 表。

    原数据流缺这一段 —— generate_all 只返回内存 dict，没写入 DB，会让后续
    测试结果（test_results.test_case_id）没有 FK 可挂。

    Args:
        test_run_id: 测试任务 ID（字符串 UUID）。
        test_cases: {"api": [...], "performance": [...], "integration": [...]}。

    Returns:
        实际入库的用例数（用于 logging）。
    """
    from app.models.database import TestCase
    from app.utils.database import AsyncSessionLocal

    total = 0
    try:
        run_uuid = uuid.UUID(test_run_id)
    except (ValueError, TypeError):
        logger.warning(f"[{test_run_id}] invalid uuid, skip persist_test_cases")
        return 0

    async with AsyncSessionLocal() as session:
        from sqlalchemy import insert as sa_insert

        rows: list[dict[str, Any]] = []
        for case_type, cases in test_cases.items():
            if not cases:
                continue
            for case in cases:
                rows.append({
                    "id": uuid.uuid4(),
                    "test_run_id": run_uuid,
                    "case_type": case_type,  # api / performance / integration
                    "case_name": (case.get("name") or case.get("case_name") or "")[:500],
                    "description": case.get("description") or "",
                    "request_data": case.get("request_data") or {},
                    "expected_result": case.get("expected_result") or {},
                    "validation_rules": case.get("validation_rules") or {},
                    "priority": case.get("priority") or "P2",
                    "api_path": case.get("api_path") or "",
                    "http_method": case.get("http_method") or "",
                })
        if not rows:
            return 0
        await session.execute(sa_insert(TestCase), rows)
        await session.commit()
        return len(rows)


# ==================== Celery 任务 ====================


@app.task(bind=True, max_retries=2)
def run_test_pipeline(self, test_run_id: str, req_dict: dict[str, Any]) -> dict[str, Any]:
    """
    执行完整测试流水线（Celery 同步任务）。

    流程：代码拉取（10%）→ 代码解析（25%）→ 用例生成（40%）→ 执行调度（50%）

    Args:
        test_run_id: 测试任务 ID（字符串 UUID）。
        req_dict: `CreateTestRunRequest.model_dump()` 的结果。

    Returns:
        {"test_run_id": str, "status": str} —— 派发结果概要。
    """
    try:
        # worker 进程不经 FastAPI lifespan，model_router 需逐任务从 DB 重载
        # （client 缓存绑定旧事件循环，必须清空重建；API 进程无需此操作）
        try:
            from app.modules.ai.model_router import refresh_model_router_for_worker
            from app.utils.database import AsyncSessionLocal

            async def _refresh_router():
                async with AsyncSessionLocal() as session:
                    await refresh_model_router_for_worker(session)

            asyncio.run(_refresh_router())
        except Exception as refresh_err:  # noqa: BLE001
            logger.warning(f"[{test_run_id}] model router refresh failed: {refresh_err}")

        # 取消检查点：拉取前
        if _is_cancelled(test_run_id):
            raise RunCancelled(test_run_id)

        # ==================== P0 模式分支 ====================
        # plan 模式：跳过 fetch/analyze/generate，直接用计划内用例资产入 test_cases
        plan_id_str = req_dict.get("plan_id")
        plan_cases = None
        if plan_id_str:
            try:
                from app.models.database import TestCaseAsset, TestPlan, TestPlanCase

                async def _load_plan_cases():
                    """从 test_plan_cases + test_case_assets 取 enabled 用例，按 case_type 分桶。"""
                    async with AsyncSessionLocal() as s:
                        pid_uuid = uuid.UUID(plan_id_str)
                        plan_row = (
                            await s.execute(
                                select(TestPlan).where(TestPlan.id == pid_uuid)
                            )
                        ).scalar_one_or_none()
                        if plan_row is None:
                            raise Exception("plan not found")
                        if plan_row.status != "active":
                            raise Exception(f"plan {plan_id_str} is {plan_row.status}, not active")
                        rows = (
                            await s.execute(
                                select(TestCaseAsset)
                                .join(TestPlanCase, TestPlanCase.case_asset_id == TestCaseAsset.id)
                                .where(
                                    TestPlanCase.plan_id == pid_uuid,
                                    TestPlanCase.enabled.is_(True),
                                )
                                .order_by(TestPlanCase.sort_order.asc())
                            )
                        ).scalars().all()
                        buckets = {"api": [], "performance": [], "integration": []}
                        # case_type 枚举是 positive/negative/boundary/exception
                        # （设计语义是"测试类型"），但 buckets 用 api/performance/integration
                        # （设计语义是"测试器类型"）——所有用例默认走 API 测试器
                        _CT_MAP = {"performance": "performance", "integration": "integration"}
                        for a in rows:
                            t = _CT_MAP.get(a.case_type, "api")
                            buckets.setdefault(t, []).append({
                                "case_id": str(a.id),
                                "case_name": a.title,
                                "request": a.request_data or {},
                                "expected": a.expected_result or {},
                            })
                        return buckets, plan_row

                plan_cases, plan_row = asyncio.run(_load_plan_cases())
                _set_task_status_sync(test_run_id, "loading_cases", {"step": "loading_plan_cases"})
                _set_task_progress_sync(test_run_id, 30, f"加载计划用例 ({sum(len(v) for v in plan_cases.values())} 条)")
                if _is_cancelled(test_run_id):
                    raise RunCancelled(test_run_id)
                logger.info(
                    f"[{test_run_id}] plan mode: loaded plan {plan_id_str} with "
                    f"api={len(plan_cases['api'])} perf={len(plan_cases['performance'])} "
                    f"integ={len(plan_cases['integration'])}"
                )
                # 计划元数据（供 analysis_result 传递给报告/缺陷）
                plan_id_for_result = plan_id_str
                plan_name_for_result = plan_row.name
                project_id_for_result = str(plan_row.project_id)
            except Exception as e:
                logger.error(f"[{test_run_id}] plan mode load failed: {e}", exc_info=True)
                raise RunCancelled  # 走失败路径标 FAILED

        # Step 1: 代码拉取（非 plan 模式）
        if not plan_cases:
            _set_task_status_sync(test_run_id, "pulling", {"step": "fetching_code"})
            _set_task_progress_sync(test_run_id, 10, "拉取代码")

        from app.modules.source import SourceAdapterFactory, SourceConfig, SourceType

        # plan 模式短路整个 fetch + analyze；只走 case_gen + persist + execute
        if not plan_cases:
            # plan 模式 req_dict 里的 source_type="plan" 不是 SourceType 成员，
            # 这里三元就地解析（占位 UPLOAD 仅用于满足 SQLEnum 校验）
            _src = req_dict.get("source_type") or "github"
            source_config = SourceConfig(
                source_type = SourceType.UPLOAD if _src == "plan" else SourceType(_src),
                github_token=req_dict.get("github_token"),
                repo_url=req_dict.get("repo_url"),
                branch=req_dict.get("branch") or "main",
                commit_sha=req_dict.get("commit_sha"),
                svn_url=req_dict.get("svn_url"),
                svn_username=req_dict.get("svn_username"),
                svn_password=req_dict.get("svn_password"),
                upload_file_path=req_dict.get("upload_file_path"),
            )

            fetch_result = SourceAdapterFactory.fetch_code(source_config)
            local_path = fetch_result.get("local_path", "")
            snapshot_id = fetch_result.get("snapshot_id")

            logger.info(f"[{test_run_id}] Code fetched: {local_path}")

            # Step 2: 代码解析（非 plan 模式）
            _set_task_status_sync(test_run_id, "analyzing", {"step": "code_analysis"})
            _set_task_progress_sync(test_run_id, 25, "代码解析")

            if _is_cancelled(test_run_id):
                raise RunCancelled(test_run_id)

            from app.modules.code_analyzer import AICodeAnalyzer, APIExtractor, StackDetector

            detector = StackDetector()
            stack_info = detector.detect(local_path)
            extractor = APIExtractor()
            apis = extractor.extract(local_path, stack_info)
        else:
            stack_info = {"stack": "plan", "language": "plan", "framework": "plan", "confidence": 1.0}
            apis = []

        if plan_cases:
            # plan 模式无代码分析——所有元数据已从 plan 拿到
            stack_info = {"stack": "plan", "language": "plan", "framework": "plan", "confidence": 1.0}
            apis = []
            ai_analysis = {"business_modules": [], "data_flow": {}, "risk_areas": [], "api_analyses": []}
            local_path = ""  # plan 模式无本地代码路径
            snapshot_id = None
        else:
            ai_analyzer = AICodeAnalyzer()
            try:
                ai_analysis = asyncio.run(
                    ai_analyzer.analyze_project(local_path, apis, stack_info)
                )
            except ModelNotConfiguredError:
                raise
            except Exception as e:
                logger.error(f"[{test_run_id}] AI analysis failed: {e}")
                ai_analysis = {
                    "business_modules": [],
                    "data_flow": {},
                    "risk_areas": [],
                    "api_analyses": [],
                }

        analysis_result: dict[str, Any] = {
            "tech_stack": stack_info,
            "apis": apis,
            "ai_analysis": ai_analysis,
            "total_apis": len(apis),
            "repo_path": local_path,
            "snapshot_id": snapshot_id,
        }
        # plan 模式补充上下文（让报告/缺陷知道这次跑的是哪个计划）
        if plan_cases:
            analysis_result["plan_id"] = plan_id_for_result
            analysis_result["plan_name"] = plan_name_for_result

        logger.info(
            f"[{test_run_id}] Analysis completed: stack={stack_info.get('stack')}, "
            f"apis={len(apis)}"
        )

        # Step 3: 用例生成（plan 模式跳过 AI 生成，直接用计划内用例）
        if not plan_cases:
            _set_task_status_sync(test_run_id, "generating", {"step": "case_generation"})
            _set_task_progress_sync(test_run_id, 40, "生成测试用例")

            if _is_cancelled(test_run_id):
                raise RunCancelled(test_run_id)

            from app.modules.case_generator import TestCaseGenerator
            from app.utils.database import get_test_run_project_id

            # 能力12 P1：解析项目 ID，让知识库注入按项目过滤（解析失败走全局回退）
            project_id = asyncio.run(get_test_run_project_id(test_run_id))

            generator = TestCaseGenerator()
            test_cases = asyncio.run(
                generator.generate_all(apis, ai_analysis, project_id=project_id)
            )
        else:
            test_cases = plan_cases
            project_id = project_id_for_result
            logger.info(f"[{test_run_id}] plan mode: skip AI generation, use {sum(len(v) for v in plan_cases.values())} plan cases")

        logger.info(
            f"[{test_run_id}] Cases generated: "
            f"api={len(test_cases.get('api', []))}, "
            f"perf={len(test_cases.get('performance', []))}, "
            f"integ={len(test_cases.get('integration', []))}"
        )

        # Step 3.5: 用例入库（test_results.test_case_id FK 需要真实 TestCase.id）
        _set_task_progress_sync(test_run_id, 45, "用例入库")
        _persist_test_cases(test_run_id, test_cases)

        # Step 4: 测试执行（内部为 Celery chain 的 apply_async，非阻塞）
        _set_task_status_sync(test_run_id, "executing", {"step": "test_execution"})
        _set_task_progress_sync(test_run_id, 50, "调度测试执行")

        from app.modules.execution.engine import TestExecutionEngine

        engine = TestExecutionEngine()
        # plan 模式无 SUT：传占位 service_url 让 prepare_environment 跳过启动
        # （性能测试在无目标 URL 时熔断保护下自然 0 用例返回）
        if plan_cases:
            analysis_result["service_url_override"] = "http://plan-mode-no-sut"
        engine.execute_all(test_run_id, analysis_result, test_cases)

        logger.info(f"[{test_run_id}] Pipeline dispatched, waiting for execution...")

        return {"test_run_id": test_run_id, "status": "executing"}

    except RunCancelled:
        logger.info(f"[{test_run_id}] Pipeline cancelled by user")
        _mark_run_cancelled(test_run_id)
        return {"test_run_id": test_run_id, "status": "cancelled"}

    except Exception as e:
        logger.error(f"[{test_run_id}] Pipeline failed: {e}", exc_info=True)

        _set_task_status_sync(test_run_id, "failed", {"error": str(e)})
        _set_task_progress_sync(test_run_id, 0, f"失败: {str(e)[:100]}")

        _mark_run_failed(test_run_id, str(e))

        return {"test_run_id": test_run_id, "status": "failed", "error": str(e)[:500]}
