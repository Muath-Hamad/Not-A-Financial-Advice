"""Quarterly AAOIFI re-screen report (docs/05 §3, quarterly cycle).

Compares a fresh screen against the deployment screen and the twin's book.
The deployment whitelist itself stays frozen — decision fidelity means the
twin's universe never changes mid-flight — so the re-screen acts through the
HARNESS layer: names that fell out of compliance are appended to
controls.json excluded_symbols (blocked from buys; in paper mode the harness
also force-exits them over <= 5 sessions). Newly eligible names are reported
and enter at the next declared redeploy (a change-management event).

Usage: python NASDAQ/live/rescreen_report.py --fresh data/rescreen/<file>.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import alert, step_summary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", required=True, help="path (repo-relative) to the new screen json")
    args = ap.parse_args()

    fresh = json.loads((PKG / args.fresh).read_text())
    deployed = json.loads((PKG / "data" / "universe_screened.json").read_text())
    fresh_ok = {u["code"] for u in fresh["universe"]}
    deployed_ok = {u["code"] for u in deployed["universe"]}
    reasons = {r["code"]: r.get("reason", "?") for r in fresh.get("rejected_detail", [])}

    newly_noncompliant = sorted(deployed_ok - fresh_ok)
    newly_eligible = sorted(fresh_ok - deployed_ok)

    twin_path = config.LEDGER / "twin" / "twin_latest.json"
    held = set()
    if twin_path.exists():
        held = set(json.loads(twin_path.read_text()).get("positions", {}))
    held_flagged = sorted(held & set(newly_noncompliant))

    today = str(dt.date.today())
    report = {
        "date": today,
        "fresh_screen": args.fresh,
        "newly_noncompliant": [{"code": c, "reason": reasons.get(c, "not in fresh screen")}
                               for c in newly_noncompliant],
        "newly_eligible": newly_eligible,
        "held_and_flagged": held_flagged,
        "policy": "excluded via controls.json (buys blocked); held names exit <= 5 sessions "
                  "in paper mode; eligible names enter at the next redeploy",
    }
    out = config.LEDGER / "compliance" / f"{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))

    if newly_noncompliant:
        controls_path = LIVE / "controls.json"
        controls = json.loads(controls_path.read_text())
        merged = sorted(set(controls.get("excluded_symbols") or []) | set(newly_noncompliant))
        controls["excluded_symbols"] = merged
        controls_path.write_text(json.dumps(controls, indent=2) + "\n")

    if held_flagged:
        alert("P1", f"Re-screen: {len(held_flagged)} HELD name(s) no longer AAOIFI-compliant",
              f"{', '.join(held_flagged)} — excluded from buys now; orderly exit within "
              f"5 sessions is the declared policy (harness-enforced in paper mode). "
              f"Report: live/ledger/compliance/{today}.json")
    elif newly_noncompliant:
        alert("P2", f"Re-screen: {len(newly_noncompliant)} whitelist name(s) fell out of compliance",
              ", ".join(newly_noncompliant[:30]))
    step_summary(f"### AAOIFI re-screen — {today}\n\n"
                 f"- newly non-compliant: **{len(newly_noncompliant)}**"
                 f" (held: **{len(held_flagged)}**)\n"
                 f"- newly eligible (next redeploy): **{len(newly_eligible)}**\n")
    print(f"re-screen report: {len(newly_noncompliant)} out, {len(newly_eligible)} in, "
          f"{len(held_flagged)} held+flagged -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
