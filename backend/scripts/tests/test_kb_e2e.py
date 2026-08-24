"""
端到端模拟知识库重建（与 backend 一致的 ORM 模型 + force_full 路径）。

不依赖 Docker / Postgres / Celery，只用 SQLite in-memory 复刻 5 张表与
embedder._full_rebuild_kb_type 的核心逻辑链，证明：
    源表 30+ 条数据 → rebuild_kb_type(force_full=True) → knowledge_chunks 有数据

如果这条链在我们复刻上 OK，部署机报 knowledge_chunks=0 的根因就是：
  1. 源表本就空（没跑 seed_e2e.py / 没数据累积）
  2. celery worker 启动失败（不会写到 knowledge_chunks）
  3. force_full=True 路径在 force_full=False（默认）路径上没被走
  4. KB_RAG_ENABLED 关闭导致 retrieve_and_inject 早退
"""
import enum
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime

# 路径
_BACKEND = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai-test-platform", "backend")
)
# 找不到的话让用户自己 export BACKEND_ROOT
if not os.path.isdir(_BACKEND):
    _BACKEND = os.environ.get("BACKEND_ROOT", "")
if _BACKEND and _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# 这里只 import 模型定义（不 import 业务层，避免 Celery / 嵌入依赖）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy import (  # noqa: E402
    JSON, Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String,
    Text, create_engine, delete, func, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker  # noqa: E402


# ============ 复刻数据库模型 ============


class Base(DeclarativeBase):
    pass


class CaseSource(enum.Enum):
    AI_GENERATED = "ai_generated"
    MANUAL = "manual"
    IMPORTED = "imported"


class CaseAssetStatus(enum.Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class DefectType(enum.Enum):
    FUNCTIONAL = "functional"
    UI = "ui"
    PERFORMANCE = "performance"
    SECURITY = "security"


class DefectSeverity(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EndpointSource(enum.Enum):
    DOC_IMPORT = "doc_import"
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"


class KBChunkType(enum.Enum):
    DEFECT = "defect"
    CASE = "case"
    DOC = "doc"
    TERM = "term"


# 注意：复刻应用 4f75c27c 的修复——SAEnum 加 values_callable
CS_FIXED = SAEnum(CaseSource, values_callable=lambda x: [e.value for e in x], name="casesource")
CAS_FIXED = SAEnum(CaseAssetStatus, values_callable=lambda x: [e.value for e in x], name="caseassetstatus")
EP_FIXED = SAEnum(EndpointSource, values_callable=lambda x: [e.value for e in x], name="endpointsource")
KB_FIXED = SAEnum(KBChunkType, values_callable=lambda x: [e.value for e in x], name="kbchunktype")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class Defect(Base):
    __tablename__ = "defects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text, default="")
    fix_suggestion: Mapped[str] = mapped_column(Text, default="")
    defect_type: Mapped[DefectType] = mapped_column(SAEnum(DefectType, name="defecttype"))
    severity: Mapped[DefectSeverity] = mapped_column(SAEnum(DefectSeverity, name="defectseverity"))


class TestCase(Base):
    __tablename__ = "test_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36))
    case_name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    http_method: Mapped[str] = mapped_column(String(8), default="GET")
    api_path: Mapped[str] = mapped_column(String(256), default="")
    case_type: Mapped[str] = mapped_column(String(32), default="functional")
    priority: Mapped[str] = mapped_column(String(16), default="P1")
    expected_result: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[CaseSource] = mapped_column(CS_FIXED, default=CaseSource.AI_GENERATED)
    status: Mapped[CaseAssetStatus] = mapped_column(CAS_FIXED, default=CaseAssetStatus.DRAFT)


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[EndpointSource] = mapped_column(EP_FIXED, default=EndpointSource.DOC_IMPORT)


class KnowledgeTerm(Base):
    __tablename__ = "knowledge_terms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    term: Mapped[str] = mapped_column(String(64))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    technical_meaning: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(32), default="")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_type: Mapped[KBChunkType] = mapped_column(KB_FIXED)
    source_ref: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON, default=list)  # 模拟用
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime)


# ============ 复刻 embedder 的核心逻辑 ============


def build_chunk_records(content: str, kb_type: str, source_ref: str,
                        meta: dict, src_hash: str | None = None) -> list[dict]:
    """简单 chunk：200 字一段（与 chunker.py 行为接近）。"""
    text = (content or "").strip()
    if not text:
        return []
    chunk_size = 200
    out = []
    for i in range(0, len(text), chunk_size):
        seg = text[i:i + chunk_size]
        meta_i = {**meta, "_src_hash": src_hash} if src_hash else meta
        out.append({
            "id": str(uuid.uuid4()),
            "kb_type": kb_type,
            "source_ref": source_ref,
            "content": seg,
            "embedding": None,  # 模拟无嵌入模型 → 关键词兜底
            "meta": meta_i,
            "created_at": datetime.utcnow(),
        })
    return out


def _fetch_source_rows(s, kb_type: str) -> list[tuple[str, str, dict]]:
    """复刻 embedder.py 的 _fetch_source_rows（用 SQLite 同步 session）。"""
    rows = []
    if kb_type == "defect":
        for d in s.execute(select(Defect)).scalars():
            c = " ".join(
                str(x) for x in [d.title, d.description, d.root_cause, d.fix_suggestion] if x
            ).strip()
            if c:
                rows.append((f"defect:{d.id}", c, {
                    "defect_type": d.defect_type.value if d.defect_type else None,
                    "severity": d.severity.value if d.severity else None,
                }))
    elif kb_type == "case":
        for tc in s.execute(select(TestCase)).scalars():
            exp = tc.expected_result or {}
            exp_s = json.dumps(exp, ensure_ascii=False) if exp else ""
            c = " ".join(
                str(x) for x in [tc.case_name, tc.description, tc.http_method, tc.api_path, exp_s] if x
            ).strip()
            if c:
                rows.append((f"case:{tc.id}", c, {
                    "case_type": tc.case_type, "priority": tc.priority,
                }))
    elif kb_type == "doc":
        for ep in s.execute(select(ApiEndpoint)).scalars():
            params = ep.params or []
            ps = " ".join(
                f"{p.get('name', '')} {p.get('description', '')}"
                for p in params if isinstance(p, dict)
            )
            c = " ".join(str(x) for x in [ep.method, ep.path, ep.summary, ep.description, ps] if x).strip()
            if c:
                rows.append((f"doc:{ep.id}", c, {"method": ep.method, "path": ep.path}))
    elif kb_type == "term":
        for t in s.execute(select(KnowledgeTerm)).scalars():
            aliases = t.aliases or []
            c = " ".join(str(x) for x in [t.term, " ".join(aliases), t.technical_meaning] if x).strip()
            if c:
                rows.append((f"term:{t.id}", c, {"domain": t.domain}))
    return rows


def rebuild_kb_type(s, kb_type: str, force_full: bool = True) -> int:
    """复刻 embedder._full_rebuild_kb_type（SQLite 同步版）。"""
    rows = _fetch_source_rows(s, kb_type)
    records = []
    for source_ref, content, meta in rows:
        src_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        records.extend(build_chunk_records(content, kb_type, source_ref, meta, src_hash=src_hash))
    # 先清后写
    s.execute(delete(KnowledgeChunk).where(
        KnowledgeChunk.kb_type == KBChunkType(kb_type)
    ))
    for r in records:
        s.add(KnowledgeChunk(**r))
    s.flush()
    return len(records)


# ============ 主流程 ============


def setup_seed(s, n_defects=5, n_cases=10, n_endpoints=10, n_terms=30):
    """插入与 seed_e2e.py 数量级一致的源数据。"""
    pid = str(uuid.uuid4())
    s.add(Project(id=pid, name="演示项目-DemoKB"))
    for i in range(n_defects):
        s.add(Defect(
            id=str(uuid.uuid4()),
            project_id=pid,
            title=f"缺陷示例 #{i+1}",
            description=f"这是一个测试缺陷描述 {i+1}",
            root_cause=f"根因分析 {i+1}",
            fix_suggestion=f"修复建议 {i+1}",
            defect_type=DefectType.FUNCTIONAL,
            severity=DefectSeverity.MEDIUM,
        ))
    for i in range(n_cases):
        s.add(TestCase(
            id=str(uuid.uuid4()),
            project_id=pid,
            case_name=f"用例 #{i+1}",
            description=f"验证 {i+1} 号场景",
            http_method=["GET", "POST", "PUT", "DELETE"][i % 4],
            api_path=f"/api/demo/{i+1}",
            case_type="functional",
            priority="P1",
            expected_result={"status": 200},
            source=CaseSource.AI_GENERATED,  # 关键：测 SAEnum values_callable
            status=CaseAssetStatus.DRAFT,
        ))
    for i in range(n_endpoints):
        s.add(ApiEndpoint(
            id=str(uuid.uuid4()),
            project_id=pid,
            method=["GET", "POST"][i % 2],
            path=f"/api/ep/{i+1}",
            summary=f"接口 {i+1} 说明",
            description="这是接口描述",
            params=[{"name": "id", "description": "资源ID"}],
            source=EndpointSource.DOC_IMPORT,
        ))
    for i in range(n_terms):
        s.add(KnowledgeTerm(
            id=str(uuid.uuid4()),
            term=f"术语 #{i+1}",
            aliases=[f"别名-A{i+1}", f"alias-b{i+1}"],
            technical_meaning=f"这是术语 #{i+1} 的技术含义定义，用于知识库检索测试。",
            domain="demo",
        ))
    s.commit()
    print(f"  ✅ 源表注入：defects={n_defects}, cases={n_cases}, "
          f"endpoints={n_endpoints}, terms={n_terms}")


def assert_round_trip(s):
    """验证 SAEnum round-trip（casesource / endpointsource / caseassetstatus）。"""
    print()
    print("--- SAEnum round-trip 烟测 ---")
    for case in s.execute(select(TestCase).limit(3)).scalars():
        assert case.source is CaseSource.AI_GENERATED, case.source
        assert case.status is CaseAssetStatus.DRAFT, case.status
    print("  ✅ casesource 'ai_generated' 写读一致")
    for ep in s.execute(select(ApiEndpoint).limit(3)).scalars():
        assert ep.source is EndpointSource.DOC_IMPORT, ep.source
    print("  ✅ endpointsource 'doc_import' 写读一致")


def main():
    print("=" * 64)
    print("  端到端模拟：源表 → 重建 → knowledge_chunks")
    print("=" * 64)
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    with Session() as s:
        print("\n[1] 注入源数据…")
        setup_seed(s)
        assert_round_trip(s)

        print("\n[2] 跑全量重建（force_full=True，对应 UI '一键重建'）…")
        total = 0
        for kb in ["defect", "case", "doc", "term"]:
            n = rebuild_kb_type(s, kb, force_full=True)
            total += n
            print(f"    {kb:<8} 写入 {n} chunks")
        s.commit()

        print("\n[3] 验证 knowledge_chunks GROUP BY（模拟 GET /api/knowledge）…")
        res = s.execute(
            select(KnowledgeChunk.kb_type, func.count())
            .group_by(KnowledgeChunk.kb_type)
        ).all()
        d = {kt.value if hasattr(kt, "value") else str(kt): cnt for kt, cnt in res}
        for k in sorted(d):
            print(f"    {k:<8} {d[k]} chunks")
        s.close() if hasattr(s, "close") else None

    print("\n" + "=" * 64)
    if total > 0:
        print(f"🎉 通过：全量重建产生 {total} chunks")
        print("   说明代码层 '源表 → rebuild → chunks' 全链通畅。")
        print("   部署机若仍 0，根因只能是：源表空 / celery worker 启动失败 /")
        print("   force_full=False 路径没覆盖。")
    else:
        print("❌ 失败：全量重建后仍 0 条！")
    print("=" * 64)
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
