"""清理平台业务/测试数据，保留 AI 模型配置、路由和初始化账号。

推荐通过仓库根目录的 ``cleanup-test-data.sh`` 调用；脚本也可在 backend
容器内单独执行：

    python scripts/cleanup_test_data.py --dry-run
    python scripts/cleanup_test_data.py --yes

数据库表采用动态发现，未来新增业务表后无需继续维护删除顺序。所有业务表在
同一事务中 TRUNCATE；任何一步失败都会回滚数据库部分。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy import bindparam, text


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.utils.database import AsyncSessionLocal  # noqa: E402


PRESERVED_TABLES = frozenset({
    "alembic_version",
    "ai_model_configs",
    "model_routing",
    "users",
})
DEFAULT_USERS = frozenset({
    "superadmin",
    "admin",
    "tester",
    "developer",
    "viewer",
})
PRESERVED_DATA_DIRS = frozenset({"embedding-cache"})
IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def cleanup_targets(all_tables: Iterable[str]) -> list[str]:
    """返回需要清空的业务表，结果稳定排序并拒绝异常标识符。"""
    result = []
    for table in sorted(set(all_tables) - PRESERVED_TABLES):
        if not IDENTIFIER_RE.fullmatch(table):
            raise RuntimeError(f"发现不安全的数据库表名，已中止: {table!r}")
        result.append(table)
    return result


def cleanup_artifact_tree(root: Path) -> tuple[list[str], list[str]]:
    """删除业务文件，保留本地 embedding 模型缓存，并重建常用空目录。"""
    root = root.resolve()
    removed: list[str] = []
    preserved: list[str] = []
    if not root.exists():
        return removed, preserved
    if root == Path(root.anchor):
        raise RuntimeError(f"拒绝清理文件系统根目录: {root}")

    for child in root.iterdir():
        if child.name in PRESERVED_DATA_DIRS:
            preserved.append(child.name)
            continue
        # 先判断 symlink，避免沿链接删除工作区之外的数据。
        if child.is_symlink() or child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            shutil.rmtree(child)
        removed.append(child.name)

    for dirname in ("code_analysis", "logs", "reports", "repos", "uploads"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    return sorted(removed), sorted(preserved)


async def _table_counts(session, tables: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        if not IDENTIFIER_RE.fullmatch(table):
            raise RuntimeError(f"发现不安全的数据库表名，已中止: {table!r}")
        counts[table] = int(
            (await session.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar()
            or 0
        )
    return counts


async def inspect_database() -> tuple[list[str], dict[str, int]]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        ))
        all_tables = [str(row[0]) for row in rows.all()]
        targets = cleanup_targets(all_tables)
        return targets, await _table_counts(session, targets)


async def cleanup_database(kept_users: list[str]) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        ))
        all_tables = [str(row[0]) for row in rows.all()]
        targets = cleanup_targets(all_tables)
        before = await _table_counts(session, targets)

        if targets:
            quoted = ", ".join(f'"{table}"' for table in targets)
            await session.execute(text(
                f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"
            ))

        delete_users = text(
            "DELETE FROM users WHERE username NOT IN :kept_users"
        ).bindparams(bindparam("kept_users", expanding=True))
        deleted_users = (
            await session.execute(delete_users, {"kept_users": kept_users})
        ).rowcount or 0
        await session.commit()

        preserved_counts = await _table_counts(session, PRESERVED_TABLES - {"alembic_version"})
        return {
            "tables_cleared": len(targets),
            "rows_cleared": sum(before.values()),
            "deleted_non_default_users": deleted_users,
            "preserved_counts": preserved_counts,
        }


async def cleanup_redis() -> int:
    from redis.asyncio import from_url

    client = from_url(settings.redis_url, decode_responses=True)
    try:
        size = int(await client.dbsize())
        await client.flushdb()
        return size
    finally:
        await client.aclose()


def cleanup_minio() -> int:
    from app.utils.storage import get_minio_client

    client = get_minio_client()
    bucket = settings.MINIO_BUCKET
    if not client.bucket_exists(bucket):
        return 0
    removed = 0
    for obj in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, obj.object_name)
        removed += 1
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="清空平台业务/测试数据，保留 AI 模型配置、模型路由和初始化账号"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="仅展示待清理数据，不执行")
    mode.add_argument("--yes", action="store_true", help="确认执行不可逆清理")
    parser.add_argument(
        "--keep-user",
        action="append",
        default=[],
        help="额外保留的用户名，可重复传入",
    )
    parser.add_argument(
        "--data-root",
        default="/app/data",
        help="业务文件根目录，默认 /app/data",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    targets, counts = await inspect_database()
    non_empty = {table: count for table, count in counts.items() if count}
    print(f"待清理业务表: {len(targets)} 张")
    print(f"待清理数据库记录: {sum(counts.values())} 条")
    for table, count in non_empty.items():
        print(f"  - {table}: {count}")
    print("保留表: " + ", ".join(sorted(PRESERVED_TABLES)))
    kept_users = sorted(DEFAULT_USERS | {settings.BOOTSTRAP_ADMIN_USERNAME} | set(args.keep_user))
    print("保留账号: " + ", ".join(kept_users))
    print("保留文件目录: " + ", ".join(sorted(PRESERVED_DATA_DIRS)))

    if args.dry_run:
        print("DRY RUN：未修改任何数据。")
        return 0

    database = await cleanup_database(kept_users)
    redis_keys = await cleanup_redis()
    minio_objects = cleanup_minio()
    removed_dirs, preserved_dirs = cleanup_artifact_tree(Path(args.data_root))
    print("清理完成：")
    print(f"  - 数据库: {database['tables_cleared']} 张表，{database['rows_cleared']} 条记录")
    print(f"  - 非初始化账号: {database['deleted_non_default_users']} 个")
    print(f"  - Redis: {redis_keys} 个键")
    print(f"  - MinIO: {minio_objects} 个对象")
    print(f"  - 磁盘目录/文件: {len(removed_dirs)} 项 ({', '.join(removed_dirs) or '无'})")
    print(f"  - 已保留: {database['preserved_counts']}，目录 {preserved_dirs}")
    return 0


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
