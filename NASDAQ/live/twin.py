"""The sim twin: deterministic replay of the frozen agent from LIVE_START.

The twin IS the live agent's state. Nothing is serialized between days:
every Cycle A replays the whole live window from LIVE_START on today's data
snapshot, which reproduces — deterministically — the exact internal state an
incremental process would carry (portfolio, adapted parameters, cooldowns,
pending orders), and doubles as the documented rebuild-from-fills procedure
(docs/05 §9). Because SIM_DECIDE_LAST=1, the final session's decide() runs,
so today's orders for tomorrow's open are read from the agent's pending book.

Cycle A runs this file twice in separate processes and compares output bytes:
that is the Phase 1 determinism gate.

Usage: python NASDAQ/live/twin.py --out twin.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402

# The canonical twin environment — set before the engine reads it at import.
os.environ["SIM_ENRICHED_SUBDIR"] = os.environ.get("TWIN_ENRICHED_SUBDIR", config.ENRICHED_SUBDIR)
os.environ["SIM_RAW_SUBDIR"] = os.environ.get("TWIN_RAW_SUBDIR", config.RAW_SUBDIR)
os.environ["SIM_START"] = os.environ.get("TWIN_START", config.LIVE_START)
os.environ["SIM_COMMISSION"] = config.TWIN_COMMISSION
os.environ["SIM_SLIPPAGE"] = config.TWIN_SLIPPAGE
os.environ["SIM_ADAPT_EVERY"] = config.ADAPT_EVERY
os.environ["SIM_DECIDE_LAST"] = "1"

sys.path.insert(0, str(PKG / "sim"))
from engine import Engine, Market, START_CASH  # noqa: E402
from metrics import series_metrics, trade_metrics  # noqa: E402


def load_strategy():
    spec = importlib.util.spec_from_file_location("strategies.live_agent", config.AGENT_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = getattr(mod, "STRATEGY", None)
    if s is None:
        raise RuntimeError(f"{config.AGENT_FILE} exposes no STRATEGY")
    if s.meta["handle"] != config.AGENT_HANDLE:
        raise RuntimeError(f"loaded {s.meta['handle']!r}, expected {config.AGENT_HANDLE!r}")
    return s


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    strategy = load_strategy()
    market = Market()
    if not market.dates:
        print(f"twin: no sessions on or after SIM_START={os.environ['SIM_START']} "
              f"in the enriched data — nothing to replay", file=sys.stderr)
        return 2
    agents, _events = Engine(market).run_all([strategy], progress_every=0)
    a = agents[0]

    dates = [str(d.date()) for d in market.dates]
    bench = (market.tasi / market.tasi.iloc[0] * START_CASH).round(2)
    snap = a._snap

    params = {}
    for name in a.meta.get("param_space", {}):
        v = getattr(strategy, name, None)
        if isinstance(v, (int, float)):
            params[name] = float(v)

    metrics = {}
    if len(dates) >= 22:
        try:
            metrics = {**series_metrics(market.dates, a.equity_hist, list(bench)),
                       **trade_metrics(a.trades, a.equity_hist, market.dates, market.names)}
        except Exception as exc:  # noqa: BLE001 - young curves lack the depth some stats need
            metrics = {"error": str(exc)[:200]}

    out = {
        "agent": config.AGENT_HANDLE,
        "freeze_commit": config.FREEZE_COMMIT,
        "live_start": dates[0] if dates else config.LIVE_START,
        "asof": dates[-1] if dates else None,
        "sessions": len(dates),
        "universe_size": len(market.codes),
        "dates": dates,
        "equity": a.equity_hist,
        "cash": a.cash_hist,
        "bench": [float(x) for x in bench],
        "positions": {c: {"shares": p["shares"], "price": p["price"],
                          "value": round(p["value"], 2),
                          "avg_cost": round(p["avg_cost"], 4),
                          "weight": round(p["weight"], 4),
                          "unrealized_pct": round(p["unrealized_pct"], 4)}
                      for c, p in snap["positions"].items()},
        "cash_final": round(snap["cash"], 2),
        "equity_final": round(snap["equity"], 2),
        "orders_next_open": a.pending,
        "params": params,
        "param_space": a.meta.get("param_space", {}),
        "trades": a.trades,
        "adaptations": a.adaptations,
        "journal": a.journal,
        "dividends_received": round(a.dividends_received, 2),
        "commissions_paid": round(a.commissions_paid, 2),
        "rejected_orders": a.rejected_orders,
        "decide_errors": a.errors,
        "metrics": metrics,
        "inputs": {
            "manifest_sha": file_sha(PKG / os.environ["SIM_RAW_SUBDIR"] / "_manifest.json"),
            "universe_sha": file_sha(PKG / "data" / "universe_screened.json"),
            "strategy_sha": file_sha(config.AGENT_FILE),
            "engine_sha": file_sha(PKG / "sim" / "engine.py"),
            "commission": config.TWIN_COMMISSION,
            "slippage": config.TWIN_SLIPPAGE,
            "adapt_every": config.ADAPT_EVERY,
        },
    }
    Path(args.out).write_text(json.dumps(out))
    print(f"twin: {len(dates)} sessions {out['live_start']} -> {out['asof']}, "
          f"equity {out['equity_final']:,.2f}, {len(a.pending)} orders pending, "
          f"errors={a.errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
