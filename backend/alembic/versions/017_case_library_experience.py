"""用例库结构化编辑、版本与执行追溯字段。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "017"
down_revision = "016"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    asset_columns = {column["name"] for column in inspector.get_columns("test_case_assets")}
    if "folder" not in asset_columns:
        op.add_column("test_case_assets", sa.Column("folder", sa.String(200), nullable=True))
    if "tags" not in asset_columns:
        op.add_column("test_case_assets", sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    if "version" not in asset_columns:
        op.add_column("test_case_assets", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    if "generation_context" not in asset_columns:
        op.add_column("test_case_assets", sa.Column("generation_context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))

    case_columns = {column["name"] for column in inspector.get_columns("test_cases")}
    if "case_asset_id" not in case_columns:
        op.add_column("test_cases", sa.Column("case_asset_id", sa.UUID(), nullable=True))
        op.create_index("ix_test_cases_case_asset_id", "test_cases", ["case_asset_id"])
        op.create_foreign_key(
            "fk_test_cases_case_asset",
            "test_cases",
            "test_case_assets",
            ["case_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if not inspector.has_table("test_case_asset_versions"):
        op.create_table(
            "test_case_asset_versions",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("case_asset_id", sa.UUID(), sa.ForeignKey("test_case_assets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("snapshot", postgresql.JSONB(), nullable=False),
            sa.Column("change_type", sa.String(30), nullable=False, server_default="edit"),
            sa.Column("changed_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("case_asset_id", "version", name="uq_case_asset_version"),
        )
        op.create_index("ix_test_case_asset_versions_case_asset_id", "test_case_asset_versions", ["case_asset_id"])
        op.create_index("idx_case_asset_versions_asset_created", "test_case_asset_versions", ["case_asset_id", "created_at"])


def downgrade() -> None:
    op.drop_table("test_case_asset_versions")
    op.drop_constraint("fk_test_cases_case_asset", "test_cases", type_="foreignkey")
    op.drop_index("ix_test_cases_case_asset_id", table_name="test_cases")
    op.drop_column("test_cases", "case_asset_id")
    op.drop_column("test_case_assets", "generation_context")
    op.drop_column("test_case_assets", "version")
    op.drop_column("test_case_assets", "tags")
    op.drop_column("test_case_assets", "folder")
