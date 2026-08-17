"""Elect the live-candidate agent from in-sample + out-of-sample results.

The election is OUT-OF-SAMPLE dominant by design: the winner is the agent we
would hand a live virtual NASDAQ account, so what matters is how it performed
on data nobody tuned against, how consistent it was across the two regimes,
and whether its behaviour is practically tradable.

Score (0-100):
  40  OOS risk-adjusted return   min-max normalized OOS Sharpe
  20  OOS growth                 min-max normalized OOS CAGR
  15  OOS drawdown control       min-max normalized -(OOS max drawdown)
  15  robustness                 0.5 * rank consistency (1 - |ISr-OOSr|/(N-1))
                                 + 0.5 * CAGR retention (OOS/IS, capped at 1, floored 0)
  10  tradability                min-max normalized -(OOS annual turnover)
                                 (lower churn = cheaper and easier to run live)

Writes NASDAQ/out/election.json with full per-agent component breakdown.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WEIGHTS = {"oos_sharpe": 40, "oos_cagr": 20, "oos_dd": 15, "robustness": 15, "tradability": 10}


def minmax(vals):
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return [0.5] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]


def main():
    is_res = json.loads((ROOT / "out" / "results_is.json").read_text())
    oos_res = json.loads((ROOT / "out" / "results_oos.json").read_text())
    im = {a["meta"]["handle"]: a["metrics"] for a in is_res["agents"]}
    om = {a["meta"]["handle"]: a["metrics"] for a in oos_res["agents"]}
    handles = sorted(om)
    n = len(handles)

    is_rank = {h: r + 1 for r, h in enumerate(
        sorted(handles, key=lambda h: -im[h]["final_equity"]))}
    oos_rank = {h: r + 1 for r, h in enumerate(
        sorted(handles, key=lambda h: -om[h]["final_equity"]))}

    sharpe_n = dict(zip(handles, minmax([om[h]["sharpe"] for h in handles])))
    cagr_n = dict(zip(handles, minmax([om[h]["cagr"] for h in handles])))
    dd_n = dict(zip(handles, minmax([om[h]["max_drawdown"] for h in handles])))  # less-negative = higher
    turn_n = dict(zip(handles, minmax([-(om[h]["turnover_annual"] or 0) for h in handles])))

    rows = []
    for h in handles:
        rank_consist = 1 - abs(is_rank[h] - oos_rank[h]) / max(1, n - 1)
        retention = 0.0
        if im[h]["cagr"] > 0:
            retention = max(0.0, min(1.0, om[h]["cagr"] / im[h]["cagr"]))
        robust = 0.5 * rank_consist + 0.5 * retention
        comp = {
            "oos_sharpe": WEIGHTS["oos_sharpe"] * sharpe_n[h],
            "oos_cagr": WEIGHTS["oos_cagr"] * cagr_n[h],
            "oos_dd": WEIGHTS["oos_dd"] * dd_n[h],
            "robustness": WEIGHTS["robustness"] * robust,
            "tradability": WEIGHTS["tradability"] * turn_n[h],
        }
        rows.append({
            "handle": h,
            "score": round(sum(comp.values()), 2),
            "components": {k: round(v, 2) for k, v in comp.items()},
            "is_rank": is_rank[h], "oos_rank": oos_rank[h],
            "is": {k: im[h][k] for k in ("total_return", "cagr", "sharpe", "max_drawdown",
                                         "n_trades", "turnover_annual")},
            "oos": {k: om[h][k] for k in ("total_return", "cagr", "sharpe", "max_drawdown",
                                          "n_trades", "turnover_annual", "sortino", "calmar",
                                          "alpha_annual", "beta_tasi", "win_rate",
                                          "profit_factor")},
            "rank_consistency": round(rank_consist, 3),
            "cagr_retention": round(retention, 3),
        })

    rows.sort(key=lambda r: -r["score"])
    out = {
        "method": "OOS-dominant weighted score; see module docstring",
        "weights": WEIGHTS,
        "freeze_commit": "7e8cdf12f1a63e6e23f691ff1f01e580ca946acf",
        "windows": {
            "in_sample": [is_res["meta"]["sim_start"], is_res["meta"]["sim_end"]],
            "out_of_sample": [oos_res["meta"]["sim_start"], oos_res["meta"]["sim_end"]],
        },
        "elected": rows[0]["handle"],
        "ranking": rows,
    }
    (ROOT / "out" / "election.json").write_text(json.dumps(out, indent=1))
    print(f"ELECTED: {rows[0]['handle']} (score {rows[0]['score']})")
    for r in rows:
        print(f"  {r['handle']:9} score={r['score']:6.2f} "
              f"IS#{r['is_rank']} OOS#{r['oos_rank']} "
              f"OOS: {r['oos']['total_return']:+.1%} sh={r['oos']['sharpe']} dd={r['oos']['max_drawdown']:.1%}")


if __name__ == "__main__":
    main()
