"""model capabilities and explicit project kind

Revision ID: 016
Revises: 015
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_model_configs", sa.Column(
        "capabilities", postgresql.JSONB(astext_type=sa.Text()),
        nullable=False, server_default=sa.text("'[\"chat\"]'::jsonb"),
    ))
    op.add_column("projects", sa.Column(
        "project_kind", sa.String(length=32), nullable=False, server_default="full",
    ))
    op.create_check_constraint(
        "ck_projects_project_kind", "projects",
        "project_kind IN ('full', 'api_testing', 'source_analysis')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projects_project_kind", "projects", type_="check")
    op.drop_column("projects", "project_kind")
    op.drop_column("ai_model_configs", "capabilities")
