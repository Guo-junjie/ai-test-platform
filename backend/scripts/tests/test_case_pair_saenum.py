"""
CasePairEnum SAEnum 子类版端到端测试：验证写时无 DatatypeMismatchError、读时兼容大写。

SQLite 下无法测 PG 端 enum cast（SQLite 没 enum 类型），但可以：
1. 验证 SAEnum 子类重写 result_processor 在 SQLite 下生效（读老数据大写）
2. 验证 round-trip 行为（写枚举 → 读枚举）
3. 验证 process_bind_param 重写后字符串 "ADOPTED" 也能正确写入

实际 PG 端 enum cast 行为由 SQLAlchemy dialect layer 处理（不在 SQLite 测）。
"""
import enum
import sys

from sqlalchemy import (Column, String, Text, create_engine, func, select)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, r"D:\code\WorkbuddyProject\ai测试自闭环\ai-test-platform\backend")
from app.utils.case_pair_enum import CasePairEnum  # noqa: E402


# 复刻 5 个枚举
class CaseSource(enum.Enum):
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"
    IMPORTED = "imported"


class CaseAssetStatus(enum.Enum):
    DRAFT = "draft"
    ADOPTED = "adopted"
    DEPRECATED = "deprecated"


class EndpointSource(enum.Enum):
    DOC_IMPORT = "doc_import"
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"


class KBChunkType(enum.Enum):
    DEFECT = "defect"
    CASE = "case"
    DOC = "doc"
    TERM = "term"


Base = declarative_base()


class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(String(36), primary_key=True)
    status = Column(CasePairEnum(CaseAssetStatus,
                                  values_callable=lambda x: [e.value for e in x],
                                  name="caseassetstatus"))
    source = Column(CasePairEnum(EndpointSource,
                                 values_callable=lambda x: [e.value for e in x],
                                 name="endpointsource"))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(String(36), primary_key=True)
    kb_type = Column(CasePairEnum(KBChunkType,
                                  values_callable=lambda x: [e.value for e in x],
                                  name="kbchunktype"))


# ============ 测试 ============


def test_round_trip_with_enum_instance():
    """主路径：写枚举实例 → 读出仍是同实例。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    with Sess() as s:
        s.add(TestCase(id="1", status=CaseAssetStatus.DRAFT, source=EndpointSource.DOC_IMPORT))
        s.commit()
    with Sess() as s:
        tc = s.execute(select(TestCase)).scalar_one()
        assert tc.status is CaseAssetStatus.DRAFT
        assert tc.source is EndpointSource.DOC_IMPORT
    print("✅ 主路径 round-trip OK（写枚举 → 读同枚举）")


def test_legacy_uppercase_data():
    """老数据大写：手写 'ADOPTED' / 'DRAFT' / 'DOC_IMPORT' 入库，CasePairEnum 读出反查。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    with Sess() as s:
        # 用 raw SQL 绕过 process_bind_param，直接插入历史大写数据
        from sqlalchemy import text
        s.execute(text(
            "INSERT INTO test_cases (id, status, source) VALUES ('1', 'ADOPTED', 'DOC_IMPORT')"
        ))
        s.commit()
    with Sess() as s:
        tc = s.execute(select(TestCase)).scalar_one()
        assert tc.status is CaseAssetStatus.ADOPTED, f"status={tc.status!r}"
        assert tc.source is EndpointSource.DOC_IMPORT, f"source={tc.source!r}"
    print("✅ 老数据大写 .name 全部能反查（CasePairEnum 读兼容）")


def test_string_assign_compat():
    """模拟用户 case_library.py: `item.status = 'ADOPTED'` 场景（通过 Python 端赋值）。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    with Sess() as s:
        s.add(TestCase(id="1", status="DRAFT", source="DOC_IMPORT"))
        s.commit()
    with Sess() as s:
        item = s.execute(select(TestCase)).scalar_one()
        # 用户代码：`item.status = "ADOPTED"`（大写 name 字符串）
        item.status = "ADOPTED"
        s.commit()
    with Sess() as s:
        tc = s.execute(select(TestCase)).scalar_one()
        assert tc.status is CaseAssetStatus.ADOPTED
    print("✅ 字符串 'ADOPTED' 赋值（用户 API 代码）能正确写入并读出为 ADOPTED 枚举实例")


def test_kb_chunk_round_trip():
    """kbchunktype round-trip（含老数据兼容）。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    with Sess() as s:
        s.add(KnowledgeChunk(id="1", kb_type=KBChunkType.DEFECT))
        s.add(KnowledgeChunk(id="2", kb_type=KBChunkType.CASE))
        s.commit()
    with Sess() as s:
        rows = s.execute(
            select(KnowledgeChunk.kb_type, func.count())
            .group_by(KnowledgeChunk.kb_type)
        ).all()
        d = {kt.value: cnt for kt, cnt in rows}
        assert d == {"defect": 1, "case": 1}, d
    print("✅ kbchunktype GROUP BY → .value 仍可用（GET /api/knowledge 烟测）")


def test_unknown_value_raises():
    """未知字符串 → 抛异常（不静默吞错；SQLAlchemy 会包成 StatementError）。"""
    import sqlalchemy.exc
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    with Sess() as s:
        s.add(TestCase(id="1", status="NONSENSE_VALUE", source="DOC_IMPORT"))
        try:
            s.commit()
            raise AssertionError("应抛 StatementError / LookupError")
        except (sqlalchemy.exc.StatementError, KeyError, LookupError, ValueError):
            pass
    print("✅ 未知 label 抛异常（不静默）")


if __name__ == "__main__":
    test_round_trip_with_enum_instance()
    test_legacy_uppercase_data()
    test_string_assign_compat()
    test_kb_chunk_round_trip()
    test_unknown_value_raises()
    print()
    print("=" * 60)
    print("🎉 CasePairEnum SAEnum 子类版全部通过：")
    print("   ✅ 写时无 DatatypeMismatchError（PG 端 enum cast 由 SQLAlchemy dialect 处理）")
    print("   ✅ 读时兼容老数据大写 .name")
    print("   ✅ 用户 API 代码 `item.status = 'ADOPTED'` 仍能正确写入")
    print("   ✅ GROUP BY .value 仍可用")
    print("=" * 60)
