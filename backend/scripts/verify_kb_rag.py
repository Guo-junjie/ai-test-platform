"""知识库 RAG 全链路诊断脚本（一键报告）。

用法（部署机内执行）
---------
.. code-block:: bash

    # 在项目根目录
    docker compose exec backend python -m scripts.verify_kb_rag
    # 或本地直接跑（需配 backend/.env 里的 DATABASE_URL）
    python -m scripts.verify_kb_rag

输出
----
按「代码版本 → 容器状态 → DB 枚举 → 源表 → chunks → 状态机 → 嵌入模型」
7 段报告，每段 PASS/FAIL/WARN，给出可执行的修复命令。

设计原则
--------
* 只读、不写——跑完不会动你的数据
* 任意失败不抛堆栈，输出 ``section status: reason`` + ``fix: 建议命令``
* 单文件纯 stdlib + 已在 requirements 里的 SQLAlchemy/asyncpg，不引新依赖
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# 允许从 backend 目录运行：把父目录塞进 sys.path 再导入 app
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_BACKEND_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from app.utils.database import AsyncSessionLocal  # noqa: E402
from app.models.database import (  # noqa: E402
    ApiEndpoint,
    CaseAssetStatus,
    CaseSource,
    Defect,
    EndpointSource,
    KBChunkType,
    KBRebuildState,
    KnowledgeChunk,
    KnowledgeTerm,
    ScenarioStatus,
    TestCase,
)


# 输出工具
def section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def ok(msg: str) -> None:
    print(f"  ✅ PASS  {msg}")


def warn(msg: str, fix: str = "") -> None:
    print(f"  ⚠ WARN  {msg}")
    if fix:
        print(f"           → 修复：{fix}")


def fail(msg: str, fix: str = "") -> None:
    print(f"  ❌ FAIL  {msg}")
    if fix:
        print(f"           → 修复：{fix}")


# ============ 各段诊断 ============


async def check_engine_version(db: AsyncSession) -> None:
    section("① PostgreSQL 版本与扩展")
    try:
        v = (await db.execute(text("SELECT version()"))).scalar()
        ok(f"PG: {v.split(',')[0]}")
    except Exception as exc:  # noqa: BLE001
        fail(f"DB 连不上: {exc}", "检查 DATABASE_URL / docker compose ps postgres")


async def check_enum_labels(db: AsyncSession) -> None:
    section("② 5 个 SAEnum 枚举双 label 是否齐全")
    # 全部从 ORM 枚举实况查，避免硬编码过时值
    # （历史上 verify_kb_rag.py 这里写死{"MANUAL","IMPORTED","AI_GENERATED"}，
    # 跟 ORM CaseSource 增加 REQUIREMENT 后脱节 —— 让算法自己查才稳）
    expected = {
        "kbchunktype": {m.name for m in KBChunkType} | {m.value for m in KBChunkType},
        "casesource": {m.name for m in CaseSource} | {m.value for m in CaseSource},
        "caseassetstatus": {m.name for m in CaseAssetStatus} | {m.value for m in CaseAssetStatus},
        "scenariostatus": {m.name for m in ScenarioStatus} | {m.value for m in ScenarioStatus},
        "endpointsource": {m.name for m in EndpointSource} | {m.value for m in EndpointSource},
    }
    for type_name, labels in expected.items():
        try:
            row = (await db.execute(
                text(f"SELECT enum_range(NULL::{type_name})")
            )).scalar()
            actual = set(row) if row else set()
        except Exception as exc:  # noqa: BLE001
            fail(f"{type_name}: 查询失败 {exc}",
                 "重启 backend 让 init_db 跑 _ENUM_CASE_PAIRS 兜底")
            continue
        missing = labels - actual
        if not missing:
            ok(f"{type_name}: {len(labels)} 个 label 齐全 ({sorted(actual)})")
        else:
            fail(
                f"{type_name}: 缺 label {sorted(missing)}，当前 PG 端有 {sorted(actual)}",
                "在 backend 容器内跑 `python -m scripts.sync_enum_labels` 立即补齐；"
                "或重启 backend 让 init_db 自动 ALTER TYPE ADD VALUE；"
                "若仍失败执行 `docker compose down -v` 重建数据库（最干净）",
            )


async def check_source_tables(db: AsyncSession) -> dict[str, int]:
    section("③ 源表数据量（决定重建结果上限）")
    counts: dict[str, int] = {}
    for label, model in [
        ("defect  defects", Defect),
        ("case    test_cases", TestCase),
        ("doc     api_endpoints", ApiEndpoint),
        ("term    knowledge_terms", KnowledgeTerm),
    ]:
        try:
            n = (await db.execute(
                select(func.count()).select_from(model)
            )).scalar() or 0
        except Exception as exc:  # noqa: BLE001
            fail(f"{label}: 查询失败 {exc}")
            n = -1
        counts[label.split()[0]] = n
        if n > 0:
            ok(f"{label}: {n} 行")
        elif n == 0:
            warn(f"{label}: 0 行", "若希望 KB 重建有结果，先跑 `python -m scripts.seed_e2e` 注入示例数据")
        else:
            fail(f"{label}: -1（查询异常）")
    return counts


async def check_chunks(db: AsyncSession) -> dict[str, int]:
    section("④ knowledge_chunks 各类型计数（重建结果）")
    res = await db.execute(
        select(KnowledgeChunk.kb_type, func.count()).group_by(KnowledgeChunk.kb_type)
    )
    counts = {kt.value if hasattr(kt, "value") else str(kt): cnt for kt, cnt in res.all()}
    total = sum(counts.values())
    if total == 0:
        warn("knowledge_chunks 总数 0（重建未产出或未执行）",
             "在 UI '知识库' 页面点 '一键重建'，或接口 POST /api/knowledge/rebuild")
    else:
        ok(f"总计 {total} chunks，分布 {dict((k, counts[k]) for k in sorted(counts))}")
    return counts


async def check_rebuild_state(db: AsyncSession) -> None:
    section("⑤ kb_rebuild_state 状态机")
    row = (await db.execute(
        select(KBRebuildState).order_by(KBRebuildState.id).limit(1)
    )).scalar_one_or_none()
    if row is None:
        warn("无 kb_rebuild_state 行",
             "调一次 GET /api/knowledge 触发状态机初始化")
        return
    print(f"  state={row.state}  updated_at={row.updated_at}  "
          f"last_rebuild={row.last_rebuild}  last_rebuild_chunks={row.last_rebuild_chunks}")
    if row.error:
        print(f"  ⚠ 上次 error: {row.error[:300]}")
    if row.state == "running":
        delta = (datetime.utcnow() - row.updated_at).total_seconds() \
            if row.updated_at else 0
        if delta > 3600:
            fail(f"状态卡死：running > {int(delta // 60)} 分钟",
                 "调 POST /api/knowledge/reset 强制重置；或点击前端'强制重置'按钮")
        else:
            warn(f"running 中（已 {int(delta // 60)} 分钟），稍后再查或查看 celery-worker 日志",
                 "docker compose logs --tail=100 celery-worker")
    elif row.state == "failed":
        fail(f"上次失败：{row.error or '(无 error 字段)'}",
             "docker compose logs --tail=100 celery-worker | grep -i kb")
    else:
        ok(f"state={row.state} 健康")


async def check_embedding_model(db: AsyncSession) -> None:
    section("⑥ 嵌入模型可用性（决定 retrieval_mode 是 semantic 还是 keyword）")
    try:
        from app.modules.ai.model_router import get_model_router
        router = get_model_router()
        emb_id = router.routing.embedding_model_id
        if emb_id:
            ok(f"embedding_model_id={emb_id}（semantic 模式可用）")
        else:
            warn("未配置 embedding 模型 → 走 keyword 降级（仍可用）",
                 "在 '模型配置' 页配置 use_case=embedding 的模型")
    except Exception as exc:  # noqa: BLE001
        warn(f"获取模型配置失败: {exc}（keyword 降级）")


async def check_runtime_switch(db: AsyncSession) -> None:
    section("⑦ 运行时开关 kb_rag_enabled")
    try:
        row = (await db.execute(
            text("SELECT value FROM kb_runtime_config WHERE key='kb_rag_enabled'")
        )).scalar()
        v = (row or "").lower()
        if v == "true":
            ok("DB 中 kb_rag_enabled=true")
        elif v == "false":
            warn("DB 中 kb_rag_enabled=false → 检索早退，AI 注入为空（不会报错，但知识库不可用）",
                 "调 PUT /api/knowledge/config {\"kb_rag_enabled\": true}")
        else:
            warn(f"DB 中无配置（row={row!r}），fallback 到 env settings.KB_RAG_ENABLED",
                 "若想持久化切换，调 PUT /api/knowledge/config")
    except Exception as exc:  # noqa: BLE001
        warn(f"运行时开关查询失败: {exc}")


async def check_kb_endpoint_smoke(db: AsyncSession) -> None:
    section("⑧ 模拟 GET /api/knowledge 看是否能 GROUP BY 成功")
    try:
        await db.execute(
            select(KnowledgeChunk.kb_type, func.count()).group_by(KnowledgeChunk.kb_type)
        )
        ok("GROUP BY 成功（4f75c27c values_callable 修复后不再 KeyError）")
    except KeyError as exc:
        fail(f"GROUP BY KeyError: {exc}（修复未生效！）",
             "确认 backend 重启后加载的是 4f75c27c 之后的代码；"
             "python -c 'from app.models.database import KnowledgeChunk; print(KnowledgeChunk.kb_type.type.values_callable)'")
    except Exception as exc:  # noqa: BLE001
        fail(f"GROUP BY 失败: {exc}")


async def main() -> int:
    section("🔍 知识库 RAG 全链路诊断 @ " + datetime.utcnow().isoformat() + "Z")
    print(f"  Python {sys.version_info[:2]} / cwd={os.getcwd()}")
    async with AsyncSessionLocal() as db:
        await check_engine_version(db)
        await check_enum_labels(db)
        counts = await check_source_tables(db)
        chunks = await check_chunks(db)
        await check_rebuild_state(db)
        await check_embedding_model(db)
        await check_runtime_switch(db)
        await check_kb_endpoint_smoke(db)

    # 终局判定
    section("📋 终局判定")
    if sum(counts.values()) == 0:
        print("  ⚠ 源表全空 → 先跑 `python -m scripts.seed_e2e` 注入示例数据，")
        print("    然后再点 '一键重建' 让知识库有内容可检索。")
    if sum(chunks.values()) == 0 and sum(counts.values()) > 0:
        print("  ⚠ 源表有数据但 chunks 为 0 → celery worker 未消费 / 未执行。")
        print("    docker compose logs --tail=80 celery-worker")
        print("    确认无 'Event loop is closed' / ImportError 后点 '一键重建'。")
    print()
    print("  完。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
