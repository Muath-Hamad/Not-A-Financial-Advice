"""Base class + contract for NASDAQ arena strategies (v4, lightweight).

Each strategy lives in NASDAQ/sim/strategies/<handle>.py and must expose a
module-level STRATEGY instance of a Strategy subclass.

Contract
--------
decide(date, view, portfolio, ctx) is called at the CLOSE of every trading day.
Orders returned are executed at the next session's OPEN (no lookahead).
Long-only, integer shares, no margin. Commission 2 bps + slippage 5 bps per side.

view: dict code -> row dict of enriched indicators as of today's close.
      Columns: Open, High, Low, Close, Volume, Dividends, Splits, AdjOpen,
      AdjHigh, AdjLow, AdjClose, sma20, sma50, sma100, sma200, ema12, ema26,
      macd, macd_signal, macd_hist, rsi14, bb_mid, bb_up, bb_low, bb_pctb,
      atr14, atr_pct, ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_12m, vol_21,
      drawdown, dist_52w_high, dist_52w_low, vol_sma20, turnover_sar (here:
      dollar turnover), rs_bench_3m. view["IXIC"] is the NASDAQ Composite row.
      Values can be NaN (young listings, warm-up) — guard every comparison.
      A code absent from view did not trade that day.

portfolio: {cash, equity, positions: {code: {shares, price, value, weight,
           avg_cost, unrealized_pct}}}

ctx keys:
      day_index      int, 0-based sim day
      breadth_sma50  fraction of universe above its 50-day SMA
      tasi_ret_1d    benchmark (IXIC) return today
      peers          dict handle -> other agents' public books:
                     {equity, ret_21, ret_63, cash_frac, positions,
                      today_trades}. Same information set for everyone.
      equity_history my own daily equity values so far
      names, sectors dict code -> str

decide() returns:
      orders     list of order dicts (see below), may be empty
      sentiment  optional float [-1, 1]
      mood       optional short label
      note       optional one-line journal entry

Order dicts:
      {"code": "AAPL", "side": "buy",  "sar": 25000, "reason": "..."}   # dollars
      {"code": "AAPL", "side": "buy",  "weight": 0.25, "reason": "..."}
      {"code": "AAPL", "side": "sell", "shares": 100, "reason": "..."}
      {"code": "AAPL", "side": "sell", "fraction": 0.5, "reason": "..."}
      {"code": "AAPL", "side": "sell", "all": True, "reason": "..."}

THE BACK-PROPAGATION LOOP (v4)
------------------------------
Every 63 sessions the engine calls strategy.adapt(feedback) if defined.

feedback = {
  "date": iso,
  "window_sessions": 63,
  "window": {ret, bench_ret, sharpe, max_dd, hit_rate, profit_factor,
             n_sells, turnover, avg_exposure},
  "cumulative": {equity, ret, dd_from_peak, sessions},
  "trades": [last window's sells: {code, realized_pnl, held_since, reason}],
  "peers": current peer books,
}

adapt() may adjust the strategy's OWN parameters and returns either None or
{"changes": {param_name: new_value}, "note": "one line why"} — the report is
logged into results for audit. Rules:
  1. DETERMINISTIC. Same inputs -> same updates. No randomness without a seed.
  2. BOUNDED. Declare meta["param_space"] = {NAME: [lo, hi]} for every
     adaptable parameter and clamp every update into its range.
  3. SMALL STEPS. Move parameters gradually (gradient-descent-like), never
     jump to extremes on one window.
  4. NO LOOKAHEAD. feedback describes the past only; adapt() sees nothing else.

meta (lightweight — no personas): handle, name, style (one line describing the
approach), risk_style, color (placeholder; dashboard overrides), and
param_space as above. Optional: emoji (defaults fine).
"""

from __future__ import annotations


class Strategy:
    meta = {
        "handle": "base",
        "name": "Base Strategy",
        "style": "",
        "risk_style": "balanced",
        "color": "#888888",
        "param_space": {},
    }

    def decide(self, date, view, portfolio, ctx):
        raise NotImplementedError

    def adapt(self, feedback):  # optional override
        return None


def is_new_week(dates, i) -> bool:
    """True on the first session of a (Mon-Fri) trading week."""
    if i == 0:
        return True
    return dates[i].weekday() < dates[i - 1].weekday() or (dates[i] - dates[i - 1]).days > 2


def is_new_month(dates, i) -> bool:
    if i == 0:
        return True
    return dates[i].month != dates[i - 1].month
