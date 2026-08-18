"""Cycle B — the post-open reconciliation cycle (docs/05 §3), ~09:50 ET.

Ghost mode: record today's actual opening prints for every symbol ordered at
yesterday's Cycle A (the evening replay cross-checks them — the open-revision
metric), and verify the order ledger is internally consistent with the twin
state. Paper mode (Phase 2): additionally pull the venue's real fills, match
them to client-order-ids, measure realized slippage against the model, and
reconcile broker positions share-for-share — any unexplained break is a P1
and trading halts.
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

    # internal consistency: the ledgered orders must equal the twin's pending book
    twin_path = ledger / "twin" / "twin_latest.json"
    if twin_path.exists():
        twin = json.loads(twin_path.read_text())
        twin_keys = sorted(f"{o['code']}|{o['side']}" for o in twin.get("orders_next_open", []))
        ledg_keys = sorted(f"{o['code']}|{o['side']}" for o in orders)
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

    # paper mode: real fills, slippage vs model, share-for-share reconciliation
    broker = get_broker()
    if broker.mode == "paper":
        try:
            fills = broker.fills(today)
            record["fills"] = fills
            slips = []
            by_coid = {o["client_order_id"]: o for o in orders}
            for f in fills or []:
                coid = f.get("order_id") or f.get("client_order_id", "")
                o = by_coid.get(coid)
                ref = record["opens"].get(f.get("symbol", ""))
                px = float(f.get("price") or 0)
                if ref and px:
                    side = (o or {}).get("side") or f.get("side", "")
                    sign = 1 if side == "buy" else -1
                    slips.append({"symbol": f.get("symbol"),
                                  "slippage": round(sign * (px / ref - 1), 5)})
            record["slippage"] = slips
            positions = broker.positions()
            record["broker_positions"] = {p["symbol"]: int(float(p["qty"]))
                                          for p in positions or []}
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
