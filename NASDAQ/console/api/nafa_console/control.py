"""The control service (docs/08 §7): preview → reason → step-up → validate →
commit → push → immediate command → confirm, for every executive action.

Each action is defined once, in `_define()`: what it changes in which file,
the impact preview the operator sees (rows before → after, orders added /
blocked / canceled, proceeds, P&L locked in, drift, fidelity warning), the
"Effective:" line, the typed confirmation word for destructive actions, and
the immediate command it needs. `preview()` and `apply()` both rebuild it
from the current state, so a stale preview (another commit landed in
between) is detected by its hash and answered with 409 and a fresh preview.

Nothing here ever reports optimistic success: a failed step makes the whole
result "Not applied" with the step that failed.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import calendar as cal
from . import payloads as P
from .writer import Conflict, Dispatcher, WriteError, blob_version

CONTROLS_REL = "NASDAQ/live/controls.json"
HALT_REL = "NASDAQ/live/ledger/halt.json"
CATEGORIES = ("Compliance", "Risk", "Operational", "Test")


def _schema(pkg: Path):
    """The harness's own controls schema (pure module, no harness side effects)."""
    live = str(pkg / "live")
    if live not in sys.path:
        sys.path.insert(0, live)
    import controls_schema  # noqa: WPS433
    return controls_schema


def new_action_id() -> str:
    """Time-sortable id, like a ULID: ms timestamp + randomness."""
    return f"{int(time.time() * 1000):012x}{secrets.token_hex(5)}".upper()


class ControlError(Exception):
    def __init__(self, status: int, message: str, preview: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.preview = preview


@dataclass
class Def:
    title: str
    sub: str
    danger: bool
    verb: str
    eff: str
    effS: str
    summary: str                         # "control: …" subject line
    rows: list[dict] = field(default_factory=list)
    added: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    canceled: list[dict] = field(default_factory=list)
    proceeds: str = "—"
    pnl: str = "$0.00"
    drift: str = "—"
    fid: str = ""
    word: str | None = None
    controls: dict | None = None         # new controls.json document
    halt: dict | None = None             # new halt.json document
    immediate: tuple[str, dict] | None = None   # ("cancel_all"|"flatten"|"dispatch", args)
    errors: list[str] = field(default_factory=list)
    pending: str = ""


# ───────── context helpers ─────────

def _money(v: float) -> str:
    return ("−$" if v < 0 else "$") + f"{abs(v):,.2f}"


def _smoney(v: float) -> str:
    return "$0.00" if abs(v) < 0.005 else ("+$" if v > 0 else "−$") + f"{abs(v):,.2f}"


def _when(c: P.Ctx) -> dict:
    """The effective moments, from the exchange calendar and the clock."""
    today = c.today
    is_session = today in cal.sessions_between(today, today)
    hm = c.now.hour * 60 + c.now.minute
    # the next 19:15 ET submit: tonight if it hasn't run yet, else the next session's
    submit_day = today if is_session and hm < 19 * 60 + 15 else cal.next_session(today)
    cycle_a_day = today if is_session and hm < 17 * 60 + 5 else cal.next_session(today)
    open_after_submit = cal.next_session(submit_day)
    tonight = submit_day == today
    return {
        "submit_day": submit_day,
        "submit": ("Tonight’s" if tonight else P.wd_label(submit_day)) + " 19:15 ET submit",
        "fills": P.wd_label(open_after_submit) + " 09:30 ET open",
        "cycle_a": "Next Cycle A, " + P.wd_label(cycle_a_day) + " 17:05 ET",
        "cycle_a_day": cycle_a_day,
        "open_day": open_after_submit,
    }


def _book(c: P.Ctx) -> dict[str, dict]:
    """Holdings the commands act on: the account in paper/live (gateway), the twin in Ghost."""
    acct = getattr(c, "account_positions", None)
    if acct:
        return acct
    return {s: {"shares": int(p.get("shares") or 0), "price": float(p.get("price") or 0), "avg_cost": float(p.get("avg_cost") or 0)}
            for s, p in c.positions.items()}


def _intents(c: P.Ctx) -> list[dict]:
    return P.pending(c)["intents"]


def _oi(o: dict, tag: str) -> dict:
    return {"side": "buy" if o["side"] == "BUY" else "sell", "sideL": o["side"], "s": o["symbol"], "q": o["qtyLabel"], "v": _money(o["estValue"]), "tag": tag}


def _state_label(c: P.Ctx) -> str:
    return {"running": "RUNNING", "paused": "ENTRIES PAUSED", "held": "NIGHT HELD", "halted": "HALTED", "stopped": "STOPPED"}[c.trading]


def _equity(c: P.Ctx) -> float:
    return float(c.twin.get("equity_final") or 1.0)


# ───────── the action catalogue ─────────

def _define(c: P.Ctx, action: str, p: dict, schema) -> Def:
    ctl = schema.normalize(copy.deepcopy(c.s.controls))
    new = copy.deepcopy(ctl)
    w = _when(c)
    book = _book(c)
    intents = _intents(c)
    live = [o for o in intents if not o.get("guardrail")]
    ghost = c.env == "ghost"
    sym = (p.get("symbol") or "").upper() or None
    h = book.get(sym) if sym else None
    errs: list[str] = []
    st = _state_label(c)

    def held_check():
        if not sym:
            errs.append("choose a holding")
        elif not h:
            errs.append(f"{sym} is not held")

    if action == "stop":
        new["kill"] = True
        d = Def("STOP TRADING", "Kill switch. Cancels open orders now and freezes every later cycle.", True, "STOP TRADING",
                "Immediate — open orders canceled now; Cycle A, submit and Cycle B frozen until you resume", "Immediate", "control: kill=true",
                rows=[{"k": "Trading state", "a": st, "b": "STOPPED (kill)"}, {"k": "controls.kill", "a": str(ctl["kill"]).lower(), "b": "true"},
                      {"k": "Next submit", "a": f"{len(live)} orders", "b": "nothing sent"}],
                canceled=[_oi(o, "cancel") for o in live], proceeds="— no positions are sold", pnl="$0.00 locked in",
                drift="The account freezes while the Model keeps trading; drift grows each session",
                fid="Trading halts; the twin keeps running for comparison. Every stopped session widens the gap to the evaluated record.",
                word="STOP", immediate=("cancel_all", {}), pending="kill = true · read by every cycle until resumed")
    elif action == "flatten":
        new["kill"] = True
        proceeds = sum(v["shares"] * v["price"] for v in book.values())
        pnl = sum((v["price"] - v["avg_cost"]) * v["shares"] for v in book.values())
        d = Def("Stop & flatten", "Kill switch plus a market-on-open sell of every position.", True, "STOP & FLATTEN",
                f"Kill: immediate · sells: {w['fills']} (market on open)", "Immediate + next open", "control: kill=true + flatten",
                rows=[{"k": "Trading state", "a": st, "b": "STOPPED + FLATTEN"}, {"k": "Positions", "a": f"{len(book)} names", "b": "0 names · 100% cash"}],
                added=[{"side": "sell", "sideL": "SELL", "s": s, "q": f"{v['shares']} sh", "v": _money(v["shares"] * v["price"]), "tag": "flatten"} for s, v in sorted(book.items())],
                canceled=[_oi(o, "cancel") for o in live], proceeds=_money(proceeds) + " at last close, before slippage",
                pnl=_smoney(pnl) + " unrealized becomes realized", drift="Account 0% invested vs the Model — maximum drift",
                fid="Large deviation: the account leaves the evaluated path entirely. Typing FLATTEN is required.",
                word="FLATTEN", immediate=("flatten", {}), pending=f"kill = true · flatten {len(book)} positions at the open")
    elif action == "pause":
        new["pause_entries"] = True
        buys = [o for o in live if o["side"] == "BUY" and o["source"] == "agent"]
        d = Def("Pause entries", "Blocks new buys. Sells, stops and forced exits still flow.", False, "Pause entries",
                w["submit"] + " re-checks controls.json — buys blocked from then", w["submit"], "control: pause_entries=true",
                rows=[{"k": "controls.pause_entries", "a": str(ctl["pause_entries"]).lower(), "b": "true"}, {"k": "Trading state", "a": st, "b": "ENTRIES PAUSED"}],
                blocked=[_oi(o, "pause_entries") for o in buys], drift=_money(sum(o["estValue"] for o in buys)) + " more cash in the account than the Model",
                fid="Declared deviation: labelled \"explained\" in the drift report, not a breach.", pending="pause_entries = true")
        if ctl["pause_entries"]:
            errs.append("entries are already paused")
    elif action == "resume_entries":
        new["pause_entries"] = False
        d = Def("Resume entries", "Lets the agent open new positions again.", False, "Resume entries", w["submit"] + " — buys are sent again", w["submit"],
                "control: pause_entries=false", rows=[{"k": "controls.pause_entries", "a": "true", "b": "false"}, {"k": "Trading state", "a": st, "b": "RUNNING"}],
                drift="Returns toward the Model", pending="pause_entries = false")
        if not ctl["pause_entries"]:
            errs.append("entries are not paused")
    elif action == "resume":
        new["kill"] = False
        d = Def("Resume trading", "Clears the kill switch. The preflight checklist passed.", False, "Resume trading", w["cycle_a"], w["cycle_a"],
                "control: kill=false", rows=[{"k": "controls.kill", "a": "true", "b": "false"}, {"k": "Trading state", "a": "STOPPED", "b": "RUNNING"}],
                drift="The next Cycle A re-aligns the account with the Model; rotation orders may be large", pending="kill = false")
        if not ctl["kill"]:
            errs.append("trading is not stopped")
        pf = preflight(c, p.get("ticks") or {}, p.get("note") or "")
        if not pf["ok"]:
            errs.append("the preflight checklist does not pass: " + "; ".join(x["l"] for x in pf["checks"] if not x["pass"]))
    elif action == "force_exit":
        held_check()
        if sym and sym not in new["excluded_symbols"]:
            new["excluded_symbols"] = sorted(new["excluded_symbols"] + [sym])
        if sym in new["locked_symbols"]:
            new["locked_symbols"] = [x for x in new["locked_symbols"] if x != sym]
        v = (h or {"shares": 0, "price": 0, "avg_cost": 0})
        wt = v["shares"] * v["price"] / _equity(c) * 100
        d = Def(f"Force exit {sym}", f"Adds {sym} to excluded_symbols: sells the whole position at the next open and blocks re-entry.", True, f"Force exit {sym}",
                f"{w['submit']} · fills {w['fills']}", w["submit"], f"control: excluded_symbols += {sym} (forced exit)",
                rows=[{"k": "excluded_symbols", "a": f"{len(ctl['excluded_symbols'])} names", "b": f"{len(new['excluded_symbols'])} names (+{sym})"},
                      {"k": "Position", "a": f"{v['shares']} sh · {wt:.1f}%", "b": "0 sh"}],
                added=[{"side": "sell", "sideL": "SELL", "s": sym, "q": f"{v['shares']} sh (all)", "v": _money(v["shares"] * v["price"]), "tag": "Forced exit"}],
                canceled=[_oi(o, "replaced") for o in live if o["symbol"] == sym],
                proceeds=_money(v["shares"] * v["price"]) + f" at last close {_money(v['price'])}",
                pnl=_smoney((v["price"] - v["avg_cost"]) * v["shares"]) + " locked in",
                drift=f"Explained deviation: the Model keeps {sym}; the account moves {wt:.1f}% to cash",
                fid="The twin's universe stays frozen (decision fidelity). The exclusion acts only through controls.json and is labelled \"explained\" in drift.",
                word=sym, pending=f"excluded_symbols += {sym} (forced exit)")
        if sym in ctl["excluded_symbols"]:
            errs.append(f"{sym} is already excluded")
    elif action == "unexclude":
        if not sym or sym not in ctl["excluded_symbols"]:
            errs.append(f"{sym or 'the name'} is not excluded")
        new["excluded_symbols"] = [x for x in ctl["excluded_symbols"] if x != sym]
        d = Def(f"Remove {sym} from exclusions", f"Buys of {sym} are allowed again if the agent ranks it.", False, "Remove exclusion", w["cycle_a"], w["cycle_a"],
                f"control: excluded_symbols -= {sym}", rows=[{"k": "excluded_symbols", "a": f"{len(ctl['excluded_symbols'])} names", "b": f"{len(new['excluded_symbols'])} names"}],
                fid="Only remove an exclusion after a documented ruling or a re-screen reversal.", pending=f"excluded_symbols -= {sym}")
    elif action == "lock":
        held_check()
        if sym in ctl["excluded_symbols"]:
            errs.append(f"{sym} is excluded; an exclusion cannot be locked")
        if sym in ctl["locked_symbols"]:
            errs.append(f"{sym} is already locked")
        new["locked_symbols"] = sorted(set(ctl["locked_symbols"]) | ({sym} if sym else set()))
        d = Def(f"Lock {sym}", f"The agent may neither sell nor add to {sym}. The position is frozen.", False, f"Lock {sym}",
                w["submit"] + f" — the submit skips {sym} with reason \"locked\"", w["submit"], f"control: locked_symbols += {sym}",
                rows=[{"k": "locked_symbols", "a": ", ".join(ctl["locked_symbols"]) or "none", "b": ", ".join(new["locked_symbols"])},
                      {"k": f"{sym} managed by", "a": "Agent", "b": "Owner (locked)"}],
                blocked=[_oi(o, "locked") for o in intents if o["symbol"] == sym and o["source"] == "agent"],
                drift=f"If the Model exits {sym}, the account keeps it (declared deviation)",
                fid=f"Stops on {sym} will not fire in the account while it is locked. The Model keeps its own stop.", pending=f"locked_symbols += {sym}")
    elif action == "unlock":
        if sym not in ctl["locked_symbols"]:
            errs.append(f"{sym or 'the name'} is not locked")
        new["locked_symbols"] = [x for x in ctl["locked_symbols"] if x != sym]
        d = Def(f"Unlock {sym}", f"Hands {sym} back to the agent.", False, f"Unlock {sym}", w["submit"], w["submit"], f"control: locked_symbols -= {sym}",
                rows=[{"k": "locked_symbols", "a": ", ".join(ctl["locked_symbols"]) or "none", "b": ", ".join(new["locked_symbols"]) or "none"}],
                drift=f"The account re-converges with the Model on {sym}", pending=f"locked_symbols -= {sym}")
    elif action == "trim":
        held_check()
        pct = int(p.get("pct") or 50)
        if pct not in (25, 50, 75, 100):
            errs.append("trim by 25, 50, 75 or 100%")
        v = (h or {"shares": 0, "price": 0, "avg_cost": 0})
        q = max(1, round(v["shares"] * pct / 100)) if v["shares"] else 0
        mid = "m-" + hashlib.sha1(f"{sym}|{pct}|{w['submit_day']}".encode()).hexdigest()[:10]
        mo = {"id": mid, "symbol": sym, "side": "sell", "qty": q, "fraction": None,
              "reason": (p.get("reason") or "manual trim by the owner").strip(), "created_by": p.get("actor") or "owner@console",
              "created": c.today, "expires": w["submit_day"]}
        new["manual_orders"] = [m for m in ctl["manual_orders"] if m.get("symbol") != sym] + [mo]
        wt0 = v["shares"] * v["price"] / _equity(c) * 100
        wt1 = (v["shares"] - q) * v["price"] / _equity(c) * 100
        d = Def(f"Trim {sym}", "Manual sell of part of the position at the next open.", True, f"Sell {q} {sym}",
                f"{w['submit']} · fills {w['fills']} · expires if unsent", w["submit"], f"control: manual_orders += SELL {q} {sym}",
                rows=[{"k": f"{sym} shares", "a": str(v["shares"]), "b": str(v["shares"] - q)}, {"k": "Weight", "a": f"{wt0:.1f}%", "b": f"{wt1:.1f}%"}],
                added=[{"side": "sell", "sideL": "SELL", "s": sym, "q": f"{q} sh", "v": _money(q * v["price"]), "tag": "Manual · owner"}],
                proceeds=_money(q * v["price"]) + " at last close", pnl=_smoney((v["price"] - v["avg_cost"]) * q) + " locked in",
                drift=f"Explained deviation: the account holds {v['shares'] - q} vs Model {v['shares']}",
                fid="controls.manual_orders[] — sized from the holding and capped at the position at submit time.",
                word=sym, pending=f"manual_orders += SELL {q} {sym}")
    elif action == "cancel_manual":
        gone = [m for m in ctl["manual_orders"] if m.get("id") == p.get("id") or m.get("symbol") == sym]
        if not gone:
            errs.append("no such manual order")
        new["manual_orders"] = [m for m in ctl["manual_orders"] if m not in gone]
        d = Def(f"Cancel manual order · {sym or (gone[0]['symbol'] if gone else '')}", "Removes the queued manual sell before it is submitted.", False, "Cancel order",
                w["submit"], w["submit"], "control: manual_orders -= " + ", ".join(m["id"] for m in gone),
                rows=[{"k": "manual_orders", "a": f"{len(ctl['manual_orders'])} queued", "b": f"{len(new['manual_orders'])} queued"}],
                canceled=[{"side": "sell", "sideL": "SELL", "s": m["symbol"], "q": f"{m.get('qty') or ''} sh", "v": "—", "tag": "cancel"} for m in gone],
                pending="manual_orders −= " + ", ".join(m["symbol"] for m in gone))
    elif action == "gross":
        cap = p.get("cap")
        if cap is not None and not (isinstance(cap, (int, float)) and 10 <= cap <= 100):
            errs.append("the cap must be between 10% and 100%, or off")
        new["gross_cap"] = round(cap / 100, 4) if cap is not None else None
        pos_val = sum(v["shares"] * v["price"] for v in book.values())
        exp = pos_val / _equity(c) * 100
        d = Def("Remove the gross exposure cap" if cap is None else f"Gross exposure cap {cap}%", "Caps total invested weight. New buys are trimmed or blocked to fit.",
                False, "Apply cap", w["cycle_a"], w["cycle_a"], f"control: gross_cap={'off' if cap is None else str(cap) + '%'}",
                rows=[{"k": "controls.gross_cap", "a": "off" if ctl["gross_cap"] is None else f"{round(ctl['gross_cap'] * 100)}%", "b": "off" if cap is None else f"{cap}%"},
                      {"k": "Exposure now", "a": f"{exp:.1f}%", "b": (f"over the cap → no new buys until below {cap}%" if cap is not None and cap < exp else "within the cap")}],
                blocked=[_oi(o, "gross_cap") for o in live if o["side"] == "BUY"] if cap is not None and cap < exp else [],
                drift="The account holds more cash than the Model" if cap is not None and cap < exp else "None",
                fid="A gross cap is a declared deviation from EXP_MAX.", pending="gross_cap = " + ("off" if cap is None else f"{cap}%"))
    elif action == "adapt":
        on = not ctl["pause_adapt"]
        new["pause_adapt"] = on
        new["pause_adapt_since"] = w["cycle_a_day"] if on else None
        d = Def("Pause adapt()" if on else "Resume adapt()", "Freezes the agent's parameters; the next adaptation will not fire." if on else "Lets adapt() fire again every 63 sessions.",
                on, "Pause adapt()" if on else "Resume adapt()", w["cycle_a"], w["cycle_a"], f"control: pause_adapt={str(on).lower()}",
                rows=[{"k": "controls.pause_adapt", "a": str(not on).lower(), "b": str(on).lower()}],
                fid=("This changes the twin path: from this session on it is no longer comparable with the frozen OOS record." if on
                     else "Resuming re-joins the pre-registered learning schedule."),
                word="PAUSE" if on else None, pending=f"pause_adapt = {str(on).lower()}")
    elif action == "release":
        s_rec = c.s.cycles.get(f"{c.asof}-S") or {}
        if s_rec.get("status") != "held":
            errs.append("there is no held night to release")
        d = Def("Release tonight’s submission", "Approves the soft-held night and runs the submit with --approved.", False, "Release night",
                "Now — the submit runs with --approved; orders fill at " + w["fills"], "Now", "command: release held night",
                rows=[{"k": "Night", "a": "HELD (approval mode)", "b": "RELEASED"}, {"k": "Orders sent", "a": "0", "b": str(len(live))}],
                added=[_oi(o, "submit") for o in live], blocked=[_oi(o, o.get("guardrail") or "blocked") for o in intents if o.get("guardrail")],
                fid="Hard holds — kill switch, drawdown kill and reconciliation halt — cannot be released here.",
                immediate=("dispatch", {"workflow": "live-submit.yml", "inputs": {}}))
    elif action == "clear_halt":
        halt = copy.deepcopy(c.s.halt or {})
        cause = (p.get("cause") or "").strip()
        if not halt.get("halted"):
            errs.append("there is no reconciliation halt")
        if len(cause) < 10:
            errs.append("write the cause (at least 10 characters)")
        halt.update({"halted": False, "cause": cause, "cleared_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                     "cleared_by": p.get("actor") or "owner@console"})
        diffs = (c.s.halt or {}).get("diffs") or []
        d = Def("Clear reconciliation halt", "Writes your cause into ledger/halt.json and sets halted to false.", False, "Clear halt",
                w["submit"], w["submit"], "control: halt cleared",
                rows=[{"k": "halt.json", "a": "halted: true", "b": "halted: false · cause recorded"}] +
                     [{"k": x.get("symbol"), "a": f"expected {x.get('expected')} · actual {x.get('actual')}", "b": "accepted (Model keeps its count)"} for x in diffs[:4]],
                fid="Clearing does not fix the share difference; it lets the submit run again. The cause stays in the audit log.",
                halt=halt, pending="halt.json halted = false (cause recorded)")
    elif action == "rerun":
        step = p.get("step") or "Cycle A"
        wf = {"Cycle A": "live-cycle-a.yml", "Submit": "live-submit.yml", "Cycle B": "live-cycle-b.yml"}.get(step)
        if not wf:
            errs.append("step must be Cycle A, Submit or Cycle B")
        d = Def(f"Re-run {step}", "workflow_dispatch of the step. Steps are idempotent: a re-run never duplicates orders.", False, f"Re-run {step}",
                "Now — the run starts within about a minute", "Now", f"command: re-run {step}",
                rows=[{"k": "Step", "a": f"{step} · latest session", "b": "dispatched"}], drift="—",
                immediate=("dispatch", {"workflow": wf, "inputs": {}}))
    else:
        raise ControlError(400, f"unknown action {action!r}")

    d.errors = errs + (schema.validate(new) if not errs else [])
    if d.controls is None and action not in ("release", "rerun", "clear_halt"):
        d.controls = new
    return d


# ───────── preflight (docs/08 §7.3) ─────────

def preflight(c: P.Ctx, ticks: dict, note: str) -> dict:
    halt = (c.s.halt or {}).get("halted")
    b = c.s.latest_cycle("B") or {}
    recon_ok = (b.get("reconcile") or {}).get("status", "ok") != "break"
    a_ok = bool(c.last_a and c.last_a.get("status") == "ok")
    eq = c.twin.get("equity") or [1]
    dd = (eq[-1] / max(eq) - 1) * 100 if eq else 0.0
    kill_line = float(c.s.config.get("KILL_DD_LIMIT") or -0.25) * 100
    alerts = getattr(c, "open_p1", [])
    broker_ok = c.env == "ghost" or bool(getattr(c, "broker_ok", False))
    ctl = c.s.controls or {}
    dev = []
    if ctl.get("locked_symbols"):
        dev.append("locked: " + ", ".join(ctl["locked_symbols"]))
    if ctl.get("excluded_symbols"):
        dev.append(f"excluded: {len(ctl['excluded_symbols'])} names")
    if ctl.get("manual_orders"):
        dev.append(f"manual orders: {len(ctl['manual_orders'])}")
    checks = [
        {"id": "halt", "l": "No reconciliation halt", "s": "fail" if halt else "pass", "d": "ledger/halt.json · halted: " + ("true" if halt else "false")},
        {"id": "recon", "l": "Last reconciliation OK", "s": "pass" if recon_ok else "fail", "d": f"Cycle B {P.wd_label(b['asof'])} · {(b.get('reconcile') or {}).get('status', b.get('status', '—'))}" if b else "no Cycle B yet"},
        {"id": "cyca", "l": "Last Cycle A OK — or acknowledged with a note", "s": "pass" if a_ok else "man", "note": not a_ok,
         "d": "ok" if a_ok else ("Failed " + P.wd_label(c.last_a["asof"]) + " — " + (c.failing or {}).get("reason", c.last_a.get("status", "")) if c.last_a else "no Cycle A yet")},
        {"id": "p1", "l": "No open P1 alerts", "s": "fail" if alerts else "pass", "d": (f"{len(alerts)} open: " + "; ".join(a["title"] for a in alerts)) if alerts else "none open", "fix": bool(alerts)},
        {"id": "dd", "l": "Drawdown above the kill line", "s": "pass" if dd > kill_line else "fail", "d": f"{dd:.1f}% from peak · kill line {kill_line:.0f}%"},
        {"id": "broker", "l": "Broker reachable", "s": "pass" if broker_ok else "fail", "d": "Ghost — rehearsal, no broker needed" if c.env == "ghost" else ("reachable" if broker_ok else "gateway unreachable")},
        {"id": "ack", "l": "Acknowledge the deviations that will apply", "s": "man", "d": " · ".join(dev) or "none"},
    ]
    for x in checks:
        x["pass"] = x["s"] == "pass" or (x["s"] == "man" and bool(ticks.get(x["id"])) and (not x.get("note") or len(note.strip()) >= 8))
    return {"checks": checks, "ok": all(x["pass"] for x in checks), "n": sum(x["pass"] for x in checks)}


# ───────── preview & apply ─────────

def _versions(writer) -> dict[str, str]:
    return {CONTROLS_REL: blob_version(writer.read(CONTROLS_REL)), HALT_REL: blob_version(writer.read(HALT_REL))}


def _stable(doc: dict | None) -> dict | None:
    """The change without the free-text fields the apply step adds (reason, actor, time)."""
    if doc is None:
        return None
    doc = copy.deepcopy(doc)
    for m in doc.get("manual_orders") or []:
        m.pop("reason", None)
        m.pop("created_by", None)
    for k in ("cause", "cleared_utc", "cleared_by"):
        doc.pop(k, None)
    return doc


def _view(d: Def, action: str, p: dict, base: dict) -> dict:
    payload = json.dumps({"action": action, "params": {k: v for k, v in p.items() if k not in ("reason", "actor", "cause", "note", "ticks")}, "base": base,
                          "controls": _stable(d.controls), "halt": _stable(d.halt)}, sort_keys=True, default=str)
    return {
        "action": action, "title": d.title, "sub": d.sub, "danger": d.danger, "verb": d.verb, "eff": d.eff, "effS": d.effS,
        "rows": d.rows, "added": d.added, "blocked": d.blocked, "canceled": d.canceled, "proceeds": d.proceeds, "pnl": d.pnl,
        "drift": d.drift, "fid": d.fid, "word": d.word, "errors": d.errors, "pending": d.pending,
        "steps": _step_labels(d), "previewHash": hashlib.sha256(payload.encode()).hexdigest()[:24],
    }


def _step_labels(d: Def) -> list[str]:
    out = ["Validated against the controls.json v2 schema"]
    if d.controls is not None or d.halt is not None:
        out += ["Committed to the ledger", "Pushed · read by the next step"]
    if d.immediate:
        kind = d.immediate[0]
        out.append({"cancel_all": "Broker: cancel all open orders", "flatten": "Broker: cancel all + market-on-open sell of every position",
                    "dispatch": "Dispatched " + str(d.immediate[1].get("workflow"))}[kind])
    return out


def preview(c: P.Ctx, writer, action: str, p: dict) -> dict:
    schema = _schema(c.settings.pkg)
    d = _define(c, action, p, schema)
    return _view(d, action, p, _versions(writer))


def _message(d: Def, actor: str, reason: str, category: str, action_id: str, eff: str) -> str:
    return (f"{d.summary}\n\nActor: {actor}\nReason: [{category}] {reason.strip()}\nEffective: {eff}\n"
            f"Console-Action-Id: {action_id}\n")


def _dump(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def apply(c: P.Ctx, writer, dispatcher: Dispatcher, gateway, action: str, p: dict, *, actor: str, reason: str, category: str,
          preview_hash: str, typed: str) -> dict:
    schema = _schema(c.settings.pkg)
    if len((reason or "").strip()) < 10:
        raise ControlError(400, "A reason of at least 10 characters is required.")
    if category not in CATEGORIES:
        raise ControlError(400, "Choose a category: " + ", ".join(CATEGORIES))
    action_id = new_action_id()
    steps: list[dict] = []
    sha = None
    p = {**p, "reason": reason, "actor": actor}
    for attempt in range(3):
        d = _define(c, action, p, schema)
        base = _versions(writer)
        view = _view(d, action, p, base)
        if view["previewHash"] != preview_hash:
            raise ControlError(409, "The state changed since the preview. Review the new impact.", view)
        if d.word and (typed or "").strip().upper() != d.word.upper():
            raise ControlError(400, f"Type {d.word} to confirm.")
        if d.errors:
            raise ControlError(422, "; ".join(d.errors), view)
        steps = [{"l": "Validated against the controls.json v2 schema", "st": "ok"}]
        files = {}
        if d.controls is not None:
            files[CONTROLS_REL] = _dump(d.controls)
        if d.halt is not None:
            files[HALT_REL] = json.dumps(d.halt, indent=1) + "\n"
        try:
            if files:
                sha = writer.commit(files, _message(d, actor, reason, category, action_id, d.eff), base)
                steps.append({"l": f"Committed {sha[:7]} to the ledger", "st": "ok"})
                steps.append({"l": writer.push_label(), "st": "ok"})
            break
        except Conflict:
            if attempt == 2:
                steps.append({"l": "Push rejected — the ledger moved; 3 attempts failed", "st": "fail"})
                return _finish(c, steps, False, action, p, actor, reason, category, d, sha, action_id)
            time.sleep(0.5)
            continue
        except WriteError as e:
            steps.append({"l": f"Write failed — {e}", "st": "fail"})
            return _finish(c, steps, False, action, p, actor, reason, category, d, sha, action_id)
    # immediate command (after the controls change is safely committed)
    if d.immediate:
        kind, args = d.immediate
        try:
            if kind in ("cancel_all", "flatten"):
                if c.env == "ghost":
                    steps.append({"l": f"Ghost: {kind.replace('_', ' ')} recorded — no broker, nothing open", "st": "ok"})
                elif gateway is not None:
                    res = gateway.command(kind, reason=reason, actor=actor, action_id=action_id)
                    ok = res.get("status") in ("ok", "ghost-noop")
                    steps.append({"l": f"Broker {kind}: {res.get('status')}" + (f" · {len((res.get('flatten') or {}).get('orders') or [])} sells accepted" if kind == "flatten" else ""),
                                  "st": "ok" if ok else "fail"})
                    if not ok:
                        return _finish(c, steps, False, action, p, actor, reason, category, d, sha, action_id)
                else:
                    dispatcher.dispatch("live-control.yml", {"action": kind, "reason": reason, "actor": actor, "action_id": action_id})
                    steps.append({"l": "Dispatched live-control.yml — the broker's answer lands in ledger/commands", "st": "ok"})
            else:
                dispatcher.dispatch(args["workflow"], args.get("inputs") or {})
                steps.append({"l": f"Dispatched {args['workflow']}", "st": "ok"})
        except Exception as e:  # noqa: BLE001
            steps.append({"l": f"Immediate command failed — {e}"[:240], "st": "fail"})
            return _finish(c, steps, False, action, p, actor, reason, category, d, sha, action_id)
    return _finish(c, steps, True, action, p, actor, reason, category, d, sha, action_id)


def _finish(c, steps, ok, action, p, actor, reason, category, d: Def, sha, action_id) -> dict:
    r0 = d.rows[0] if d.rows else None
    ev = {"id": action_id, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"), "actor": actor, "action": d.title,
          "params": {k: v for k, v in p.items() if k not in ("reason", "actor")}, "reason": f"[{category}] {reason.strip()}", "category": category,
          "effective": d.effS, "before_after": f"{r0['k']}: {r0['a']} → {r0['b']}" if r0 else "—", "applied": ok, "sha": sha, "steps": steps}
    c.settings_store.record_control(ev)
    return {"applied": ok, "steps": steps, "sha": sha, "actionId": action_id, "title": d.title, "eff": d.eff, "pending": d.pending}
