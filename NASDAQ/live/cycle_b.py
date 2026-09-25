"""Cycle B — the post-open reconciliation cycle (docs/05 §3), ~09:50 ET.

Ghost mode: record today's actual opening prints for every symbol ordered at
yesterday's Cycle A (the evening replay cross-checks them — the open-revision
metric), and verify the order ledger is internally consistent with the twin
state. Paper mode (Phase 2): additionally look up every order last night's
submit step sent (by our client order id), measure realized slippage against
the official open, and reconcile the account share for share: positions
before submission plus filled quantities must equal positions now. Any
unexplained difference is a P1 and sets ledger/halt.json, which stops the
submit step until a human clears it (docs/07).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import alert, step_summary  # noqa: E402
from broker import get_broker  # noqa: E402
from calendar_util import is_session, now_et, previous_session  # noqa: E402


def fetch_opens(codes: list[str], day: str) -> dict:
    """Today's opening prints via yfinance (the open auction is long done by 09:50)."""
    import yfinance as yf

    opens: dict = {}
    end = str(dt.date.fromisoformat(day) + dt.timedelta(days=1))
    for code in codes:
        symbol = "^IXIC" if code == "IXIC" else code
        try:
            h = yf.Ticker(symbol).history(start=day, end=end, auto_adjust=False)
            if h is not None and not h.empty:
                opens[code] = round(float(h["Open"].iloc[0]), 4)
            else:
                opens[code] = None
        except Exception:  # noqa: BLE001
            opens[code] = None
    return opens


def reconcile_paper(broker, ledger: Path, prev: str, today: str, record: dict) -> None:
    """Trace last night's submissions and reconcile the account (paper mode)."""
    from execution import broker_holdings, diff_positions, expected_positions

    s_rec_path = ledger / "cycles" / f"{prev}-S.json"
    if not s_rec_path.exists():
        record["reconcile"] = {"status": "no_submission_record"}
        orders_path = ledger / "orders" / f"{prev}.json"
        if orders_path.exists() and json.loads(orders_path.read_text()).get("orders"):
            alert("P1", f"Cycle B {today}: orders were ledgered for {prev} but never submitted",
                  f"live/ledger/cycles/{prev}-S.json is missing. Check the live-submit "
                  f"workflow runs; the account traded nothing at today's open.")
        return
    s_rec = json.loads(s_rec_path.read_text())
    record["submit_status"] = s_rec.get("status")
    if "positions_before" not in s_rec:
        # the submit step never read the account (broker unreachable, or no
        # decision to submit): there is no baseline to reconcile against, and
        # that night's own alert already covers it
        record["reconcile"] = {"status": "no_baseline", "submit_status": s_rec.get("status")}
        return
    before = {k: int(v) for k, v in (s_rec.get("positions_before") or {}).items()}
    fills = []
    for sub in s_rec.get("submissions", []):
        o = broker.order_by_client_id(sub["client_order_id"]) or {}
        fills.append({"symbol": sub["code"], "side": sub["side"], "qty": sub["qty"],
                      "client_order_id": sub["client_order_id"],
                      "broker_id": o.get("id") or sub.get("broker_id"),
                      "status": o.get("status"),
                      "filled_qty": int(float(o.get("filled_qty") or 0)),
                      "filled_avg_price": float(o.get("filled_avg_price") or 0) or None})
    record["fills"] = fills

    # slippage against the official opening print, signed so positive = cost
    missing_opens = sorted({f["symbol"] for f in fills} - set(record.get("opens", {})))
    if missing_opens:
        record.setdefault("opens", {}).update(fetch_opens(missing_opens, today))
    slips = []
    for f in fills:
        ref = record["opens"].get(f["symbol"])
        if f["filled_qty"] and f["filled_avg_price"] and ref:
            sign = 1 if f["side"] == "buy" else -1
            slips.append({"symbol": f["symbol"], "side": f["side"],
                          "slippage": round(sign * (f["filled_avg_price"] / ref - 1), 5)})
    record["slippage"] = slips
    if slips:
        avg = sum(s["slippage"] for s in slips) / len(slips)
        record["slippage_avg"] = round(avg, 5)
        if avg > config.SLIPPAGE_ALERT:
            alert("P2", f"Cycle B {today}: average slippage {avg:.2%} per side",
                  f"Above the {config.SLIPPAGE_ALERT:.2%} band (docs/05 §8).")

    missed = [f for f in fills if f["filled_qty"] < f["qty"]]
    record["missed"] = [{"symbol": f["symbol"], "side": f["side"], "qty": f["qty"],
                         "filled": f["filled_qty"], "status": f["status"]} for f in missed]
    if missed:
        alert("P2", f"Cycle B {today}: {len(missed)} order(s) not fully filled at the open",
              json.dumps(record["missed"]))

    # share for share: the account must equal what it held plus what filled
    actual = broker_holdings(broker.positions())
    expected = expected_positions(before, fills)
    diffs = diff_positions(expected, actual)
    record["reconcile"] = {"status": "ok" if not diffs else "break",
                           "expected": expected, "actual": actual, "diffs": diffs}
    if diffs:
        halt = {"halted": True, "since": today, "reason": "unexplained position break",
                "diffs": diffs,
                "clear": "set halted to false in live/ledger/halt.json and commit, "
                         "after the cause is written into this file"}
        (ledger / "halt.json").write_text(json.dumps(halt, indent=1))
        alert("P1", f"Cycle B {today}: reconciliation break, submissions halted",
              "```json\n" + json.dumps(diffs, indent=1)[:2500] + "\n```\n"
              "The account does not equal its pre-submission holdings plus today's fills. "
              "The submit step sends nothing until live/ledger/halt.json is cleared.")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        import os
        os.environ["LIVE_SMOKE"] = "1"
    ledger = config.LEDGER / "smoke" if args.smoke else config.LEDGER

    now = now_et()
    today = str(now.date())
    if not is_session(today):
        print(f"{today} is not a session; nothing to reconcile")
        return 0
    # crons fire 13:50 and 14:50 UTC; skip the slot that lands before the open
    if not args.smoke and now.hour * 60 + now.minute < 9 * 60 + 35:
        print(f"{now:%H:%M} ET is before 09:35 ET; the later cron slot will run this cycle")
        return 0
    b_path = ledger / "cycles" / f"{today}-B.json"
    if b_path.exists():
        print(f"cycle B for {today} already recorded")
        return 0

    prev = previous_session(today)
    record = {"cycle": "B", "asof": today, "orders_from": prev,
              "ts_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "smoke": bool(args.smoke)}

    orders_path = ledger / "orders" / f"{prev}.json"
    if not orders_path.exists():
        record["status"] = "no_orders_ledgered"
        b_path.parent.mkdir(parents=True, exist_ok=True)
        b_path.write_text(json.dumps(record, indent=1))
        print(f"cycle B {today}: no order file for {prev} (fine before the first Cycle A)")
        return 0
    orders = json.loads(orders_path.read_text())["orders"]

    # internal consistency: the ledgered orders must equal the twin's pending
    # book (forced Sharia exits are the harness's own additions, not the twin's)
    twin_path = ledger / "twin" / "twin_latest.json"
    if twin_path.exists():
        twin = json.loads(twin_path.read_text())
        twin_keys = sorted(f"{o['code']}|{o['side']}" for o in twin.get("orders_next_open", []))
        ledg_keys = sorted(f"{o['code']}|{o['side']}" for o in orders if not o.get("forced"))
        record["ledger_matches_twin"] = twin_keys == ledg_keys
        if not record["ledger_matches_twin"]:
            alert("P1", f"Cycle B {today}: order ledger does not match twin pending book",
                  f"twin: {twin_keys}\nledger: {ledg_keys}\nReconciliation break — "
                  f"halt until a human clears it (docs/05 §3).")

    codes = sorted({o["code"] for o in orders}) + ["IXIC"]
    record["opens"] = fetch_opens(codes, today)
    missing = [c for c, v in record["opens"].items() if v is None]
    if missing:
        alert("P2", f"Cycle B {today}: no opening print for {len(missing)} symbol(s)",
              ", ".join(missing))

    # paper mode: trace every submitted order, slippage vs the official open,
    # and share-for-share reconciliation against the pre-submission book
    broker = get_broker()
    if broker.mode == "paper":
        try:
            reconcile_paper(broker, ledger, prev, today, record)
        except Exception as exc:  # noqa: BLE001
            record["broker_error"] = str(exc)[:300]
            alert("P1", f"Cycle B {today}: broker reconciliation failed", str(exc)[:800])

    record["status"] = "ok"
    b_path.parent.mkdir(parents=True, exist_ok=True)
    b_path.write_text(json.dumps(record, indent=1))
    step_summary(f"### Cycle B — {today}\n\nOpens recorded for {len(codes)} symbols "
                 f"(orders from {prev}); "
                 f"{'ledger==twin ok' if record.get('ledger_matches_twin', True) else 'RECONCILIATION BREAK'}.")
    print(f"cycle B {today}: recorded opens for {len(codes)} symbols")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        alert("P1", "Cycle B crashed", f"{type(exc).__name__}: {exc}"[:800])
        raise
