"""引入覆盖率采集会话和服务状态，保留旧覆盖率报告。"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade() -> None:
    from app.models.database import CoverageRun, CoverageService

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("coverage_reports"):
        columns = {column["name"] for column in inspector.get_columns("coverage_reports")}
        if "coverage_run_id" not in columns:
            op.add_column("coverage_reports", sa.Column("coverage_run_id", sa.UUID(), nullable=True))
        if "service_name" not in columns:
            op.add_column("coverage_reports", sa.Column("service_name", sa.String(200), nullable=True))
        op.execute("CREATE INDEX IF NOT EXISTS ix_coverage_reports_coverage_run_id ON coverage_reports (coverage_run_id)")
    CoverageRun.__table__.create(bind, checkfirst=True)
    CoverageService.__table__.create(bind, checkfirst=True)
    foreign_keys = sa.inspect(bind).get_foreign_keys("coverage_reports")
    if not any(fk.get("constrained_columns") == ["coverage_run_id"] for fk in foreign_keys):
        op.create_foreign_key("fk_coverage_reports_run", "coverage_reports", "coverage_runs",
                              ["coverage_run_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    for fk in sa.inspect(op.get_bind()).get_foreign_keys("coverage_reports"):
        if fk.get("constrained_columns") == ["coverage_run_id"]:
            op.drop_constraint(fk["name"], "coverage_reports", type_="foreignkey")
    op.drop_table("coverage_services")
    op.drop_table("coverage_runs")
    op.drop_index("ix_coverage_reports_coverage_run_id", table_name="coverage_reports")
    op.drop_column("coverage_reports", "service_name")
    op.drop_column("coverage_reports", "coverage_run_id")
