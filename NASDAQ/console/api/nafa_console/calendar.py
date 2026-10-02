"""NASDAQ sessions, via the same exchange calendar the harness uses."""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

ET = ZoneInfo("America/New_York")
_CAL = mcal.get_calendar("NASDAQ")


def now_et() -> dt.datetime:
    return dt.datetime.now(tz=ET)


@lru_cache(maxsize=64)
def sessions_between(start: str, end: str) -> tuple[str, ...]:
    """ISO dates of every session in [start, end]."""
    sched = _CAL.schedule(start_date=start, end_date=end)
    return tuple(str(d.date()) for d in sched.index)


def _shift(day: str, days: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


def next_session(day: str) -> str:
    s = sessions_between(_shift(day, 1), _shift(day, 14))
    return s[0]


def previous_session(day: str) -> str:
    s = sessions_between(_shift(day, -14), _shift(day, -1))
    return s[-1]


def last_sessions(end: str, n: int) -> list[str]:
    s = sessions_between(_shift(end, -3 * n - 14), end)
    return list(s[-n:])


def latest_completed_session(now: dt.datetime | None = None) -> str:
    """The latest session whose 16:00 ET close has passed."""
    now = now or now_et()
    today = now.date().isoformat()
    s = sessions_between(_shift(today, -14), today)
    if s and s[-1] == today and now.hour < 16:
        return s[-2]
    return s[-1]


def sessions_after(asof: str, upto: str) -> list[str]:
    """Sessions strictly after `asof`, up to and including `upto`."""
    if upto <= asof:
        return []
    return [d for d in sessions_between(_shift(asof, 1), upto)]
