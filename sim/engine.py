"""Day-synchronized multi-agent backtest engine for the TASI top-50 universe.

Realism model:
- Prices are Yahoo's split-adjusted raw series: continuous across bonus issues,
  so positions never need share adjustments; dividends (also split-adjusted)
  are credited as cash on their ex-date.
- Decisions happen at the close of day t; orders fill at the open of t+1 with
  slippage. Commission is a discount-broker 8 bps per side (v2).
- Long-only, integer shares, no margin. Halted names: orders stay pending up
  to 5 sessions, then expire.
- All agents share one calendar. Each day, after the close, every agent posts
  (sentiment, mood, optional shout) to the "majlis" board; the next day every
  agent can read yesterday's board — agents genuinely communicate.
- v2: every agent also sees ctx["peers"] — the other agents' current books
  (weights, cash fraction, trailing returns, today's fills). Public track
  records, same information set for everyone, no lookahead.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ENRICHED = ROOT / "data" / "enriched"

COMMISSION_RATE = 0.0008  # v2: discount-broker all-in commission per side (8 bps)
SLIPPAGE = 0.0005          # v2: 5 bps
START_CASH = 100_000.0
SIM_START = "2022-01-01"
ORDER_TTL = 5                     # sessions an order survives a trading halt


class Market:
    """Numpy-backed market data: per-code value matrices with lazy row dicts,
    sized for the full ~230-stock main market."""

    def __init__(self):
        manifest = json.loads((ROOT / "data" / "raw" / "_manifest.json").read_text())
        self.names, self.sectors = {}, {}
        self._cols = {}     # code -> list of columns
        self._vals = {}     # code -> ndarray (n_rows, n_cols)
        self._pos = {}      # code -> {Timestamp: row index}
        above_parts, valid_parts = {}, {}
        for code, meta in manifest.items():
            if meta.get("status") == "failed":
                continue
            df = pd.read_csv(ENRICHED / f"{code}.csv", index_col="Date", parse_dates=True)
            if code != "TASI":
                self.names[code] = meta.get("name", code)
                self.sectors[code] = meta.get("sector", "Other")
                above_parts[code] = (df["AdjClose"] > df["sma50"]).astype("float64")
                valid_parts[code] = df["sma50"].notna().astype("float64")
            self._cols[code] = list(df.columns)
            self._vals[code] = df.to_numpy(dtype="float64")
            self._pos[code] = {d: i for i, d in enumerate(df.index)}
        self.codes = [c for c in self._cols if c != "TASI"]

        dates = sorted(set().union(*[set(self._pos[c]) for c in self.codes]))
        self.dates = [d for d in dates if d >= pd.Timestamp(SIM_START)]

        tasi_idx = pd.DatetimeIndex(sorted(self._pos["TASI"]))
        ci = self._cols["TASI"].index("AdjClose")
        tasi_ser = pd.Series(self._vals["TASI"][:, ci], index=tasi_idx)
        union_idx = pd.DatetimeIndex(sorted(set(tasi_idx) | set(self.dates)))
        tasi = tasi_ser.reindex(union_idx).ffill()
        self.tasi = tasi.reindex(pd.DatetimeIndex(self.dates))
        self.tasi_ret = self.tasi.pct_change().fillna(0.0)

        above = pd.DataFrame(above_parts).reindex(pd.DatetimeIndex(self.dates))
        valid = pd.DataFrame(valid_parts).reindex(pd.DatetimeIndex(self.dates))
        num = (above * valid).sum(axis=1)
        den = valid.sum(axis=1).replace(0, float("nan"))
        self._breadth = (num / den).fillna(0.5).to_dict()

        self._cache_date = None
        self._cache_view = None

    def _build_view(self, date):
        v = {}
        for c in self.codes:
            i = self._pos[c].get(date)
            if i is not None:
                v[c] = dict(zip(self._cols[c], self._vals[c][i]))
        it = self._pos["TASI"].get(date)
        if it is not None:
            v["TASI"] = dict(zip(self._cols["TASI"], self._vals["TASI"][it]))
        return v

    def view(self, date):
        if self._cache_date != date:
            self._cache_view = self._build_view(date)
            self._cache_date = date
        return self._cache_view

    def row(self, code, date):
        if self._cache_date == date:
            return self._cache_view.get(code)
        i = self._pos[code].get(date)
        if i is None:
            return None
        return dict(zip(self._cols[code], self._vals[code][i]))

    def breadth(self, date):
        return self._breadth.get(date, 0.5)


class Portfolio:
    def __init__(self):
        self.cash = START_CASH
        self.shares = {}      # code -> int
        self.avg_cost = {}    # code -> float
        self.last_price = {}  # code -> last seen close (for marking through halts)
        self.first_bought = {}  # code -> date of position opening (for holding-period stats)
        self.silent_days = {}   # code -> consecutive sessions without a price row

    def snapshot(self, date, market):
        pos = {}
        equity = self.cash
        for c, sh in self.shares.items():
            if sh <= 0:
                continue
            r = market.row(c, date)
            px = r["Close"] if r else self.last_price.get(c, self.avg_cost.get(c, 0.0))
            val = sh * px
            equity += val
            pos[c] = {
                "shares": sh,
                "price": px,
                "value": val,
                "avg_cost": self.avg_cost.get(c, px),
                "unrealized_pct": (px / self.avg_cost[c] - 1.0) if self.avg_cost.get(c) else 0.0,
            }
        for c in pos:
            pos[c]["weight"] = pos[c]["value"] / equity if equity > 0 else 0.0
        return {"cash": self.cash, "equity": equity, "positions": pos}


class AgentState:
    def __init__(self, strategy):
        self.strategy = strategy
        self.meta = strategy.meta
        self.handle = strategy.meta["handle"]
        self.pf = Portfolio()
        self.pending = []          # orders awaiting execution
        self.equity_hist = []      # aligned to engine dates
        self.cash_hist = []
        self.trades = []
        self.journal = []
        self.sentiment_hist = []   # aligned to dates (ffilled)
        self.holdings_monthly = []
        self.dividends_received = 0.0
        self.commissions_paid = 0.0
        self.rejected_orders = 0
        self.errors = 0
        self._last_sentiment = 0.0


def _validated(order, pf_snap):
    if not isinstance(order, dict):
        return None
    code = str(order.get("code", ""))
    side = order.get("side")
    if side not in ("buy", "sell"):
        return None
    return {**order, "code": code, "side": side}


class Engine:
    def __init__(self, market: Market):
        self.m = market

    def run_all(self, strategies, progress_every=250):
        m = self.m
        agents = [AgentState(s) for s in strategies]
        majlis = []  # yesterday's posts
        chat = []    # full chat log
        events = []  # notable market events for the dashboard/commentary

        for i, date in enumerate(m.dates):
            iso = str(date.date())
            # --- corporate actions + executions + marking, per agent ---
            for a in agents:
                pf = a.pf
                # dividends on ex-date
                for c, sh in list(pf.shares.items()):
                    if sh <= 0:
                        continue
                    r = m.row(c, date)
                    if r and r.get("Dividends", 0.0) > 0:
                        amt = sh * r["Dividends"]
                        pf.cash += amt
                        a.dividends_received += amt
                # execute pending orders at today's open
                still_pending = []
                for od in a.pending:
                    r = m.row(od["code"], date)
                    if r is None or math.isnan(r.get("Open", float("nan"))):
                        od["ttl"] = od.get("ttl", ORDER_TTL) - 1
                        if od["ttl"] > 0:
                            still_pending.append(od)
                        continue
                    self._fill(a, od, r, iso)
                a.pending = still_pending
                # mark to market at close; force-exit names silent for 20+ sessions
                # (delisted or long-suspended — prevents zombie holdings)
                for c in list(pf.shares):
                    r = m.row(c, date)
                    if r:
                        pf.last_price[c] = r["Close"]
                        pf.silent_days[c] = 0
                    else:
                        pf.silent_days[c] = pf.silent_days.get(c, 0) + 1
                        if pf.silent_days[c] >= 20 and pf.shares.get(c, 0) > 0:
                            n = pf.shares.pop(c)
                            px = pf.last_price.get(c, pf.avg_cost.get(c, 0.0)) * (1 - SLIPPAGE)
                            gross = n * px
                            fee = gross * COMMISSION_RATE
                            pf.cash += gross - fee
                            realized = (px - pf.avg_cost.get(c, px)) * n
                            a.commissions_paid += fee
                            a.trades.append({
                                "date": iso, "code": c, "side": "sell", "shares": n,
                                "price": round(px, 3), "value": round(gross, 2),
                                "fee": round(fee, 2), "realized_pnl": round(realized, 2),
                                "held_since": pf.first_bought.pop(c, None),
                                "reason": "forced exit: name suspended/delisted (20 sessions without prices)"})
                            pf.silent_days.pop(c, None)
                snap = pf.snapshot(date, m)
                a._snap = snap
                a.equity_hist.append(round(snap["equity"], 2))
                a.cash_hist.append(round(pf.cash, 2))
                if i == len(m.dates) - 1 or (i > 0 and date.month != m.dates[i - 1].month):
                    a.holdings_monthly.append({
                        "date": iso,
                        "cash": round(pf.cash, 2),
                        "positions": {c: {"shares": p["shares"], "value": round(p["value"], 2)}
                                      for c, p in snap["positions"].items()},
                    })

            # --- market events (for chat/commentary) ---
            tret = float(m.tasi_ret.iloc[i])
            if abs(tret) >= 0.02:
                events.append({"date": iso, "type": "crash" if tret < 0 else "rally",
                               "tasi_ret": round(tret, 4)})

            # --- decisions at the close (not on the final day) ---
            if i == len(m.dates) - 1:
                break
            view = m.view(date)
            peers_all = {}
            for a in agents:
                eq = a.equity_hist
                snap = a._snap
                peers_all[a.handle] = {
                    "equity": eq[-1],
                    "ret_21": eq[-1] / eq[-22] - 1 if len(eq) >= 22 else 0.0,
                    "ret_63": eq[-1] / eq[-64] - 1 if len(eq) >= 64 else 0.0,
                    "cash_frac": snap["cash"] / snap["equity"] if snap["equity"] > 0 else 1.0,
                    "positions": {c: round(pp["weight"], 4) for c, pp in snap["positions"].items()},
                    "today_trades": [
                        {"code": t["code"], "side": t["side"], "value": t["value"],
                         "realized_pnl": t.get("realized_pnl")}
                        for t in a.trades if t["date"] == iso],
                }
            ctx = {
                "day_index": i,
                "breadth_sma50": m.breadth(date),
                "tasi_ret_1d": tret,
                "majlis": majlis,
                "names": m.names,
                "sectors": m.sectors,
            }
            new_posts = []
            for a in agents:
                snap = a._snap
                ctx["equity_history"] = a.equity_hist
                ctx["peers"] = {h: v for h, v in peers_all.items() if h != a.handle}
                try:
                    decision = a.strategy.decide(date, view, snap, ctx) or {}
                except Exception:
                    a.errors += 1
                    decision = {}
                sent = float(decision.get("sentiment", a._last_sentiment))
                sent = max(-1.0, min(1.0, sent))
                a._last_sentiment = sent
                a.sentiment_hist.append(sent)
                mood = str(decision.get("mood", ""))[:40]
                note = str(decision.get("note", ""))[:500]
                if note:
                    a.journal.append({"date": iso, "mood": mood, "sentiment": sent, "note": note})
                shout = decision.get("shout")
                if shout:
                    post = {"date": iso, "handle": a.handle, "sentiment": sent,
                            "mood": mood, "shout": str(shout)[:400]}
                    new_posts.append(post)
                    chat.append(post)
                for od in decision.get("orders", []) or []:
                    od = _validated(od, snap)
                    if od is None:
                        a.rejected_orders += 1
                        continue
                    od["ttl"] = ORDER_TTL
                    od["queued"] = iso
                    a.pending.append(od)
            majlis = new_posts
            if progress_every and i % progress_every == 0:
                lead = max(agents, key=lambda x: x.equity_hist[-1])
                print(f"  {iso}: leader {lead.handle} {lead.equity_hist[-1]:,.0f} SAR")

        return agents, chat, events

    def _fill(self, a: AgentState, od, r, iso):
        pf = a.pf
        code = od["code"]
        side = od["side"]
        open_px = r["Open"]
        if side == "buy":
            px = open_px * (1 + SLIPPAGE)
            budget = None
            if od.get("sar") is not None:
                budget = float(od["sar"])
            elif od.get("weight") is not None:
                snap_eq = pf.cash + sum(
                    sh * pf.last_price.get(c, 0.0) for c, sh in pf.shares.items())
                budget = float(od["weight"]) * snap_eq
            elif od.get("shares") is not None:
                budget = float(od["shares"]) * px * (1 + COMMISSION_RATE)
            if budget is None:
                a.rejected_orders += 1
                return
            budget = min(budget, pf.cash)
            n = int(budget / (px * (1 + COMMISSION_RATE)))
            if n < 1:
                a.rejected_orders += 1
                return
            cost = n * px
            fee = cost * COMMISSION_RATE
            pf.cash -= cost + fee
            prev = pf.shares.get(code, 0)
            pf.avg_cost[code] = (
                (pf.avg_cost.get(code, 0.0) * prev + cost) / (prev + n) if prev + n else px)
            if prev == 0:
                pf.first_bought[code] = iso
            pf.shares[code] = prev + n
            a.commissions_paid += fee
            a.trades.append({"date": iso, "code": code, "side": "buy", "shares": n,
                             "price": round(px, 3), "value": round(cost, 2),
                             "fee": round(fee, 2), "reason": str(od.get("reason", ""))[:200]})
        else:
            held = pf.shares.get(code, 0)
            if held <= 0:
                a.rejected_orders += 1
                return
            if od.get("all"):
                n = held
            elif od.get("fraction") is not None:
                n = int(held * max(0.0, min(1.0, float(od["fraction"]))))
            elif od.get("shares") is not None:
                n = min(held, int(od["shares"]))
            elif od.get("sar") is not None:
                n = min(held, int(float(od["sar"]) / (open_px or 1)))
            else:
                n = held
            if n < 1:
                a.rejected_orders += 1
                return
            px = open_px * (1 - SLIPPAGE)
            gross = n * px
            fee = gross * COMMISSION_RATE
            pf.cash += gross - fee
            realized = (px - pf.avg_cost.get(code, px)) * n
            pf.shares[code] = held - n
            hold_since = pf.first_bought.get(code)
            if pf.shares[code] == 0:
                pf.shares.pop(code)
                pf.first_bought.pop(code, None)
            a.commissions_paid += fee
            a.trades.append({"date": iso, "code": code, "side": "sell", "shares": n,
                             "price": round(px, 3), "value": round(gross, 2),
                             "fee": round(fee, 2), "realized_pnl": round(realized, 2),
                             "held_since": hold_since,
                             "reason": str(od.get("reason", ""))[:200]})
