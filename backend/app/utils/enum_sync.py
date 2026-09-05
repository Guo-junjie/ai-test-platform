"""PG 枚举 label 同步工具 — 给老库补齐 init_db 启动期漏建的双 label。

背景
----
``init_db()`` 在 ``app/models/database.py`` 启动期会跑一次 ``_ENUM_CASE_PAIRS`` 同步，
但有几个边界场景会让老库落单 label：

1. **历史老库用 ``commit 1cae8652 + 2728d61c`` 之前的代码部署过**——那时没这套兜底，
   ``casesource`` enum 只有 ``AI_GENERATED / MANUAL`` 两个 label（大写）。后续在
   ``commit 182fb2b`` 加了 ``CaseSource.REQUIREMENT = "requirement"`` ，
   但**老部署重启 backend 时** init_db 会跑成功补上 REQUIREMENT / requirement，
   **没重启**就仍报 ``invalid input value for enum casesource: "requirement"``。

2. **直接用 alembic upgrade 而不是 init_db**：alembic 迁移可能漏跑某些 label。

本模块提供「**无论 backend 是否重启都能同步**」的入口：

* ``sync_enum_case_pairs(conn)`` —— 库内同步，autocommit 连接调一次即可；
* ``run_enum_sync_and_report()`` —— 脚本入口，给运维/不重启 backend 的场景手动跑一次。

历史教训（避免重蹈覆辙）
----------------------
- **SQLAlchemy 写 bind 用 member.value（小写）**：见 commit 4f75c27c 的 ``values_callable``
- **PG enum label 集由 ``create_all`` 创建一次的 member.name（大写）决定**：历史数据
  仅含大写 label；新加 PyEnum 成员时 PG 端 label 必须显式 ``ALTER TYPE ... ADD VALUE``
- **大小写必须共存**：member.name 和 member.value 同时插；少哪个就哪个会失败
"""
from __future__ import annotations

from typing import Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

# 与 init_db._ENUM_CASE_PAIRS 保持一致 — 不要忘加新的 PyEnum 列
_PAIR_LIST: Tuple[Tuple[str, type], ...] = (
    ("kbchunktype", __import__("app.models.database", fromlist=["KBChunkType"]).KBChunkType),
    ("casesource", __import__("app.models.database", fromlist=["CaseSource"]).CaseSource),
    ("caseassetstatus", __import__("app.models.database", fromlist=["CaseAssetStatus"]).CaseAssetStatus),
    ("scenariostatus", __import__("app.models.database", fromlist=["ScenarioStatus"]).ScenarioStatus),
    ("endpointsource", __import__("app.models.database", fromlist=["EndpointSource"]).EndpointSource),
    # P0：SourceType 模型从裸 SAEnum 改为 values_callable=小写，老库只有大写 label，
    # 启动时 ALTER ADD VALUE 补齐小写避免 LookupError（同时支持两类值写入）
    ("sourcetype", __import__("app.models.database", fromlist=["SourceType"]).SourceType),
    # R3：定时任务目标类型新增 PLAN（测试计划周期回归）
    ("scheduledtasktargettype", __import__("app.models.database", fromlist=["ScheduledTaskTargetType"]).ScheduledTaskTargetType),
)


async def sync_enum_case_pairs(conn: AsyncConnection) -> dict:
    """对 5 个 SAEnum 枚举同时补齐 .name（大写）+ .value（小写）两套 PG label。

    调用前提
    --------
    连接必须在 **AUTOCOMMIT** 隔离级别下（ALTER TYPE ... ADD VALUE 在事务内无法执行）。

    调用前后无需 schema 锁；这是 PG 17+ 推荐的幂等补值方式。

    Parameters
    ----------
    conn : AsyncConnection
        AUTOCOMMIT 隔离级别的 asyncpg/SQLAlchemy 连接。

    Returns
    -------
    dict : ``{enum_type_name: {"before": set, "added": list, "current": set}}``
    """
    result: dict = {}
    for type_name, enum_cls in _PAIR_LIST:
        # 当前 PG 端 label 集
        cur_row = await conn.execute(text(f"SELECT enum_range(NULL::{type_name})"))
        cur_range = cur_row.scalar() or ""
        # enum_range 返回 '{a,b,c}' 形式
        if isinstance(cur_range, str):
            current = set(filter(None, cur_range.strip("{}").split(",")))
        else:
            current = set(cur_range or [])
        before = set(current)

        added: list[str] = []
        # 同时建大小写两个 label —— 4f75c27c 行为
        for label in (
            *(m.name for m in enum_cls),
            *(m.value for m in enum_cls),
        ):
            if label in current:
                continue
            try:
                await conn.execute(
                    text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")
                )
                added.append(label)
                current.add(label)
            except Exception as e:  # noqa: BLE001
                # 不打断同步；log 就行（一般是因为枚举正在被并发使用 → 重试）
                # 错误典型：0A000 ALTER TYPE ... ADD cannot run inside a transaction block
                # 若发生，建议重启 backend 由 init_db 单独处理
                added.append(f"❌{label}:{type(e).__name__}")

        result[type_name] = {
            "before": sorted(before),
            "added": added,
            "current": sorted(current),
        }
    return result


async def run_enum_sync_and_report(engine: AsyncEngine | None = None) -> dict:
    """脚本入口：在 AUTOCOMMIT 连接上跑 ``sync_enum_case_pairs``，并打印人类可读报告。

    用途
    ----
    不重启 backend 的运维场景（容器跑 live、数据被新枚举值触发错误）。

    Returns
    -------
    dict : 同 ``sync_enum_case_pairs`` 的返回值
    """
    if engine is None:
        from app.utils.database import async_engine

        engine = async_engine

    async with engine.connect() as conn:
        autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        result = await sync_enum_case_pairs(autocommit_conn)

    # 人类可读报告
    print("=" * 72)
    print("  enum 双 label 同步报告")
    print("=" * 72)
    any_change = False
    for type_name, info in result.items():
        added_labels = [a for a in info["added"] if not a.startswith("❌")]
        if added_labels:
            any_change = True
        status = "✅ PASS" if not [a for a in info["added"] if a.startswith("❌")] else "⚠ 部分失败"
        print(f"  {status}  {type_name}: +{added_labels or '0'} 个 label")
        if len(info["current"]) < len(info["before"]) + len(added_labels):
            print(f"         当前 labels: {info['current']}")

    if not any_change:
        print()
        print("  ℹ 全部双 label 已齐全，无需操作。")
    else:
        print()
        print("  ✅ 同步完毕。如果仍报 'invalid input value for enum ...',")
        print("     1) 确认 backend 应用进程加载的就是最新代码（含此同步）")
        print("     2) 或 `docker compose down -v` 重建数据库（最干净）")

    return result


def get_pair_list() -> Sequence[Tuple[str, type]]:
    """暴露枚举配对给外部脚本（如 alembic 迁移）。"""
    return _PAIR_LIST
