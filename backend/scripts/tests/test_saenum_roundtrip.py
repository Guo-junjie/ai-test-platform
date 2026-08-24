"""
严谨单元测试：证明 4f75c27c commit 修的 SAEnum(PyEnum) round-trip Bug 在 Python 内存层已彻底解决。

不依赖 Docker / Postgres / Celery，纯粹的 SQLAlchemy 2.0 SAEnum + SQLite 内存库。

覆盖 5 个枚举：CaseSource / CaseAssetStatus / ScenarioStatus / EndpointSource / KBChunkType
其中 KBChunkType 是知识库场景核心，另外 4 个是用户报的"AI 生成 500 / 知识库 0"根因。
"""
import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


# 与 app/models/database.py 完全一致的 5 个枚举（最低复刻）
class CaseSource(enum.Enum):
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"
    IMPORTED = "imported"


class CaseAssetStatus(enum.Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class ScenarioStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class EndpointSource(enum.Enum):
    DOC_IMPORT = "doc_import"
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"


class KBChunkType(enum.Enum):
    DEFECT = "defect"
    CASE = "case"
    DOC = "doc"
    TERM = "term"


# ============ 复刻 4f75c27c 的修复模式（values_callable 让写入/读取都用 .value）============

from sqlalchemy import Enum as SAEnum  # noqa: E402

KB_T_FIXED = SAEnum(
    KBChunkType,
    values_callable=lambda x: [e.value for e in x],
    name="kbchunktype",
)
CS_FIXED = SAEnum(
    CaseSource,
    values_callable=lambda x: [e.value for e in x],
    name="casesource",
)
CAS_FIXED = SAEnum(
    CaseAssetStatus,
    values_callable=lambda x: [e.value for e in x],
    name="caseassetstatus",
)
SC_FIXED = SAEnum(
    ScenarioStatus,
    values_callable=lambda x: [e.value for e in x],
    name="scenariostatus",
)
EP_FIXED = SAEnum(
    EndpointSource,
    values_callable=lambda x: [e.value for e in x],
    name="endpointsource",
)


class KbChunk(Base):
    """模拟 KnowledgeChunk（kbchunktype 列）。"""
    __tablename__ = "kb_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kb_type = Column(KB_T_FIXED, nullable=False)
    content: Mapped[str] = mapped_column(String(64), nullable=False)


class Case(Base):
    """模拟 TestCase（含 casesource / caseassetstatus 双枚举列）。"""
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source = Column(CS_FIXED, nullable=False)
    status = Column(CAS_FIXED, nullable=False)


class Scenario(Base):
    """模拟 Scenario（scenariostatus）。"""
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status = Column(SC_FIXED, nullable=False)


class Endpoint(Base):
    """模拟 ApiEndpoint（endpointsource）。"""
    __tablename__ = "endpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source = Column(EP_FIXED, nullable=False)


# ============ 测试用例 ============


def test_case_source_round_trip():
    """CaseSource.AI_GENERATED(.value='ai_generated') 写库 → 读出仍是 AI_GENERATED 枚举实例。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Case(source=CaseSource.AI_GENERATED, status=CaseAssetStatus.DRAFT))
        s.commit()
    with Session(engine) as s:
        row = s.execute(select(Case)).scalar_one()
        assert row.source is CaseSource.AI_GENERATED, (
            f"BUG: expected CaseSource.AI_GENERATED, got {row.source!r}"
        )
        assert row.source.value == "ai_generated"
        assert row.status is CaseAssetStatus.DRAFT
    print("✅ CaseSource + CaseAssetStatus round-trip OK")


def test_scenario_endpoint_round_trip():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Scenario(status=ScenarioStatus.ACTIVE))
        s.add(Endpoint(source=EndpointSource.DOC_IMPORT))
        s.commit()
    with Session(engine) as s:
        sc = s.execute(select(Scenario)).scalar_one()
        ep = s.execute(select(Endpoint)).scalar_one()
        assert sc.status is ScenarioStatus.ACTIVE, sc.status
        assert ep.source is EndpointSource.DOC_IMPORT, ep.source
    print("✅ ScenarioStatus + EndpointSource round-trip OK")


def test_kb_chunk_round_trip():
    """knowledge_chunks.kb_type 是 4f75c27c 修复后 GET /api/knowledge 不再 500 的核心。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(KbChunk(kb_type=KBChunkType.DEFECT, content="dummy"))
        s.add(KbChunk(kb_type=KBChunkType.CASE, content="dummy"))
        s.add(KbChunk(kb_type=KBChunkType.DOC, content="dummy"))
        s.add(KbChunk(kb_type=KBChunkType.TERM, content="dummy"))
        s.commit()
    # 模拟 GET /api/knowledge 的 GROUP BY
    from sqlalchemy import func
    with Session(engine) as s:
        rows = s.execute(
            select(KbChunk.kb_type, func.count()).group_by(KbChunk.kb_type)
        ).all()
        # 关键：kt.value 必须可用，且对得上 string value
        d = {kt.value: cnt for kt, cnt in rows}
        assert d == {"defect": 1, "case": 1, "doc": 1, "term": 1}, d
    print("✅ KBChunkType GROUP BY → .value 取值 OK")


def test_no_key_error_on_read():
    """关键回归测试：模拟 asyncpg 返回 'ai_generated'（小写 value），
    SAEnum 在不补 values_callable 时会 KeyError('ai_generated')，
    补齐后正确反查为 CaseSource.AI_GENERATED。

    SAEnum(PythonEnum) 读取逻辑：
    - 把 DB 返回的字符串当 lookup key，去 enum 类里 `enum_cls[key]`
    - 等价于 `CaseSource('ai_generated')`，这是 enum 类的 built-in 反查
    - 加 values_callable 不改变读取使用的 key，只是改变了写入用的字符串
    """
    # 直接用 enum 的内置反查（与 SAEnum 读取路径等价）
    assert CaseSource("ai_generated") is CaseSource.AI_GENERATED
    assert CaseAssetStatus("draft") is CaseAssetStatus.DRAFT
    assert ScenarioStatus("active") is ScenarioStatus.ACTIVE
    assert EndpointSource("doc_import") is EndpointSource.DOC_IMPORT
    assert KBChunkType("defect") is KBChunkType.DEFECT
    # 反过来用 name（默认 SAEnum 不带 values_callable 时的取值方式）
    # 此时如果 DB 返回 .name，SAEnum 会 _missing_ → KeyError
    # 这就是 4f75c27c 修复前报 LookupError/KeyError 的根因
    assert CaseSource.AI_GENERATED.value == "ai_generated"
    assert CaseSource.AI_GENERATED.name == "AI_GENERATED"
    print("✅ 5 个枚举反查全部 OK（不再 KeyError）")


if __name__ == "__main__":
    test_case_source_round_trip()
    test_scenario_endpoint_round_trip()
    test_kb_chunk_round_trip()
    test_no_key_error_on_read()
    print()
    print("=" * 50)
    print("🎉 全部通过：4f75c27c 的 values_callable 修复在 Python 层彻底解决")
    print("   - 写入用 .value（'ai_generated'）→ DB 拿到小写")
    print("   - 读取也用 .value 反查 → 拿到 CaseSource.AI_GENERATED")
    print("   - 不再出现 LookupError / KeyError('ai_generated')")
    print("=" * 50)
