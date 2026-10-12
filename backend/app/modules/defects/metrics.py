"""缺陷日快照；看板实时口径与日快照共享状态语义。"""
import asyncio
from datetime import datetime, time, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.models.database import Defect, DefectDailyMetric, DefectWorkflowRevision, Project, ProjectDefectSettings
from app.utils.database import AsyncSessionLocal
from .workflow import DEFAULT_WORKFLOW


async def refresh_daily_metrics():
    calculated_at = datetime.now(timezone.utc)
    updated = 0
    async with AsyncSessionLocal() as db:
        projects = (await db.execute(select(Project).where(Project.is_active.is_(True)))).scalars().all()
        for project in projects:
            settings = await db.get(ProjectDefectSettings, project.id)
            timezone_name = settings.timezone if settings else "Asia/Shanghai"
            try:
                zone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                zone, timezone_name = ZoneInfo("Asia/Shanghai"), "Asia/Shanghai"
            local_date = calculated_at.astimezone(zone).date()
            bucket = datetime.combine(local_date, time.min, zone).astimezone(timezone.utc)
            defects = (await db.execute(select(Defect).where(Defect.project_id == project.id,
                Defect.deleted_at.is_(None)))).scalars().all()
            revision_ids = {item.workflow_revision_id for item in defects if item.workflow_revision_id}
            definitions = {item.id: item.definition_json for item in (await db.execute(select(DefectWorkflowRevision).where(
                DefectWorkflowRevision.id.in_(revision_ids)))).scalars().all()} if revision_ids else {}
            by_state, by_severity, backlog = {}, {}, 0
            for defect in defects:
                by_state[defect.workflow_state] = by_state.get(defect.workflow_state, 0) + 1
                severity = defect.severity.value
                by_severity[severity] = by_severity.get(severity, 0) + 1
                definition = definitions.get(defect.workflow_revision_id, DEFAULT_WORKFLOW)
                state = next((item for item in definition["states"] if item["key"] == defect.workflow_state), {})
                backlog += int(bool(state.get("is_backlog")))
            row = (await db.execute(select(DefectDailyMetric).where(
                DefectDailyMetric.project_id == project.id, DefectDailyMetric.date == bucket,
                DefectDailyMetric.dimension_key == "all", DefectDailyMetric.definition_version == 1))).scalar_one_or_none()
            payload = {"total": len(defects), "backlog": backlog, "by_state": by_state, "by_severity": by_severity}
            if row is None:
                row = DefectDailyMetric(id=uuid4(), project_id=project.id, date=bucket, timezone=timezone_name,
                    definition_version=1, dimension_key="all", dimensions_json={}, metrics_json=payload,
                    calculated_at=calculated_at)
                db.add(row)
            else:
                row.timezone, row.metrics_json, row.calculated_at = timezone_name, payload, calculated_at
            updated += 1
        await db.commit()
    return updated


def run_daily_metrics():
    return asyncio.run(refresh_daily_metrics())
