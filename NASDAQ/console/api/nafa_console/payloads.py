"""Build the v1 API payloads (web/src/api/types.ts) from a ledger snapshot.

Rules:
* Only what the ledger says. Anything it does not hold yet (confidence
  sub-scores, stop levels and ATR before the insights step of M3, live daily
  prices, an account in Ghost) is returned as null, never estimated.
* Dates are ISO; the UI formats them. Times are ET, as "HH:MM ET".
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from . import calendar as cal
from .ledger import Snapshot
from .settings import Settings

ROADMAP = json.loads((Path(__file__).with_name("roadmap.json")).read_text(encoding="utf-8"))
ET = cal.ET
MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ───────── small helpers ─────────

def wd_label(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{WD[d.weekday()]} {d.day} {MO[d.month - 1]}"


def parse_utc(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def et_hm(t: dt.datetime | None) -> str | None:
    return t.astimezone(ET).strftime("%H:%M") + " ET" if t else None


def clean_name(name: str) -> str:
    for suffix in (" Common Stock", " Class A Common Stock", " Ordinary Shares", " American Depositary Shares"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def pct(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{d}f}%"


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def next_quarter_start(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    for m in (1, 4, 7, 10):
        q = dt.date(d.year, m, 1)
        if q > d:
            return q.isoformat()
    return dt.date(d.year + 1, 1, 1).isoformat()


# ───────── the shared context for one request ─────────

class Ctx:
    """Derived facts shared by every builder for one snapshot and moment."""

    def __init__(self, snap: Snapshot, settings: Settings, now: dt.datetime, indexer: dict, account=None):
        self.s = snap
        self.settings = settings
        self.now = now.astimezone(ET)
        self.today = self.now.date().isoformat()
        self.indexer = indexer
        self.twin = snap.twin or {}
        self.asof: str = self.twin.get("asof") or self.today
        self.positions: dict = self.twin.get("positions") or {}
        self.trades: list = self.twin.get("trades") or []
        self.slippage = float(snap.config.get("TWIN_SLIPPAGE") or self.twin.get("inputs", {}).get("slippage") or 0.0005)
        a_keys = snap.cycle_keys("A")
        self.a_records = [snap.cycles[k] for k in a_keys]
        self.last_a = self.a_records[-1] if self.a_records else None
        self.last_good_a = next((r for r in reversed(self.a_records) if r.get("status") == "ok"), None)
        self.mode = (self.last_a or {}).get("mode") or "ghost"
        self.env = {"ghost": "ghost", "paper": "paper", "live": "live"}.get(self.mode, "ghost")
        self.controls = snap.controls or {}
        self.excluded = list(self.controls.get("excluded_symbols") or [])
        self.held = sorted(self.positions)
        self.forced = [s for s in self.held if s in self.excluded]
        self.failing = self._failing()
        self.expected_asof = self._expected_asof()
        self.sessions_behind = len(cal.sessions_after(self.asof, self.expected_asof)) if self.twin else 0
        self.fresh = snap.latest_fresh_screen
        self.uni = snap.universe_by_code
        self.fresh_by_code = {u["code"]: u for u in (self.fresh[1].get("universe", []) if self.fresh else [])}
        self.fresh_rejected = {u["code"]: u for u in (self.fresh[1].get("rejected_detail", []) if self.fresh else [])}
        self.review = (snap.overrides or {}).get("review", {})
        self.insights_doc = self._insights_doc()
        self.insights = self.insights_doc.get("positions", {})
        # the Account book (M2): AccountView from the gateway, None in Ghost / without a gateway
        self.account = account
        self.account_positions = (account.positions if account is not None else None) or None
        self.broker_ok = bool(account is not None and account.reachable)
        # filled in by the app: open P1 alerts (preflight) and the store (audit records)
        self.open_p1: list = []
        self.settings_store = None

    # -- derived state --
    def _failing(self) -> dict | None:
        bad: list[dict] = []
        for r in reversed(self.a_records):
            if r.get("status") == "ok":
                break
            bad.append(r)
        if not bad:
            return None
        bad.reverse()
        newest = bad[-1]
        reason, checks = describe_failure(newest)
        return {"count": len(bad), "from": bad[0].get("asof"), "to": newest.get("asof"), "reason": reason, "checks": checks}

    def _expected_asof(self) -> str:
        """The session a Cycle A should have valued by now (it runs 17:05 ET)."""
        latest = cal.latest_completed_session(self.now)
        if latest == self.today and self.now.hour < 18:
            return cal.previous_session(self.today)
        return latest

    def _insights_doc(self) -> dict:
        p = self.settings.ledger_dir / "insights" / f"{self.asof}.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def insight_history(self) -> list[tuple[str, dict]]:
        """(asof, positions) for every insights file, oldest first."""
        out = []
        for f in sorted((self.settings.ledger_dir / "insights").glob("*.json")):
            try:
                out.append((f.stem, json.loads(f.read_text(encoding="utf-8")).get("positions", {})))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    @property
    def health(self) -> str:
        if not self.twin:
            return "empty"
        ix = self.indexer.get("last")
        if ix and not ix.get("ok"):
            return "error"
        if self.env != "ghost" and self.account is not None and not self.account.reachable:
            return "error"
        if self.failing and self.sessions_behind >= 1:
            return "stale"
        return "loaded"

    @property
    def trading(self) -> str:
        if self.controls.get("kill"):
            return "stopped"
        if (self.s.halt or {}).get("halted"):
            return "halted"
        if self.controls.get("pause_entries"):
            return "paused"
        return "running"


def describe_failure(rec: dict) -> tuple[str, str]:
    """Plain wording of why a Cycle A record failed, plus the other checks."""
    status = rec.get("status", "?")
    gate = (rec.get("data_gate") or {}).get("checks") or {}
    parts, other = [], []
    cov = gate.get("coverage_at_asof") or {}
    if cov:
        (other if cov.get("pass") else parts).append(f"coverage at asof {pct(cov.get('value'))} {'≥' if cov.get('pass') else '<'} {pct(cov.get('min'), 0)}")
    fo = gate.get("fetch_ok") or {}
    if fo:
        (other if fo.get("pass") else parts).append(f"fetch ok {pct(fo.get('value'))}")
    xs = gate.get("cross_source") or {}
    if xs:
        txt = f"cross-source {xs.get('compared', 0)} compared, {xs.get('unavailable', 0)} unavailable"
        if xs.get("disagreements"):
            txt += f", {len(xs['disagreements'])} disagree"
        (other if xs.get("pass") else parts).append(txt)
    ix = gate.get("ixic_at_asof") or {}
    if ix and not ix.get("pass"):
        parts.append("no NASDAQ Composite bar at asof")
    if status == "data_gate_tripped":
        reason = "Data gate tripped: " + ("; ".join(parts) if parts else "see the record")
    else:
        reason = status.replace("_", " ")
    return reason, " · ".join(other)


# ───────── facts and system status ─────────

def facts_next_open(c: Ctx) -> str:
    today_is_session = c.today in cal.sessions_between(c.today, c.today)
    if today_is_session and c.now.hour * 60 + c.now.minute < 9 * 60 + 30:
        return c.today
    return cal.next_session(c.today)


def facts(c: Ctx) -> dict:
    s = c.s
    good_t = parse_utc((c.last_good_a or {}).get("ts_utc"))
    last_t = parse_utc((c.last_a or {}).get("ts_utc"))
    today_is_session = c.today in cal.sessions_between(c.today, c.today)
    next_open = facts_next_open(c)
    open_at = dt.datetime.combine(dt.date.fromisoformat(next_open), dt.time(9, 30), tzinfo=ET)
    submit_at = dt.datetime.combine(c.now.date(), dt.time(19, 15), tzinfo=ET)
    ix = c.indexer
    last_ok = parse_utc((ix.get("last_ok") or {}).get("at_utc"))
    down = bool(ix.get("last") and not ix["last"].get("ok"))
    halt = None
    h = s.halt or {}
    if h.get("halted") and h.get("diffs"):
        d0 = h["diffs"][0]
        halt = {"symbol": d0.get("symbol"), "expected": d0.get("expected"), "actual": d0.get("actual"), "at": h.get("since")}
    screen_dates = list(s.compliance) + [x.get("date") for x in (s.universe.get("corrections") or []) if x.get("date")]
    last_screen = max(screen_dates) if screen_dates else c.asof
    journal = (c.twin.get("journal") or [])
    regime = None
    rg = c.insights_doc.get("regime") or {}
    if rg.get("ixic_vs_sma200") is not None:
        regime = (f"NASDAQ Composite {rg['ixic_vs_sma200'] * 100:+.1f}% vs its 200-day and {rg.get('ixic_vs_sma50', 0) * 100:+.1f}% vs its 50-day average"
                  f" · breadth {rg.get('breadth', 0) * 100:.0f}% · regime dial {rg.get('score')} · mood {rg.get('mood') or '—'}")
    elif journal:
        j = journal[-1]
        regime = f"{j.get('mood', '?')} · sentiment {j.get('sentiment', 0):+.2f} ({wd_label(j['date'])}) — {j.get('note', '')}".strip()
    return {
        "today": c.today,
        "model": {
            "asof": c.asof,
            "builtAt": et_hm(good_t),
            "ageMin": int((c.now - good_t).total_seconds() // 60) if good_t else None,
            "sessionsBehind": c.sessions_behind,
        },
        "lastCycleA": None if not c.last_a else {
            "session": c.last_a.get("asof"), "ok": c.last_a.get("status") == "ok",
            "finishedAt": et_hm(last_t), "durationS": c.last_a.get("duration_s"),
        },
        "failing": c.failing,
        "nextOpen": next_open,
        "submitInMin": int((submit_at - c.now).total_seconds() // 60) if today_is_session and c.now < submit_at and c.now.hour >= 16 else None,
        "openInMin": int((open_at - c.now).total_seconds() // 60),
        "ledger": {
            "commit": s.head.sha[:7] if s.head else None,
            "syncedMinAgo": int((dt.datetime.now(dt.timezone.utc) - last_ok).total_seconds() // 60) if last_ok else None,
            "down": down,
            "downMin": int((dt.datetime.now(dt.timezone.utc) - last_ok).total_seconds() // 60) if down and last_ok else None,
        },
        "broker": None if c.account is None else {"reachable": c.account.reachable, "lastOk": c.account.at_label, "latencyMs": c.account.latency_ms},
        "accountAt": c.account.at_label if c.account is not None else None,
        "halt": halt,
        "screen": {"last": last_screen, "next": next_quarter_start(last_screen)},
        "d1Due": ROADMAP.get("d1Due", "2026-10-30"),
        "paperStart": ROADMAP.get("paperStart", "2026-11-02"),
        "twinStart": c.twin.get("live_start") or c.asof,
        "regime": regime,
    }


def system(c: Ctx) -> dict:
    stop_at = None
    if c.trading == "stopped" and c.s.controls_log:
        stop_at = et_hm(parse_utc(c.s.controls_log[0].when))
    return {
        "env": c.env,
        "health": c.health,
        "trading": c.trading,
        "released": False,
        "haltCleared": False,
        "stopAt": stop_at,
        "flatten": False,
        "clock": {"d": wd_label(c.today), "t": c.now.strftime("%H:%M") + " ET"},
        "facts": facts(c),
    }


def controls(c: Ctx) -> dict:
    gc = c.controls.get("gross_cap")
    return {
        "lockedSymbols": list(c.controls.get("locked_symbols") or []),
        "forcedExits": c.forced,
        "manualOrders": [
            {"symbol": m.get("symbol"), "shares": int(m.get("qty") or m.get("shares") or 0), "pct": int(m.get("pct") or 0)}
            for m in (c.controls.get("manual_orders") or [])
        ],
        "excludedSymbols": c.excluded,
        "excludedMore": 0,
        "grossCap": round(gc * 100) if isinstance(gc, (int, float)) else None,
        "pauseAdapt": bool(c.controls.get("pause_adapt")),
    }


# ───────── overview ─────────

def _phase(c: Ctx) -> dict:
    gate = c.s.gate or {}
    streak, target = int(gate.get("streak") or 0), int(gate.get("target") or 10)
    open_dec = [d for d in ROADMAP["decisions"] if d["status"] == "Open" and d.get("dueIso")]
    open_dec.sort(key=lambda d: d["dueIso"])
    nd = next((d for d in open_dec if d["dueIso"] >= c.today), None)
    dec = f"Next decision: {nd['id']} {nd['title']} — {(dt.date.fromisoformat(nd['dueIso']) - dt.date.fromisoformat(c.today)).days} days" if nd else "No open decision with a date"
    if c.env == "ghost":
        return {"n": streak, "of": target, "title": "Phase 1 · Ghost", "gate": f"Gate streak {streak} / {target} deterministic sessions",
                "dates": f"phase ends {wd_label(ROADMAP.get('ghostEnds', '2026-10-30'))}" + (" · stalled while Cycle A fails" if c.failing else ""),
                "decision": dec}
    return {"n": streak, "of": target, "title": "Phase 2 · Paper" if c.env == "paper" else "Phase 5 · Real money",
            "gate": f"Clean sessions {streak} / {target}", "dates": "", "decision": dec}


def _markers(c: Ctx) -> list[dict]:
    dates = c.twin.get("dates") or []
    out = []
    for k, r in c.s.cycles.items():
        rec = r.get("reconcile") or {}
        if k.endswith("-B") and rec.get("status") == "break" and r.get("asof") in dates:
            out.append({"date": r["asof"], "kind": "halt", "text": "Halt — reconciliation break"})
    for cm in c.s.controls_log:
        when = parse_utc(cm.when)
        if not when:
            continue
        d = when.astimezone(ET).date().isoformat()
        day = next((x for x in dates if x >= d), None)
        if day:
            out.append({"date": day, "kind": "override", "text": "Control change — " + cm.subject})
    for a in c.twin.get("adaptations") or []:
        if a.get("date") in dates:
            out.append({"date": a["date"], "kind": "adaptation", "text": "Adaptation — parameters re-fitted"})
    return out


def overview(c: Ctx) -> dict:
    t = c.twin
    dates, eq, bench = t.get("dates") or [], t.get("equity") or [], t.get("bench") or []
    return {
        "system": system(c),
        "controls": controls(c),
        "me": {"user": c.settings.user, "role": c.settings.role},
        "asof": c.asof,
        "twinStart": t.get("live_start") or c.asof,
        "startCapital": float(eq[0]) if eq else float(c.s.config.get("START_CASH") or 100000),
        "equity": float(t.get("equity_final") or (eq[-1] if eq else 0)),
        "cash": float(t.get("cash_final") or 0),
        "accountCash": c.account.cash if c.account is not None else None,
        "equityCurve": [{"date": d, "model": float(e), "account": (c.account.history.get(d) if c.account is not None else None), "benchmark": float(b)}
                        for d, e, b in zip(dates, eq, bench)],
        "markers": _markers(c),
        "phase": _phase(c),
    }


# ───────── holdings ─────────

def _holding_start(c: Ctx, sym: str) -> tuple[str | None, str]:
    """Date the current holding opened (first buy after the last full exit)
    and the opening buy's reason."""
    pos, start, reason = 0, None, ""
    for tr in c.trades:
        if tr.get("code") != sym:
            continue
        n = int(tr.get("shares") or 0)
        if tr.get("side") == "buy":
            if pos == 0:
                start, reason = tr.get("date"), tr.get("reason", "")
            pos += n
        else:
            pos -= n
            if pos <= 0:
                pos, start, reason = 0, None, ""
    return start, reason


def lots(c: Ctx, sym: str) -> list[dict]:
    """Open FIFO lots of the current holding."""
    q: list[list] = []
    for tr in c.trades:
        if tr.get("code") != sym:
            continue
        n = int(tr.get("shares") or 0)
        if tr.get("side") == "buy":
            q.append([tr.get("date"), n, float(tr.get("price") or 0)])
        else:
            while n > 0 and q:
                take = min(n, q[0][1])
                q[0][1] -= take
                n -= take
                if q[0][1] == 0:
                    q.pop(0)
    return [{"opened": d, "shares": n, "cost": round(p, 4)} for d, n, p in q if n > 0]


def sessions_count(c: Ctx, start: str | None, end: str) -> int:
    if not start:
        return 0
    return len(cal.sessions_between(start, end))


def _ratios(c: Ctx, sym: str) -> tuple[float | None, float | None, str | None, dict]:
    src = c.fresh_by_code.get(sym) or c.fresh_rejected.get(sym)
    when = c.fresh[0] if (src and c.fresh) else None
    if not src:
        src = c.uni.get(sym) or {}
        corr = c.s.universe.get("corrections") or []
        when = corr[-1].get("date") if (src and corr) else None
    d, k = src.get("debt_ratio"), src.get("cash_ratio")
    return (round(d * 100, 2) if d is not None else None, round(k * 100, 2) if k is not None else None, when, src)


def position(c: Ctx, sym: str) -> dict:
    p = c.positions[sym]
    u = c.uni.get(sym) or c.fresh_by_code.get(sym) or {}
    start, why = _holding_start(c, sym)
    debt, cash, screened, src = _ratios(c, sym)
    flags = list(u.get("review_flags") or [])
    review_txt = c.review.get(sym) or (flags[0] if flags else None)
    prev = c.s.previous_prices.get(sym)
    price = float(p.get("price") or 0)
    ins = c.insights.get(sym) or {}
    conf = None
    if all(k in ins for k in ("signal", "risk_room", "regime", "data")):
        conf = {"signal": ins["signal"], "riskRoom": ins["risk_room"], "regime": ins["regime"], "data": ins["data"], "atEntry": ins.get("at_entry", ins["signal"])}
    next_orders = (c.s.orders.get(c.asof) or {}).get("orders") or []
    rank_exit = any(o.get("code") == sym and o.get("side") == "sell" and "momentum decay" in (o.get("reason") or "") for o in next_orders)
    return {
        "symbol": sym,
        "name": clean_name(u.get("name") or sym),
        "sector": u.get("sector") or "—",
        "industry": u.get("industry") or "—",
        "shares": int(p.get("shares") or 0),
        "avgCost": float(p.get("avg_cost") or 0),
        "last": price,
        "dayPct": round((price / prev - 1) * 100, 2) if prev else None,
        "entryDate": start or c.asof,
        "heldSessions": sessions_count(c, start, c.asof),
        "atr": ins.get("atr"),
        "high": ins.get("high"),
        "rank": ins.get("rank"),
        "offHighPct": ins.get("off_high_pct"),
        "smaStack": ins.get("sma_stack"),
        "initialStop": ins.get("initial_stop"),
        "trailingStop": ins.get("trailing_stop"),
        "confidence": conf,
        "crossSource": ins.get("cross_source"),
        "debtPct": debt,
        "cashPct": cash,
        "screenedOn": screened,
        "review": {"keyword": review_txt, "category": "owner ruling pending (D1)"} if review_txt else None,
        "entryReason": why.replace("->", "→"),
        "rankExit": rank_exit,
        "nextDividend": None,
        "account": account_leg(c, sym, start, int(p.get("shares") or 0), float(p.get("avg_cost") or 0)),
    }


def account_leg(c: Ctx, sym: str, start: str | None, model_shares: int, model_avg: float) -> dict | None:
    if c.account is None:
        return None
    from .account import ledger_fills
    ap = (c.account.positions or {}).get(sym) or {}
    fills = ledger_fills(c.s.cycles)
    entry = fills.get((start, sym, "buy")) if start else None
    shares = int(ap.get("shares") or 0)
    drift = None
    if shares != model_shares:
        why = _drift_reason(c, sym)
        drift = {"row": why or f"Account holds {shares}, the Model {model_shares}", "short": (why or "shares differ").split(":")[0].lower()[:40],
                 "detail": f"The account holds {shares} of {model_shares}." + (f" {why}." if why else " No ledger record explains it yet — check the Cycle B reconciliation.")}
    return {"shares": shares, "avgCost": float(ap.get("avg_cost") or model_avg), "slippageBps": (entry or {}).get("slippage_bps") or 0.0, "drift": drift}


def _drift_reason(c: Ctx, sym: str) -> str | None:
    """The ledger's own explanation of a share difference, newest first."""
    for key in sorted(c.s.cycles, reverse=True)[:12]:
        rec = c.s.cycles[key]
        plan = rec.get("plan") or {}
        for a in plan.get("adjusted") or []:
            if a.get("code") == sym:
                return f"Buy trimmed to available cash at submit: {a.get('from')} → {a.get('to')} ({key[:10]})"
        for sk in plan.get("skipped") or []:
            if sk.get("code") == sym and sk.get("reason") in ("locked", "pause_entries"):
                return f"Order skipped at submit: {sk['reason']} ({key[:10]})"
        for m in rec.get("missed") or []:
            if m.get("symbol") == sym:
                return f"Not fully filled at the open: {m.get('filled')} of {m.get('qty')} ({key[:10]})"
        for d in (rec.get("reconcile") or {}).get("diffs") or []:
            if d.get("symbol") == sym:
                return f"Reconciliation break: expected {d.get('expected')}, actual {d.get('actual')} ({key[:10]})"
    if sym in c.excluded:
        return "Excluded symbol: forced exit"
    if sym in (c.controls.get("locked_symbols") or []):
        return "Locked by the owner: the agent's orders are skipped"
    return None


def holdings(c: Ctx) -> dict:
    out = {"asof": c.asof, "positions": [position(c, s) for s in sorted(c.positions, key=lambda s: -float(c.positions[s].get("value") or 0))]}
    if c.account is not None:
        out["accountOnly"] = [{"symbol": s, "shares": v["shares"], "avgCost": v["avg_cost"], "last": v["price"]}
                              for s, v in sorted((c.account.positions or {}).items()) if s not in c.positions]
    return out


def _price_series(c: Ctx, sym: str) -> tuple[list[dict], str | None]:
    for sub in ("enriched_live", "enriched_full"):
        f = c.settings.pkg / "data" / sub / f"{sym}.csv"
        if not f.exists():
            continue
        with f.open(newline="") as fh:
            rows = [(r["Date"][:10], r.get("AdjClose") or r.get("Close")) for r in csv.DictReader(fh)]
        rows = [(d, float(x)) for d, x in rows if x and d <= c.asof][-260:]
        if rows and rows[-1][0] == c.asof:
            return [{"date": d, "close": round(x, 4)} for d, x in rows], None
    return [], ("Daily prices for the live sessions are not stored in the ledger yet. "
                "The chart fills once the insights step (M3) ledgers them, or on the Unraid box where Cycle A's data is local.")


def calibration_bands(settings) -> list[dict]:
    """OOS share of trades won per confidence band (live/calibration.py output); [] when not computed."""
    try:
        d = json.loads((settings.pkg / "out" / "confidence_calibration.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [{"band": b["band"], "n": b["n"], "wonRate": b.get("trade_won_rate")} for b in d.get("bands", [])]


def holding_detail(c: Ctx, sym: str) -> dict | None:
    if sym not in c.positions:
        return None
    ins_prices = (c.insights_doc.get("prices") or {}).get(sym)
    if ins_prices:
        prices, note = [{"date": d, "close": float(x)} for d, x in ins_prices], None
    else:
        prices, note = _price_series(c, sym)
    start, _ = _holding_start(c, sym)
    hist = [v[sym].get("overall") for d, v in c.insight_history() if sym in v and (not start or d >= start) and v[sym].get("overall") is not None]
    return {"symbol": sym, "prices": prices, "confidenceHistory": hist, "lots": lots(c, sym), "pricesNote": note,
            "calibration": calibration_bands(c.settings)}


# ───────── orders ─────────

def pending(c: Ctx) -> dict:
    f = c.s.orders.get(c.asof) or {}
    nxt = cal.next_session(c.asof)
    expired = nxt < c.today or (nxt == c.today and c.now.hour * 60 + c.now.minute >= 9 * 60 + 30)
    intents = []
    if not expired:
        for i, o in enumerate(f.get("orders") or []):
            side = "BUY" if o.get("side") == "buy" else "SELL"
            qty = int((o.get("share_preview") or {}).get("qty") or o.get("shares") or 0)
            ref = o.get("ref_close")
            est = qty * ref if (qty and ref) else float(o.get("sar") or 0)
            blocked = list(o.get("blocked") or [])
            sym = o.get("code")
            intents.append({
                "id": f"o{i}", "symbol": sym, "name": clean_name((c.uni.get(sym) or {}).get("name") or sym),
                "side": side, "shares": qty,
                "qtyLabel": f"{qty} sh" + (" (all)" if o.get("all") else ""),
                "amountLabel": f"${float(o['sar']):,.0f} → {qty} sh" if o.get("sar") else "",
                "refClose": float(ref) if ref else 0.0, "estValue": round(est, 2),
                "reason": (o.get("reason") or "").replace("->", "→"),
                "source": "forced" if o.get("forced") else "agent",
                "guardrail": blocked[0] if blocked else None,
                "guardrailNote": ", ".join(blocked[1:]) if len(blocked) > 1 else "",
                "clientOrderId": o.get("client_order_id") or "",
            })
    # An expired plan is never shown as pending: the next open is the calendar's.
    return {"asof": c.asof, "nextOpen": facts_next_open(c) if expired else nxt, "intents": intents}


def _decision_close(c: Ctx, tr: dict) -> float | None:
    """ref_close the order was ledgered at (orders/<decision day>.json), when it exists."""
    try:
        dec = cal.previous_session(tr["date"])
    except Exception:  # noqa: BLE001
        return None
    for o in (c.s.orders.get(dec) or {}).get("orders") or []:
        if o.get("code") == tr.get("code") and o.get("side") == tr.get("side") and o.get("ref_close"):
            return float(o["ref_close"])
    return None


def official_open(c: Ctx, tr: dict) -> float:
    px = float(tr.get("price") or 0)
    return px / (1 + c.slippage) if tr.get("side") == "buy" else px / (1 - c.slippage)


def history(c: Ctx) -> dict:
    out = []
    acct_fills = {}
    if c.account is not None:
        from .account import ledger_fills
        acct_fills = ledger_fills(c.s.cycles)
    for i, tr in enumerate(c.trades):
        side = "BUY" if tr.get("side") == "buy" else "SELL"
        af = acct_fills.get((tr["date"], tr.get("code"), tr.get("side")))
        out.append({
            "id": f"t{i}",
            "decisionDate": cal.previous_session(tr["date"]),
            "fillDate": tr["date"],
            "symbol": tr.get("code"),
            "side": side,
            "shares": int(tr.get("shares") or 0),
            "accountShares": (af["qty"] if af and af["qty"] != int(tr.get("shares") or 0) else None),
            "decisionClose": _decision_close(c, tr),
            "officialOpen": round(af["open"], 4) if af and af.get("open") else round(official_open(c, tr), 4),
            "fillPrice": float(af["price"]) if af and af.get("price") else float(tr.get("price") or 0),
            "fees": float(tr.get("fee") or 0),
            "realized": tr.get("realized_pnl"),
            "heldDays": sessions_count(c, tr.get("held_since"), tr["date"]) if side == "SELL" else None,
            "reason": (tr.get("reason") or "").replace("->", "→"),
        })
    out.reverse()
    return {"since": c.twin.get("live_start") or c.asof, "total": len(out), "feesSinceStart": float(c.twin.get("commissions_paid") or 0), "orders": out}


EXIT_RULES = [("initial stop", "stop"), ("hard stop", "stop"), ("trailing", "trail"), ("momentum decay", "rank"), ("rank", "rank"),
              ("time stop", "time"), ("sma200", "sma"), ("de-risk", "derisk"), ("sharia", "forced"), ("forced", "forced"), ("manual", "manual")]


def exit_reason(reason: str) -> str:
    r = reason.lower()
    return next((k for pat, k in EXIT_RULES if pat in r), "other")


def _conf_at_entry(hist: list[tuple[str, dict]], sym: str, since: str | None) -> int | None:
    for d, v in hist:
        if sym in v and (since is None or d >= since) and v[sym].get("at_entry") is not None:
            return int(v[sym]["at_entry"])
    return None


def round_trips(c: Ctx) -> dict:
    trips = []
    hist = c.insight_history()
    for tr in c.trades:
        if tr.get("side") != "sell" or tr.get("realized_pnl") is None:
            continue
        n = int(tr.get("shares") or 0) or 1
        px = float(tr.get("price") or 0)
        entry = px - float(tr["realized_pnl"]) / n
        sec = (c.uni.get(tr["code"]) or c.fresh_rejected.get(tr["code"]) or {}).get("sector") or "—"
        trips.append({
            "symbol": tr["code"], "sector": sec, "entryDate": tr.get("held_since") or tr["date"], "exitDate": tr["date"],
            "days": sessions_count(c, tr.get("held_since"), tr["date"]), "entryPrice": round(entry, 4), "exitPrice": px,
            "pnl": float(tr["realized_pnl"]), "exitReason": exit_reason(tr.get("reason") or ""), "confAtEntry": _conf_at_entry(hist, tr["code"], tr.get("held_since")),
            "reason": tr.get("reason") or "",
        })
    trips.reverse()
    return {"fees": float(c.twin.get("commissions_paid") or 0), "trips": trips}


# ───────── compliance ─────────

def grade(debt: float | None, cash: float | None, review: bool, excluded: bool, data_days: int | None) -> str:
    """docs/08 §5: A ≥ 10 pp headroom on both ratios, no flag, data < 100 days;
    B under 10 pp or data 100–200 days; C review-flagged, under 3 pp or stale;
    F fails a layer or is excluded."""
    if excluded:
        return "F"
    if debt is None or cash is None:
        return "C"
    head = min(30 - debt, 30 - cash)
    if head < 0:
        return "F"
    if review or head < 3 or (data_days is not None and data_days > 200):
        return "C"
    if head < 10 or (data_days is not None and data_days >= 100):
        return "B"
    return "A"


def _reason_for(c: Ctx, code: str, given: str) -> str:
    if given and given not in ("?", "not in fresh screen"):
        return given
    rej = c.fresh_rejected.get(code)
    if rej:
        reasons = (rej.get("ratio_reasons") or []) + (rej.get("business_reasons") or []) + (rej.get("instrument_reasons") or []) + (rej.get("override_reasons") or [])
        if reasons:
            return "; ".join(reasons)
    if code not in c.fresh_by_code and code not in c.fresh_rejected:
        return "left the top-500 NASDAQ screen by market cap"
    return given or "—"


def compliance(c: Ctx) -> dict:
    rows = []
    for code, u in sorted(c.uni.items()):
        debt, cash, when, _ = _ratios(c, code)
        excluded = code in c.excluded
        review = bool(u.get("review_flags"))
        days = (dt.date.fromisoformat(c.today) - dt.date.fromisoformat(when)).days if when else None
        flag = ""
        if excluded:
            flag = "excluded after the re-screen: " + _reason_for(c, code, "?")
        elif review:
            flag = (c.review.get(code) or u["review_flags"][0]) + " — D1 ruling"
        rows.append({
            "symbol": code, "name": clean_name(u.get("name") or code), "grade": grade(debt, cash, review, excluded, days),
            "status": "Excluded" if excluded else "Under review" if review else "Compliant",
            "debtPct": debt, "cashPct": cash, "flag": flag,
        })
    rescreens = []
    for date in sorted(c.s.compliance, reverse=True):
        rep = c.s.compliance[date]
        out = rep.get("newly_noncompliant") or []
        inn = rep.get("newly_eligible") or []
        held_hit = rep.get("held_and_flagged") or []
        rescreens.append({
            "id": date, "date": wd_label(date) + " " + date[:4], "kind": "Quarterly re-screen" if out or inn else "Baseline screen",
            "file": date, "dot": "warn" if out else "ok",
            "summary": f"{len(out)} newly non-compliant · {len(inn)} newly eligible · {len(held_hit)} held affected",
            "stats": [{"l": "Newly non-compliant", "v": str(len(out)), "cls": "danger" if out else ""},
                      {"l": "Newly eligible", "v": str(len(inn)), "cls": ""},
                      {"l": "Held names affected", "v": str(len(held_hit)), "cls": "danger" if held_hit else "pos"},
                      {"l": "Forced exits caused", "v": str(len([x for x in held_hit])), "cls": ""}],
            "outTitle": "Newly non-compliant → added to excluded_symbols (buys blocked)", "outTag": "excluded",
            "out": [{"symbol": x.get("code"), "reason": _reason_for(c, x.get("code"), x.get("reason", ""))} for x in out],
            "inTitle": f"Newly eligible · {len(inn)}" if inn else "", "in": inn,
            "inNote": "The universe is frozen for the evaluation: newly eligible names wait for the next declared redeploy." if inn else "",
            "note": rep.get("policy") or "", "noteCls": "info" if not held_hit else "warn",
        })
    for corr in reversed(c.s.universe.get("corrections") or []):
        removed = corr.get("removed") or []
        rescreens.append({
            "id": "fix-" + corr.get("date", ""), "date": wd_label(corr["date"]) + " " + corr["date"][:4],
            "kind": f"Universe correction · {len(removed)} removed", "file": "universe_screened.json", "dot": "info",
            "summary": f"{len(removed)} removed by {corr.get('rule_layers', 'a rule change')}",
            "stats": [{"l": "Removed", "v": str(len(removed)), "cls": "danger"}, {"l": "Universe now", "v": str(len(c.uni)), "cls": ""}],
            "outTitle": "Removed", "outTag": "removed",
            "out": [{"symbol": r.get("code"), "reason": "; ".join(r.get("reasons") or [])} for r in removed],
            "inTitle": "", "in": [], "inNote": "", "note": "Rule layers: " + corr.get("rule_layers", ""), "noteCls": "info",
        })
    fs = c.fresh
    return {
        "screenedOn": fs[0] if fs else (max(c.s.compliance) if c.s.compliance else c.asof),
        "nextScreen": next_quarter_start(fs[0] if fs else c.asof),
        "universeSize": len(c.uni),
        "reviewFlagged": sum(1 for u in c.uni.values() if u.get("review_flags")),
        "excludedAfterRescreen": len(c.excluded),
        "universe": rows,
        "rescreens": rescreens,
    }


# ───────── alerts ─────────

def alerts(c: Ctx, states: dict) -> dict:
    out: list[dict] = []

    def add(key: str, priority: str, title: str, detail: str, source: str, when: str) -> None:
        aid = "A-" + stable_id(key)
        st = states.get(aid)
        out.append({"id": aid, "priority": priority, "title": title, "detail": detail, "source": source, "githubIssue": None,
                    "raisedAt": when, "status": st["status"] if st else "open", "note": st["note"] if st else ""})

    f = c.failing
    if f:
        add(f"cycle-a-fail-{f['from']}", "P1", f"Cycle A failed {f['count']} session{'s' if f['count'] != 1 else ''} in a row — {f['reason'].split(':')[0].lower()}",
            f["reason"].split(": ", 1)[-1] + (" · " + f["checks"] if f["checks"] else ""), f"Cycle A · {wd_label(f['to'])}", wd_label(f["to"]))
    if c.sessions_behind >= 2:
        add(f"stale-{c.asof}", "P2", f"Model book {c.sessions_behind} sessions behind",
            f"last good asof {wd_label(c.asof)}; confidence Data sub-scores are stale", "console check", wd_label(c.today))
    if (c.s.halt or {}).get("halted"):
        h = c.s.halt
        add(f"halt-{h.get('since')}", "P1", "Reconciliation break — submit halted", h.get("reason", ""), f"Cycle B · {h.get('since')}", h.get("since", ""))
    for sym in c.held:
        u = c.uni.get(sym) or {}
        if sym in c.excluded:
            add(f"forced-{sym}", "P2", f"{sym} excluded — forced exit at the next open", "held name on excluded_symbols", "controls.json", wd_label(c.today))
        elif u.get("review_flags") or c.review.get(sym):
            add(f"review-{sym}", "P2", f"{sym} review-flagged — owner ruling due {wd_label(ROADMAP.get('d1Due', '2026-10-30'))}",
                "business screen: \"" + (c.review.get(sym) or u["review_flags"][0]) + "\"", "sharia_overrides.json", wd_label(c.today))
    last = c.last_a or {}
    det = last.get("determinism") or {}
    if det and det.get("match") is False:
        add(f"determinism-{last.get('asof')}", "P1", "Determinism broken — replays disagree", "the twin replayed twice gave different hashes", f"Cycle A · {last.get('asof')}", last.get("asof", ""))
    if c.env != "ghost" and c.account is not None and not c.account.reachable:
        add(f"broker-down-{c.today}", "P1", "Broker gateway unreachable", (c.account.error or "")[:200] + (f" · last success {c.account.at_label}" if c.account.at_label else ""),
            "console check", wd_label(c.today))
    a_last = c.s.latest_cycle("A") or {}
    for b in (a_last.get("account_drift") or {}).get("breaches") or []:
        add(f"drift-{a_last.get('asof')}-{b['symbol']}", "P1", f"Account drift: {b['symbol']} {b['diff']:+d} sh beyond tolerance",
            f"twin {b['twin']} · account {b['account']}", f"Cycle A · {a_last.get('asof')}", wd_label(a_last.get("asof") or c.today))
    b_last = c.s.latest_cycle("B") or {}
    if (b_last.get("slippage_avg") or 0) > float(c.s.config.get("SLIPPAGE_ALERT") or 0.001):
        add(f"slip-{b_last.get('asof')}", "P2", f"Average slippage {b_last['slippage_avg'] * 1e4:.1f} bps per side",
            "above the 10 bps band (docs/05 §8)", f"Cycle B · {b_last.get('asof')}", wd_label(b_last.get("asof") or c.today))
    for m in b_last.get("missed") or []:
        add(f"missed-{b_last.get('asof')}-{m.get('symbol')}", "P2", f"{m.get('symbol')} not fully filled at the open",
            f"{m.get('filled')} of {m.get('qty')} ({m.get('status')})", f"Cycle B · {b_last.get('asof')}", wd_label(b_last.get("asof") or c.today))
    ins_status = (a_last.get("insights") or {})
    if ins_status.get("status") == "error":
        add(f"insights-{a_last.get('asof')}", "P2", "Insights step failed — confidence not refreshed", ins_status.get("error", ""), f"Cycle A · {a_last.get('asof')}",
            wd_label(a_last.get("asof") or c.today))
    if c.controls.get("kill"):
        add("kill", "P2", "Kill switch active — trading stopped", "No orders are ledgered or sent until resumed", "controls.json", wd_label(c.today))
    return {"alerts": out}


# ───────── health ─────────

def _cell(rec: dict | None, kind: str) -> str:
    if not rec:
        return "skip"
    st = rec.get("status", "")
    if kind == "A":
        return "ok" if st == "ok" else "fail"
    if kind == "B":
        return "fail" if (rec.get("reconcile") or {}).get("status") == "break" else "ok"
    return {"held": "held", "ok": "ok"}.get(st, "skip")


def _trim(rec: dict) -> dict:
    """The raw record, minus bulky lists, for the Health inspector."""
    r = json.loads(json.dumps(rec))
    r.pop("controls", None)
    gate = (r.get("data_gate") or {}).get("checks") or {}
    cov = gate.get("coverage_at_asof") or {}
    if isinstance(cov.get("missing"), list) and len(cov["missing"]) > 8:
        cov["missing"] = cov["missing"][:8] + [f"… {len(rec['data_gate']['checks']['coverage_at_asof']['missing']) - 8} more"]
    return r


def health(c: Ctx) -> dict:
    s = c.s
    last_key_day = max([k[:10] for k in s.cycles] + [c.asof])
    days = cal.last_sessions(max(last_key_day, c.expected_asof), 14)
    cycles: dict[str, list[str]] = {"A": [], "S": [], "B": []}
    records: dict[str, Any] = {}
    for kind in ("A", "S", "B"):
        for i, d in enumerate(days):
            rec = s.cycles.get(f"{d}-{kind}")
            cycles[kind].append(_cell(rec, kind))
            records[f"{kind}{i}"] = _trim(rec) if rec else {"step": {"A": "cycle_a", "S": "cycle_submit", "B": "cycle_b"}[kind], "session": d, "status": "no record" + (" (ghost: no submit step)" if kind == "S" and c.env == "ghost" else "")}
    a_idx = [i for i, d in enumerate(days) if f"{d}-A" in s.cycles]
    default = f"A{a_idx[-1]}" if a_idx else "A13"
    gate = s.gate or {}
    hist = {h.get("asof"): h for h in gate.get("history") or []}
    hashes = []
    for r in list(reversed(c.a_records))[:6]:
        d = r.get("asof")
        if r.get("status") == "ok":
            det = r.get("determinism") or {}
            g = r.get("ghost_gate") or {}
            hashes.append({"date": wd_label(d), "hash": det.get("sha256") or (hist.get(d) or {}).get("hash8") or "—", "cls": "pos" if det.get("match", True) else "danger",
                           "result": (f"✓ {g.get('streak')}/{g.get('target')}" if g else "✓") if det.get("match", True) else "✕ mismatch"})
        else:
            hashes.append({"date": wd_label(d), "hash": "no hash — Cycle A failed", "cls": "danger", "result": "✕"})
    good = c.last_good_a or {}
    latest = c.last_a or {}
    dg = latest.get("data_gate") or {}
    ch = dg.get("checks") or {}
    checks = []
    if "ixic_at_asof" in ch:
        checks.append({"ok": bool(ch["ixic_at_asof"].get("pass")), "label": "NASDAQ Composite bar at asof", "value": "present" if ch["ixic_at_asof"].get("pass") else "missing", "min": ""})
    if "fetch_ok" in ch:
        x = ch["fetch_ok"]
        checks.append({"ok": bool(x.get("pass")), "label": "Fetch ok", "value": pct(x.get("value")), "min": "min " + pct(x.get("min"), 0)})
    if "coverage_at_asof" in ch:
        x = ch["coverage_at_asof"]
        checks.append({"ok": bool(x.get("pass")), "label": "Coverage at asof", "value": pct(x.get("value")), "min": "min " + pct(x.get("min"), 0)})
    if "cross_source" in ch:
        x = ch["cross_source"]
        weak = x.get("pass") and (x.get("compared") or 0) < 10
        checks.append({"ok": None if weak else bool(x.get("pass")), "label": "Cross-source check",
                       "value": f"{x.get('compared', 0)} compared · {x.get('unavailable', 0)} unavailable", "min": f"{len(x.get('disagreements') or [])} disagree"})
    missing = None
    cov = ch.get("coverage_at_asof") or {}
    if cov and not cov.get("pass"):
        total = len(c.uni) or 319
        count = total - round((cov.get("value") or 0) * total)
        missing = {"count": count, "total": total, "sample": list(cov.get("missing") or [])[:12],
                   "note": "Nothing trades on partial data: the session is skipped, never guessed."}
    f = c.failing
    hb = []
    for kind, step, exp in (("A", "cycle_a", "17:05"), ("B", "cycle_b", "09:50")):
        r = s.latest_cycle(kind)
        t = parse_utc((r or {}).get("ts_utc"))
        ok = r is not None and _cell(r, kind) == "ok"
        hb.append({"step": step, "expected": exp, "last": (t.astimezone(ET).strftime("%a %H:%M:%S") if t else "—"),
                   "duration": f"{r['duration_s']:.0f} s" if r and r.get("duration_s") else "—",
                   "status": "OK" if ok else ("Failed" if r else "No record"), "dot": "ok" if ok else "red", "cls": "pos" if ok else "danger"})
    for step, exp in (("deadman", "18:15"), ("cycle_submit", "19:15"), ("cycle_submit (retry)", "19:45"), ("deadman --submit", "21:30")):
        hb.append({"step": step, "expected": exp, "last": "—", "duration": "—", "status": "Ghost: rehearsal only" if c.env == "ghost" and "submit" in step else "Scheduled", "dot": "off", "cls": "muted"})
    if s.compliance:
        d = max(s.compliance)
        hb.append({"step": "rescreen", "expected": "1st of quarter 10:00", "last": wd_label(d), "duration": "—", "status": "OK", "dot": "ok", "cls": "pos"})
    ix = c.indexer
    last_ok = parse_utc((ix.get("last_ok") or {}).get("at_utc"))
    down = bool(ix.get("last") and not ix["last"].get("ok"))
    mins = int((dt.datetime.now(dt.timezone.utc) - last_ok).total_seconds() // 60) if last_ok else None
    if c.env == "ghost":
        broker = [{"k": "Mode", "v": "Ghost — no broker; nightly rehearsal against the twin’s book", "cls": ""},
                  {"k": "Paper account", "v": "opens before the paper phase (task P1)", "cls": "dim"},
                  {"k": "Live keys", "v": "never on GitHub — Unraid box only", "cls": "dim"}]
    elif c.account is None:
        broker = [{"k": "Broker gateway", "v": "not configured (CONSOLE_GATEWAY_URL)", "cls": "warn"}]
    else:
        a = c.account
        broker = [{"k": "Endpoint", "v": "Alpaca " + c.env + " via the gateway", "cls": ""},
                  {"k": "Reachable", "v": (f"✓ {a.latency_ms} ms" if a.reachable else "✕ " + (a.error or "unreachable"))[:80], "cls": "pos" if a.reachable else "danger"},
                  {"k": "Account status", "v": (a.status or "—") + " · cash account expected (margin off)", "cls": ""},
                  {"k": "Cash", "v": f"${a.cash:,.2f}" if a.cash is not None else "—", "cls": ""},
                  {"k": "Open orders", "v": str(len(a.open_orders)) if a.reachable else "unknown", "cls": "" if a.reachable else "warn"},
                  {"k": "Last snapshot", "v": a.at_label or "—", "cls": ""},
                  {"k": "Key permissions", "v": "trading only · no transfers · paper keys only in this container", "cls": "dim"}]
    summary = (f"Cycle A failing since {wd_label(f['from'])} · {f['reason'].split(':')[0].lower()} · model book stuck at {wd_label(c.asof)}" if f
               else f"All scheduled steps healthy · last Cycle A {wd_label(latest.get('asof', c.asof))} {et_hm(parse_utc(latest.get('ts_utc'))) or ''}".strip())
    return {
        "summary": summary,
        "degraded": bool(f) or down,
        "sessions": [{"dow": WD[dt.date.fromisoformat(d).weekday()], "label": f"{dt.date.fromisoformat(d).day} {MO[dt.date.fromisoformat(d).month - 1]}"} for d in days],
        "cycles": cycles,
        "records": records,
        "defaultCell": default,
        "gate": {
            "streak": int(gate.get("streak") or 0), "target": int(gate.get("target") or 10),
            "stalled": f"Stalled — {f['count']} failed session{'s' if f['count'] != 1 else ''}" if f else None,
            "earliestPass": "10 clean sessions after the streak restarts" if f else "after 10 consecutive matches",
            "hashes": hashes,
            "lastSha256": ((good.get("determinism") or {}).get("sha256")) or "—",
            "replayNote": (f"✓ replay matches the ledgered twin ({wd_label(good['asof'])})" if (good.get("determinism") or {}).get("match") else "no successful replay yet"),
        },
        "dataGate": {
            "when": f"Cycle A · {wd_label(latest['asof'])} {et_hm(parse_utc(latest.get('ts_utc'))) or ''}".strip() if latest else "no Cycle A yet",
            "tripped": (f"Tripped {f['count']} session{'s' if f['count'] != 1 else ''}" if f and dg.get("status") == "trip" else None),
            "checks": checks,
            "missing": missing,
        },
        "broker": broker,
        "heartbeats": hb,
        "indexer": {
            "commit": s.head.sha[:7] if s.head else "—",
            "message": s.head.subject if s.head else "—",
            "lag": "—" if mins is None else f"{mins} min since the last pull",
            "errors": str(ix.get("errors_24h") or 0) + (f" · {ix['last_error']}" if ix.get("last_error") else ""),
            "readModel": f"{len(s.cycles)} cycle records · {len(c.trades)} twin trades · {len(c.uni)} universe names",
            "down": down,
            "label": (f"Down · {mins} min" if down and mins is not None else "Down") if down else "In sync",
        },
    }


# ───────── roadmap ─────────

def roadmap(c: Ctx, open_p1: bool) -> dict:
    cur = {"ghost": 0, "paper": 1, "live": 4}[c.env]
    gate = c.s.gate or {}
    phases = []
    for p in ROADMAP["phases"]:
        gates = []
        for g in p["gates"]:
            if g == "ghost_streak":
                gates.append({"ok": False if c.failing else (True if gate.get("passed") else None),
                              "label": f"10 consecutive deterministic sessions — {gate.get('streak', 0)} / {gate.get('target', 10)}" + (", stalled" if c.failing else "")})
            elif g == "no_open_p1":
                gates.append({"ok": not open_p1, "label": "Zero open P1 issues"})
            else:
                gates.append({"ok": None, "label": g})
        phases.append({"n": p["n"], "label": p["label"], "dates": p["dates"], "gates": gates})
    today = dt.date.fromisoformat(c.today)

    def days(iso: str | None) -> int | None:
        return (dt.date.fromisoformat(iso) - today).days if iso else None

    return {
        "current": cur,
        "currentFailing": bool(c.failing) and cur == 0,
        "phases": phases,
        "decisions": [{"id": d["id"], "title": d["title"], "recommendation": d["recommendation"], "due": d["due"], "daysLeft": days(d.get("dueIso")), "status": d["status"]} for d in ROADMAP["decisions"]],
        "tasks": [{"group": t["group"], "id": t["id"], "task": t["task"], "owner": t["owner"], "due": t["due"], "daysLeft": days(t.get("dueIso")), "status": t["status"]} for t in ROADMAP["tasks"]],
    }

