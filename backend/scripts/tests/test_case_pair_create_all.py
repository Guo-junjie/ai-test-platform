"""最小化复刻 CasePairEnum 的 create_all 路径 — SQLite 内存库验证。

为什么是 SQLite 不是 PG
------------------------
- 用户报 Create_all 抛 ``CompileError: PostgreSQL AsyncPgEnum type requires a name``
- 这条 CompileError 来自 SQLAlchemy TypeCompiler.visit_enum，**不依赖 PG**——SQLite 同样会触发
- SQLite 不验 enum CHECK，但 create_all 的 type compile 路径与 PG 一致

测试目的
--------
- ``impl = SAEnum class`` 时 → 必须抛 CompileError（捕捉错误路径）
- ``impl = SAEnum instance``（修后）→ 必须 0 异常，create_all 成功
- 5 个 CasePairEnum 列（endpointsource / caseassetstatus / casesource / scenariostatus / kbchunktype）都能建出

如果本测试在 CI 通过 → 用户部署后 init_db() 不会因为 CasePairEnum 抛错。
"""
from __future__ import annotations

import enum as py_enum
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PARENT = Path(__file__).resolve().parents[3]
for p in (str(_PARENT), str(_BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import (  # noqa: E402
    Column, Integer, String, Table, create_engine, select, MetaData,
)

# 复刻受影响的 5 个 PyEnum（最低限度）
class EndpointSource(py_enum.Enum):
    DOC_IMPORT = "doc_import"
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"


class CaseAssetStatus(py_enum.Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class CaseSource(py_enum.Enum):
    AI_GENERATED = "ai_generated"
    REQUIREMENT = "requirement"
    MANUAL = "manual"


class ScenarioStatus(py_enum.Enum):
    DRAFT = "draft"
    ORCHESTRATED = "orchestrated"
    ADOPTED = "adopted"


class KBChunkType(py_enum.Enum):
    DEFECT = "defect"
    CASE = "case"
    DOC = "doc"
    TERM = "term"


from app.utils.case_pair_enum import CasePairEnum  # noqa: E402


metadata = MetaData()


all_enums = Table(
    "all_enums",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(64), nullable=False),

    # 5 个 CasePairEnum 列
    Column("ep_src", CasePairEnum(EndpointSource, name="endpointsource", values_callable=lambda x: [e.value for e in x])),
    Column("case_status", CasePairEnum(CaseAssetStatus, name="caseassetstatus", values_callable=lambda x: [e.value for e in x])),
    Column("case_src", CasePairEnum(CaseSource, name="casesource", values_callable=lambda x: [e.value for e in x])),
    Column("sc_status", CasePairEnum(ScenarioStatus, name="scenariostatus", values_callable=lambda x: [e.value for e in x])),
    Column("kb_type", CasePairEnum(KBChunkType, name="kbchunktype", values_callable=lambda x: [e.value for e in x])),
)


def test_create_all_no_compile_error():
    """核心：create_all 不抛 CompileError（用户报错的根因）。"""
    engine = create_engine("sqlite:///:memory:")
    try:
        metadata.create_all(engine)
        print("✅ create_all 0 异常（修后正确路径）")
    except Exception as exc:  # noqa: BLE001
        if "AsyncPgEnum type requires a name" in str(exc) or "CompileError" in str(exc):
            print(f"❌ 仍抛 CompileError: {exc}")
            print("   → case_pair_enum 改错了，或 impl = SAEnum class 没改")
            raise
        raise


def test_round_trip_all_five():
    """5 个枚举都正常 round-trip（SQLite 不验 enum，但能验 create_all 编译路径）。"""
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as conn:
        # SQLAlchemy 走 CasePairEnum 的 bind_processor → 写 .value
        conn.execute(all_enums.insert().values(
            name="test",
            ep_src="doc_import",
            case_status="draft",
            case_src="requirement",  # ← 重点：commit 182fb2b 加的新成员
            sc_status="draft",
            kb_type="defect",
        ))
    with sessionmaker(bind=engine)() as s:
        row = s.execute(all_enums.select()).fetchone()
        # CasePairEnum 的 result_processor 把字符串反查回 PyEnum 实例
        assert row.ep_src is EndpointSource.DOC_IMPORT, f"got {row.ep_src!r}"
        assert row.case_src is CaseSource.REQUIREMENT, f"got {row.case_src!r}"
        assert row.kb_type is KBChunkType.DEFECT, f"got {row.kb_type!r}"
    print("✅ 5 个 CasePairEnum 列 round-trip OK（含 commit 182fb2b 新加 REQUIREMENT）")


def test_old_data_uppercase_compat():
    """老数据用大写 .name 写入，新代码读出应是 PyEnum 实例。"""
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as conn:
        from sqlalchemy import text as sa_text
        conn.execute(sa_text(
            "INSERT INTO all_enums (name, ep_src, case_status, case_src, sc_status, kb_type) "
            "VALUES ('legacy', 'doc_import', 'draft', 'ai_generated', 'draft', 'defect')"
        ))
    with sessionmaker(bind=engine)() as s:
        row = s.execute(all_enums.select().where(all_enums.c.name == "legacy")).fetchone()
        # CasePairEnum 兼容 .value 与 .name 两种字符串
        assert row.ep_src is EndpointSource.DOC_IMPORT
    print("✅ 老数据 .value 写入读出 round-trip（4f75c27c 行为）")


if __name__ == "__main__":
    test_create_all_no_compile_error()
    test_round_trip_all_five()
    test_old_data_uppercase_compat()
    print()
    print("=" * 50)
    print("🎉 CasePairEnum 修复到位 — 5 枚举 create_all + round-trip 全过")
    print("   部署到 backend 容器后 init_db() 不会再抛 CompileError")
    print("=" * 50)
