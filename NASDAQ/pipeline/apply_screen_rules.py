"""Re-apply the offline rule layers of the AAOIFI screen to a screened file.

pipeline/sharia_screen.py fetches fundamentals over the network. Its
instrument screen, curated exclusions (data/sharia_overrides.json) and
review flags need no network, so this script re-applies them to an existing
screened universe, moves any name that now fails into rejected_detail, and
records the correction. The financial ratios are left as they were.

Usage: python NASDAQ/pipeline/apply_screen_rules.py [path, default data/universe_screened.json]

Changing the deployment universe changes the twin's world (market breadth
included), so it is a change-management event: run the 2023-26 regression
and record the result (docs/06, docs/07).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from sharia_screen import apply_rule_layers, load_overrides  # noqa: E402


def main() -> int:
    path = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "data/universe_screened.json")
    screen = json.loads(path.read_text())
    overrides = load_overrides()

    kept, moved = [], []
    for rec in screen["universe"]:
        rec = apply_rule_layers(dict(rec), overrides)
        (kept if rec["pass"] else moved).append(rec)
    for rec in screen.get("rejected_detail", []):
        apply_rule_layers(rec, overrides)
        rec["pass"] = False

    screen["universe"] = kept
    screen["rejected_detail"] = moved + screen.get("rejected_detail", [])
    screen["passed"] = len(kept)
    screen["rejected"] = len(screen["rejected_detail"])
    screen.setdefault("corrections", []).append({
        "date": str(dt.date.today()),
        "rule_layers": "instrument screen (common shares only) + data/sharia_overrides.json",
        "removed": [{"code": r["code"], "name": r.get("name"),
                     "reasons": r["instrument_reasons"] + r["override_reasons"]} for r in moved],
    })
    path.write_text(json.dumps(screen, ensure_ascii=False, indent=1))
    flagged = [r["code"] for r in kept if r.get("review_flags")]
    print(f"{path.name}: {len(kept)} pass, {len(moved)} removed "
          f"({', '.join(r['code'] for r in moved) or 'none'}); "
          f"{len(flagged)} flagged for policy review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
