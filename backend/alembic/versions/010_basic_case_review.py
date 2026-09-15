"""用例评审状态与追加式操作记录。"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("test_case_assets")}
    if "review_state" not in columns:
        op.add_column("test_case_assets", sa.Column("review_state", sa.String(24),
                                                    nullable=False, server_default="draft"))
    op.execute("UPDATE test_case_assets SET review_state = 'approved' WHERE status::text IN ('adopted', 'ADOPTED')")
    if not inspector.has_table("case_review_events"):
        op.create_table(
            "case_review_events",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("case_asset_id", sa.UUID(), sa.ForeignKey("test_case_assets.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action", sa.String(24), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_case_review_events_case_asset_id ON case_review_events (case_asset_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_case_review_events_project_id ON case_review_events (project_id)")


def downgrade() -> None:
    op.drop_index("ix_case_review_events_project_id", table_name="case_review_events")
    op.drop_index("ix_case_review_events_case_asset_id", table_name="case_review_events")
    op.drop_table("case_review_events")
    op.drop_column("test_case_assets", "review_state")
