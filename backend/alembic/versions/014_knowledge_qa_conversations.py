"""新增知识问答会话与消息持久化。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"


def upgrade() -> None:
    op.create_table(
        "knowledge_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False, server_default="新对话"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_message_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "idx_knowledge_conversations_user_updated",
        "knowledge_conversations",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "idx_knowledge_conversations_project", "knowledge_conversations", ["project_id"]
    )

    op.create_table(
        "knowledge_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("feedback_rating", sa.String(length=10), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["knowledge_conversations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_knowledge_message_sequence"
        ),
    )
    op.create_index(
        "idx_knowledge_messages_conversation_created",
        "knowledge_messages",
        ["conversation_id", "created_at"],
    )

    op.add_column(
        "knowledge_feedback",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "knowledge_feedback",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_feedback_conversation",
        "knowledge_feedback",
        "knowledge_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_knowledge_feedback_message",
        "knowledge_feedback",
        "knowledge_messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_knowledge_feedback_conversation", "knowledge_feedback", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_feedback_conversation", table_name="knowledge_feedback")
    op.drop_constraint("fk_knowledge_feedback_message", "knowledge_feedback", type_="foreignkey")
    op.drop_constraint("fk_knowledge_feedback_conversation", "knowledge_feedback", type_="foreignkey")
    op.drop_column("knowledge_feedback", "message_id")
    op.drop_column("knowledge_feedback", "conversation_id")
    op.drop_index("idx_knowledge_messages_conversation_created", table_name="knowledge_messages")
    op.drop_table("knowledge_messages")
    op.drop_index("idx_knowledge_conversations_project", table_name="knowledge_conversations")
    op.drop_index("idx_knowledge_conversations_user_updated", table_name="knowledge_conversations")
    op.drop_table("knowledge_conversations")
