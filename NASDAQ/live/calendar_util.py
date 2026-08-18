"""NASDAQ session-calendar helpers.

The exchange calendar (holidays and half-days included) drives every scheduling
decision; workflow crons only get the harness onto the runner — these functions
decide whether and for which session a cycle actually runs.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

ET = ZoneInfo("America/New_York")
_CAL = mcal.get_calendar("NASDAQ")


def now_et() -> dt.datetime:
    return dt.datetime.now(tz=ET)


def _schedule(start, end):
    return _CAL.schedule(start_date=str(start), end_date=str(end))


def is_session(day: str | dt.date) -> bool:
    return len(_schedule(day, day)) > 0


def latest_completed_session(now: dt.datetime | None = None) -> str:
    """ISO date of the most recent session whose close has passed.

    Run at 17:00 ET on a trading day this is today; run mid-session or on a
    weekend it is the previous session — which makes late re-runs and smoke
    runs pick the right data window automatically.
    """
    now = now or now_et()
    sched = _schedule(now.date() - dt.timedelta(days=14), now.date())
    done = sched[sched["market_close"] <= now]
    if done.empty:
        raise RuntimeError("no completed session in the last 14 days")
    return str(done.index[-1].date())


def previous_session(day: str) -> str:
    d = dt.date.fromisoformat(day)
    sched = _schedule(d - dt.timedelta(days=14), d - dt.timedelta(days=1))
    if sched.empty:
        raise RuntimeError(f"no session before {day}")
    return str(sched.index[-1].date())


def next_session(day: str) -> str:
    d = dt.date.fromisoformat(day)
    sched = _schedule(d + dt.timedelta(days=1), d + dt.timedelta(days=14))
    if sched.empty:
        raise RuntimeError(f"no session after {day}")
    return str(sched.index[0].date())


def session_close_et(day: str) -> dt.datetime:
    sched = _schedule(day, day)
    if sched.empty:
        raise RuntimeError(f"{day} is not a session")
    return sched["market_close"].iloc[0].tz_convert(ET).to_pydatetime()
