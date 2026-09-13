"""为 Go coverprofile 增加覆盖率工具枚举值。"""

from alembic import op

revision = "008"
down_revision = "007"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE coveragetool ADD VALUE IF NOT EXISTS 'GO_COVER'")
        op.execute("ALTER TYPE coveragetool ADD VALUE IF NOT EXISTS 'go_cover'")


def downgrade() -> None:
    # PostgreSQL 不支持安全删除枚举值；历史报告可能引用该值。
    pass
