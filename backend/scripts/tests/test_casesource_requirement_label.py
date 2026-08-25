"""端到端验证：CaseSource.REQUIREMENT 新 label 在 PG 端确实可用（不抛 InvalidTextRepresentationError）。

触发原因
--------
用户 2026-08-25 11:10 报：
- POST /api/requirements/{id}/generate-cases → 500 ``invalid input value for enum casesource: "requirement"``
- GET /api/cases?source=requirement → 同样 500

根因
----
PG 端 ``casesource`` enum 仅有历史 label（大写 ``AI_GENERATED / MANUAL`` 或早期大写变种），
``commit 182fb2b`` 在 ORM 加了 ``CaseSource.REQUIREMENT = "requirement"`` 但 PG enum label 集未同步。
SQLAlchemy 通过 ``values_callable=lambda x: [e.value for e in x]`` 写 .value 小写，
PG 端没 'requirement' label → 抛 InvalidTextRepresentationError。

本测试做的事
------------
1. 查 PG 端 ``casesource`` 当前 label 集，与 ORM ``CaseSource`` 期望对比
2. 缺 label 时**就地 ALTER TYPE ADD VALUE**（不依赖 init_db 重启）
3. 再用 ORM INSERT 一行 ``TestCaseAsset(source=CaseSource.REQUIREMENT)`` 验证能落库
4. SELECT 回读这行，验证 round-trip（不抛 LookupError / 不丢字段）

怎么跑
------
- 部署机内：``docker compose exec backend python -m scripts.tests.test_casesource_requirement_label``
- 本机：``DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/db python -m scripts.tests.test_casesource_requirement_label``

退出码
------
- 0 — 全部通过（同步 + INSERT + SELECT round-trip）
- 2 — PG 连不上（无法验证）
- 1 — 同步失败或 round-trip 抛错
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 让脚本能 import app.* —— 同 scripts/verify_kb_rag.py 套路
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PARENT = Path(__file__).resolve().parents[3]
for p in (str(_PARENT), str(_BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uuid  # noqa: E402

from sqlalchemy import delete, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.utils.database import async_engine, AsyncSessionLocal  # noqa: E402
from app.utils.enum_sync import sync_enum_case_pairs  # noqa: E402
from app.models.database import (  # noqa: E402
    CaseSource,
    Project,
    TestCaseAsset,
)


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def ok(msg: str) -> None:
    print(f"  ✅ PASS  {msg}")


def fail(msg: str, fix: str = "") -> None:
    print(f"  ❌ FAIL  {msg}")
    if fix:
        print(f"           → 修复：{fix}")


def warn(msg: str) -> None:
    print(f"  ⚠ WARN  {msg}")


async def step1_pg_has_casesource_type(db: AsyncSession) -> bool:
    section("① PG 端 casesource enum 是否存在")
    try:
        row = (await db.execute(text("SELECT enum_range(NULL::casesource)"))).scalar()
        labels = set((row or "").strip("{}").split(",")) if isinstance(row, str) else set(row or [])
        ok(f"casesource 当前 PG label: {sorted(labels)}")
        return True
    except Exception as exc:  # noqa: BLE001
        fail(f"casesource enum 不存在或查询失败: {exc}", "重启 backend 让 init_db create_all 建枚举")
        return False


async def step2_ensure_labels(autocommit_conn) -> set:
    section("② 补齐 ORM CaseSource 期望的 label（.name ∪ .value）")
    expected = {m.name for m in CaseSource} | {m.value for m in CaseSource}
    cur_row = await autocommit_conn.execute(text("SELECT enum_range(NULL::casesource)"))
    cur_range = cur_row.scalar() or ""
    if isinstance(cur_range, str):
        current = set(filter(None, cur_range.strip("{}").split(",")))
    else:
        current = set(cur_range or [])
    missing = expected - current
    if missing:
        warn(f"缺 label {sorted(missing)}，开始 ALTER TYPE ADD VALUE IF NOT EXISTS")
    async with async_engine.connect() as conn:
        ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        report = await sync_enum_case_pairs(ac)
    casesource_info = report.get("casesource", {})
    added_clean = [a for a in casesource_info.get("added", []) if not a.startswith("❌")]
    failed = [a for a in casesource_info.get("added", []) if a.startswith("❌")]
    if failed:
        fail(f"同步失败：{failed}", "重启 backend 由 init_db 单独处理；或 docker compose down -v 重建数据库")
        return current
    if added_clean:
        ok(f"casesource 新增 label: {added_clean}")
    else:
        ok("casesource 全部 label 已齐")
    # 再确认一次
    cur_row = await autocommit_conn.execute(text("SELECT enum_range(NULL::casesource)"))
    cur_range = cur_row.scalar() or ""
    if isinstance(cur_range, str):
        new_set = set(filter(None, cur_range.strip("{}").split(",")))
    else:
        new_set = set(cur_range or [])
    final_missing = expected - new_set
    if final_missing:
        fail(f"仍然缺 label: {sorted(final_missing)}", "重启 backend 让 init_db 单独处理")
        return new_set
    return new_set


async def step3_insert_round_trip(db: AsyncSession) -> bool:
    section("③ ORM 写 source=CaseSource.REQUIREMENT → 回读验证（不抛 InvalidTextRepresentationError）")
    # 找一个 e2e-demo-project（也可能不存在）— 不能依赖项目存在，用硬创建临时
    proj_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    try:
        # 写一行（init test fixture — 缺 project 就直接 INSERT project）
        proj_id = uuid.UUID("84a23092-198f-428c-841c-b23096463dc0")  # 用户日志里的 demo-project
        # 先确保 project 存在（不一定有）
        proj = (await db.execute(select(Project).where(Project.id == proj_id))).scalar_one_or_none()
        if proj is None:
            warn(f"project {proj_id} 不存在，改用临时 UUID 写测试行")
            proj_id = uuid.uuid4()
            # 临时建一个空 project（不进 commit 可能 rollback？commit 写入）
            await db.execute(text(
                "INSERT INTO projects(id, name, code, owner_id, created_at, updated_at) "
                "VALUES (:id, :name, :code, :owner_id, NOW(), NOW())"
            ), {
                "id": str(proj_id),
                "name": "__test_casesource_requirement__",
                "code": "test-casesource-req",
                "owner_id": "6ae0f3f6-f120-4e50-b5f6-e953bed2b130",  # 用户日志里的 user id
            })

        # 清理重复（同一 asset_id 跑两次时）
        await db.execute(delete(TestCaseAsset).where(TestCaseAsset.id == asset_id))

        # 写测试行 — 这就是要测的根因路径
        asset = TestCaseAsset(
            id=asset_id,
            project_id=proj_id,
            title="[TEST] casesource=REQUIREMENT round-trip",
            status="draft",
            source=CaseSource.REQUIREMENT,
        )
        db.add(asset)
        await db.commit()
        ok(f"INSERT source=REQUIREMENT OK → asset_id={asset_id}")

        # 回读 — SELECT WHERE source='requirement' 不能抛 InvalidTextRepresentationError
        row = (await db.execute(
            select(TestCaseAsset).where(TestCaseAsset.source == CaseSource.REQUIREMENT)
        )).scalars().first()
        if row is None:
            fail("SELECT WHERE source=REQUIREMENT 返回空",
                 "可能写入端用了大写 'REQUIREMENT' 但 PG 只有 'requirement'")
            return False
        # round-trip 应让 .source == CaseSource.REQUIREMENT
        if row.source is not CaseSource.REQUIREMENT:
            fail(f"round-trip 失真: {row.source!r} != CaseSource.REQUIREMENT",
                 "检查 CasePairEnum.values_callable")
            return False
        ok(f"SELECT 回读 .source = {row.source!r}（round-trip 一致）")

        # 清理测试行
        await db.execute(delete(TestCaseAsset).where(TestCaseAsset.id == asset_id))
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        fail(f"INSERT 或 SELECT 抛错: {type(exc).__name__}: {exc}",
             "确认 PG casesource 已含 'requirement' label；"
             "若已含仍报错，检查 SAEnum 的 values_callable")
        return False
    finally:
        # 顺手清理临时 project（不影响）
        try:
            await db.execute(text(
                "DELETE FROM projects WHERE code = 'test-casesource-req'"
            ))
            await db.commit()
        except Exception:
            await db.rollback()


async def main() -> int:
    print("🔍 CaseSource.REQUIREMENT 真 PG round-trip 验证 @ " + datetime.utcnow().isoformat() + "Z")
    try:
        async with async_engine.connect() as conn:
            health = (await conn.execute(text("SELECT 1"))).scalar()
            if health != 1:
                fail("PG 连不上（SELECT 1 != 1）", "检查 DATABASE_URL")
                return 2
    except Exception as exc:  # noqa: BLE001
        fail(f"PG 连不上: {exc}",
             "检查 DATABASE_URL / docker compose ps postgres；"
             "本机测试用 DATABASE_URL=postgresql+asyncpg://...@localhost:5432/...")
        return 2

    async with AsyncSessionLocal() as db:
        # ①
        if not await step1_pg_has_casesource_type(db):
            return 1
        # ② — 同步（用 autocommit 连接）
        async with async_engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            labels = await step2_ensure_labels(ac)
            if not labels:
                return 1
            # ③ — INSERT + SELECT round-trip
            ok_round_trip = await step3_insert_round_trip(db)
        if not ok_round_trip:
            return 1

    print()
    print("=" * 72)
    print("  🎉 全部通过：CaseSource.REQUIREMENT 在 PG 端可用，无 InvalidTextRepresentationError")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    finally:
        try:
            asyncio.run(async_engine.dispose())
        except Exception:
            pass
    sys.exit(rc)
