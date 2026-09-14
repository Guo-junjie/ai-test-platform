"""从已发布项目测试计划启动 Java 常驻服务，并验证 Test Run 自动关联 Coverage Run。"""

import argparse
import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.database import (
    CoverageReport, CoverageRun, EnvironmentProfile, EnvironmentProfileRevision,
    Project, TestCaseAsset, TestPlan,
    TestPlanRevision, TestPlanRevisionCase, TestResult, TestRun, TestStatus, User,
)
from app.modules.runs.case_snapshot import case_content_hash, executable_case_payload
from app.modules.runs.orchestrator import RunOrchestrator
from app.utils.database import AsyncSessionLocal


async def main(mismatch: bool = False) -> None:
    requested_commit = "wrong-java-commit" if mismatch else "java-sample-v1"
    async with AsyncSessionLocal() as db:
        project = (await db.execute(select(Project).where(
            Project.name == "覆盖率验收样例（Java 常驻）"))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        environment = (await db.execute(select(EnvironmentProfile).where(
            EnvironmentProfile.project_id == project.id,
            EnvironmentProfile.name == "Java JaCoCo 测试环境"))).scalar_one_or_none()
        if environment is None:
            environment = EnvironmentProfile(
                id=uuid.uuid4(), project_id=project.id, name="Java JaCoCo 测试环境",
                base_url="http://aitp-java-sample:8204", healthcheck_path="/health",
                status="published", created_by=user.id,
            )
            db.add(environment)
            await db.flush()
            env_revision = EnvironmentProfileRevision(
                id=uuid.uuid4(), profile_id=environment.id, revision=1,
                config_json={"base_url": environment.base_url,
                             "healthcheck_path": "/health", "auth_strategy": "none",
                             "auth_config": {}},
                health_status="healthy", status="published",
                published_at=datetime.utcnow(), published_by=user.id,
            )
            db.add(env_revision)
            await db.flush()
            environment.current_revision_id = env_revision.id
        asset = TestCaseAsset(
            id=uuid.uuid4(), project_id=project.id, case_type="positive",
            execution_kind="api", title="Java 项目计划：查询订单",
            request_data={"method": "GET", "url": "/orders/1"},
            expected_result={"status_code": 200}, created_by=user.id,
        )
        db.add(asset)
        await db.flush()
        plan = TestPlan(id=uuid.uuid4(), project_id=project.id,
                        name=f"Java 覆盖率验收计划 {uuid.uuid4().hex[:8]}", created_by=user.id)
        db.add(plan)
        await db.flush()
        revision = TestPlanRevision(
            id=uuid.uuid4(), plan_id=plan.id, revision=1,
            plan_state_hash=case_content_hash(asset), case_count=1, enabled_count=1,
            status="published", created_by=user.id,
            environment_profile_id=environment.id,
        )
        db.add(revision)
        db.add(TestPlanRevisionCase(
            revision_id=revision.id, case_asset_id=asset.id, title=asset.title,
            execution_kind="api", enabled=True, sort_order=0,
            case_payload=executable_case_payload(asset), content_hash=case_content_hash(asset),
        ))
        await db.commit()
        dispatched = await RunOrchestrator.create_plan_run(
            plan.id, db, user_id=user.id, commit_sha=requested_commit)

    run_id = uuid.UUID(dispatched["test_run_id"])
    print(json.dumps({"plan_id": str(plan.id), "test_run_id": str(run_id)}, ensure_ascii=False), flush=True)
    for _ in range(90):
        await asyncio.sleep(2)
        async with AsyncSessionLocal() as db:
            run = (await db.execute(select(TestRun).where(TestRun.id == run_id))).scalar_one()
            if run.status not in {TestStatus.COMPLETED, TestStatus.FAILED, TestStatus.CANCELLED}:
                continue
            coverage = (await db.execute(select(CoverageRun).where(
                CoverageRun.test_run_id == run_id))).scalar_one_or_none()
            report = (await db.execute(select(CoverageReport).where(
                CoverageReport.test_run_id == run_id))).scalar_one_or_none()
            result = (await db.execute(select(TestResult).where(
                TestResult.test_run_id == run_id))).scalar_one_or_none()
            summary = {"test_status": run.status.value, "test_error": run.error_message,
                       "commit_sha": run.commit_sha,
                       "coverage_status": coverage.status if coverage else None,
                       "coverage_error": coverage.error_message if coverage else None,
                       "report_id": str(report.id) if report else None,
                       "covered_lines": coverage.covered_lines if coverage else None,
                       "api_case_passed": result.is_passed if result else None}
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if mismatch:
                valid = (run.status == TestStatus.FAILED and run.commit_sha == requested_commit
                         and coverage and coverage.status == "FAILED" and not report
                         and "不一致" in (coverage.error_message or ""))
            else:
                valid = (run.status == TestStatus.COMPLETED and run.commit_sha == requested_commit
                         and coverage and coverage.status == "COMPLETED"
                         and report and coverage.covered_lines and result and result.is_passed)
            if not valid:
                raise SystemExit(1)
            return
    raise SystemExit("项目测试计划验收超时")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mismatch", action="store_true", help="验收部署提交号不一致时拒绝采集")
    asyncio.run(main(parser.parse_args().mismatch))
