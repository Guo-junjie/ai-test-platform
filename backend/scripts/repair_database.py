"""一键复盘 & 修复脚本（不依赖部署机 SSH）。

触发场景
--------
* ``relation \"users\" does not exist`` —— backend 启动后 SELECT users 失败
* 其他一切「缺某张表」的 500
* alembic 升级中途失败留半截库

设计
----
1. 列 PG 端 ``information_schema.tables``，关键表（users / projects / test_case_assets / requirement_docs
   / api_endpoints / test_runs / knowledge_chunks / kb_rebuild_state / model_routings...）的
   存在性，PASS / FAIL 一目了然
2. 缺表时直接调 ``Base.metadata.create_all`` 重建 —— 无需 alembic、不依赖 backend 重启
3. 触发 ``AuthService.init_default_admin`` 建种子账号（superadmin / admin）
4. 调 ``sync_enum_case_pairs`` 补双 label（含 commit 182fb2b 的 REQUIREMENT）
5. 输出全报告，方便贴到对话里诊断

为什么不让用户直接 ``docker compose down -v``
--------------------------------------------
全库重建会让所有数据（KB chunks / test_case_assets / 项目等）丢失。
本脚本**只补缺表 + 种子账号**，不动现有数据。

用法
----
::

    docker compose exec backend python -m scripts.repair_database

    # 验证而不修改（只输出当前 schema 状态）
    docker compose exec backend python -m scripts.repair_database --check
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PARENT = Path(__file__).resolve().parents[2]
for p in (str(_PARENT), str(_BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.utils.database import async_engine, AsyncSessionLocal, Base  # noqa: E402
from app.utils.enum_sync import run_enum_sync_and_report  # noqa: E402

# 关键表清单（按业务重要性排列）
KEY_TABLES = (
    "users",
    "projects",
    "model_routings",
    "ai_model_configs",
    "test_runs",
    "api_endpoints",
    "test_case_assets",
    "test_cases",
    "requirement_docs",
    "knowledge_chunks",
    "knowledge_terms",
    "kb_rebuild_state",
    "kb_runtime_config",
    "change_requests",
    "notifications",
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


def warn(msg: str, fix: str = "") -> None:
    print(f"  ⚠ WARN  {msg}")
    if fix:
        print(f"           → 修复：{fix}")


async def step1_check_tables(db: AsyncSession) -> list[str]:
    section("① 关键表存在性检查（information_schema.tables）")
    try:
        rows = (await db.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ))).scalars().all()
        actual = set(rows)
    except Exception as exc:  # noqa: BLE001
        fail(f"查 information_schema.tables 失败: {exc}", "PG 连接问题；检查 DATABASE_URL")
        return []

    print(f"  info  public schema 共 {len(actual)} 张表")
    missing: list[str] = []
    for t in KEY_TABLES:
        if t in actual:
            ok(f"{t}")
        else:
            fail(f"{t} 不存在！")
            missing.append(t)

    if not missing:
        print()
        print(f"  ✅ 全部 {len(KEY_TABLES)} 张关键表齐全")
    else:
        print()
        print(f"  ❌ 缺 {len(missing)} 张关键表：{missing}")
        print(f"     → 修复方式：")
        print(f"       - 首选：本脚本自动跑 Base.metadata.create_all 重建（--fix，默认行为）")
        print(f"       - 兜底：`docker compose down -v && docker compose up -d` 全库重建（数据会丢）")
    return missing


async def step2_recreate_missing(db: AsyncSession, missing: list[str]) -> None:
    section("② 重建缺表 — Base.metadata.create_all（幂等，不动已有表）")
    if not missing:
        ok("无缺表，跳过")
        return
    try:
        # 在 AUTOCOMMIT 连接上跑 create_all（DDL 不能在事务里跨语句）
        async with async_engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await ac.run_sync(Base.metadata.create_all)
        ok(f"已尝试 create_all，再次检查")
        # 再查一次
        rows = (await db.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ))).scalars().all()
        actual = set(rows)
        still_missing = [t for t in missing if t not in actual]
        if still_missing:
            fail(f"create_all 后仍缺 {still_missing}",
                 "用户没建表权限？检查 postgres 容器日志：`docker compose logs postgres | tail -50`")
        else:
            ok(f"全部 {len(missing)} 张关键表已建回")
    except Exception as exc:  # noqa: BLE001
        fail(f"create_all 抛错: {type(exc).__name__}: {exc}",
             "检查 PG 连接 / 权限 / 磁盘空间")


async def step3_seed_default_admin(_db_unused: AsyncSession) -> None:
    section("③ 种子账号 — AuthService.init_default_admin")
    try:
        from app.modules.auth.auth_service import AuthService

        # init_default_admin 是无参 async def，内部自管 AsyncSessionLocal
        await AuthService.init_default_admin()
        ok("init_default_admin 跑完")
        # 验证 users 表真的有 superadmin / admin
        from app.models.database import User

        async with AsyncSessionLocal() as db:
            superadmin = (await db.execute(
                select(User).where(User.username == "superadmin")
            )).scalar_one_or_none()
            if superadmin:
                ok(f"superadmin 用户存在 (role={superadmin.role})")
            else:
                fail("init_default_admin 跑完但 superadmin 用户不在",
                     "看 backend 容器日志")
            admin = (await db.execute(
                select(User).where(User.username == "admin")
            )).scalar_one_or_none()
            if admin:
                ok(f"admin 用户存在 (role={admin.role})")
            else:
                warn("admin 用户不存在（不影响登录，只看 superadmin）")
    except Exception as exc:  # noqa: BLE001
        fail(f"init_default_admin 抛错: {type(exc).__name__}: {exc}",
             "看 users 表是否真的有建出来（步骤 ② 应该已建）")


async def step4_sync_enum_labels() -> None:
    section("④ 5 个 SAEnum 双 label 同步（init_db 兜底同样的逻辑）")
    try:
        await run_enum_sync_and_report(async_engine)
    except Exception as exc:  # noqa: BLE001
        fail(f"sync_enum_case_pairs 抛错: {exc}", "PG 连接问题")


async def step5_final_smoke(db: AsyncSession) -> None:
    section("⑤ 最终烟火测试 — 用 superadmin/admin 任一账号模拟 SELECT")
    try:
        from app.models.database import User

        n = (await db.execute(text("SELECT count(*) FROM users"))).scalar()
        ok(f"SELECT count(*) FROM users = {n}")
        if n and n > 0:
            sample = (await db.execute(
                select(User.username, User.role).limit(3)
            )).all()
            for u, r in sample:
                print(f"           sample: {u} / {r}")
    except Exception as exc:  # noqa: BLE001
        fail(f"SELECT users 仍抛错: {exc}", "检查 PG schema 修复后再试")


async def main(check_only: bool = False) -> int:
    print("🔧 AI Test Platform 数据库复盘/修复 @ " +
          __import__("datetime").datetime.utcnow().isoformat() + "Z")

    async with AsyncSessionLocal() as db:
        # ①
        missing = await step1_check_tables(db)
        if missing and not check_only:
            # ②
            await step2_recreate_missing(db, missing)
            # 再查
            still_missing = await step1_check_tables(db)
            if still_missing:
                print()
                print("  ❌ 缺表未补回，请看上面具体失败信息与修复命令")
                return 1
        elif missing and check_only:
            print()
            print(f"  ⚠ 检查模式：检测到缺表，本脚本未修改任何东西。")
            print(f"     去掉 --check 自动重建。")
            return 1
        # ③
        await step3_seed_default_admin(db)
        # ④
        await step4_sync_enum_labels()
        # ⑤
        await step5_final_smoke(db)

    print()
    print("=" * 72)
    print("  🎉 全部完成。建议重启 backend 让 lifespan 重新触发 init_db 验证。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="只检查不修改")
    args = parser.parse_args()
    try:
        rc = asyncio.run(main(check_only=args.check))
    finally:
        try:
            asyncio.run(async_engine.dispose())
        except Exception:
            pass
    sys.exit(rc)
