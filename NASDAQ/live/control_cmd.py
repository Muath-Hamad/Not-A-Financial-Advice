"""Immediate broker commands for the console (docs/08 §7.1–§7.2).

Controls normally act through controls.json at the next cycle. Two actions
cannot wait: STOP TRADING cancels the open on-open orders now, and stop &
flatten also queues a market-on-open sell of every position. This step runs
them with the paper keys (GitHub phase: the live-control workflow; on the
box: run-step) and writes the broker's answer to ledger/commands/<ts>.json,
which the console reads back as the confirmation. Ghost mode records a no-op.

Usage:
  python NASDAQ/live/control_cmd.py --action cancel_all --reason "..." --actor owner@console
  python NASDAQ/live/control_cmd.py --action flatten   --reason "..." --actor owner@console --id 01J...
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
from alert import alert  # noqa: E402
from broker import get_broker  # noqa: E402

ACTIONS = ("cancel_all", "flatten")


def run(action: str, reason: str, actor: str, action_id: str | None, ledger: Path, broker=None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if len(reason.strip()) < 10:
        raise ValueError("a reason of at least 10 characters is required")
    now = dt.datetime.now(dt.timezone.utc)
    broker = broker or get_broker()
    rec: dict = {"action": action, "reason": reason.strip(), "actor": actor, "console_action_id": action_id,
                 "mode": broker.mode, "ts_utc": now.isoformat(timespec="seconds")}
    try:
        rec["cancel"] = broker.cancel_all()
        if action == "flatten":
            from calendar_util import latest_completed_session
            rec["flatten"] = broker.flatten(latest_completed_session())
        rec["status"] = "ok" if (rec.get("flatten") or {}).get("status", "ok") in ("ok", "ghost-noop") else "partial"
    except Exception as exc:  # noqa: BLE001 — the record says what failed; the console shows "Not applied"
        rec["status"] = "failed"
        rec["error"] = f"{type(exc).__name__}: {exc}"[:500]
    out = ledger / "commands" / f"{now:%Y%m%dT%H%M%SZ}-{action}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    rec["path"] = str(out)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True, choices=ACTIONS)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--actor", default="owner@console")
    ap.add_argument("--id", default=None, help="the console's action id, echoed into the record")
    args = ap.parse_args()
    rec = run(args.action, args.reason, args.actor, args.id, config.LEDGER)
    level = "P1" if rec["status"] != "ok" else "P2"
    alert(level, f"Control command {args.action}: {rec['status']}",
          f"actor {args.actor} · reason: {args.reason}\n" + json.dumps({k: rec.get(k) for k in ("cancel", "flatten", "error")})[:1500])
    print(f"{args.action}: {rec['status']} → {rec['path']}")
    return 0 if rec["status"] != "failed" else 1


if __name__ == "__main__":
    os.environ.setdefault("LIVE_MODE", "ghost")
    sys.exit(main())
