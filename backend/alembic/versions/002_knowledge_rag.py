"""knowledge_base_rag - 知识库 RAG（能力12）P0 三件事 schema

新增：
  - kbchunktype 枚举（name + value 双标签，兼容 asyncpg，避免 DatatypeMismatchError）
  - knowledge_chunks / knowledge_terms / kb_rebuild_state 三表
  - model_routing.embedding_model_id 列（FK→ai_model_configs，nullable）
  - kb_rebuild_state 幂等种子 (id=1, state='idle')

与 init_db() 的 create_all 幂等共存：upgrade 全程存在性守卫，
重复 `alembic upgrade head` 不报错。

铁律：绝不使用 pgvector，embedding 保持 JSONB。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM as PG_ENUM


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# kbchunktype：同时含成员名(DEFECT...)与成员值(defect...)标签，零风险兼容 asyncpg。
# 运行时 SAEnum(KBChunkType, name="kbchunktype") 持久化成员名（DEFECT/CASE/DOC/TERM），
# 但为兼容历史与双写场景，一并建出 value 形式标签。
_KBCHUNK_TYPE_LABELS = (
    "DEFECT",
    "CASE",
    "DOC",
    "TERM",
    "defect",
    "case",
    "doc",
    "term",
)


def _is_offline() -> bool:
    """离线（--sql 生成）模式：跳过 inspect，直接无条件建/删。"""
    return op.get_context().is_offline_mode()


def upgrade() -> None:
    """建立知识库 RAG 所需的表 / 枚举 / 列（幂等）。"""
    offline = _is_offline()

    if offline:
        tables: set[str] = set()
        existing_enums: set[str] = set()
        model_routing_cols: set[str] = set()
    else:
        bind = op.get_bind()
        insp = inspect(bind)
        tables = set(insp.get_table_names())
        existing_enums = {e["name"] for e in insp.get_enums()}
        model_routing_cols = {c["name"] for c in insp.get_columns("model_routing")}

    # ---- 1. kbchunktype 枚举（不存在则建 8 标签；已存在则补标签，PG16 支持 IF NOT EXISTS） ----
    if "kbchunktype" not in existing_enums:
        labels_sql = ", ".join(f"'{lbl}'" for lbl in _KBCHUNK_TYPE_LABELS)
        op.execute(f'CREATE TYPE "kbchunktype" AS ENUM ({labels_sql})')
    else:
        for lbl in _KBCHUNK_TYPE_LABELS:
            op.execute(f"ALTER TYPE kbchunktype ADD VALUE IF NOT EXISTS '{lbl}'")

    # 引用已创建的类型（create_type=False，避免重复建类型）
    kb_type_col = PG_ENUM(name="kbchunktype", create_type=False)

    # ---- 2. knowledge_chunks（source_ref 仅普通非唯一索引） ----
    if "knowledge_chunks" not in tables:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column("kb_type", kb_type_col, nullable=False),
            sa.Column("source_ref", sa.String(200), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("meta", JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        # 普通（非唯一）索引：一个 source_ref 对应多条 chunk，绝不建唯一约束。
        # 同时补上与 ORM/database.py 一致的单列索引，避免 future alembic
        # autogenerate 持续吐 CREATE INDEX 差异（F1）。
        op.create_index(
            "ix_knowledge_chunks_source_ref", "knowledge_chunks", ["source_ref"]
        )
        op.create_index(
            "ix_knowledge_chunks_kb_type", "knowledge_chunks", ["kb_type"]
        )
        op.create_index(
            "ix_knowledge_chunks_created_at", "knowledge_chunks", ["created_at"]
        )
        op.create_index(
            "ix_knowledge_chunks_type_created",
            "knowledge_chunks",
            ["kb_type", "created_at"],
        )

    # ---- 3. knowledge_terms ----
    if "knowledge_terms" not in tables:
        op.create_table(
            "knowledge_terms",
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column("term", sa.String(200), nullable=False),
            sa.Column("aliases", JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("technical_meaning", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(100), nullable=True),
            sa.Column("meta", JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_knowledge_terms_term", "knowledge_terms", ["term"])
        op.create_index(
            "ix_knowledge_terms_domain", "knowledge_terms", ["domain"]
        )

    # ---- 4. kb_rebuild_state ----
    if "kb_rebuild_state" not in tables:
        op.create_table(
            "kb_rebuild_state",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("state", sa.String(20), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_rebuild", sa.DateTime(), nullable=True),
            sa.Column("last_rebuild_chunks", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    # ---- 5. model_routing.embedding_model_id（列存在则跳过，老库兼容） ----
    if "embedding_model_id" not in model_routing_cols:
        op.add_column(
            "model_routing",
            sa.Column("embedding_model_id", sa.String(64), nullable=True),
        )
        op.create_foreign_key(
            "fk_model_routing_embedding",
            "model_routing",
            "ai_model_configs",
            ["embedding_model_id"],
            ["id"],
        )

    # ---- 6. 幂等种子 kb_rebuild_state(id=1, state='idle') ----
    op.execute(
        "INSERT INTO kb_rebuild_state (id, state) "
        "SELECT 1, 'idle' WHERE NOT EXISTS "
        "(SELECT 1 FROM kb_rebuild_state WHERE id = 1)"
    )


def downgrade() -> None:
    """对称回滚（逆序）。全程存在性守卫，避免 init_db()/create_all 抢先建
    表/列/索引/外键后回滚中断。
    """
    if _is_offline():
        op.drop_constraint(
            "fk_model_routing_embedding", "model_routing", type_="foreignkey"
        )
        op.drop_column("model_routing", "embedding_model_id")
        op.drop_table("kb_rebuild_state")
        op.drop_table("knowledge_terms")
        op.drop_index(
            "ix_knowledge_chunks_type_created", table_name="knowledge_chunks"
        )
        op.drop_index(
            "ix_knowledge_chunks_created_at", table_name="knowledge_chunks"
        )
        op.drop_index(
            "ix_knowledge_chunks_kb_type", table_name="knowledge_chunks"
        )
        op.drop_index(
            "ix_knowledge_chunks_source_ref", table_name="knowledge_chunks"
        )
        op.drop_table("knowledge_chunks")
        op.execute('DROP TYPE IF EXISTS "kbchunktype"')
        return

    bind = op.get_bind()
    insp = inspect(bind)

    # 先取 FK 集合——FK 是否存在决定能否 drop（F2 必修）
    fks = {fk["name"] for fk in insp.get_foreign_keys("model_routing")}
    cols = {c["name"] for c in insp.get_columns("model_routing")}
    if "fk_model_routing_embedding" in fks:
        op.drop_constraint(
            "fk_model_routing_embedding", "model_routing", type_="foreignkey"
        )
    if "embedding_model_id" in cols:
        op.drop_column("model_routing", "embedding_model_id")

    table_names = set(insp.get_table_names())
    if "kb_rebuild_state" in table_names:
        op.drop_table("kb_rebuild_state")
    if "knowledge_terms" in table_names:
        op.drop_table("knowledge_terms")
    if "knowledge_chunks" in table_names:
        # 与 upgrade 对称；按存在性守卫逐个 drop（drop_table 会自动删索引，
        # 这些显式 drop 只是为兼容部分索引由外部路径建的场景）
        existing_idx = {
            i["name"] for i in insp.get_indexes("knowledge_chunks")
        }
        for idx_name in (
            "ix_knowledge_chunks_type_created",
            "ix_knowledge_chunks_created_at",
            "ix_knowledge_chunks_kb_type",
            "ix_knowledge_chunks_source_ref",
        ):
            if idx_name in existing_idx:
                op.drop_index(idx_name, table_name="knowledge_chunks")
        op.drop_table("knowledge_chunks")

    op.execute('DROP TYPE IF EXISTS "kbchunktype"')
