"""清理后缺陷流程可重新初始化，模型与账号保持不变；只允许迁移夹具库。"""
import asyncio
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select, text
from app.config import settings
from app.models import database as m
from app.modules.defects.service import create_defect
from app.schemas.defects import DefectCreate
from app.utils.database import AsyncSessionLocal
from scripts.cleanup_test_data import DEFAULT_USERS, PRESERVED_TABLES, cleanup_database, inspect_database


def digest(rows):
    return hashlib.sha256(json.dumps([dict(row) for row in rows], sort_keys=True, default=str).encode()).hexdigest()


async def verify():
    assert settings.POSTGRES_DB.startswith("aitp_defect019_check_legacy_"), "禁止在业务数据库中运行"
    kept_users = sorted(DEFAULT_USERS | {settings.BOOTSTRAP_ADMIN_USERNAME})
    async with AsyncSessionLocal() as db:
        before = {table: digest((await db.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))).mappings().all()) for table in ("ai_model_configs", "model_routing")}
        user_rows = (await db.execute(select(m.User.__table__).where(m.User.username.in_(kept_users)).order_by(m.User.id))).mappings().all()
        user_digest = digest(user_rows)
        assert (await db.execute(select(m.DefectEvent.id).limit(1))).first(), "必须先运行迁移夹具验证"
    await cleanup_database(kept_users)
    targets, counts = await inspect_database()
    assert sum(counts.values()) == 0 and "defect_events" in targets and "defect_occurrences" in targets
    async with AsyncSessionLocal() as db:
        for table, original in before.items():
            assert original == digest((await db.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))).mappings().all())
        users = (await db.execute(select(m.User.__table__).where(m.User.username.in_(kept_users)).order_by(m.User.id))).mappings().all()
        assert user_digest == digest(users)
        assert (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "019"
        owner = (await db.execute(select(m.User).where(m.User.is_active.is_(True), m.User.username.in_(kept_users)).limit(1))).scalar_one()
        project_id = uuid4()
        db.add(m.Project(id=project_id, name="清理后初始化验证", owner_id=owner.id, source_type=m.SourceType.UPLOAD))
        await db.flush()
        defect = await create_defect(db, owner, DefectCreate(project_id=project_id, title="清理后可登记", description="验证默认工作流重建", creation_request_id=uuid4()))
        assert defect.workflow_revision_id and defect.workflow_state == "new" and defect.event_sequence == 1
        await db.rollback()
    print("PASS：新增缺陷业务表已清空；模型、路由、初始化账号与密码哈希保持不变；默认流程可重新初始化。")


if __name__ == "__main__":
    asyncio.run(verify())
