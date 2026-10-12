"""报告重生成复用检测身份，不重建人工协作资产。"""
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models.database import Defect, DefectOccurrence, DefectSeverity, TestCase, TestResult, TestRun
from app.utils.logger import get_logger
from .service import append_event, ensure_workflow, utcnow
from .workflow import project_state

logger = get_logger(__name__)


def detection_signature(case_id):
    return hashlib.sha256(("case:" + str(case_id)).encode()).hexdigest()


async def persist_run_defects(db, run_id, items, category_mapping, project_id=None):
    run = (await db.execute(select(TestRun).where(TestRun.id == run_id).with_for_update())).scalar_one_or_none()
    if run is None:
        raise ValueError("自动发现缺陷关联的测试运行不存在")
    if project_id and UUID(str(project_id)) != run.project_id:
        raise ValueError("缺陷项目归属必须与真实测试运行一致")
    cases = (await db.execute(select(TestCase).where(TestCase.test_run_id == run.id))).scalars().all()
    case_map = {item.id: item for item in cases}
    results = (await db.execute(select(TestResult).where(TestResult.test_run_id == run.id).order_by(TestResult.executed_at))).scalars().all()
    result_map = {item.test_case_id: item for item in results}
    occurrences = (await db.execute(select(DefectOccurrence).where(DefectOccurrence.test_run_id == run.id))).scalars().all()
    existing = {item.signature for item in occurrences}
    revision = None
    inserted = 0
    candidates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates.append(item)
        # 旧分析器的 AI 分组可能改变主用例。按真实用例展开后，重生成报告仍
        # 能复用每一条检测身份；分组只是建议，不自动合并团队管理的缺陷资产。
        related = item.get("related_cases")
        for related_case in related if isinstance(related, list) else []:
            if isinstance(related_case, dict):
                candidates.append({**item, "case_id": related_case.get("case_id"),
                                   "case_name": related_case.get("case_name"), "ai_grouped": True})
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if item.get("category") in {"infrastructure_error", "environment_error"}:
            continue
        try:
            case_id = UUID(str(item.get("case_id")))
        except (ValueError, TypeError):
            logger.warning("[%s] AI 缺陷缺少真实执行用例，保留在报告中，不创建无法追踪的缺陷资产", run.id)
            continue
        case = case_map.get(case_id)
        result = result_map.get(case_id)
        if case is None or result is None or result.is_passed:
            logger.warning("[%s] 忽略无法关联本次失败检测的 AI 缺陷", run.id)
            continue
        signature = detection_signature(case_id)
        if signature in existing:
            continue
        if revision is None:
            revision = await ensure_workflow(db, run.project_id)
        from app.models.database import DefectType
        category = str(item.get("category") or item.get("defect_type") or "").lower()
        kind = category_mapping.get(category, DefectType.PROGRAM)
        try:
            severity = DefectSeverity(item.get("severity", "P2"))
        except ValueError:
            severity = DefectSeverity.P2
        steps = item.get("reproduction_steps") or item.get("reproduce_steps") or []
        if isinstance(steps, str):
            steps = [steps]
        if not isinstance(steps, list):
            steps = []
        title = str(item.get("title") or item.get("case_name") or "自动化测试发现缺陷")[:500]
        defect = Defect(id=uuid4(), project_id=run.project_id, test_run_id=run.id, test_case_id=case.id,
                        reporter_id=run.user_id, title=title,
                        description=str(item.get("description") or item.get("root_cause") or title),
                        defect_type=kind, severity=severity, priority="normal", labels=[],
                        reproduce_steps=[str(value)[:2000] for value in steps[:100]],
                        root_cause=item.get("root_cause"), fix_suggestion=item.get("fix_suggestion"),
                        source="pipeline", source_metadata={"test_result_id": str(result.id), "signature_version": 1,
                                                             "ai_grouped": bool(item.get("ai_grouped"))},
                        workflow_state="new", workflow_revision_id=revision.id, row_version=1,
                        event_sequence=0, reopened_count=0, updated_at=utcnow())
        if run.environment_profile_id:
            from .service import prepare_fields
            from .permissions import DefectContext
            from app.models.database import Project
            project = (await db.execute(select(Project).where(Project.id == run.project_id))).scalar_one()
            fields = await prepare_fields(db, DefectContext(project, None, set(), False),
                                          {"environment_profile_id": run.environment_profile_id})
            for key, value in fields.items():
                setattr(defect, key, value)
            # 运行时的修订版是证据，不用环境当前发布版冒充当次版本。
            if run.environment_revision_id:
                from app.models.database import EnvironmentProfileRevision
                revision_env = (await db.execute(select(EnvironmentProfileRevision).where(
                    EnvironmentProfileRevision.id == run.environment_revision_id,
                    EnvironmentProfileRevision.profile_id == run.environment_profile_id))).scalar_one_or_none()
                if revision_env:
                    defect.environment_revision_id = revision_env.id
                    # 只展示名称。URL 使用运行当时地址并剔除凭据及查询。
                    from urllib.parse import urlsplit
                    parsed = urlsplit(run.target_service_url or "")
                    defect.environment_snapshot = {"name": defect.environment_snapshot.get("name"),
                                                   "base_url": parsed.scheme + "://" + (parsed.hostname or "") +
                                                   ((":" + str(parsed.port)) if parsed.port else "") + parsed.path}
        project_state(defect)
        db.add(defect)
        await db.flush()
        evidence = {"status_code": result.status_code, "is_passed": result.is_passed,
                    "method": case.http_method or (case.request_data or {}).get("method"), "path": case.api_path}
        db.add(DefectOccurrence(id=uuid4(), defect_id=defect.id, project_id=run.project_id,
                                test_run_id=run.id, test_case_id=case.id, test_result_id=result.id,
                                case_asset_id=case.case_asset_id, signature=signature, signature_version=1,
                                evidence_json=evidence, observed_at=utcnow()))
        append_event(db, defect, None, "created", {}, extra={"source": "pipeline", "test_result_id": str(result.id)})
        existing.add(signature)
        inserted += 1
    await db.flush()
    return inserted
