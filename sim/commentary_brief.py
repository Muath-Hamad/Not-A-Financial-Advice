"""Extract a compact per-agent 'story brief' from out/results.json for the
commentary workflow: yearly performance, rank evolution, notable trades,
big market days, and majlis excerpts. Writes out/briefs.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    res = json.loads((ROOT / "out" / "results.json").read_text())
    dates = res["dates"]
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    names = res["meta"]["names"]

    # rank per agent per year-end
    year_ends = {}
    for i, d in enumerate(dates):
        year_ends[d[:4]] = i  # last session index of each year

    briefs = {}
    for a in res["agents"]:
        eq = pd.Series(a["equity"], index=idx)
        yearly = {}
        prev_val = eq.iloc[0]
        prev_end = None
        for y, i in year_ends.items():
            end_val = a["equity"][i]
            start_val = a["equity"][0] if prev_end is None else a["equity"][prev_end]
            yearly[y] = {
                "end_equity": round(end_val),
                "year_return": round(end_val / start_val - 1, 4),
                "rank": 1 + sum(1 for b in res["agents"] if b["equity"][i] > end_val),
            }
            prev_end = i
        sells = [t for t in a["trades"] if t["side"] == "sell"]
        best = sorted(sells, key=lambda t: -t.get("realized_pnl", 0))[:3]
        worst = sorted(sells, key=lambda t: t.get("realized_pnl", 0))[:3]
        my_shouts = [c for c in res["chat"] if c["handle"] == a["meta"]["handle"]]
        others = [c for c in res["chat"] if c["handle"] != a["meta"]["handle"]]
        briefs[a["meta"]["handle"]] = {
            "meta": a["meta"],
            "metrics": a["metrics"],
            "yearly": yearly,
            "dividends_received": a["dividends_received"],
            "commissions_paid": a["commissions_paid"],
            "best_trades": [{**t, "name": names.get(t["code"], t["code"])} for t in best],
            "worst_trades": [{**t, "name": names.get(t["code"], t["code"])} for t in worst],
            "n_trades": a["metrics"]["n_trades"],
            "sample_own_shouts": my_shouts[:: max(1, len(my_shouts) // 12)][:12],
            "sample_others_shouts": others[:: max(1, len(others) // 15)][:15],
            "final_positions": a["final_positions"],
        }

    events = res["events"]
    big = sorted(events, key=lambda e: abs(e["tasi_ret"]), reverse=True)[:12]
    out = {
        "briefs": briefs,
        "events_big": big,
        "leaderboard_final": sorted(
            [{"handle": a["meta"]["handle"], "name": a["meta"]["name"],
              "final": a["metrics"]["final_equity"], "ret": a["metrics"]["total_return"]}
             for a in res["agents"]], key=lambda x: -x["final"]),
        "tasi_return": res["tasi_metrics"]["total_return"],
        "sim_span": [res["meta"]["sim_start"], res["meta"]["sim_end"]],
    }
    (ROOT / "out" / "briefs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote out/briefs.json")


if __name__ == "__main__":
    main()
