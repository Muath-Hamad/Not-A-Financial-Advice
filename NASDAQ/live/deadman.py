"""The dead-man's switch (docs/05 §6): runs OUTSIDE Cycle A, after its deadline.

If today was a session and no Cycle A record exists by DEADMAN_DEADLINE_ET,
the scheduler itself has silently died — the classic failure where nothing
errors and nothing runs. Files a P1 issue (deduped per day).

With --submit (paper mode only), the same check for the submit step: orders
were ledgered tonight but no submission record exists by SUBMIT_DEADLINE_ET.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import alert  # noqa: E402
from calendar_util import is_session, now_et  # noqa: E402


def check_submit(today: str, hour: int) -> int:
    if os.environ.get("LIVE_MODE", "ghost") != "paper":
        print("ghost mode: nothing is submitted, submit check not applicable")
        return 0
    if hour < config.SUBMIT_DEADLINE_ET:
        print(f"before the {config.SUBMIT_DEADLINE_ET}:00 ET submit deadline; not checking yet")
        return 0
    orders_path = config.LEDGER / "orders" / f"{today}.json"
    if not orders_path.exists():
        print(f"no orders ledgered for {today}; nothing had to be submitted")
        return 0
    sendable = [o for o in json.loads(orders_path.read_text()).get("orders", [])
                if not o.get("blocked")]
    if not sendable:
        print(f"every order for {today} was blocked; nothing had to be submitted")
        return 0
    if (config.LEDGER / "cycles" / f"{today}-S.json").exists():
        print(f"submit record for {today} exists — heartbeat ok")
        return 0
    alert("P1", f"DEAD-MAN: orders for {today} were never submitted",
          f"{len(sendable)} order(s) are ledgered in live/ledger/orders/{today}.json but "
          f"live/ledger/cycles/{today}-S.json does not exist. Run the live-submit "
          f"workflow manually before 09:28 ET, or the account skips tomorrow's open.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="check the submit step instead")
    args = ap.parse_args()
    now = now_et()
    today = str(now.date())
    if not is_session(today):
        print(f"{today} is not a session; dead-man check not applicable")
        return 0
    if args.submit:
        return check_submit(today, now.hour)
    if now.hour < config.DEADMAN_DEADLINE_ET:
        print(f"before the {config.DEADMAN_DEADLINE_ET}:00 ET deadline; not checking yet")
        return 0
    a_record = config.LEDGER / "cycles" / f"{today}-A.json"
    if a_record.exists():
        print(f"cycle A for {today} is recorded — heartbeat ok")
        return 0
    alert("P1", f"DEAD-MAN: no Cycle A record for {today}",
          f"It is past {config.DEADMAN_DEADLINE_ET}:00 ET on a trading day and "
          f"live/ledger/cycles/{today}-A.json does not exist. The decision cycle "
          f"never ran or never committed. Check the live-cycle-a workflow runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
