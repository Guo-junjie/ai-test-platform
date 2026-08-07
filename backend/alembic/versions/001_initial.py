"""initial migration - create all tables

Revision ID: 001
Revises:
Create Date: 2025-01-15 00:00:00

创建全部 10 张表及 PostgreSQL 原生枚举类型。
表结构严格对齐 app/models/database.py 中的 SQLAlchemy 模型定义。

Tables:
    1. users              — 用户表
    2. projects           — 项目表（多租户隔离）
    3. ai_model_configs   — AI 模型配置表
    4. model_routing      — 模型路由配置表
    5. test_runs          — 测试任务表
    6. test_cases         — 测试用例表
    7. test_results       — 测试结果表
    8. defects            — 缺陷表
    9. test_reports       — 测试报告表
    10. audit_logs        — 审计日志表

Enum Types:
    UserRole, SourceType, TestStatus, DefectSeverity, DefectType, ModelProvider
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM as PG_ENUM


# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ==================== 枚举类型定义 ====================

ENUM_DEFINITIONS = [
    ("UserRole", ["admin", "tester", "developer", "viewer"]),
    ("SourceType", ["github", "svn", "upload"]),
    (
        "TestStatus",
        [
            "pending",
            "pulling",
            "analyzing",
            "generating",
            "executing",
            "analyzing_defects",
            "reporting",
            "completed",
            "failed",
            "cancelled",
        ],
    ),
    ("DefectSeverity", ["P0", "P1", "P2", "P3"]),
    (
        "DefectType",
        ["business", "program", "performance", "integration", "security"],
    ),
    ("ModelProvider", ["openai", "anthropic", "custom", "local"]),
]


def _create_enum_types() -> None:
    """创建所有 PostgreSQL 原生枚举类型。"""
    for enum_name, values in ENUM_DEFINITIONS:
        values_sql = ", ".join(f"'{v}'" for v in values)
        op.execute(
            f'CREATE TYPE "{enum_name}" AS ENUM ({values_sql})'
        )


def _drop_enum_types() -> None:
    """删除所有 PostgreSQL 原生枚举类型（逆序）。"""
    for enum_name, _ in reversed(ENUM_DEFINITIONS):
        op.execute(f'DROP TYPE IF EXISTS "{enum_name}"')


def _enum(name: str) -> PG_ENUM:
    """引用已创建的枚举类型（不重复创建）。"""
    return PG_ENUM(name=name, create_type=False)


# ==================== Upgrade ====================


def upgrade() -> None:
    """创建全部表结构与枚举类型。"""

    # -------- 1. 创建枚举类型 --------
    _create_enum_types()

    # -------- 2. users 表 --------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", _enum("UserRole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # -------- 3. projects 表 --------
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", _enum("SourceType"), nullable=False),
        sa.Column("source_config", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quality_gate_config", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -------- 4. ai_model_configs 表 --------
    op.create_table(
        "ai_model_configs",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider", _enum("ModelProvider"), nullable=False),
        sa.Column("api_base_url", sa.String(500), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("api_version", sa.String(50), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("timeout", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("use_cases", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.Column("is_fallback", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # -------- 5. model_routing 表 --------
    op.create_table(
        "model_routing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code_analysis_model_id", sa.String(64), nullable=False),
        sa.Column("case_generation_model_id", sa.String(64), nullable=False),
        sa.Column("defect_analysis_model_id", sa.String(64), nullable=False),
        sa.Column("fix_suggestion_model_id", sa.String(64), nullable=False),
        sa.Column("fallback_model_id", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["code_analysis_model_id"], ["ai_model_configs.id"]),
        sa.ForeignKeyConstraint(["case_generation_model_id"], ["ai_model_configs.id"]),
        sa.ForeignKeyConstraint(["defect_analysis_model_id"], ["ai_model_configs.id"]),
        sa.ForeignKeyConstraint(["fix_suggestion_model_id"], ["ai_model_configs.id"]),
        sa.ForeignKeyConstraint(["fallback_model_id"], ["ai_model_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # -------- 6. test_runs 表 --------
    op.create_table(
        "test_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", _enum("SourceType"), nullable=False),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("branch", sa.String(200), nullable=True),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("commit_message", sa.Text(), nullable=True),
        sa.Column("status", _enum("TestStatus"), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("analysis_result", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_test_runs_project_status", "test_runs", ["project_id", "status"])
    op.create_index("idx_test_runs_created", "test_runs", ["created_at"])

    # -------- 7. test_cases 表 --------
    op.create_table(
        "test_cases",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("case_type", sa.String(50), nullable=False),
        sa.Column("case_name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("request_data", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_result", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_rules", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("priority", sa.String(10), nullable=True),
        sa.Column("api_path", sa.String(500), nullable=True),
        sa.Column("http_method", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_test_cases_run_type", "test_cases", ["test_run_id", "case_type"])

    # -------- 8. test_results 表 --------
    op.create_table(
        "test_results",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_case_id", UUID(as_uuid=True), nullable=False),
        sa.Column("is_passed", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("tps", sa.Float(), nullable=True),
        sa.Column("qps", sa.Float(), nullable=True),
        sa.Column("error_rate", sa.Float(), nullable=True),
        sa.Column("concurrent_users", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_trace", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"]),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_test_results_run_passed", "test_results", ["test_run_id", "is_passed"]
    )

    # -------- 9. defects 表 --------
    op.create_table(
        "defects",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_case_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("defect_type", _enum("DefectType"), nullable=False),
        sa.Column("severity", _enum("DefectSeverity"), nullable=False),
        sa.Column("reproduce_steps", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("fix_suggestion", sa.Text(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"]),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_defects_run_severity", "defects", ["test_run_id", "severity"]
    )

    # -------- 10. test_reports 表 --------
    op.create_table(
        "test_reports",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("report_data", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("html_path", sa.String(500), nullable=True),
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("share_token", sa.String(64), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("gate_passed", sa.Boolean(), nullable=True),
        sa.Column("gate_details", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("share_token"),
    )

    # -------- 11. audit_logs 表 --------
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("details", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_audit_logs_user_created", "audit_logs", ["user_id", "created_at"]
    )
    op.create_index("idx_audit_logs_action", "audit_logs", ["action"])


# ==================== Downgrade ====================


def downgrade() -> None:
    """删除全部表与枚举类型（逆序）。"""

    # -------- 删除表（逆序，尊重外键约束） --------
    op.drop_table("audit_logs")
    op.drop_table("test_reports")
    op.drop_table("defects")
    op.drop_table("test_results")
    op.drop_table("test_cases")
    op.drop_table("test_runs")
    op.drop_table("model_routing")
    op.drop_table("ai_model_configs")
    op.drop_table("projects")
    op.drop_table("users")

    # -------- 删除枚举类型 --------
    _drop_enum_types()
