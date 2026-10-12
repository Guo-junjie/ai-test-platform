"""缺陷协作、可靠通知、批量作业、指标快照与工作流草稿。"""

from alembic import op

revision = "020"
down_revision = "019"


DDL = [
    "ALTER TABLE project_defect_settings ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai'",
    "ALTER TABLE defect_workflows ADD COLUMN IF NOT EXISTS active_revision_id UUID",
    "ALTER TABLE defect_workflows ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()",
    "CREATE TABLE IF NOT EXISTS defect_comments (id UUID PRIMARY KEY, defect_id UUID NOT NULL, project_id UUID NOT NULL REFERENCES projects(id), author_id UUID NOT NULL REFERENCES users(id), body TEXT NOT NULL, mention_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb, row_version INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), edited_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ, FOREIGN KEY(defect_id, project_id) REFERENCES defects(id, project_id) ON DELETE RESTRICT)",
    "CREATE INDEX IF NOT EXISTS ix_defect_comments_defect_id ON defect_comments(defect_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_comments_project_id ON defect_comments(project_id)",
    "CREATE TABLE IF NOT EXISTS defect_watchers (id UUID PRIMARY KEY, defect_id UUID NOT NULL, project_id UUID NOT NULL REFERENCES projects(id), user_id UUID NOT NULL REFERENCES users(id), kind VARCHAR(16) NOT NULL DEFAULT 'watch', created_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), FOREIGN KEY(defect_id, project_id) REFERENCES defects(id, project_id) ON DELETE RESTRICT, CONSTRAINT uq_defect_watcher_kind UNIQUE(defect_id,user_id,kind), CONSTRAINT ck_defect_watcher_kind CHECK(kind IN ('watch','cc')))",
    "CREATE INDEX IF NOT EXISTS ix_defect_watchers_defect_id ON defect_watchers(defect_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_watchers_project_id ON defect_watchers(project_id)",
    "CREATE TABLE IF NOT EXISTS defect_attachments (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), defect_id UUID, comment_id UUID REFERENCES defect_comments(id), uploader_id UUID NOT NULL REFERENCES users(id), filename VARCHAR(500) NOT NULL, content_type VARCHAR(200) NOT NULL, size INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL, object_key VARCHAR(700) NOT NULL UNIQUE, status VARCHAR(16) NOT NULL DEFAULT 'staged', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ, FOREIGN KEY(defect_id, project_id) REFERENCES defects(id, project_id) ON DELETE RESTRICT, CONSTRAINT ck_defect_attachment_status CHECK(status IN ('staged','ready','failed','deleted')))",
    "CREATE INDEX IF NOT EXISTS ix_defect_attachments_project_id ON defect_attachments(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_defect_attachments_defect_id ON defect_attachments(defect_id)",
    "CREATE TABLE IF NOT EXISTS notification_outbox (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), event_id UUID NOT NULL UNIQUE, payload JSONB NOT NULL DEFAULT '{}'::jsonb, status VARCHAR(16) NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(), locked_until TIMESTAMPTZ, last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), CONSTRAINT ck_notification_outbox_status CHECK(status IN ('pending','processing','completed','failed')))",
    "CREATE INDEX IF NOT EXISTS ix_notification_outbox_project_id ON notification_outbox(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_notification_outbox_ready ON notification_outbox(status,next_attempt_at)",
    "CREATE TABLE IF NOT EXISTS notification_deliveries (id UUID PRIMARY KEY, outbox_id UUID NOT NULL REFERENCES notification_outbox(id) ON DELETE CASCADE, user_id UUID NOT NULL REFERENCES users(id), channel VARCHAR(20) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, delivered_at TIMESTAMPTZ, last_error TEXT, CONSTRAINT uq_notification_delivery_target UNIQUE(outbox_id,user_id,channel))",
    "CREATE TABLE IF NOT EXISTS defect_views (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), owner_id UUID NOT NULL REFERENCES users(id), name VARCHAR(100) NOT NULL, visibility VARCHAR(16) NOT NULL DEFAULT 'private', query_json JSONB NOT NULL DEFAULT '{}'::jsonb, columns_json JSONB NOT NULL DEFAULT '[]'::jsonb, sort_json JSONB NOT NULL DEFAULT '[]'::jsonb, row_version INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), CONSTRAINT uq_defect_view_owner_name UNIQUE(project_id,owner_id,name), CONSTRAINT ck_defect_view_visibility CHECK(visibility IN ('private','project')))",
    "CREATE INDEX IF NOT EXISTS ix_defect_views_project_id ON defect_views(project_id)",
    "CREATE TABLE IF NOT EXISTS defect_jobs (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), creator_id UUID NOT NULL REFERENCES users(id), kind VARCHAR(24) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'pending', request_key UUID NOT NULL, input_hash VARCHAR(64) NOT NULL, input_key VARCHAR(700), result_key VARCHAR(700), summary_json JSONB NOT NULL DEFAULT '{}'::jsonb, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ, CONSTRAINT uq_defect_job_request UNIQUE(project_id,creator_id,kind,request_key), CONSTRAINT ck_defect_job_kind CHECK(kind IN ('import_preview','import_commit','export','workflow_migration')), CONSTRAINT ck_defect_job_status CHECK(status IN ('pending','running','completed','failed','expired')))",
    "CREATE INDEX IF NOT EXISTS ix_defect_jobs_project_id ON defect_jobs(project_id)",
    "CREATE TABLE IF NOT EXISTS defect_daily_metrics (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id), date TIMESTAMPTZ NOT NULL, timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai', definition_version INTEGER NOT NULL DEFAULT 1, dimension_key VARCHAR(200) NOT NULL DEFAULT 'all', dimensions_json JSONB NOT NULL DEFAULT '{}'::jsonb, metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb, calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(), history_coverage_from TIMESTAMPTZ, CONSTRAINT uq_defect_daily_metric UNIQUE(project_id,date,dimension_key,definition_version))",
    "CREATE INDEX IF NOT EXISTS ix_defect_daily_metrics_project_id ON defect_daily_metrics(project_id)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS source_event_id UUID",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS resource_type VARCHAR(50)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS resource_id UUID",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(200)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_dedupe_key ON notifications(dedupe_key) WHERE dedupe_key IS NOT NULL",
    "UPDATE defect_workflows w SET active_revision_id=(SELECT r.id FROM defect_workflow_revisions r WHERE r.workflow_id=w.id AND r.status='published' ORDER BY r.revision DESC LIMIT 1) WHERE w.active_revision_id IS NULL",
]


def upgrade():
    for statement in DDL:
        op.execute(statement)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_notifications_dedupe_key")
    for column in ("dedupe_key", "resource_id", "resource_type", "source_event_id"):
        op.execute(f"ALTER TABLE notifications DROP COLUMN IF EXISTS {column}")
    for table in ("defect_daily_metrics", "defect_jobs", "defect_views", "notification_deliveries", "notification_outbox", "defect_attachments", "defect_watchers", "defect_comments"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE defect_workflows DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE defect_workflows DROP COLUMN IF EXISTS active_revision_id")
    op.execute("ALTER TABLE project_defect_settings DROP COLUMN IF EXISTS timezone")
