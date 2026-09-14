"""在已部署的平台容器内触发独立 Python 样例的真实 Celery 测试链路。

运行：python tests/manual_verify_coverage_agent.py
需要先启动 test-agent/compose.example.yml，并将 COVERAGE_AGENT_SAMPLE_TOKEN 注入 worker。
此脚本只创建独立验收项目和测试任务，不修改现有项目。
"""

import asyncio
import json
import uuid

from sqlalchemy import select

from app.models.database import (
    CoverageReport, CoverageRun, CoverageService, Project, SourceType, TestCase,
    TestResult, TestRun, TestStatus, User,
)
from app.modules.execution.engine import TestExecutionEngine
from app.utils.database import AsyncSessionLocal


async def main() -> None:
    case = {"case_name": "查询已支付订单", "request": {"method": "GET", "url": "/orders/1"},
            "expected": {"status_code": 200}}
    project_id, run_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one()
        existing = (await db.execute(select(Project).where(
            Project.name == "覆盖率验收样例（Python）").order_by(Project.created_at.desc()).limit(1))).scalar_one_or_none()
        if existing:
            project_id = existing.id
        else:
            db.add(Project(id=project_id, name="覆盖率验收样例（Python）", owner_id=user.id,
                           source_type=SourceType.UPLOAD,
                           source_config={"coverage_config": {"enabled": True, "required": True,
                               "services": [{"name": "sample-python", "agent_url": "http://host.docker.internal:8765",
                                             "token_env": "COVERAGE_AGENT_SAMPLE_TOKEN", "language": "python",
                                             "tool": "coverage.py", "primary": True}]}},
                           quality_gate_config={"auto_coverage": True}))
        db.add(TestRun(id=run_id, project_id=project_id, user_id=user.id,
                       source_type=SourceType.UPLOAD, status=TestStatus.PENDING,
                       analysis_result={"tech_stack": {"stack": "python"}}))
        db.add(TestCase(test_run_id=run_id, case_type="api", case_name=case["case_name"],
                        request_data=case["request"], expected_result=case["expected"],
                        api_path="/orders/1", http_method="GET"))
        await db.commit()

    root_task_id = TestExecutionEngine().execute_all(
        str(run_id), {"tech_stack": {"stack": "python"}},
        {"api": [case], "performance": [], "integration": []})
    print(json.dumps({"project_id": str(project_id), "test_run_id": str(run_id),
                      "celery_task_id": root_task_id}, ensure_ascii=False), flush=True)

    for _ in range(90):
        await asyncio.sleep(2)
        async with AsyncSessionLocal() as db:
            run = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one()
            coverage = (await db.execute(select(CoverageRun).where(
                CoverageRun.test_run_id == run_id))).scalar_one_or_none()
            if run.status not in {TestStatus.COMPLETED, TestStatus.FAILED, TestStatus.CANCELLED}:
                continue
            service = (await db.execute(select(CoverageService).where(
                CoverageService.coverage_run_id == coverage.id))).scalar_one_or_none() if coverage else None
            report = (await db.execute(select(CoverageReport).where(
                CoverageReport.test_run_id == run_id))).scalar_one_or_none()
            result = (await db.execute(select(TestResult).where(
                TestResult.test_run_id == run_id))).scalar_one_or_none()
            summary = {"test_status": run.status.value, "test_error": run.error_message,
                       "coverage_status": coverage.status if coverage else None,
                       "coverage_error": coverage.error_message if coverage else None,
                       "service_status": service.status if service else None,
                       "line_rate": coverage.line_rate if coverage else None,
                       "covered_lines": coverage.covered_lines if coverage else None,
                       "report_id": str(report.id) if report else None,
                       "api_case_passed": result.is_passed if result else None,
                       "api_status_code": result.status_code if result else None}
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if not (run.status == TestStatus.COMPLETED and coverage and coverage.status == "COMPLETED"
                    and coverage.covered_lines and report and result and result.is_passed
                    and result.status_code == 200):
                raise SystemExit(1)
            return
    raise SystemExit("Celery 验收任务超时")


if __name__ == "__main__":
    asyncio.run(main())
