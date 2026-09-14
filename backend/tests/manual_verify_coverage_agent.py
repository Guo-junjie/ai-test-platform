"""在已部署的平台容器内触发 Python、Go 或 Java 样例的真实 Celery 测试链路。

运行：python tests/manual_verify_coverage_agent.py [--language python|go|iotfast|java]
需要先启动对应的 test-agent/compose.*example.yml，并将令牌注入 worker。
此脚本只创建独立验收项目和测试任务，不修改现有项目。
"""

import argparse
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


SAMPLES = {
    "python": {"name": "覆盖率验收样例（Python）", "service": "sample-python",
               "url": "http://host.docker.internal:8765", "token": "COVERAGE_AGENT_SAMPLE_TOKEN",
               "tool": "coverage.py"},
    "go": {"name": "覆盖率验收样例（Go）", "service": "sample-go",
           "url": "http://host.docker.internal:8766", "token": "COVERAGE_AGENT_GO_SAMPLE_TOKEN",
           "tool": "go_cover"},
    "iotfast": {"name": "覆盖率验收样例（IoTFast）", "service": "iotfast-go",
                "url": "http://host.docker.internal:8768", "token": "COVERAGE_AGENT_IOTFAST_TOKEN",
                "tool": "go_cover", "language": "go", "path": "/swagger",
                "case_name": "访问 IoTFast Swagger 页面"},
    "java": {"name": "覆盖率验收样例（Java 常驻）", "service": "sample-java",
             "url": "http://host.docker.internal:8767", "token": "COVERAGE_AGENT_JAVA_SAMPLE_TOKEN",
             "tool": "jacoco", "path": "/orders/1", "commit": "java-sample-v1"},
}


async def main(language: str = "python", min_line_rate: float | None = None) -> None:
    sample = SAMPLES[language]
    project_name = sample["name"] if min_line_rate is None else sample["name"] + "（门禁验收）"
    target_language = sample.get("language", language)
    path = sample.get("path", "/orders/1")
    case = {"case_name": sample.get("case_name", "查询已支付订单"),
            "request": {"method": "GET", "url": path},
            "expected": {"status_code": 200}}
    project_id, run_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one()
        existing = (await db.execute(select(Project).where(
            Project.name == project_name).order_by(Project.created_at.desc()).limit(1))).scalar_one_or_none()
        if existing:
            project_id = existing.id
        else:
            db.add(Project(id=project_id, name=project_name, owner_id=user.id,
                           source_type=SourceType.UPLOAD,
                           source_config={"coverage_config": {"enabled": True, "required": True,
                               "min_line_rate": min_line_rate,
                               "services": [{"name": sample["service"], "agent_url": sample["url"],
                                             "token_env": sample["token"], "language": target_language,
                                             "tool": sample["tool"], "primary": True}]}},
                           quality_gate_config={"auto_coverage": True}))
        db.add(TestRun(id=run_id, project_id=project_id, user_id=user.id,
                       source_type=SourceType.UPLOAD, status=TestStatus.PENDING,
                       commit_sha=sample.get("commit"),
                       analysis_result={"tech_stack": {"stack": target_language}}))
        db.add(TestCase(test_run_id=run_id, case_type="api", case_name=case["case_name"],
                        request_data=case["request"], expected_result=case["expected"],
                        api_path=path, http_method="GET"))
        await db.commit()

    root_task_id = TestExecutionEngine().execute_all(
        str(run_id), {"tech_stack": {"stack": target_language}},
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
            expected_status = TestStatus.FAILED if min_line_rate is not None else TestStatus.COMPLETED
            expected_coverage_status = "FAILED" if min_line_rate is not None else "COMPLETED"
            if not (run.status == expected_status and coverage and coverage.status == expected_coverage_status
                    and coverage.covered_lines and report and result and result.is_passed
                    and result.status_code == 200 and
                    (min_line_rate is None or coverage.line_rate < min_line_rate)):
                raise SystemExit(1)
            return
    raise SystemExit("Celery 验收任务超时")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=SAMPLES, default="python")
    parser.add_argument("--min-line-rate", type=float, default=None,
                        help="设置高于样例实际值的门槛，验收严格模式会阻断测试任务")
    args = parser.parse_args()
    asyncio.run(main(args.language, args.min_line_rate))
