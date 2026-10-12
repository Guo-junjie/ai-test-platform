"""缺陷迁移只读预检：不运行迁移、不修改业务数据、不输出账号或密钥。"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.utils.database import AsyncSessionLocal


async def inspect_defects():
    async with AsyncSessionLocal() as db:
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        states = (await db.execute(text("SELECT status, count(*) AS count FROM defects GROUP BY status ORDER BY status NULLS FIRST"))).mappings().all()
        invalid = (await db.execute(text("SELECT id, status FROM defects WHERE status IS NOT NULL AND status NOT IN ('open','in_fix','verified','closed','rejected') ORDER BY id"))).mappings().all()
        orphaned = (await db.execute(text("SELECT count(*) FROM defects d LEFT JOIN test_runs r ON r.id=d.test_run_id WHERE coalesce(d.project_id,r.project_id) IS NULL"))).scalar_one()
        repeated = (await db.execute(text("SELECT count(*) FROM (SELECT test_run_id,test_case_id FROM defects WHERE test_run_id IS NOT NULL AND test_case_id IS NOT NULL GROUP BY test_run_id,test_case_id HAVING count(*)>1) groups"))).scalar_one()
        report = {"read_only": True, "migration_head": version, "total": sum(row["count"] for row in states),
                  "legacy_status_distribution": [dict(row) for row in states],
                  "invalid_states": [{"id": str(row["id"]), "status": row["status"]} for row in invalid],
                  "unassigned_project_count": orphaned, "repeated_execution_case_groups": repeated,
                  "can_migrate": not invalid,
                  "notes": ["未知状态必须先人工核对。", "无法归属项目的记录保留，普通成员不可见。", "迁移不补造历史责任人、验证人和过程时间。", "同一次旧检测存在多个缺陷时，保留全部缺陷，只为稳定检测身份选取一条 occurrence。"]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not invalid else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(inspect_defects()))
