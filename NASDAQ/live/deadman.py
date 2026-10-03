"""The dead-man's switch (docs/05 §6): runs OUTSIDE Cycle A, after its deadline.

If today was a session and no Cycle A record exists by DEADMAN_DEADLINE_ET,
the scheduler itself has silently died — the classic failure where nothing
errors and nothing runs. Files a P1 issue (deduped per day).

With --submit (paper mode only), the same check for the submit step: orders
were ledgered tonight but no submission record exists by SUBMIT_DEADLINE_ET.

A missing record is not a dead step while its workflow has a run queued or in
progress: GitHub starts the crons hours late and Cycle A can wait out Yahoo's
evening data gap (config.FETCH_WAIT_MAX_MIN). A run older than its job's
timeout is stuck, not late, and does not count. With --after-cycle-a the check
also runs whenever a Cycle A run ends without success (the workflow passes
only those): the session must then have a record on main. That catches what
no in-run alert can — a timeout, a lost runner, a ledger push that never
landed. A successful run either recorded its session or exited on purpose.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import _api, _repo, _token, alert  # noqa: E402
from calendar_util import decision_session, is_session, now_et  # noqa: E402

# job timeout + margin, minutes: a run older than this is stuck, not late
IN_FLIGHT_MAX_MIN = {"live-cycle-a.yml": 240 + 30, "live-submit.yml": 20 + 10}


def run_in_flight(workflow: str, now: dt.datetime | None = None) -> str | None:
    """URL of a live queued or running scheduled/manual run of `workflow` (a
    file in .github/workflows), or None. Push runs are smoke drills and do not
    count, nor does a run older than its job could live (age from its start,
    or from its creation while it waits). Without a token or API access the
    answer is None: alert rather than hush."""
    if not (_repo() and _token()):
        return None
    try:
        runs = _api("GET", f"/repos/{_repo()}/actions/workflows/{workflow}/runs?per_page=20")
    except Exception as exc:  # noqa: BLE001 - the check degrades to alerting
        print(f"could not list {workflow} runs: {exc}")
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    limit = dt.timedelta(minutes=IN_FLIGHT_MAX_MIN.get(workflow, 60))
    for run in runs.get("workflow_runs", []):
        if run.get("status") == "completed" or run.get("event") == "push":
            continue
        since = run.get("run_started_at") if run.get("status") == "in_progress" else None
        since = since or run.get("created_at")
        try:
            age = now - dt.datetime.fromisoformat(since.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            age = dt.timedelta(0)
        url = run.get("html_url") or str(run.get("id"))
        if age > limit:
            print(f"{workflow} run {url} has been {run.get('status')} for {age}; "
                  f"treating it as stuck")
            continue
        return url
    return None


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
    running = run_in_flight("live-submit.yml")
    if running:
        print(f"no submit record for {today} yet, but a submit run is in flight ({running})")
        return 0
    alert("P1", f"DEAD-MAN: orders for {today} were never submitted",
          f"{len(sendable)} order(s) are ledgered in live/ledger/orders/{today}.json but "
          f"live/ledger/cycles/{today}-S.json does not exist. Run the live-submit "
          f"workflow manually before 09:28 ET, or the account skips tomorrow's open.")
    return 0


def check_after_cycle_a(now) -> int:
    asof = decision_session(now)
    if (config.LEDGER / "cycles" / f"{asof}-A.json").exists():
        print(f"cycle A for {asof} is recorded — heartbeat ok")
        return 0
    running = run_in_flight("live-cycle-a.yml")
    if running:
        print(f"no Cycle A record for {asof} yet; another cycle A run is in flight "
              f"({running}) and its completion checks again")
        return 0
    run_url = os.environ.get("RUN_URL")
    alert("P1", f"DEAD-MAN: no Cycle A record for {asof}",
          f"A live-cycle-a run finished{f' ({run_url})' if run_url else ''} but "
          f"live/ledger/cycles/{asof}-A.json is not on main: the run timed out, was "
          f"cancelled, lost its runner or could not push its ledger. Run the "
          f"live-cycle-a workflow manually; it decides {asof} if it starts "
          f"{config.CYCLE_A_RUNTIME_MARGIN_MIN} minutes or more before Alpaca's "
          f"{config.SUBMIT_CUTOFF_ET[0]:02d}:{config.SUBMIT_CUTOFF_ET[1]:02d} ET cutoff.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="check the submit step instead")
    ap.add_argument("--after-cycle-a", action="store_true",
                    help="a Cycle A run just ended without success: its session "
                         "must still be recorded")
    args = ap.parse_args()
    now = now_et()
    if args.after_cycle_a:
        return check_after_cycle_a(now)
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
    running = run_in_flight("live-cycle-a.yml")
    if running:
        print(f"no Cycle A record for {today} yet, but a cycle A run is in flight ({running})")
        return 0
    alert("P1", f"DEAD-MAN: no Cycle A record for {today}",
          f"It is past {config.DEADMAN_DEADLINE_ET}:00 ET on a trading day and "
          f"live/ledger/cycles/{today}-A.json does not exist. The decision cycle "
          f"never ran or never committed. Check the live-cycle-a workflow runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
