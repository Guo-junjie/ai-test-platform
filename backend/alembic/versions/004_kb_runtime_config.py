"""004_kb_runtime_config - 知识库运行时配置表

用途：把 `KB_RAG_ENABLED` 从「env + 重启」升级为「DB 表 + 运行时切换」。
前端在「知识库RAG」页可直接切换开关，API 立即生效，无需重启 backend。
env 仍作首次 fallback（启动时若表为空）。

铁律：与 init_db() 的 create_all 幂等共存；不破坏既有表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_offline() -> bool:
    return op.get_context().is_offline_mode()


def upgrade() -> None:
    if _is_offline():
        tables: set[str] = set()
    else:
        insp = inspect(op.get_bind())
        tables = set(insp.get_table_names())

    if "kb_runtime_config" not in tables:
        op.create_table(
            "kb_runtime_config",
            sa.Column("key", sa.String(64), nullable=False),
            sa.Column("value", JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    if _is_offline():
        op.drop_table("kb_runtime_config")
        return

    insp = inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "kb_runtime_config" in tables:
        op.drop_table("kb_runtime_config")