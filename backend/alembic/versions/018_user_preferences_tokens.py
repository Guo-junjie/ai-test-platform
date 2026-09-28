"""用户通知偏好与个人 API Token。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "018"
down_revision = "017"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("user_preferences"):
        op.create_table(
            "user_preferences",
            sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("notification_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if not inspector.has_table("personal_access_tokens"):
        op.create_table(
            "personal_access_tokens",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("prefix", sa.String(16), nullable=False),
            sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_personal_access_tokens_user_id", "personal_access_tokens", ["user_id"])
        op.create_index("ix_personal_access_tokens_token_hash", "personal_access_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("personal_access_tokens")
    op.drop_table("user_preferences")
