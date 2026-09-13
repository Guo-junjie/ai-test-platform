"""计划修订版固化可执行用例载荷。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "007"
down_revision = "006"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # 早期 Alembic 链未创建 M2 计划表；新库由 init_db.create_all 建表。
    if inspector.has_table("test_plan_revision_cases") and "case_payload" not in {
        column["name"] for column in inspector.get_columns("test_plan_revision_cases")
    }:
        op.add_column("test_plan_revision_cases", sa.Column("case_payload", JSONB(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("test_plan_revision_cases") and "case_payload" in {
        column["name"] for column in inspector.get_columns("test_plan_revision_cases")
    }:
        op.drop_column("test_plan_revision_cases", "case_payload")
