"""Performance (M2), agent internals and the monthly review pack (M3).

All numbers come from the twin, the ledger, the account (when there is one)
and the out-of-sample record; nothing is estimated. Short live records get
null where a statistic needs more history (CAGR, Calmar need ≥ 63 sessions).
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
from collections import defaultdict

from . import payloads as P

MIN_ANNUAL = 63


def _returns(series: list[float]) -> list[float]:
    return [series[i] / series[i - 1] - 1 for i in range(1, len(series)) if series[i - 1]]


def stats(series: list[float]) -> dict:
    """Total return, CAGR, Sharpe, Sortino, max drawdown, Calmar, volatility."""
    if len(series) < 2:
        return {}
    r = _returns(series)
    n = len(r)
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1)) if n > 1 else 0.0
    dn = math.sqrt(sum(min(x, 0) ** 2 for x in r) / n)
    pk, mdd = series[0], 0.0
    for v in series:
        pk = max(pk, v)
        mdd = min(mdd, v / pk - 1)
    total = series[-1] / series[0] - 1
    cagr = (1 + total) ** (252 / n) - 1 if n >= MIN_ANNUAL else None
    return {"total": total, "cagr": cagr, "sharpe": mean / sd * math.sqrt(252) if sd else None,
            "sortino": mean / dn * math.sqrt(252) if dn else None, "mdd": mdd,
            "calmar": (cagr / abs(mdd)) if (cagr is not None and mdd) else None, "vol": sd * math.sqrt(252)}


def monthly(dates: list[str], series: list[float]) -> dict[str, float]:
    last: dict[str, float] = {}
    first_prev: dict[str, float] = {}
    prev_val = series[0] if series else None
    for d, v in zip(dates, series):
        m = d[:7]
        if m not in first_prev:
            first_prev[m] = prev_val
        last[m] = v
        prev_val = v
    return {m: last[m] / first_prev[m] - 1 for m in last if first_prev.get(m)}


def _oos(settings) -> dict:
    p = settings.pkg / "out" / "results_oos.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    a = next((x for x in d.get("agents", []) if x["meta"]["handle"] == "trend"), None)
    return {"metrics": a["metrics"], "window": [d["meta"]["sim_start"], d["meta"]["sim_end"]], "adaptations": a.get("adaptations", [])} if a else {}


def calibration(settings) -> dict | None:
    p = settings.pkg / "out" / "confidence_calibration.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def performance(c: P.Ctx) -> dict:
    t = c.twin
    dates, eq, bench = t.get("dates") or [], t.get("equity") or [], t.get("bench") or []
    acct_series = None
    if c.account is not None and c.account.history:
        pts = [(d, c.account.history.get(d)) for d in dates]
        pts = [(d, v) for d, v in pts if v]
        if len(pts) >= 2:
            acct_series = pts
    sm, sb = stats(eq), stats(bench)
    sa = stats([v for _, v in acct_series]) if acct_series else {}
    rt = P.round_trips(c)["trips"]
    wins = [x for x in rt if x["pnl"] > 0]
    oos = _oos(c.settings)
    om = oos.get("metrics") or {}

    def row(key, label, note, field, unit, ref):
        return {"key": key, "label": label, "note": note, "unit": unit, "model": sm.get(field), "account": sa.get(field) if acct_series else None,
                "bench": sb.get(field), "ref": ref}

    metrics = [
        row("total", "Total return", f"since {P.wd_label(t.get('live_start') or c.asof)}", "total", "pct", om.get("total_return")),
        row("cagr", "CAGR", f"needs ≥ {MIN_ANNUAL} sessions", "cagr", "pct", om.get("cagr")),
        row("sharpe", "Sharpe", "annualised, daily, rf = 0", "sharpe", "ratio", om.get("sharpe")),
        row("sortino", "Sortino", "downside deviation", "sortino", "ratio", om.get("sortino")),
        row("mdd", "Max drawdown", "peak to trough", "mdd", "pct", om.get("max_drawdown")),
        row("calmar", "Calmar", "CAGR ÷ max drawdown", "calmar", "ratio", om.get("calmar")),
        row("vol", "Volatility", "annualised", "vol", "pct", om.get("ann_vol")),
        {"key": "win", "label": "Win rate", "note": "closed round trips", "unit": "pct", "model": (len(wins) / len(rt)) if rt else None,
         "account": None, "bench": None, "ref": om.get("win_rate")},
        {"key": "trades", "label": "Trades", "note": "orders filled", "unit": "count", "model": len(c.trades), "account": None, "bench": None, "ref": om.get("n_trades")},
    ]
    live_m = monthly(dates, eq)
    years = sorted({m[:4] for m in live_m}, reverse=True)
    rows = [{"label": "Twin " + y, "live": True, "months": [live_m.get(f"{y}-{i:02d}") for i in range(1, 13)]} for y in years]
    oos_m = om.get("monthly_returns") or {}
    for y in sorted({m[:4] for m in oos_m}, reverse=True):
        rows.append({"label": "OOS " + y, "live": False, "months": [oos_m.get(f"{y}-{i:02d}") for i in range(1, 13)]})
    for r in rows:
        p = 1.0
        for v in r["months"]:
            if v is not None:
                p *= 1 + v
        r["year"] = p - 1

    def pnl_since(i: int) -> dict:
        i = max(0, min(i, len(eq) - 1))
        return {"pnl": eq[-1] - eq[i], "pct": (eq[-1] / eq[i] - 1) if eq[i] else 0.0}

    asof = dt.date.fromisoformat(c.asof)
    week_start = (asof - dt.timedelta(days=asof.weekday())).isoformat()
    month_start = asof.replace(day=1).isoformat()
    idx_before = lambda day: max([i for i, d in enumerate(dates) if d < day] or [0])  # noqa: E731
    periods = {"today": pnl_since(len(eq) - 2), "wtd": pnl_since(idx_before(week_start)), "mtd": pnl_since(idx_before(month_start)), "all": pnl_since(0)}
    by_holding = [{"label": s, "value": (float(p.get("price") or 0) - float(p.get("avg_cost") or 0)) * int(p.get("shares") or 0)} for s, p in c.positions.items()]
    by_holding.sort(key=lambda x: -x["value"])
    realized = sum(x["pnl"] for x in rt)
    fees = float(t.get("commissions_paid") or 0)
    if rt:
        by_holding.append({"label": f"Closed ({len(rt)})", "value": realized})
    if fees:
        by_holding.append({"label": "Fees", "value": -fees})
    sector = defaultdict(float)
    for s, p in c.positions.items():
        sector[(c.uni.get(s) or {}).get("sector") or "Other"] += (float(p.get("price") or 0) - float(p.get("avg_cost") or 0)) * int(p.get("shares") or 0)
    for x in rt:
        sector[x["sector"] if x["sector"] != "—" else "Other"] += x["pnl"]
    execution = None
    gap = None
    if c.account is not None:
        from .account import ledger_fills
        fills = [{"date": d, "symbol": s, "side": side, "bps": v["slippage_bps"]} for (d, s, side), v in sorted(ledger_fills(c.s.cycles).items()) if v.get("slippage_bps") is not None]
        missed = sum(len(r.get("missed") or []) for k, r in c.s.cycles.items() if k.endswith("-B"))
        te = []
        if acct_series and len(acct_series) > 2:
            am = monthly([d for d, _ in acct_series], [v for _, v in acct_series])
            for m in sorted(am):
                if m in live_m:
                    te.append({"month": m, "value": abs(am[m] - live_m[m])})
        avg = sum(f["bps"] for f in fills) / len(fills) if fills else None
        execution = {"fills": fills, "avgBps": avg, "outliers": sum(1 for f in fills if abs(f["bps"]) > 10), "missed": missed, "trackingError": te}
        if acct_series:
            model_pnl = eq[-1] - eq[0]
            acct_pnl = acct_series[-1][1] - acct_series[0][1]
            slip_cost = sum(v["qty"] * (v["price"] or 0) * (v["slippage_bps"] or 0) / 1e4 for v in ledger_fills(c.s.cycles).values())
            gap = [{"label": "Slippage", "value": -slip_cost},
                   {"label": "Drift and other", "value": (acct_pnl - model_pnl) + slip_cost},
                   {"label": "Account − Model", "value": acct_pnl - model_pnl}]
    oos_ref = {"sharpe": om.get("sharpe"), "mdd": om.get("max_drawdown"), "cagr": om.get("cagr"), "total": om.get("total_return"),
               "calmar": om.get("calmar"), "trades": om.get("n_trades"), "window": oos.get("window")}
    return {
        "since": t.get("live_start") or c.asof, "sessions": len(dates), "metrics": metrics, "monthly": rows, "periods": periods,
        "byHolding": by_holding, "bySector": sorted(({"label": k, "value": v} for k, v in sector.items()), key=lambda x: -x["value"]),
        "gap": gap, "execution": execution,
        "dividends": {"gross": float(t.get("dividends_received") or 0), "withholding": -0.3 * float(t.get("dividends_received") or 0)},
        "reference": oos_ref,
    }


def agent(c: P.Ctx) -> dict:
    t = c.twin
    params, space = t.get("params") or {}, t.get("param_space") or {}
    oos = _oos(c.settings)
    frozen = {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("frozen_trend", c.settings.pkg / "sim" / "strategies" / "trend.py")
        mod = importlib.util.module_from_spec(spec)
        import sys
        sys.path.insert(0, str(c.settings.pkg / "sim"))
        spec.loader.exec_module(mod)
        s0 = mod.Trend()
        frozen = {k: float(getattr(s0, k)) for k in space if hasattr(s0, k)}
    except Exception:  # noqa: BLE001
        frozen = {}
    regime = c.insights_doc.get("regime") or {}
    journal = [{"date": j["date"], "mood": j.get("mood"), "sentiment": j.get("sentiment"), "note": (j.get("note") or "").replace(" Common Stock", "")}
               for j in reversed(t.get("journal") or [])]
    sessions = int(t.get("sessions") or 0)
    every = int(float((t.get("inputs") or {}).get("adapt_every") or 63))
    nxt = None
    if t.get("dates"):
        try:
            remaining = every - (sessions % every)
            d = t["dates"][-1]
            for _ in range(remaining):
                d = P.cal.next_session(d)
            nxt = d
        except Exception:  # noqa: BLE001
            nxt = None
    ctl = c.controls
    cal = calibration(c.settings)
    rt = P.round_trips(c)["trips"]
    live_bands = []
    for name, lo, hi in (("high", 70, 101), ("med", 40, 70), ("low", 0, 40)):
        rs = [x for x in rt if x["confAtEntry"] is not None and lo <= x["confAtEntry"] < hi]
        live_bands.append({"band": name, "n": len(rs), "hit": (sum(x["pnl"] > 0 for x in rs) / len(rs)) if rs else None,
                           "ret": (sum(x["exitPrice"] / x["entryPrice"] - 1 for x in rs) / len(rs)) if rs else None})
    return {
        "handle": t.get("agent") or "trend", "freezeCommit": t.get("freeze_commit"),
        "params": [{"k": k, "v": params.get(k), "lo": space[k][0], "hi": space[k][1], "frozen": frozen.get(k)} for k in space],
        "regime": regime, "mood": (t.get("journal") or [{}])[-1].get("mood") if t.get("journal") else None,
        "sentiment": [{"date": j["date"], "s": j.get("sentiment")} for j in (t.get("journal") or [])],
        "journal": journal[:20],
        "adaptations": [{"date": a.get("date"), "changes": a.get("changes"), "note": a.get("note"), "live": True} for a in reversed(t.get("adaptations") or [])],
        "oosAdaptations": [{"date": a.get("date"), "changes": a.get("changes"), "note": a.get("note")} for a in reversed(oos.get("adaptations") or [])][:6],
        "nextAdapt": None if ctl.get("pause_adapt") else nxt, "adaptEvery": every, "sessions": sessions,
        "adaptPaused": bool(ctl.get("pause_adapt")), "adaptPausedSince": ctl.get("pause_adapt_since"),
        "calibration": cal, "liveBands": live_bands,
    }


# ───────── monthly review pack (task E1) ─────────

def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def _usd(x) -> str:
    return "—" if x is None else ("−$" if x < 0 else "$") + f"{abs(x):,.2f}"


def review(c: P.Ctx, month: str, audit_rows: list[dict], alerts: list[dict]) -> str:
    """A self-contained HTML page for one month: performance, trades, drift,
    execution, alerts, compliance changes and every override with its reason."""
    t = c.twin
    dates, eq, bench = t.get("dates") or [], t.get("equity") or [], t.get("bench") or []
    idx = [i for i, d in enumerate(dates) if d.startswith(month)]
    esc = html.escape
    if idx:
        i0 = max(0, idx[0] - 1)
        m_ret = eq[idx[-1]] / eq[i0] - 1
        b_ret = bench[idx[-1]] / bench[i0] - 1
        st = stats(eq[i0: idx[-1] + 1])
    else:
        m_ret = b_ret = None
        st = {}
    trades = [x for x in t.get("trades") or [] if x["date"].startswith(month)]
    trips = [x for x in P.round_trips(c)["trips"] if x["exitDate"].startswith(month)]
    month_audit = [a for a in audit_rows if (a.get("at") or "").startswith(month)]
    comp = [(d, r) for d, r in c.s.compliance.items() if d.startswith(month)]
    perf = performance(c)
    exe = perf.get("execution") or {}
    m_fills = [f for f in exe.get("fills") or [] if f["date"].startswith(month)]
    rows = lambda items: "".join(items) or "<tr><td colspan=9 class=m>none</td></tr>"  # noqa: E731
    out = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>NAFA review {esc(month)}</title>
<style>body{{font:13px/1.5 Inter,system-ui,sans-serif;color:#121720;max-width:980px;margin:32px auto;padding:0 20px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:15px;margin:28px 0 8px;border-bottom:1px solid #e2e5eb;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{padding:5px 8px;border-bottom:1px solid #eef0f3;text-align:left}}
th{{color:#646e80;font-weight:500}}.r{{text-align:right}}.m{{color:#646e80}}.pos{{color:#0b7f55}}.neg{{color:#c92a37}}
.k{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.k div{{border:1px solid #e2e5eb;border-radius:8px;padding:10px}}.k b{{display:block;font-size:17px}}
@media print{{body{{margin:0}}}}</style></head><body>
<h1>Monthly review · {esc(month)}</h1><div class=m>NAFA Operations Console · agent {esc(t.get('agent') or 'trend')} · {esc(c.env)} · generated {esc(c.today)} · model conviction is not a forecast</div>
<h2>Performance</h2><div class=k>
<div>Model return<b class="{'pos' if (m_ret or 0) >= 0 else 'neg'}">{_pct(m_ret)}</b></div>
<div>NASDAQ Composite<b>{_pct(b_ret)}</b></div>
<div>Max drawdown in month<b>{_pct(st.get('mdd'))}</b></div>
<div>Equity at month end<b>{_usd(eq[idx[-1]] if idx else None)}</b></div></div>
<h2>Trades ({len(trades)})</h2><table><tr><th>Date</th><th>Symbol</th><th>Side</th><th class=r>Shares</th><th class=r>Price</th><th class=r>Realized</th><th>Reason</th></tr>
{rows(f"<tr><td>{esc(x['date'])}</td><td>{esc(x['code'])}</td><td>{esc(x['side'])}</td><td class=r>{x['shares']}</td><td class=r>{_usd(x['price'])}</td><td class=r>{_usd(x.get('realized_pnl'))}</td><td>{esc(x.get('reason', ''))}</td></tr>" for x in trades)}</table>
<h2>Closed round trips ({len(trips)})</h2><table><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th class=r>P&amp;L</th><th>Exit reason</th></tr>
{rows(f"<tr><td>{esc(x['symbol'])}</td><td>{esc(x['entryDate'])}</td><td>{esc(x['exitDate'])}</td><td class='r {'pos' if x['pnl'] > 0 else 'neg'}'>{_usd(x['pnl'])}</td><td>{esc(x['reason'])}</td></tr>" for x in trips)}</table>
<h2>Execution and drift</h2><p>{'Ghost mode: no broker fills; the twin fills at the open with modelled slippage.' if c.env == 'ghost' else f"{len(m_fills)} fills · average slippage {sum(f['bps'] for f in m_fills) / len(m_fills):+.1f} bps" if m_fills else 'No fills recorded this month.'}</p>
<h2>Alerts</h2><table><tr><th>Priority</th><th>Alert</th><th>Status</th></tr>
{rows(f"<tr><td>{esc(a['priority'])}</td><td>{esc(a['title'])}<div class=m>{esc(a['detail'])}</div></td><td>{esc(a['status'])}</td></tr>" for a in alerts)}</table>
<h2>Compliance changes</h2><table><tr><th>Date</th><th>Newly non-compliant</th><th>Newly eligible</th><th>Held affected</th></tr>
{rows(f"<tr><td>{esc(d)}</td><td>{len(r.get('newly_noncompliant') or [])}</td><td>{len(r.get('newly_eligible') or [])}</td><td>{', '.join(r.get('held_and_flagged') or []) or '0'}</td></tr>" for d, r in comp)}</table>
<h2>Overrides and control changes ({len(month_audit)})</h2><table><tr><th>When</th><th>Actor</th><th>Action</th><th>Before → after</th><th>Reason</th><th>Result</th></tr>
{rows(f"<tr><td>{esc(a['t'])}</td><td>{esc(a['actor'])}</td><td>{esc(a['act'])}</td><td>{esc(a['ba'])}</td><td>{esc(a['reason'])}</td><td>{esc(a['res'])}</td></tr>" for a in month_audit)}</table>
</body></html>"""
    return out


def months(c: P.Ctx) -> list[str]:
    return sorted({d[:7] for d in c.twin.get("dates") or []}, reverse=True)

