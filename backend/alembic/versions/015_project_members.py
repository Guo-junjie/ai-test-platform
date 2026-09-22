"""项目成员授权，已有项目仅保留负责人和管理员访问权。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "015"
down_revision = "014"


def upgrade():
    op.create_table(
        "project_members",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access", sa.String(16), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
        sa.CheckConstraint("access IN ('read', 'write')", name="ck_project_member_access"),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])


def downgrade():
    op.drop_table("project_members")
