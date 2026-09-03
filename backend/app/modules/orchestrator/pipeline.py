"""
全链路测试编排器 — 从代码获取到报告生成的一站式编排

编排完整流程：
1. 代码获取 (SourceAdapterFactory.fetch_code)
2. AI 代码分析 (StackDetector → APIExtractor → AICodeAnalyzer)
3. 测试用例生成 (TestCaseGenerator)
4. 测试执行 (TestExecutionEngine)
5. 缺陷分析 (DefectAnalyzer)
6. 报告生成 (ReportGenerator)

每步更新 Redis 进度，任一步失败则记录并返回部分结果。
本编排器是对 api/test_run.py 中 _execute_full_pipeline 的封装和增强，
添加了缺陷分析和报告生成的自动衔接。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import TestRun, TestStatus, Project
from app.utils.database import AsyncSessionLocal
from app.utils.logger import get_logger
from app.utils.redis_client import set_task_status, set_task_progress

logger = get_logger(__name__)


class PipelineOrchestrator:
    """
    全链路测试编排器。

    从代码获取到报告生成的一站式编排，串联所有测试阶段。
    每步更新 Redis 进度，任一步失败则记录并返回部分结果。

    用法::

        orchestrator = PipelineOrchestrator()
        run_id = await orchestrator.run_full_pipeline(
            project_id="...",
            source_config={...},
            run_options={...},
        )
    """

    # 各阶段进度百分比
    PROGRESS_FETCH = 10
    PROGRESS_ANALYZE = 25
    PROGRESS_GENERATE = 40
    PROGRESS_EXECUTE = 55
    PROGRESS_DEFECT = 80
    PROGRESS_REPORT = 90
    PROGRESS_DONE = 100

    def __init__(self) -> None:
        """初始化编排器。"""
        self._partial_results: dict[str, Any] = {}

    async def run_full_pipeline(
        self,
        project_id: str,
        source_config: dict[str, Any],
        run_options: dict[str, Any],
    ) -> str:
        """
        编排完整流程：代码获取 → AI分析 → 用例生成 → 测试执行 → 缺陷分析 → 报告生成。

        Args:
            project_id: 项目 ID。
            source_config: 数据源配置（source_type, repo_url, branch 等）。
            run_options: 运行选项（owner_id, github_token 等）。

        Returns:
            test_run_id: 创建的测试任务 ID。
        """
        logger.info(
            f"Starting full pipeline: project_id={project_id}, "
            f"source_type={source_config.get('source_type')}"
        )

        # 创建 TestRun 记录
        test_run_id = await self._create_test_run(project_id, source_config, run_options)
        self._partial_results = {"test_run_id": test_run_id}

        try:
            # Step 1: 代码获取
            local_path, snapshot_id = await self._step_fetch_code(
                test_run_id, source_config
            )
            self._partial_results["local_path"] = local_path
            self._partial_results["snapshot_id"] = snapshot_id

            # Step 2: AI 代码分析
            analysis_result = await self._step_analyze_code(
                test_run_id, local_path, snapshot_id
            )
            self._partial_results["analysis_result"] = analysis_result

            # Step 3: 测试用例生成
            test_cases = await self._step_generate_cases(
                test_run_id, analysis_result
            )
            self._partial_results["test_cases"] = test_cases

            # Step 4: 测试执行
            execution_result = await self._step_execute_tests(
                test_run_id, analysis_result, test_cases
            )
            self._partial_results["execution_result"] = execution_result

            # Step 5: 缺陷分析
            defect_result = await self._step_analyze_defects(
                test_run_id, execution_result, analysis_result
            )
            self._partial_results["defect_result"] = defect_result

            # Step 6: 报告生成
            report_result = await self._step_generate_report(
                test_run_id, analysis_result, execution_result, defect_result
            )
            self._partial_results["report_result"] = report_result

            # 完成
            await self._mark_completed(test_run_id)
            logger.info(f"Pipeline completed successfully: {test_run_id}")

        except Exception as e:
            logger.error(
                f"Pipeline failed at some step: {test_run_id}, error: {e}",
                exc_info=True,
            )
            await self._mark_failed(test_run_id, str(e))

        return test_run_id

    # ==================== 内部步骤 ====================

    async def _create_test_run(
        self,
        project_id: str,
        source_config: dict[str, Any],
        run_options: dict[str, Any],
    ) -> str:
        """创建 TestRun 数据库记录。"""
        from app.models.database import SourceType as ModelSourceType

        source_type_str = source_config.get("source_type", "github")
        try:
            source_type = ModelSourceType(source_type_str)
        except ValueError:
            source_type = ModelSourceType.GITHUB

        owner_id = run_options.get("owner_id", "00000000-0000-0000-0000-000000000000")

        run_id = uuid.uuid4()
        async with AsyncSessionLocal() as session:
            test_run = TestRun(
                id=run_id,
                project_id=uuid.UUID(project_id),
                user_id=uuid.UUID(owner_id),
                source_type=source_type,
                source_ref=source_config.get("repo_url", "")
                or source_config.get("svn_url", "")
                or source_config.get("upload_file_path", ""),
                branch=source_config.get("branch", "main"),
                commit_sha=source_config.get("commit_sha"),
                status=TestStatus.PULLING,
                progress=0,
                started_at=datetime.utcnow(),
            )
            session.add(test_run)
            await session.commit()

        logger.info(f"TestRun created: {run_id}")
        await set_task_status(str(run_id), "pulling", {"step": "init"})
        return str(run_id)

    async def _step_fetch_code(
        self,
        test_run_id: str,
        source_config: dict[str, Any],
    ) -> tuple[str, str | None]:
        """Step 1: 获取代码。"""
        await set_task_status(test_run_id, "pulling", {"step": "fetching_code"})
        await set_task_progress(test_run_id, self.PROGRESS_FETCH, "拉取代码")

        from app.modules.source import SourceConfig, SourceAdapterFactory, SourceType

        config = SourceConfig(
            source_type=SourceType(source_config.get("source_type", "github")),
            github_token=source_config.get("github_token"),
            repo_url=source_config.get("repo_url"),
            branch=source_config.get("branch", "main"),
            commit_sha=source_config.get("commit_sha"),
            svn_url=source_config.get("svn_url"),
            svn_username=source_config.get("svn_username"),
            svn_password=source_config.get("svn_password"),
            upload_file_path=source_config.get("upload_file_path"),
        )

        fetch_result = SourceAdapterFactory.fetch_code(config)
        local_path = fetch_result.get("local_path", "")
        snapshot_id = fetch_result.get("snapshot_id")

        # 更新数据库快照 ID
        await self._update_test_run(test_run_id, snapshot_id=snapshot_id)

        logger.info(f"[{test_run_id}] Code fetched: {local_path}")
        return local_path, snapshot_id

    async def _step_analyze_code(
        self,
        test_run_id: str,
        local_path: str,
        snapshot_id: str | None,
    ) -> dict[str, Any]:
        """Step 2: AI 代码分析。"""
        await set_task_status(test_run_id, "analyzing", {"step": "code_analysis"})
        await set_task_progress(test_run_id, self.PROGRESS_ANALYZE, "代码解析")

        from app.modules.code_analyzer import (
            AICodeAnalyzer,
            APIExtractor,
            StackDetector,
        )

        detector = StackDetector()
        stack_info = detector.detect(local_path)

        extractor = APIExtractor()
        apis = extractor.extract(local_path, stack_info)

        ai_analyzer = AICodeAnalyzer()
        try:
            ai_analysis = await ai_analyzer.analyze_project(
                local_path, apis, stack_info
            )
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

        # 保存分析结果到数据库
        await self._update_test_run(
            test_run_id, analysis_result=analysis_result
        )

        logger.info(
            f"[{test_run_id}] Analysis completed: stack={stack_info.get('stack')}, "
            f"apis={len(apis)}"
        )
        return analysis_result

    async def _step_generate_cases(
        self,
        test_run_id: str,
        analysis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 3: 测试用例生成。"""
        await set_task_status(test_run_id, "generating", {"step": "case_generation"})
        await set_task_progress(test_run_id, self.PROGRESS_GENERATE, "生成测试用例")

        from app.modules.case_generator import TestCaseGenerator
        from app.utils.database import get_test_run_project_id

        # 能力12 P1：解析项目 ID，让知识库注入按项目过滤（解析失败走全局回退）
        project_id = await get_test_run_project_id(test_run_id)

        generator = TestCaseGenerator()
        apis = analysis_result.get("apis", [])
        ai_analysis = analysis_result.get("ai_analysis", {})
        test_cases = await generator.generate_all(apis, ai_analysis, project_id=project_id)

        logger.info(
            f"[{test_run_id}] Cases generated: "
            f"api={len(test_cases.get('api', []))}, "
            f"perf={len(test_cases.get('performance', []))}, "
            f"integ={len(test_cases.get('integration', []))}"
        )
        return test_cases

    async def _step_execute_tests(
        self,
        test_run_id: str,
        analysis_result: dict[str, Any],
        test_cases: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 4: 测试执行。"""
        await set_task_status(test_run_id, "executing", {"step": "test_execution"})
        await set_task_progress(test_run_id, self.PROGRESS_EXECUTE, "调度测试执行")

        from app.modules.execution.engine import TestExecutionEngine

        engine = TestExecutionEngine()
        engine.execute_all(test_run_id, analysis_result, test_cases)

        logger.info(f"[{test_run_id}] Test execution dispatched")
        return {"status": "dispatched", "engine": type(engine).__name__}

    async def _step_analyze_defects(
        self,
        test_run_id: str,
        execution_result: dict[str, Any],
        analysis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 5: 缺陷分析。"""
        await set_task_status(
            test_run_id, "analyzing_defects", {"step": "defect_analysis"}
        )
        await set_task_progress(test_run_id, self.PROGRESS_DEFECT, "缺陷分析")

        try:
            from app.modules.defect_analyzer import DefectAnalyzer

            analyzer = DefectAnalyzer()
            defect_result = await analyzer.analyze(test_run_id)

            logger.info(
                f"[{test_run_id}] Defect analysis completed: "
                f"{defect_result.get('summary', {}).get('total', 0)} defects found"
            )
            return defect_result

        except ImportError:
            logger.warning(
                f"[{test_run_id}] DefectAnalyzer not available, skipping"
            )
            return {"summary": {"total": 0, "by_severity": {}, "by_type": {}}}
        except Exception as e:
            logger.error(f"[{test_run_id}] Defect analysis failed: {e}")
            return {
                "summary": {"total": 0, "by_severity": {}, "by_type": {}},
                "error": str(e),
            }

    async def _step_generate_report(
        self,
        test_run_id: str,
        analysis_result: dict[str, Any],
        execution_result: dict[str, Any],
        defect_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 6: 报告生成。"""
        await set_task_status(test_run_id, "reporting", {"step": "report_generation"})
        await set_task_progress(test_run_id, self.PROGRESS_REPORT, "生成报告")

        try:
            from app.modules.report_generator import ReportGenerator

            generator = ReportGenerator()
            report_result = await generator.generate(
                test_run_id=test_run_id,
                analysis_result=analysis_result,
                defect_result=defect_result,
            )

            logger.info(f"[{test_run_id}] Report generated successfully")
            return report_result

        except ImportError:
            logger.warning(
                f"[{test_run_id}] ReportGenerator not available, skipping"
            )
            return {"status": "skipped", "reason": "module_not_available"}
        except Exception as e:
            logger.error(f"[{test_run_id}] Report generation failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ==================== 数据库辅助 ====================

    async def _update_test_run(
        self, test_run_id: str, **kwargs: Any
    ) -> None:
        """更新 TestRun 记录的指定字段。"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
            )
            run = result.scalar_one_or_none()
            if run is None:
                logger.warning(f"TestRun not found for update: {test_run_id}")
                return

            for key, value in kwargs.items():
                if hasattr(run, key) and value is not None:
                    setattr(run, key, value)

            await session.commit()

    async def _mark_completed(self, test_run_id: str) -> None:
        """标记任务完成。"""
        await set_task_status(test_run_id, "completed")
        await set_task_progress(test_run_id, self.PROGRESS_DONE, "完成")

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TestRun).where(TestRun.id == uuid.UUID(test_run_id))
            )
            run = result.scalar_one_or_none()
            if run:
                run.status = TestStatus.COMPLETED
                run.progress = self.PROGRESS_DONE
                run.completed_at = datetime.utcnow()
                await session.commit()

    async def _mark_failed(self, test_run_id: str, error: str) -> None:
        """标记任务失败。"""
        await set_task_status(test_run_id, "failed", {"error": error[:200]})
        await set_task_progress(test_run_id, 0, f"失败: {error[:100]}")

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

    def get_partial_results(self) -> dict[str, Any]:
        """获取部分执行结果（用于失败时返回已完成的步骤数据）。"""
        return self._partial_results
