"""
能力8：5 段式 Cron 下次执行时间计算（纯 Python，不依赖 croniter）

支持语法：* / 数字 / a-b / */n / a-b/n / a,b,c（与 Vixie cron 常用子集一致）。

时间约定：
- 平台内部一律存 naive UTC（与 models/database.py 的 datetime.utcnow 一致）；
- 用户视角的 cron 语义按北京时间（Asia/Shanghai）解释——「0 8 * * *」即北京 08:00
  触发。中国现行无夏令时，固定 +8 偏移即可；zoneinfo 可用时仍优先用真实时区。
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    _CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - 容器缺 tzdata 时退化为固定偏移
    _CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

_UTC = timezone.utc

# 字段边界：(分, 时, 日, 月, 周)
_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))

_WEEKDAY_MAP = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 0}  # 0 与 7 均为周日


def _parse_field(expr: str, lo: int, hi: int) -> frozenset[int]:
    """把单个 cron 字段解析为允许值集合；非法字段抛 ValueError。"""
    values: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty cron field part in '{expr}'")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(f"invalid step in '{part}'")
        else:
            base = part
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(base)
            end = hi if "/" in part else start
        if start < lo or end > hi or start > end:
            raise ValueError(f"cron field out of range: '{part}' (bounds {lo}-{hi})")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"cron field matches nothing: '{expr}'")
    return frozenset(values)


def _day_matches(day: datetime, doms: frozenset[int], dows: frozenset[int],
                 dom_restricted: bool, dow_restricted: bool) -> bool:
    """Vixie cron 的日匹配规则：日与周均受限时命中其一即可，否则要求各自命中。"""
    dom_ok = day.day in doms
    # Python weekday(): 周一=0..周日=6；cron 周日=0
    dow_ok = (day.weekday() + 1) % 7 in dows
    if dom_restricted and dow_restricted:
        return dom_ok or dow_ok
    if dom_restricted:
        return dom_ok
    if dow_restricted:
        return dow_ok
    return True


def next_run(cron_expression: str, after: datetime | None = None) -> datetime | None:
    """
    计算 cron 表达式在 after（naive UTC）之后的下一次触发时间，返回 naive UTC。

    解析失败返回 None（调用方应跳过该任务并记日志，而不是抛异常拖垮整个 tick）。
    """
    parts = (cron_expression or "").split()
    if len(parts) != 5:
        return None
    try:
        mins = _parse_field(parts[0], *_FIELD_BOUNDS[0])
        hours = _parse_field(parts[1], *_FIELD_BOUNDS[1])
        doms = _parse_field(parts[2], *_FIELD_BOUNDS[2])
        months = _parse_field(parts[3], *_FIELD_BOUNDS[3])
        dows = frozenset(_WEEKDAY_MAP[d] for d in _parse_field(parts[4], *_FIELD_BOUNDS[4]))
    except ValueError as e:
        logger.warning(f"invalid cron '{cron_expression}': {e}")
        return None

    dom_restricted = parts[2] != "*"
    dow_restricted = parts[4] != "*"

    # cron 语义按北京时间解释：把起点转到北京本地时间逐字段推进，得到本地触发点后再转回 UTC
    after_utc = after or datetime.utcnow()
    if after_utc.tzinfo is not None:
        after_utc = after_utc.replace(tzinfo=None)
    t = after_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    t_local = t.replace(tzinfo=_UTC).astimezone(_CN_TZ)

    # 每轮外层至少前进 1 分钟；正常 cron 在 ~366*24*60 轮内必命中（闰年极端如 2月30日除外）
    for _ in range(600_000):
        if t_local.month not in months:
            # 跳到下个月 1 日 00:00（本地）
            year, month = t_local.year, t_local.month + 1
            if month > 12:
                year, month = year + 1, 1
            t_local = t_local.replace(year=year, month=month, day=1, hour=0, minute=0)
            continue
        if not _day_matches(t_local, doms, dows, dom_restricted, dow_restricted):
            t_local = (t_local + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t_local.hour not in hours:
            t_local = (t_local + timedelta(hours=1)).replace(minute=0)
            continue
        if t_local.minute not in mins:
            t_local = t_local + timedelta(minutes=1)
            continue
        return t_local.astimezone(_UTC).replace(tzinfo=None)
    return None
