"""回填历史测试任务开始时间，统一执行时长的 UTC 计算基准。"""

from alembic import op

revision = "012"
down_revision = "011"


def upgrade() -> None:
    op.execute("UPDATE test_runs SET started_at = created_at WHERE started_at IS NULL")


def downgrade() -> None:
    # started_at 已成为执行审计字段，不删除已回填的历史证据。
    pass
