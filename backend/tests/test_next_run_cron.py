"""5 段式 cron 下次执行时间计算器测试（能力8 调度核心，纯函数无 IO）。

时间约定：cron 按北京时间解释，返回 naive UTC。
回归背景：2026-08-30 部署机实锤 django-celery-beat 无法在 FastAPI 项目工作，
自研 tick 调度依赖本计算器——这里的用例是调度正确性的最后防线。
"""
from datetime import datetime

import pytest

from app.modules.scheduler.next_run import next_run

# 基准点：2026-08-30 是周日；12:00 UTC = 北京 20:00
AFTER = datetime(2026, 8, 30, 12, 0, 0)


class TestNextRun:
    def test_every_two_minutes(self):
        assert next_run("*/2 * * * *", AFTER) == datetime(2026, 8, 30, 12, 2)

    def test_daily_beijing_8am_is_utc_0(self):
        # 北京 08:00 = UTC 00:00，次日命中
        assert next_run("0 8 * * *", AFTER) == datetime(2026, 8, 31, 0, 0)

    def test_weekly_monday(self):
        # 北京周一 10:00 = UTC 02:00；8/31 是周一
        assert next_run("0 10 * * 1", AFTER) == datetime(2026, 8, 31, 2, 0)

    def test_monthly_first(self):
        # 北京 9/1 00:00 = UTC 8/31 16:00
        assert next_run("0 0 1 * *", AFTER) == datetime(2026, 8, 31, 16, 0)

    def test_workday_range(self):
        # 1-5 工作日 + 小时范围，周一 09:00 北京 = UTC 01:00
        assert next_run("*/10 9-17 * * 1-5", AFTER) == datetime(2026, 8, 31, 1, 0)

    def test_past_date_rolls_next_year(self):
        # 8/15 14:30 已过 → 明年 8/15，北京 14:30 = UTC 06:30
        assert next_run("30 14 15 8 *", AFTER) == datetime(2027, 8, 15, 6, 30)

    def test_minute_boundary_next_minute(self):
        assert next_run("* * * * *", AFTER) == datetime(2026, 8, 30, 12, 1)

    def test_sequential_advancement(self):
        """tick 语义：每次从上次结果之后推进（每 30 分钟一档）。"""
        t, seq = AFTER, []
        for _ in range(4):
            t = next_run("*/30 * * * *", t)
            seq.append(t)
        assert seq == [
            datetime(2026, 8, 30, 12, 30),
            datetime(2026, 8, 30, 13, 0),
            datetime(2026, 8, 30, 13, 30),
            datetime(2026, 8, 30, 14, 0),
        ]

    @pytest.mark.parametrize(
        "cron",
        ["bad cron", "* * *", "61 * * * *", "* * * 13 *", "0 25 * * *", ""],
    )
    def test_invalid_expressions_return_none(self, cron):
        assert next_run(cron, AFTER) is None

    def test_dow_7_is_sunday(self):
        # cron 周字段 0 和 7 都是周日；北京周日 12:30 = UTC 04:30
        # 基准点为周日北京 20:30（12:00 UTC 之后的第一档 12:30 已过）→ 下一周日 9/6
        r7 = next_run("30 12 * * 7", AFTER)
        r0 = next_run("30 12 * * 0", AFTER)
        assert r7 == r0 == datetime(2026, 9, 6, 4, 30)
