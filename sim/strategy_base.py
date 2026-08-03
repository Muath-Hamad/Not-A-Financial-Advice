"""Base class + helpers for agent strategies.

Each agent strategy lives in sim/strategies/<handle>.py and must expose a
module-level `STRATEGY` instance of a Strategy subclass.

Contract
--------
decide(date, view, portfolio, ctx) is called at the CLOSE of every trading day.
Orders returned are executed at the next session's OPEN (no lookahead).

view: dict code -> row (pandas Series) of enriched indicators as of today's
      close. Missing/halted tickers are absent. "TASI_SR" is the index row.
portfolio: dict with keys cash, equity, positions {code: {shares, value,
      weight, avg_cost, unrealized_pct}}.
ctx: dict with keys:
      day_index      int, 0-based sim day
      breadth_sma50  float, fraction of universe above its 50-day SMA
      tasi_ret_1d    float, index return today
      majlis         list of yesterday's posts: {handle, sentiment, mood, shout}
      equity_history list of my own daily equity values so far
      names          dict code -> company name
      sectors        dict code -> sector

Return a dict:
      orders     list of order dicts (see below), may be empty
      sentiment  float in [-1, 1], today's market mood
      mood       short label, in character ("greedy", "nervous", ...)
      note       one journal line, in character
      shout      optional message posted to the shared majlis chat

Order dicts (long-only, no margin):
      {"code": "1120", "side": "buy",  "sar": 25000, "reason": "..."}
      {"code": "1120", "side": "buy",  "weight": 0.25, "reason": "..."}   # fraction of equity
      {"code": "1120", "side": "sell", "shares": 100, "reason": "..."}
      {"code": "1120", "side": "sell", "fraction": 0.5, "reason": "..."}  # of held shares
      {"code": "1120", "side": "sell", "all": True, "reason": "..."}
"""

from __future__ import annotations


class Strategy:
    meta = {
        "handle": "base",
        "name": "Base Strategy",
        "emoji": "🤖",
        "tagline": "",
        "character": "",
        "risk_style": "balanced",
        "color": "#888888",
    }

    def decide(self, date, view, portfolio, ctx):
        raise NotImplementedError


def is_new_week(dates, i) -> bool:
    """True on the first session of a Tadawul week (Sun-Thu)."""
    if i == 0:
        return True
    return dates[i].weekday() < dates[i - 1].weekday() or (dates[i] - dates[i - 1]).days > 2


def is_new_month(dates, i) -> bool:
    if i == 0:
        return True
    return dates[i].month != dates[i - 1].month
