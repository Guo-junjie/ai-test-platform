"""用例评审任务、评审人及不可变版本绑定。"""

from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "023"
down_revision = "022"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("case_review_tasks"):
        op.create_table(
            "case_review_tasks",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("case_asset_id", sa.UUID(), sa.ForeignKey("test_case_assets.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("case_version_id", sa.UUID(), sa.ForeignKey("test_case_asset_versions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("case_version", sa.Integer(), nullable=False),
            sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("approval_rule", sa.String(16), nullable=False, server_default="all"),
            sa.Column("submission_comment", sa.Text(), nullable=True),
            sa.Column("submitted_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("submitted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("case_asset_id", "round", name="uq_case_review_task_round"),
            sa.CheckConstraint("status IN ('pending', 'approved', 'changes_requested', 'cancelled')", name="ck_case_review_task_status"),
            sa.CheckConstraint("approval_rule IN ('all')", name="ck_case_review_task_rule"),
        )
        op.create_index("ix_case_review_tasks_project_id", "case_review_tasks", ["project_id"])
        op.create_index("ix_case_review_tasks_case_asset_id", "case_review_tasks", ["case_asset_id"])
        op.create_index("idx_case_review_tasks_project_status", "case_review_tasks", ["project_id", "status", "created_at"])
        op.create_index("idx_case_review_tasks_asset_created", "case_review_tasks", ["case_asset_id", "created_at"])
        op.create_index(
            "uq_case_review_tasks_active",
            "case_review_tasks",
            ["case_asset_id"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("case_review_assignments"):
        op.create_table(
            "case_review_assignments",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column("task_id", sa.UUID(), sa.ForeignKey("case_review_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reviewer_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("task_id", "reviewer_id", name="uq_case_review_assignment_reviewer"),
            sa.CheckConstraint("status IN ('pending', 'approved', 'changes_requested', 'cancelled')", name="ck_case_review_assignment_status"),
        )
        op.create_index("ix_case_review_assignments_task_id", "case_review_assignments", ["task_id"])
        op.create_index("ix_case_review_assignments_reviewer_id", "case_review_assignments", ["reviewer_id"])
        op.create_index(
            "idx_case_review_assignments_reviewer_status",
            "case_review_assignments",
            ["reviewer_id", "status", "created_at"],
        )

    inspector = sa.inspect(bind)
    event_columns = {column["name"] for column in inspector.get_columns("case_review_events")}
    if "task_id" not in event_columns:
        op.add_column("case_review_events", sa.Column("task_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_case_review_events_task",
            "case_review_events",
            "case_review_tasks",
            ["task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_case_review_events_task_id", "case_review_events", ["task_id"])
    if "case_version_id" not in event_columns:
        op.add_column("case_review_events", sa.Column("case_version_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_case_review_events_version",
            "case_review_events",
            "test_case_asset_versions",
            ["case_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "case_version" not in event_columns:
        op.add_column("case_review_events", sa.Column("case_version", sa.Integer(), nullable=True))

    _backfill_legacy_pending(bind)


def _backfill_legacy_pending(bind) -> None:
    """为升级前的待评审用例补任务；无可用评审人时安全退回草稿。"""
    assets = bind.execute(sa.text("""
        SELECT a.id, a.project_id, a.created_by, a.version, a.title, a.description,
               a.execution_kind, a.case_type, a.request_data, a.expected_result,
               a.priority, a.folder, a.tags, a.pre_script, a.post_script, a.sql_script,
               p.owner_id
          FROM test_case_assets a
          JOIN projects p ON p.id = a.project_id
         WHERE a.review_state = 'pending'
           AND NOT EXISTS (
               SELECT 1 FROM case_review_tasks t
                WHERE t.case_asset_id = a.id AND t.status = 'pending'
           )
    """)).mappings().all()
    now = datetime.utcnow()
    for asset in assets:
        submitter = bind.execute(sa.text("""
            SELECT actor_id FROM case_review_events
             WHERE case_asset_id = :case_id AND action = 'submit'
             ORDER BY created_at DESC LIMIT 1
        """), {"case_id": asset["id"]}).scalar_one_or_none() or asset["created_by"] or asset["owner_id"]
        reviewer = bind.execute(sa.text("""
            SELECT u.id
              FROM users u
              LEFT JOIN project_members pm ON pm.user_id = u.id AND pm.project_id = :project_id
             WHERE u.is_active IS TRUE
               AND u.role::text IN ('SUPER_ADMIN', 'ADMIN', 'TEST_MANAGER', 'super_admin', 'admin', 'test_manager')
               AND (u.id = :owner_id OR pm.project_id IS NOT NULL OR u.role::text IN ('SUPER_ADMIN', 'ADMIN', 'super_admin', 'admin'))
             ORDER BY CASE WHEN u.id = :owner_id THEN 0 WHEN pm.project_id IS NOT NULL THEN 1 ELSE 2 END,
                      u.created_at ASC
             LIMIT 1
        """), {"project_id": asset["project_id"], "owner_id": asset["owner_id"]}).scalar_one_or_none()
        if reviewer is None or submitter is None:
            bind.execute(sa.text("""
                UPDATE test_case_assets SET review_state = 'draft', status = 'draft'
                 WHERE id = :case_id
            """), {"case_id": asset["id"]})
            continue

        version = int(asset["version"] or 1)
        version_id = bind.execute(sa.text("""
            SELECT id FROM test_case_asset_versions
             WHERE case_asset_id = :case_id AND version = :version
        """), {"case_id": asset["id"], "version": version}).scalar_one_or_none()
        if version_id is None:
            version_id = uuid.uuid4()
            snapshot = {
                "title": asset["title"], "description": asset["description"] or "",
                "execution_kind": asset["execution_kind"] or "api", "case_type": asset["case_type"],
                "request_data": asset["request_data"] or {}, "expected_result": asset["expected_result"] or {},
                "priority": asset["priority"] or "P2", "folder": asset["folder"] or "",
                "tags": asset["tags"] or [],
                "pre_script": asset["pre_script"] or "", "post_script": asset["post_script"] or "",
                "sql_script": asset["sql_script"] or "",
            }
            bind.execute(sa.text("""
                INSERT INTO test_case_asset_versions
                    (id, case_asset_id, version, snapshot, change_type, changed_by, created_at)
                VALUES (:id, :case_id, :version, CAST(:snapshot AS jsonb), 'legacy_baseline', :actor, :created_at)
            """), {"id": version_id, "case_id": asset["id"], "version": version,
                    "snapshot": __import__("json").dumps(snapshot, ensure_ascii=False, default=str),
                    "actor": asset["created_by"], "created_at": now})

        task_id = uuid.uuid4()
        bind.execute(sa.text("""
            INSERT INTO case_review_tasks
                (id, project_id, case_asset_id, case_version_id, case_version, round, status,
                 approval_rule, submission_comment, submitted_by, submitted_at, created_at, updated_at)
            VALUES (:id, :project_id, :case_id, :version_id, :version, 1, 'pending',
                    'all', '由历史待评审状态迁移', :submitter, :created_at, :created_at, :created_at)
        """), {"id": task_id, "project_id": asset["project_id"], "case_id": asset["id"],
                "version_id": version_id, "version": version, "submitter": submitter, "created_at": now})
        bind.execute(sa.text("""
            INSERT INTO case_review_assignments
                (id, task_id, reviewer_id, status, created_at, updated_at)
            VALUES (:id, :task_id, :reviewer_id, 'pending', :created_at, :created_at)
        """), {"id": uuid.uuid4(), "task_id": task_id, "reviewer_id": reviewer, "created_at": now})
        bind.execute(sa.text("""
            UPDATE case_review_events
               SET task_id = :task_id, case_version_id = :version_id, case_version = :version
             WHERE id = (
                 SELECT id FROM case_review_events
                  WHERE case_asset_id = :case_id AND action = 'submit'
                  ORDER BY created_at DESC LIMIT 1
             )
        """), {"task_id": task_id, "version_id": version_id, "version": version,
                "case_id": asset["id"]})


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    event_columns = {column["name"] for column in inspector.get_columns("case_review_events")}
    if "case_version" in event_columns:
        op.drop_column("case_review_events", "case_version")
    if "case_version_id" in event_columns:
        op.drop_constraint("fk_case_review_events_version", "case_review_events", type_="foreignkey")
        op.drop_column("case_review_events", "case_version_id")
    if "task_id" in event_columns:
        op.drop_index("ix_case_review_events_task_id", table_name="case_review_events")
        op.drop_constraint("fk_case_review_events_task", "case_review_events", type_="foreignkey")
        op.drop_column("case_review_events", "task_id")
    op.drop_table("case_review_assignments")
    op.drop_table("case_review_tasks")
