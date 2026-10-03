"""controls.json schema v2 (docs/08 §7.2): defaults, normalization, validation.

Every key the harness reads lives here, with the meaning "missing = off", so
an older controls.json keeps working unchanged. Pure functions, no I/O beyond
`load`; the console API validates its writes with the same rules.

Keys:
  version            2
  kill               bool    — no orders ledgered or sent; cycles frozen
  pause_entries      bool    — blocks buys; exits still flow
  excluded_symbols   [str]   — blocks buys; a held name is sold in full at the next open
  gross_cap          float|None (0..1) — caps gross exposure
  locked_symbols     [str]   — the agent may neither buy nor sell the name
  manual_orders      [{id, symbol, side, qty|fraction, reason, created_by, created, expires}]
  pause_adapt        bool    — freezes adapt() from `pause_adapt_since` on
  pause_adapt_since  "YYYY-MM-DD"|None
  allow_manual_buys  bool    — manual buys are refused unless this is true
"""

from __future__ import annotations

import json
import re
from pathlib import Path

VERSION = 2
DEFAULTS: dict = {
    "version": VERSION,
    "kill": False,
    "pause_entries": False,
    "excluded_symbols": [],
    "gross_cap": None,
    "locked_symbols": [],
    "manual_orders": [],
    "pause_adapt": False,
    "pause_adapt_since": None,
    "allow_manual_buys": False,
}
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize(raw: dict | None) -> dict:
    """Defaults filled in; unknown keys (such as `note`) kept as they are."""
    out = dict(raw or {})            # keep the file's own key order (clean diffs)
    for k, v in DEFAULTS.items():
        out.setdefault(k, v)
    for k in ("excluded_symbols", "locked_symbols", "manual_orders"):
        out[k] = list(out.get(k) or [])
    return out


def load(path: Path) -> dict:
    return normalize(json.loads(Path(path).read_text(encoding="utf-8")))


def validate(c: dict) -> list[str]:
    """Problems with a controls document; [] means valid."""
    errs: list[str] = []
    for k in ("kill", "pause_entries", "pause_adapt", "allow_manual_buys"):
        if not isinstance(c.get(k), bool):
            errs.append(f"{k} must be true or false")
    gc = c.get("gross_cap")
    if gc is not None and not (isinstance(gc, (int, float)) and 0 < float(gc) <= 1):
        errs.append("gross_cap must be null or a fraction in (0, 1]")
    for k in ("excluded_symbols", "locked_symbols"):
        v = c.get(k)
        if not isinstance(v, list) or not all(isinstance(s, str) and SYMBOL.match(s) for s in v):
            errs.append(f"{k} must be a list of ticker symbols")
        elif len(set(v)) != len(v):
            errs.append(f"{k} has duplicates")
    both = set(c.get("excluded_symbols") or []) & set(c.get("locked_symbols") or [])
    if both:
        errs.append("a name cannot be both excluded and locked: " + ", ".join(sorted(both)))
    since = c.get("pause_adapt_since")
    if since is not None and not (isinstance(since, str) and DATE.match(since)):
        errs.append("pause_adapt_since must be null or YYYY-MM-DD")
    ids = set()
    for i, m in enumerate(c.get("manual_orders") or []):
        where = f"manual_orders[{i}]"
        if not isinstance(m, dict):
            errs.append(f"{where} must be an object")
            continue
        if not m.get("id") or m["id"] in ids:
            errs.append(f"{where}: missing or duplicate id")
        ids.add(m.get("id"))
        if not isinstance(m.get("symbol"), str) or not SYMBOL.match(m["symbol"]):
            errs.append(f"{where}: bad symbol")
        if m.get("side") not in ("buy", "sell"):
            errs.append(f"{where}: side must be buy or sell")
        if m.get("side") == "buy" and not c.get("allow_manual_buys"):
            errs.append(f"{where}: manual buys are off (allow_manual_buys=false)")
        qty, frac = m.get("qty"), m.get("fraction")
        if (qty is None) == (frac is None):
            errs.append(f"{where}: give exactly one of qty or fraction")
        if qty is not None and not (isinstance(qty, int) and qty >= 1):
            errs.append(f"{where}: qty must be a whole number ≥ 1")
        if frac is not None and not (isinstance(frac, (int, float)) and 0 < float(frac) <= 1):
            errs.append(f"{where}: fraction must be in (0, 1]")
        if m.get("side") == "buy" and frac is not None:
            errs.append(f"{where}: a manual buy needs a share qty")
        if not isinstance(m.get("reason"), str) or len(m["reason"].strip()) < 10:
            errs.append(f"{where}: reason of at least 10 characters required")
        exp = m.get("expires")
        if not (isinstance(exp, str) and DATE.match(exp)):
            errs.append(f"{where}: expires must be YYYY-MM-DD (the session it is meant for)")
    return errs


def active_manual_orders(c: dict, asof: str) -> list[dict]:
    """Manual orders still valid for the open that follows session `asof`:
    created on or before it and expiring on or after it."""
    out = []
    for m in c.get("manual_orders") or []:
        if str(m.get("expires", "")) >= asof and str(m.get("created", asof))[:10] <= asof:
            out.append(m)
    return out
