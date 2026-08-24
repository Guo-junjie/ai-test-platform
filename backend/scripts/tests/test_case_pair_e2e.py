"""
端到端验证 CasePairEnum 修复：在 SQLite 里模拟 PG「老数据大写 + 4f75c27c 修复后」场景。

模拟：手写一段历史 row（包含大写 .name 'DOC_IMPORT' / 'DRAFT' / 'AI_GENERATED'），
然后用 CasePairEnum 取回这些 row，确认：
  ① 不会抛 LookupError
  ② 取出的 row 字段值是正确枚举实例（不丢失）
  ③ 同时 4f75c27c 的 round-trip（写小写 / 读小写）仍正常
"""
import enum
import sys

from sqlalchemy import (JSON, Column, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, func, select)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

sys.path.insert(0, r"D:\code\WorkbuddyProject\ai测试自闭环\ai-test-platform\backend")
from app.utils.case_pair_enum import CasePairEnum  # noqa: E402


# 复刻受影响的 5 枚举（保持 .name 全大写、.value 全小写）
class CaseSource(enum.Enum):
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"
    IMPORTED = "imported"


class CaseAssetStatus(enum.Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
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


class Project(Base):
    __tablename__ = "projects"
    id = Column(String(36), primary_key=True)
    name = Column(String(64))


class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(String(36), primary_key=True)
    project_id = Column(String(36))
    status = Column(CasePairEnum(CaseAssetStatus,
                                    values_callable=lambda x: [e.value for e in x],
                                    name="caseassetstatus"))
    source = Column(CasePairEnum(CaseSource,
                                   values_callable=lambda x: [e.value for e in x],
                                   name="casesource"))


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"
    id = Column(String(36), primary_key=True)
    project_id = Column(String(36))
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


def test_legacy_uppercase_data():
    """老数据大写场景：手写 'DOC_IMPORT' / 'DRAFT' / 'AI_GENERATED' 入库，
    用 4f75c27c + CasePairEnum 修复后的代码读出，必须能反查为枚举实例。"""
    import uuid as _uuid
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    pid = str(_uuid.uuid4())
    with Sess() as s:
        s.add(Project(id=pid, name="demo"))
        # 模拟 PG 端老数据：直接 raw SQL 写入大写 .name
        s.execute(
            TestCase.__table__.insert().values(
                id=str(_uuid.uuid4()), project_id=pid,
                status="DRAFT", source="AI_GENERATED",  # 大写 name
            )
        )
        s.execute(
            ApiEndpoint.__table__.insert().values(
                id=str(_uuid.uuid4()), project_id=pid,
                source="DOC_IMPORT",  # 大写 name
            )
        )
        s.execute(
            KnowledgeChunk.__table__.insert().values(
                id=str(_uuid.uuid4()),
                kb_type="DEFECT",  # 大写 name
            )
        )
        s.commit()

    # 现在用 ORM 读（4f75c27c + CasePairEnum 修复后）——必须成功
    with Sess() as s:
        tc = s.execute(select(TestCase)).scalar_one()
        assert tc.status is CaseAssetStatus.DRAFT, f"status={tc.status!r}"
        assert tc.source is CaseSource.AI_GENERATED, f"source={tc.source!r}"

        ep = s.execute(select(ApiEndpoint)).scalar_one()
        assert ep.source is EndpointSource.DOC_IMPORT, f"ep.source={ep.source!r}"

        kc = s.execute(select(KnowledgeChunk)).scalar_one()
        assert kc.kb_type is KBChunkType.DEFECT, f"kc.kb_type={kc.kb_type!r}"
    print("✅ 老数据大写 .name 全部能正确反查为枚举实例（4f75c27c 漏掉的关键场景已修）")


def test_round_trip_still_works():
    """4f75c27c 的 round-trip 行为不能被破坏：用枚举实例写入，读出仍是同实例。"""
    import uuid as _uuid
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    pid = str(_uuid.uuid4())
    with Sess() as s:
        s.add(Project(id=pid, name="demo"))
        s.add(TestCase(id=str(_uuid.uuid4()), project_id=pid,
                       status=CaseAssetStatus.REVIEWED,
                       source=CaseSource.MANUAL))
        s.add(ApiEndpoint(id=str(_uuid.uuid4()), project_id=pid,
                          source=EndpointSource.MANUAL))
        s.add(KnowledgeChunk(id=str(_uuid.uuid4()),
                             kb_type=KBChunkType.CASE))
        s.commit()
    with Sess() as s:
        assert s.execute(select(TestCase)).scalar_one().status is CaseAssetStatus.REVIEWED
        assert s.execute(select(TestCase)).scalar_one().source is CaseSource.MANUAL
        assert s.execute(select(ApiEndpoint)).scalar_one().source is EndpointSource.MANUAL
        assert s.execute(select(KnowledgeChunk)).scalar_one().kb_type is KBChunkType.CASE
    print("✅ 4f75c27c round-trip 行为未受影响（写枚举 → 读同枚举）")


def test_group_by_for_kb_status():
    """GET /api/knowledge 用的 GROUP BY：kctype.value 还能拿到 .value。"""
    import uuid as _uuid
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    with Sess() as s:
        s.add(KnowledgeChunk(id=str(_uuid.uuid4()), kb_type=KBChunkType.DEFECT))
        s.add(KnowledgeChunk(id=str(_uuid.uuid4()), kb_type=KBChunkType.DEFECT))
        s.add(KnowledgeChunk(id=str(_uuid.uuid4()), kb_type=KBChunkType.CASE))
        s.add(KnowledgeChunk(id=str(_uuid.uuid4()), kb_type=KBChunkType.TERM))
        s.commit()
    with Sess() as s:
        rows = s.execute(
            select(KnowledgeChunk.kb_type, func.count())
            .group_by(KnowledgeChunk.kb_type)
        ).all()
        d = {kt.value: cnt for kt, cnt in rows}
        assert d == {"defect": 2, "case": 1, "term": 1}, d
    print("✅ GROUP BY → kctype.value 仍能正确返回 dict（GET /api/knowledge 烟测）")


if __name__ == "__main__":
    test_legacy_uppercase_data()
    test_round_trip_still_works()
    test_group_by_for_kb_status()
    print()
    print("=" * 60)
    print("🎉 CasePairEnum 修复 + 4f75c27c 兼容性，端到端 SQLite 全过")
    print("   → 老数据大写 .name 'DOC_IMPORT'/'DRAFT'/'AI_GENERATED' 全部能反查")
    print("   → round-trip 行为未破坏")
    print("   → GROUP BY .value 仍可用")
    print("=" * 60)
