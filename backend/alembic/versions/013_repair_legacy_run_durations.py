"""修复历史时区混用造成的约 8 小时执行时长。"""

from alembic import op

revision = "013"
down_revision = "012"


def upgrade() -> None:
    # 旧 worker 用数据库 NOW() 写入无时区字段，Asia/Shanghai 会比应用 UTC 时间多 8 小时。
    # 仅在结果实际执行时间能证明该偏差时修复，避免改动真实长时间任务。
    op.execute("""
        WITH result_times AS (
            SELECT test_run_id, MAX(executed_at) AS actual_finished
            FROM test_results
            WHERE executed_at IS NOT NULL
            GROUP BY test_run_id
        )
        UPDATE test_plan_executions pe
        SET finished_at = rt.actual_finished,
            duration_ms = GREATEST(
                0,
                (EXTRACT(EPOCH FROM (rt.actual_finished - pe.started_at)) * 1000)::integer
            )
        FROM result_times rt
        WHERE pe.test_run_id = rt.test_run_id
          AND pe.finished_at - rt.actual_finished BETWEEN INTERVAL '7 hours 30 minutes'
                                                       AND INTERVAL '8 hours 30 minutes'
    """)
    op.execute("""
        WITH result_times AS (
            SELECT test_run_id, MAX(executed_at) AS actual_finished
            FROM test_results
            WHERE executed_at IS NOT NULL
            GROUP BY test_run_id
        )
        UPDATE test_runs tr
        SET completed_at = rt.actual_finished
        FROM result_times rt
        WHERE tr.id = rt.test_run_id
          AND tr.completed_at - rt.actual_finished > INTERVAL '6 hours'
          AND rt.actual_finished >= COALESCE(tr.started_at, tr.created_at)
    """)


def downgrade() -> None:
    # 无法可靠恢复错误的本地时区时间。
    pass
