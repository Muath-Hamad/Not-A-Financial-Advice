"""The dead-man's switch (docs/05 §6): runs OUTSIDE Cycle A, after its deadline.

If today was a session and no Cycle A record exists by DEADMAN_DEADLINE_ET,
the scheduler itself has silently died — the classic failure where nothing
errors and nothing runs. Files a P1 issue (deduped per day).
"""

from __future__ import annotations

import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import alert  # noqa: E402
from calendar_util import is_session, now_et  # noqa: E402


def main() -> int:
    now = now_et()
    today = str(now.date())
    if not is_session(today):
        print(f"{today} is not a session; dead-man check not applicable")
        return 0
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
