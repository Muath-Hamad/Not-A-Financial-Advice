"""Cycle A data gate (docs/05 §3): refuse to trade on suspect data.

Hard checks (any failure trips the gate — no orders tomorrow):
  * the benchmark (IXIC) has a bar at asof,
  * >= GATE_FETCH_OK_MIN of the universe fetched at all,
  * >= GATE_COVERAGE_MIN of fetched names have a bar at asof,
  * no cross-checked close disagrees with the second source by > GATE_CROSS_TOL.

The second source is NASDAQ's own chart API (api.nasdaq.com) — the exchange's
published daily bars, fully independent of Yahoo, and proven reachable from
GitHub runners (Stooq serves runners a JavaScript challenge page and was
dropped). Only asof's close is compared, where adjustment conventions cannot
differ. If the second source is unreachable the gate does not trip — an
outage there must not halt trading — but the run is marked degraded and a P2
goes out.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402


def _our_close(code: str, asof: str) -> float | None:
    path = config.PKG / config.RAW_SUBDIR / f"{code}.csv.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt") as f:
        header = f.readline().strip().split(",")
        try:
            di, ci = header.index("Date"), header.index("Close")
        except ValueError:
            return None
        for line in f:
            parts = line.rstrip("\n").split(",")
            if parts[di] == asof:
                try:
                    return float(parts[ci])
                except ValueError:
                    return None
    return None


def _second_source_close(code: str, asof: str) -> float | None:
    sym, cls = ("COMP", "index") if code == "IXIC" else (code, "stocks")
    url = (f"https://api.nasdaq.com/api/quote/{sym}/chart"
           f"?assetclass={cls}&fromdate={asof}&todate={asof}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode("utf-8", "replace"))
    chart = ((payload.get("data") or {}).get("chart")) or []
    y, m, d = asof.split("-")
    want = f"{int(m)}/{int(d)}/{y}"   # the API prints dates as 8/17/2026
    for bar in chart:
        z = bar.get("z") or {}
        if z.get("dateTime") == want:
            # stocks carry z.close, indices z.lastSalePrice; the numeric y
            # is the close in both shapes
            val = bar.get("y")
            return float(val) if isinstance(val, (int, float)) and val > 0 else None
    return None


def run_gate(asof: str, priority_codes: list[str]) -> dict:
    manifest = json.loads((config.PKG / config.RAW_SUBDIR / "_manifest.json").read_text())
    ok = {c: m for c, m in manifest.items() if m.get("status") == "ok"}
    names = [c for c in ok if c != "IXIC"]

    fetch_frac = len(ok) / max(1, len(manifest))
    at_asof = [c for c in names if ok[c].get("last") == asof]
    coverage = len(at_asof) / max(1, len(names))
    ixic_ok = ok.get("IXIC", {}).get("last") == asof

    checks = {
        "ixic_at_asof": {"pass": bool(ixic_ok), "last": manifest.get("IXIC", {}).get("last")},
        "fetch_ok": {"pass": fetch_frac >= config.GATE_FETCH_OK_MIN,
                     "value": round(fetch_frac, 4), "min": config.GATE_FETCH_OK_MIN},
        "coverage_at_asof": {"pass": coverage >= config.GATE_COVERAGE_MIN,
                             "value": round(coverage, 4), "min": config.GATE_COVERAGE_MIN,
                             "missing": sorted(set(names) - set(at_asof))[:25]},
    }

    # cross-check set: benchmark + book/orders first, then largest names
    xset: list[str] = []
    for c in ["IXIC"] + priority_codes + names:
        if c in ok and c not in xset:
            xset.append(c)
        if len(xset) >= config.GATE_XCHECK_MAX:
            break

    disagreements, unavailable, compared = [], [], 0
    for c in xset:
        ours = _our_close(c, asof)
        if ours is None:
            unavailable.append(c)
            continue
        try:
            theirs = _second_source_close(c, asof)
        except Exception:  # noqa: BLE001 - network trouble = unavailable, not disagreement
            theirs = None
        if theirs is None or theirs <= 0:
            unavailable.append(c)
        else:
            compared += 1
            diff = abs(ours / theirs - 1.0)
            if diff > config.GATE_CROSS_TOL:
                disagreements.append({"code": c, "ours": ours, "nasdaq": theirs,
                                      "diff": round(diff, 5)})
        time.sleep(0.25)

    checks["cross_source"] = {
        "pass": not disagreements,
        "compared": compared,
        "unavailable": len(unavailable),
        "disagreements": disagreements,
        "tol": config.GATE_CROSS_TOL,
    }

    hard_fail = not all(checks[k]["pass"] for k in
                        ("ixic_at_asof", "fetch_ok", "coverage_at_asof", "cross_source"))
    degraded = compared == 0
    status = "trip" if hard_fail else ("degraded" if degraded else "pass")
    return {"status": status, "asof": asof, "checks": checks}
