"""异步用例生成任务与手工执行闭环。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "024"
down_revision = "023"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("case_generation_tasks"):
        op.create_table(
            "case_generation_tasks",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("source_doc_id", sa.UUID(), sa.ForeignKey("interface_docs.id", ondelete="SET NULL")),
            sa.Column("endpoint_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("endpoint_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_case_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("generated_case_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("generation_engine", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("degraded_reason", sa.Text()),
            sa.Column("error_message", sa.Text()),
            sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("celery_task_id", sa.String(100)),
            sa.Column("started_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_case_generation_task_status"),
            sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_case_generation_task_progress"),
        )
        op.create_index("ix_case_generation_tasks_project_id", "case_generation_tasks", ["project_id"])
        op.create_index("ix_case_generation_tasks_created_by", "case_generation_tasks", ["created_by"])
        op.create_index("idx_case_generation_tasks_project_created", "case_generation_tasks", ["project_id", "created_at"])
        op.create_index("idx_case_generation_tasks_creator_status", "case_generation_tasks", ["created_by", "status", "created_at"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("manual_case_executions"):
        op.create_table(
            "manual_case_executions",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("case_asset_id", sa.UUID(), sa.ForeignKey("test_case_assets.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("case_version_id", sa.UUID(), sa.ForeignKey("test_case_asset_versions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("case_version", sa.Integer(), nullable=False),
            sa.Column("executed_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="in_progress"),
            sa.Column("step_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("actual_result", sa.Text()),
            sa.Column("notes", sa.Text()),
            sa.Column("defect_id", sa.UUID(), sa.ForeignKey("defects.id", ondelete="SET NULL")),
            sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('in_progress', 'passed', 'failed', 'blocked', 'cancelled')", name="ck_manual_case_execution_status"),
        )
        op.create_index("ix_manual_case_executions_project_id", "manual_case_executions", ["project_id"])
        op.create_index("ix_manual_case_executions_case_asset_id", "manual_case_executions", ["case_asset_id"])
        op.create_index("ix_manual_case_executions_executed_by", "manual_case_executions", ["executed_by"])
        op.create_index("idx_manual_case_executions_case_created", "manual_case_executions", ["case_asset_id", "created_at"])
        op.create_index("idx_manual_case_executions_project_status", "manual_case_executions", ["project_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_table("manual_case_executions")
    op.drop_table("case_generation_tasks")
