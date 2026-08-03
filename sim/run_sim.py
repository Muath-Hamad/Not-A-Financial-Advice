"""Run all agent strategies through the engine and dump results for the dashboard.

Usage: python sim/run_sim.py [--strategies sim/strategies] [--out out/results.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))

from engine import Engine, Market, START_CASH  # noqa: E402
from metrics import series_metrics, trade_metrics  # noqa: E402


def load_strategies(strat_dir: Path):
    strategies = []
    for py in sorted(strat_dir.glob("*.py")):
        if py.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"strategies.{py.stem}", py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        s = getattr(mod, "STRATEGY", None)
        if s is None:
            print(f"WARNING: {py.name} has no STRATEGY, skipping", file=sys.stderr)
            continue
        strategies.append(s)
        print(f"loaded {s.meta['handle']:>12}  {s.meta['name']}")
    return strategies


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default=str(ROOT / "sim" / "strategies"))
    ap.add_argument("--out", default=str(ROOT / "out" / "results.json"))
    args = ap.parse_args()

    market = Market()
    print(f"market: {len(market.codes)} stocks, {len(market.dates)} sessions "
          f"({market.dates[0].date()} → {market.dates[-1].date()})")
    strategies = load_strategies(Path(args.strategies))
    if not strategies:
        print("no strategies found", file=sys.stderr)
        return 1

    engine = Engine(market)
    agents, chat, events = engine.run_all(strategies)

    dates = [str(d.date()) for d in market.dates]
    tasi_norm = (market.tasi / market.tasi.iloc[0] * START_CASH).round(2)

    out = {
        "meta": {
            "start_cash": START_CASH,
            "sim_start": dates[0],
            "sim_end": dates[-1],
            "sessions": len(dates),
            "universe_size": len(market.codes),
            "names": market.names,
            "sectors": market.sectors,
        },
        "dates": dates,
        "tasi": [float(x) for x in tasi_norm],
        "events": events,
        "chat": chat,
        "agents": [],
    }

    for a in agents:
        sm = series_metrics(market.dates, a.equity_hist, list(tasi_norm))
        tm = trade_metrics(a.trades, a.equity_hist, market.dates, market.names)
        final_snap = a.holdings_monthly[-1] if a.holdings_monthly else {"positions": {}, "cash": a.pf.cash}
        out["agents"].append({
            "meta": a.meta,
            "equity": a.equity_hist,
            "cash": a.cash_hist,
            "sentiment": a.sentiment_hist,
            "trades": a.trades,
            "journal": a.journal,
            "holdings_monthly": a.holdings_monthly,
            "final_positions": final_snap,
            "dividends_received": round(a.dividends_received, 2),
            "commissions_paid": round(a.commissions_paid, 2),
            "rejected_orders": a.rejected_orders,
            "decide_errors": a.errors,
            "metrics": {**sm, **tm},
        })
        print(f"{a.handle:>12}: final {sm['final_equity']:>12,.0f} SAR "
              f"({sm['total_return']:+.1%}), maxDD {sm['max_drawdown']:.1%}, "
              f"{tm['n_trades']} trades, errors={a.errors}")

    tasi_metrics = series_metrics(market.dates, list(tasi_norm), list(tasi_norm))
    out["tasi_metrics"] = tasi_metrics
    print(f"{'TASI':>12}: final {tasi_metrics['final_equity']:>12,.0f} SAR "
          f"({tasi_metrics['total_return']:+.1%})")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out))
    print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
