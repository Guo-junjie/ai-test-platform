"""缺陷协作与工作流引用约束加固。"""
from alembic import op

revision = "022"
down_revision = "021"


def upgrade():
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_defect_workflow_active_revision') THEN
            ALTER TABLE defect_workflows ADD CONSTRAINT fk_defect_workflow_active_revision
            FOREIGN KEY(active_revision_id) REFERENCES defect_workflow_revisions(id) ON DELETE RESTRICT;
        END IF;
    END $$""")
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_notification_outbox_event') THEN
            ALTER TABLE notification_outbox ADD CONSTRAINT fk_notification_outbox_event
            FOREIGN KEY(event_id) REFERENCES defect_events(id) ON DELETE RESTRICT;
        END IF;
    END $$""")


def downgrade():
    op.execute("ALTER TABLE notification_outbox DROP CONSTRAINT IF EXISTS fk_notification_outbox_event")
    op.execute("ALTER TABLE defect_workflows DROP CONSTRAINT IF EXISTS fk_defect_workflow_active_revision")
