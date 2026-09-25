"""Build the NASDAQ Arena dashboard: election + IS/OOS comparison.

Reads out/results_is.json, out/results_oos.json, out/election.json,
data/universe_screened.json. Writes dashboard/index.html.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PALETTE = [
    ("#2a78d6", "#3987e5"),  # blue
    ("#eb6834", "#d95926"),  # orange
    ("#1baf7a", "#199e70"),  # aqua
    ("#eda100", "#c98500"),  # yellow
    ("#e87ba4", "#d55181"),  # magenta
]

MAX_POINTS = 700


def downsample(dates, vals, n=MAX_POINTS):
    if len(vals) <= n:
        return dates, [round(v) for v in vals]
    step = len(vals) / n
    idx = sorted({int(i * step) for i in range(n)} | {len(vals) - 1})
    return [dates[i] for i in idx], [round(vals[i]) for i in idx]


def slim_period(res, trades_keep=True):
    dates = res["dates"]
    d2, tasi = downsample(dates, res["tasi"])
    agents = {}
    for a in res["agents"]:
        h = a["meta"]["handle"]
        _, eq = downsample(dates, a["equity"])
        agents[h] = {
            "equity": eq,
            "metrics": a["metrics"],
            "adaptations": a.get("adaptations", []),
            "dividends": a.get("dividends_received", 0),
            "fees": a.get("commissions_paid", 0),
            "trades": [[t["date"], t["code"], t["side"], t["shares"], t["price"],
                        t["value"], round(t.get("realized_pnl", 0), 2) if t["side"] == "sell" else None,
                        t.get("reason", "")[:110]]
                       for t in a["trades"]] if trades_keep else [],
        }
    return {"dates": d2, "tasi": tasi, "tasi_metrics": res["tasi_metrics"],
            "meta": res["meta"], "agents": agents}


def main():
    is_res = json.loads((ROOT / "out" / "results_is.json").read_text())
    oos_res = json.loads((ROOT / "out" / "results_oos.json").read_text())
    election = json.loads((ROOT / "out" / "election.json").read_text())
    screen = json.loads((ROOT / "data" / "universe_screened.json").read_text())

    from collections import Counter
    reasons = Counter()
    for r in screen["rejected_detail"]:
        for x in r["business_reasons"]:
            reasons[x] += 1
        for x in r["ratio_reasons"]:
            key = ("debt/mcap >= 30%" if x.startswith("debt/mcap")
                   else "cash/mcap >= 30%" if x.startswith("cash/mcap") else x)
            reasons[key] += 1

    handles = [r["handle"] for r in election["ranking"]]
    meta_by = {a["meta"]["handle"]: a["meta"] for a in oos_res["agents"]}
    agents_meta = {}
    for i, h in enumerate(handles):
        m = meta_by[h]
        agents_meta[h] = {
            "name": m.get("name", h), "style": m.get("style", m.get("tagline", "")),
            "risk_style": m.get("risk_style", ""),
            "color": PALETTE[i % 5][0], "color_dark": PALETTE[i % 5][1],
            "param_space": m.get("param_space", {}),
        }

    payload = {
        "election": election,
        "agents_meta": agents_meta,
        "screen": {
            "reference": screen["reference"],
            "screened": screen["screened"], "passed": screen["passed"],
            "rejected": screen["rejected"],
            "rejection_reasons": dict(reasons.most_common(12)),
            "top_passed": [{"code": u["code"], "name": u["name"],
                            "debt_ratio": u.get("debt_ratio"), "cash_ratio": u.get("cash_ratio")}
                           for u in screen["universe"][:15]],
            "sample_rejected": [{"code": r["code"], "name": r["name"],
                                 "why": (r["business_reasons"] + r["ratio_reasons"])[:2]}
                                for r in screen["rejected_detail"][:15]],
        },
        "is": slim_period(is_res, trades_keep=False),
        "oos": slim_period(oos_res, trades_keep=True),
    }

    template = (ROOT / "dashboard" / "template.html").read_text()
    data_js = "window.DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    out = ROOT / "dashboard" / "index.html"
    out.write_text(template.replace("/*__DATA__*/", data_js))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
