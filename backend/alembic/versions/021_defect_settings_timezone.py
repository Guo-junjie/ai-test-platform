"""缺陷指标与项目配置时区。"""
from alembic import op

revision = "021"
down_revision = "020"


def upgrade():
    # IF NOT EXISTS 兼容从最终版 020 全新安装，以及早期已执行 020 的部署。
    op.execute("ALTER TABLE project_defect_settings ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai'")


def downgrade():
    op.execute("ALTER TABLE project_defect_settings DROP COLUMN IF EXISTS timezone")
