"""NL → Cron 规则引擎测试（能力8 前端"自然语言解析"预览的核心，纯函数无 IO）。"""
import pytest

from app.modules.scheduler.cron_parser import CronParser


@pytest.fixture(scope="module")
def parser():
    return CronParser()


class TestRuleParse:
    def test_daily_hour(self, parser):
        assert parser._rule_parse("每天早上8点") == "0 8 * * *"

    def test_daily_hour_minute(self, parser):
        cron = parser._rule_parse("每天8点30分")
        assert cron == "30 8 * * *"

    def test_every_n_hours(self, parser):
        assert parser._rule_parse("每4小时") == "0 */4 * * *"

    def test_every_n_minutes(self, parser):
        assert parser._rule_parse("每30分钟") == "*/30 * * * *"

    def test_weekly(self, parser):
        assert parser._rule_parse("每周一") == "0 0 * * 1"

    def test_workday(self, parser):
        assert parser._rule_parse("工作日") == "0 9 * * 1-5"

    def test_monthly_day_hour(self, parser):
        cron = parser._rule_parse("每月5号8点")
        assert cron is not None
        parts = cron.split()
        assert parts[2] == "5" and parts[1] == "8"

    def test_no_match_returns_none(self, parser):
        assert parser._rule_parse("月圆之夜") is None

    def test_empty(self, parser):
        assert parser._rule_parse("") is None


class TestDescribe:
    def test_describe_daily(self, parser):
        assert "8" in parser.describe("0 8 * * *")

    def test_describe_invalid_len(self, parser):
        assert "Cron" in parser.describe("* * *")
