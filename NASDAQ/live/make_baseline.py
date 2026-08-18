"""Derive the anomaly-panel baselines (docs/05 §5) from the agent's OOS record.

Run once (and after any redeploy that changes the agent): reads
out/results_oos.json and writes live/baseline.json with the distributions the
cockpit compares each live day against — exposure, daily turnover, orders per
day, position count — plus the OOS precedent numbers the performance panel
draws as reference lines.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402


def pcts(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    def q(p: float) -> float:
        i = min(len(s) - 1, max(0, round(p * (len(s) - 1))))
        return round(s[int(i)], 4)
    return {"p5": q(0.05), "p25": q(0.25), "p50": q(0.50),
            "p75": q(0.75), "p95": q(0.95), "n": len(s)}


def main() -> int:
    res = json.loads((PKG / "out" / "results_oos.json").read_text())
    agent = next(a for a in res["agents"] if a["meta"]["handle"] == config.AGENT_HANDLE)

    equity, cash, dates = agent["equity"], agent["cash"], res["dates"]
    exposure = [1 - c / e for c, e in zip(cash, equity) if e > 0]

    by_date: dict[str, float] = {}
    orders_by_date: dict[str, int] = {}
    for t in agent["trades"]:
        by_date[t["date"]] = by_date.get(t["date"], 0.0) + t["value"]
        orders_by_date[t["date"]] = orders_by_date.get(t["date"], 0) + 1
    eq_by_date = dict(zip(dates, equity))
    turnover_all = [by_date.get(d, 0.0) / eq_by_date[d] for d in dates if eq_by_date[d] > 0]
    turnover_active = [v for v in turnover_all if v > 0]
    orders_active = list(orders_by_date.values())

    positions = [len(h["positions"]) for h in agent["holdings_monthly"]]

    m = agent["metrics"]
    out = {
        "source": f"out/results_oos.json · {config.AGENT_HANDLE} · "
                  f"{res['meta']['sim_start']} → {res['meta']['sim_end']}",
        "exposure": pcts(exposure),
        "turnover_daily_all": pcts(turnover_all),
        "turnover_daily_active": pcts(turnover_active),
        "orders_per_active_day": pcts([float(x) for x in orders_active]),
        "positions_monthly": pcts([float(x) for x in positions]),
        "trades_per_week": round(m["n_trades"] / (len(dates) / 5), 2),
        "oos": {
            "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"],
            "cagr": m["cagr"], "total_return": m["total_return"],
            "ann_vol": m["ann_vol"], "calmar": m["calmar"],
        },
    }
    (LIVE / "baseline.json").write_text(json.dumps(out, indent=1))
    print(f"baseline written: exposure p50 {out['exposure']['p50']:.0%}, "
          f"active-day turnover p95 {out['turnover_daily_active']['p95']:.1%}, "
          f"OOS sharpe {m['sharpe']:.2f}, maxDD {m['max_drawdown']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
