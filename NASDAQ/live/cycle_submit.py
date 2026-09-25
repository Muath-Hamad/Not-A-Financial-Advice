"""Submit step: send the ledgered orders to the broker (docs/07), 19:15 ET.

Cycle A decides at 17:00 ET and writes orders/<asof>.json. Alpaca only
accepts on-open orders between 19:00 and 09:28 ET, so submission is its own
scheduled step. It sends what Cycle A ledgered, with three adjustments that
only the account can inform:

* sells are sized from the shares the account actually holds,
* account-held names on the exclusion list are force-exited,
* buys are trimmed if they would need more cash than tonight's sells free.

Hard holds (kill switch, drawdown kill, reconciliation halt, a blocked
account, an account that does not match the twin's book) stop the night and
file a P1. Soft holds (approval mode, a portfolio-level guardrail) wait for
a human: a manual run with --approved releases them. A held night stays held
for the scheduled slots; only a manual run re-evaluates it.

Ghost mode runs the same logic against the twin's book and records what it
WOULD send, so the path is exercised before any key exists. Every run that
finds a Cycle A decision leaves cycles/<asof>-S.json; submissions carry
Alpaca's order id, which Cycle B uses to trace each fill back to its ledger
entry.

Usage:
  python NASDAQ/live/cycle_submit.py            # scheduled (19:15 ET slot)
  python NASDAQ/live/cycle_submit.py --smoke    # ledger/smoke/, no alerts, no window check
  python NASDAQ/live/cycle_submit.py --approved # manual run: releases a soft hold
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import alert, step_summary  # noqa: E402
from broker import BrokerError, get_broker  # noqa: E402
from execution import (broker_holdings, drift_vs_twin, in_submit_window,  # noqa: E402
                       plan_submissions)


APPROVAL_HOLD = "approval mode: waiting for a manual run of the submit workflow"


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="ledger/smoke/, no alerts, no time-window check")
    ap.add_argument("--approved", action="store_true",
                    help="a human released tonight's batch (approval mode, "
                         "portfolio guardrail holds)")
    ap.add_argument("--asof", help="override the session (tests and drills)")
    args = ap.parse_args()
    if args.smoke:
        os.environ["LIVE_SMOKE"] = "1"
    ledger = config.LEDGER / "smoke" if args.smoke else config.LEDGER
    mode = os.environ.get("LIVE_MODE", "ghost")

    from calendar_util import latest_completed_session, now_et
    now = now_et()
    if not args.smoke and not in_submit_window(now):
        print(f"{now:%H:%M} ET is outside Alpaca's on-open window "
              f"(19:00-09:28 ET); nothing sent")
        return 0
    asof = args.asof or latest_completed_session(now)
    if args.smoke and not args.asof:
        # drill against the newest smoke decision, whatever day it was made
        smoke_a = sorted((ledger / "cycles").glob("*-A.json"))
        if smoke_a:
            asof = smoke_a[-1].name[:10]
    s_path = ledger / "cycles" / f"{asof}-S.json"
    prior = None if args.smoke else load(s_path)  # smoke drills are re-runnable
    if prior and prior.get("status") in ("submitted", "ghost_recorded", "nothing_to_send",
                                         "held_by_cycle_a"):
        print(f"submit step for {asof} already recorded ({prior['status']}); nothing to do")
        return 0
    if prior and prior.get("status") == "held" and not args.approved:
        print(f"submit step for {asof} is held ({'; '.join(prior.get('holds', []))}); "
              f"a manual run of the submit workflow releases it")
        return 0

    record: dict = {"cycle": "S", "asof": asof, "mode": mode, "ts_utc": utcnow(),
                    "smoke": bool(args.smoke)}

    # ---- what did Cycle A decide? ----------------------------------------
    a_rec = load(ledger / "cycles" / f"{asof}-A.json")
    orders_file = load(ledger / "orders" / f"{asof}.json")
    if not a_rec:
        # Cycle A may only be late (queued cron, slow fetch): record nothing so
        # the next slot retries. The dead-man switch covers a cycle that never ran.
        print(f"submit {asof}: no Cycle A record yet; a later slot will retry")
        return 0
    if a_rec.get("status") != "ok" or not orders_file:
        record["status"] = "held_by_cycle_a"
        record["cycle_a_status"] = a_rec.get("status")
        write_json(s_path, record)
        print(f"submit {asof}: Cycle A status {a_rec.get('status')!r}; nothing to send")
        return 0

    controls = json.loads((LIVE / "controls.json").read_text())
    excluded = set(controls.get("excluded_symbols") or [])
    halt = load(ledger / "halt.json", {}) or {}
    holds = []
    if controls.get("kill"):
        holds.append("kill switch on (controls.json)")
    if a_rec.get("kill_triggered"):
        holds.append(f"drawdown kill triggered ({a_rec.get('drawdown_from_peak')})")
    if halt.get("halted"):
        holds.append(f"reconciliation halt since {halt.get('since')}: {halt.get('reason')}")

    # Soft holds wait for a human: a manual run (--approved) releases them.
    # Approval mode (pilot weeks) holds every batch; a portfolio-level
    # guardrail (daily turnover, gross cap) holds the night it trips.
    soft = []
    if os.environ.get("APPROVAL_MODE", "").lower() == "true" and not args.smoke:
        soft.append(APPROVAL_HOLD)
    for v in (a_rec.get("guardrails") or {}).get("violations", []):
        if not v.get("code"):
            soft.append(f"portfolio guardrail {v['rule']}: {v.get('detail')}")
    if args.approved and soft:
        record["released_by_manual_run"] = soft
        soft = []

    # ---- the account's view ----------------------------------------------
    twin = load(ledger / "twin" / "twin_latest.json", {}) or {}
    twin_pos = twin.get("positions", {})
    entries = orders_file.get("orders", [])
    closes = {e["code"]: e.get("ref_close") for e in entries}
    for code, p in twin_pos.items():
        closes.setdefault(code, p.get("price"))

    broker = get_broker()
    if broker.mode == "ghost":
        # rehearse against the twin's own book: what a matching account would get
        held = {c: int(p["shares"]) for c, p in twin_pos.items()}
        cash = float(twin.get("cash_final", 0.0))
        equity = float(twin.get("equity_final", 0.0))
        record["account"] = {"source": "twin (ghost rehearsal)", "cash": cash, "equity": equity}
    else:
        try:
            acct = broker.account()
            held = broker_holdings(broker.positions())
        except Exception as exc:  # noqa: BLE001
            record["status"] = "broker_unreachable"
            record["error"] = str(exc)[:500]
            write_json(s_path, record)
            alert("P1", f"Submit {asof}: broker unreachable",
                  f"{exc}"[:800] + "\nNothing was sent. Re-run the submit workflow "
                  "before 09:28 ET, or the day is skipped.")
            return 0
        cash = float(acct.get("cash") or 0.0)
        equity = float(acct.get("equity") or 0.0)
        record["account"] = {k: acct.get(k) for k in
                             ("status", "cash", "equity", "buying_power",
                              "trading_blocked", "account_blocked", "multiplier")}
        if acct.get("trading_blocked") or acct.get("account_blocked"):
            holds.append("account blocked by the broker")
        # start-in-step guard: the account must describe the twin's portfolio
        drift = drift_vs_twin(twin_pos, held, closes, equity or 1.0, excluded)
        record["drift_at_submit"] = drift
        if (drift.get("gap_share") or 0.0) > config.START_MISMATCH_MAX:
            holds.append(
                f"account and twin books differ by {drift['gap_share']:.0%} of equity "
                f"(limit {config.START_MISMATCH_MAX:.0%}); check that LIVE_START was reset "
                f"to the first paper session")
    record["positions_before"] = held

    plan = plan_submissions(asof, entries, held, closes, cash, equity, excluded,
                            float(config.TWIN_SLIPPAGE))
    record["plan"] = plan

    if holds or soft:
        record["status"] = "held"
        record["holds"] = holds + soft
        write_json(s_path, record)
        level = "P2" if (holds + soft) == [APPROVAL_HOLD] else "P1"
        release = "" if holds else ("\nA manual run of the live-submit workflow releases "
                                    "it (before 09:28 ET).")
        alert(level, f"Submit {asof}: {len(plan['submit'])} order(s) held",
              "\n".join(f"- {h}" for h in holds + soft) + release)
        return 0

    if not plan["submit"]:
        record["status"] = "nothing_to_send"
        write_json(s_path, record)
        print(f"submit {asof}: nothing to send")
        return 0

    # ---- send ------------------------------------------------------------
    results, failures = [], []
    for o in plan["submit"]:
        try:
            r = broker.submit_moo(o["code"], o["side"], o["qty"], o["client_order_id"])
            results.append({**o, "broker_id": r.get("id"), "broker_status": r.get("status")})
        except BrokerError as exc:
            if exc.status == 422 and "client_order_id" in exc.body:
                # already accepted on an earlier attempt: re-read it, do not resend
                prior_order = broker.order_by_client_id(o["client_order_id"]) or {}
                results.append({**o, "broker_id": prior_order.get("id"),
                                "broker_status": prior_order.get("status"), "resumed": True})
            else:
                failures.append({**o, "error": str(exc)[:300]})
        except Exception as exc:  # noqa: BLE001
            failures.append({**o, "error": f"{type(exc).__name__}: {exc}"[:300]})

    record["submissions"] = results
    record["failures"] = failures
    if broker.mode == "ghost":
        record["status"] = "ghost_recorded"
    else:
        record["status"] = "submitted" if not failures else "partial"
    write_json(s_path, record)
    if failures:
        alert("P1", f"Submit {asof}: {len(failures)} order(s) rejected",
              "\n".join(f"- {f['code']} {f['side']} {f['qty']}: {f['error']}" for f in failures))
    if plan["adjusted"]:
        alert("P2", f"Submit {asof}: {len(plan['adjusted'])} buy(s) trimmed to available cash",
              json.dumps(plan["adjusted"]))
    step_summary(f"### Submit — {asof} ({mode})\n\n"
                 f"{len(results)} sent, {len(failures)} rejected, "
                 f"{len(plan['skipped'])} skipped, {len(plan['adjusted'])} trimmed.")
    print(f"submit {asof}: {record['status']} — {len(results)} sent, {len(failures)} failed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        alert("P1", "Submit step crashed", f"{type(exc).__name__}: {exc}"[:800])
        raise
