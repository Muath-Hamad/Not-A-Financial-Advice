"""Day-synchronized multi-agent backtest engine for the TASI top-50 universe.

Realism model:
- Prices are Yahoo's split-adjusted raw series: continuous across bonus issues,
  so positions never need share adjustments; dividends (also split-adjusted)
  are credited as cash on their ex-date.
- Decisions happen at the close of day t; orders fill at the open of t+1 with
  slippage. Commission is Tadawul's 15.5 bps + 15% VAT per side.
- Long-only, integer shares, no margin. Halted names: orders stay pending up
  to 5 sessions, then expire.
- All agents share one calendar. Each day, after the close, every agent posts
  (sentiment, mood, optional shout) to the "majlis" board; the next day every
  agent can read yesterday's board — agents genuinely communicate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ENRICHED = ROOT / "data" / "enriched"

COMMISSION_RATE = 0.00155 * 1.15  # Tadawul max commission + 15% VAT, per side
SLIPPAGE = 0.001                  # 10 bps
START_CASH = 100_000.0
SIM_START = "2022-01-01"
ORDER_TTL = 5                     # sessions an order survives a trading halt


class Market:
    def __init__(self):
        manifest = json.loads((ROOT / "data" / "raw" / "_manifest.json").read_text())
        cfg = json.loads((ROOT / "data" / "tickers.json").read_text())
        self.names = {e["code"]: e["name"] for e in cfg["universe"]}
        self.sectors = {e["code"]: e["sector"] for e in cfg["universe"]}
        self.frames = {}
        for code in manifest:
            if manifest[code].get("status") == "failed":
                continue
            df = pd.read_csv(ENRICHED / f"{code}.csv", index_col="Date", parse_dates=True)
            self.frames[code] = df
        self.codes = [c for c in self.frames if c != "TASI"]

        dates = sorted(set().union(*[set(self.frames[c].index) for c in self.codes]))
        self.dates = [d for d in dates if d >= pd.Timestamp(SIM_START)]

        tasi = self.frames["TASI"]["AdjClose"].reindex(
            pd.Index(sorted(set(tasi_d for tasi_d in self.frames["TASI"].index) | set(self.dates)))
        ).ffill()
        self.tasi = tasi.reindex(self.dates)
        self.tasi_ret = self.tasi.pct_change().fillna(0.0)

        # Precompute per-date row lookups (as-of close) and open prices.
        self._rows = {c: df.to_dict("index") for c, df in self.frames.items()}
        # breadth: fraction of universe above sma50, per date
        self._breadth = {}
        for d in self.dates:
            above = tot = 0
            for c in self.codes:
                r = self._rows[c].get(d)
                if r and not math.isnan(r.get("sma50", float("nan"))):
                    tot += 1
                    if r["AdjClose"] > r["sma50"]:
                        above += 1
            self._breadth[d] = above / tot if tot else 0.5

    def row(self, code, date):
        return self._rows[code].get(date)

    def view(self, date):
        v = {}
        for c in self.codes:
            r = self._rows[c].get(date)
            if r is not None:
                v[c] = r
        t = self._rows["TASI"].get(date)
        if t is not None:
            v["TASI"] = t
        return v

    def breadth(self, date):
        return self._breadth[date]


class Portfolio:
    def __init__(self):
        self.cash = START_CASH
        self.shares = {}      # code -> int
        self.avg_cost = {}    # code -> float
        self.last_price = {}  # code -> last seen close (for marking through halts)
        self.first_bought = {}  # code -> date of position opening (for holding-period stats)

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
                # mark to market at close
                for c in list(pf.shares):
                    r = m.row(c, date)
                    if r:
                        pf.last_price[c] = r["Close"]
                snap = pf.snapshot(date, m)
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
                snap = a.pf.snapshot(date, m)
                ctx["equity_history"] = a.equity_hist
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
