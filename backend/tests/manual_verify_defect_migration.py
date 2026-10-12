"""018→019 迁移夹具验收；只允许独立 legacy 验证库，不作用于平台业务库。"""
import argparse
import asyncio
import json
from datetime import datetime
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import select, text
from app.config import settings
from app.models import database as m
from app.utils.database import AsyncSessionLocal

PROJECT = uuid5(NAMESPACE_URL, "defect019:migration:test-project")
RUN = uuid5(NAMESPACE_URL, "defect019:migration:test-run")
STEPS = ["点击提交", "[备注]保留旧格式内容", "正常操作"]
CASES = [("open", False, "unassigned"), ("in_fix", False, "in_progress"),
         ("verified", True, "resolved"), ("closed", True, "closed"),
         ("rejected", False, "rejected"), (None, True, "resolved"), (None, False, "unassigned")]


def identifier(index):
    return uuid5(NAMESPACE_URL, "defect019:migration:record:" + str(index))


async def verify(stage):
    assert settings.POSTGRES_DB.startswith("aitp_defect019_check_legacy_"), "禁止在其他数据库运行"
    async with AsyncSessionLocal() as db:
        head = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        if stage == "seed":
            assert head == "018"
            owner = (await db.execute(select(m.User.id).limit(1))).scalar_one()
            db.add(m.Project(id=PROJECT, owner_id=owner, name="迁移验证夹具", source_type=m.SourceType.UPLOAD))
            await db.flush()
            db.add(m.TestRun(id=RUN, project_id=PROJECT, user_id=owner, source_type=m.SourceType.UPLOAD))
            await db.flush()
            for index, (state, resolved, _) in enumerate(CASES + [("unexpected", False, "")]):
                await db.execute(text("""INSERT INTO defects (id,test_run_id,title,description,defect_type,severity,
                    reproduce_steps,status,is_resolved,created_at) VALUES
                    (:id,:run,'迁移夹具','原始证据','PROGRAM','P1',CAST(:steps AS jsonb),:state,:resolved,:created)"""),
                    {"id": identifier(index), "run": RUN, "steps": json.dumps(STEPS), "state": state,
                     "resolved": resolved, "created": datetime(2020, 1, 1)})
            await db.commit()
            print("已写入 7 种历史状态及 1 种异常状态夹具（专用隔离库）。")
        elif stage == "remove-invalid":
            assert head == "018", "异常状态迁移必须完整回滚"
            assert not (await db.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='defects' AND column_name='defect_key'"))).first()
            await db.execute(text("DELETE FROM defects WHERE id=:id"), {"id": identifier(7)})
            await db.commit()
            print("异常迁移未修改结构；已移除该专用异常夹具。")
        else:
            assert head == "019"
            for index, (old_state, old_resolved, target) in enumerate(CASES):
                defect = await db.get(m.Defect, identifier(index))
                assert defect.project_id == PROJECT and defect.workflow_state == target
                assert defect.reproduce_steps == STEPS and defect.created_at == datetime(2020, 1, 1)
                assert defect.reporter_id is None and defect.assignee_id is None and defect.resolved_at is None
                baseline = defect.source_metadata["legacy_snapshot"]
                assert baseline["status"] == old_state and baseline["is_resolved"] == old_resolved
                events = (await db.execute(select(m.DefectEvent).where(m.DefectEvent.defect_id == defect.id))).scalars().all()
                assert len(events) == 1 and events[0].event_type == "legacy_imported" and events[0].is_legacy
                assert defect.is_resolved == (target in {"resolved", "closed"})
                if target in {"resolved", "closed", "rejected"}:
                    assert defect.resolution == "legacy_unknown"
            print("PASS：7 种历史状态、任务项目回填、原始步骤/时间、未知责任人及迁移基线全部正确。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["seed", "remove-invalid", "verify"])
    asyncio.run(verify(parser.parse_args().stage))
