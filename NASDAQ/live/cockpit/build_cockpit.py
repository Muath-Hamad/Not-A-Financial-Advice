"""Build the live cockpit (docs/05 §5) from the ledger.

Reads twin_latest.json, the cycle records, gate.json, controls.json,
baseline.json and the AAOIFI screen; writes a self-contained HTML page.
Rebuilt at the end of every Cycle A, committed with the ledger.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE.parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402

MAX_POINTS = 700


def downsample(dates, *series):
    n = len(dates)
    if n <= MAX_POINTS:
        return [dates] + [list(s) for s in series]
    step = n / MAX_POINTS
    idx = sorted({int(i * step) for i in range(MAX_POINTS)} | {n - 1})
    return [[dates[i] for i in idx]] + [[s[i] for i in idx] for s in series]


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(config.LEDGER))
    ap.add_argument("--out", default=str(HERE / "index.html"))
    args = ap.parse_args()
    ledger = Path(args.ledger)

    twin = load(ledger / "twin" / "twin_latest.json")
    if twin is None:
        print("no twin state yet; cockpit not built")
        return 0

    d2, eq, cash, bench = downsample(twin["dates"], twin["equity"], twin["cash"], twin["bench"])
    slim_twin = {k: twin[k] for k in
                 ("asof", "live_start", "sessions", "equity_final", "cash_final",
                  "positions", "params", "param_space", "adaptations", "freeze_commit")}
    slim_twin.update({"dates": d2, "equity": eq, "cash": cash, "bench": bench,
                      "metrics": {k: twin.get("metrics", {}).get(k)
                                  for k in ("sharpe", "cagr", "max_drawdown", "ann_vol",
                                            "sortino", "calmar", "win_rate", "n_trades")}})

    cycles = []
    for p in sorted((ledger / "cycles").glob("*.json"), reverse=True)[:40]:
        r = load(p, {})
        info = ""
        if r.get("cycle") == "A" and r.get("twin"):
            info = (f"equity ${r['twin']['equity_final']:,.0f} · "
                    f"{r['twin']['n_orders_next_open']} orders · "
                    f"{len(r.get('guardrails', {}).get('violations', []))} flags")
        elif r.get("cycle") == "B":
            n_opens = len([v for v in (r.get("opens") or {}).values() if v])
            info = f"{n_opens} opens recorded"
        cycles.append({"asof": r.get("asof"), "cycle": r.get("cycle"),
                       "status": r.get("status", "?"), "info": info})

    last_a = next((load(p) for p in sorted((ledger / "cycles").glob("*-A.json"),
                                           reverse=True)), {}) or {}
    last_b = next((load(p) for p in sorted((ledger / "cycles").glob("*-B.json"),
                                           reverse=True)), {}) or {}
    # keep the embedded records light
    for rec in (last_a, last_b):
        rec.pop("controls", None)
        rec.pop("submitted", None)
        if "opens" in rec:
            rec["opens"] = {k: v for k, v in list(rec["opens"].items())[:60]}

    orders_file = load(ledger / "orders" / f"{twin['asof']}.json", {})
    orders = orders_file.get("orders", [])
    for o in orders:
        o.pop("client_order_id", None)

    baseline = load(LIVE / "baseline.json", {})
    controls = load(LIVE / "controls.json", {})
    gate = load(ledger / "gate.json", {"streak": 0, "target": config.GATE_TARGET_STREAK,
                                       "passed": False, "history": []})

    screen = load(PKG / "data" / "universe_screened.json", {})
    screen_slim = {"screened": screen.get("screened", 0),
                   "passed": len(screen.get("universe", [])),
                   "basis": "as-of deployment screen; quarterly re-screen updates exclusions"}

    names = {u["code"]: u.get("name", "") for u in screen.get("universe", [])
             if u["code"] in twin["positions"]}

    # today's anomaly readings vs the baseline
    exposure = 1 - twin["cash_final"] / twin["equity_final"] if twin["equity_final"] else None
    today_trades = [t for t in twin.get("trades", []) if t["date"] == twin["asof"]]
    turnover = sum(t["value"] for t in today_trades) / twin["equity_final"] \
        if twin["equity_final"] else None
    anomaly = {"exposure": round(exposure, 4) if exposure is not None else None,
               "turnover": round(turnover, 4) if turnover is not None else None,
               "orders": len(orders),
               "positions": len(twin["positions"])}

    payload = {
        "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": last_a.get("mode", "ghost"),
        "twin": slim_twin,
        "orders": orders,
        "cycles": cycles,
        "last_a": last_a,
        "last_b": last_b,
        "gate": gate,
        "controls": {k: controls.get(k) for k in
                     ("kill", "pause_entries", "excluded_symbols", "gross_cap")},
        "baseline": baseline,
        "anomaly": anomaly,
        "screen": screen_slim,
        "names": names,
    }

    template = (HERE / "template.html").read_text()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template.replace("/*__DATA__*/{}", json.dumps(payload)))
    print(f"cockpit built: {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
