"""Build the self-contained dashboard: inject a slimmed results payload into template.html.

Usage: python dashboard/build_dashboard.py
Reads  out/results.json (+ out/commentary.json if present)
Writes dashboard/index.html
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Validated categorical palette (dataviz reference instance): slot -> (light, dark)
PALETTE = [
    ("#2a78d6", "#3987e5"),  # blue
    ("#eb6834", "#d95926"),  # orange
    ("#1baf7a", "#199e70"),  # aqua
    ("#eda100", "#c98500"),  # yellow
    ("#e87ba4", "#d55181"),  # magenta
    ("#008300", "#008300"),  # green
    ("#4a3aa7", "#9085e9"),  # violet
    ("#e34948", "#e66767"),  # red
]


def slim_trades(trades):
    out = []
    for t in trades:
        out.append([
            t["date"], t["code"], t["side"], t["shares"], t["price"], t["value"],
            round(t.get("realized_pnl", 0.0), 2) if t["side"] == "sell" else None,
            t.get("reason", "")[:140],
        ])
    return out


def sample_journal(journal, events_dates, max_entries=160):
    """Keep the characterful subset: event days, sentiment swings, spaced regulars."""
    if len(journal) <= max_entries:
        return journal
    keep = {}
    prev_s = None
    for i, j in enumerate(journal):
        score = 0.0
        if j["date"] in events_dates:
            score += 2.0
        if prev_s is not None:
            score += abs(j["sentiment"] - prev_s)
        prev_s = j["sentiment"]
        score += (len(j["note"]) > 120) * 0.3
        keep[i] = score
    picked = sorted(sorted(keep, key=keep.get, reverse=True)[: max_entries - 20])
    # always include first and last entries + regular spacing fillers
    n = len(journal)
    regs = set(range(0, n, max(1, n // 20)))
    idx = sorted(set(picked) | regs | {0, n - 1})[:max_entries]
    return [journal[i] for i in idx]


def condense_holdings(monthly, names):
    out = []
    for h in monthly:
        pos = sorted(h["positions"].items(), key=lambda kv: -kv[1]["value"])
        total = h["cash"] + sum(p["value"] for _, p in pos)
        top = [[c, round(p["value"], 0)] for c, p in pos[:9]]
        other = sum(p["value"] for _, p in pos[9:])
        if other > 0:
            top.append(["other", round(other, 0)])
        out.append({"date": h["date"], "cash": round(h["cash"], 0), "total": round(total, 0), "top": top})
    return out


def main():
    res = json.loads((ROOT / "out" / "results.json").read_text())
    commentary_path = ROOT / "out" / "commentary.json"
    commentary = json.loads(commentary_path.read_text()) if commentary_path.exists() else {}

    events_dates = {e["date"] for e in res["events"]}
    agents = []
    for i, a in enumerate(res["agents"]):
        com = commentary.get(a["meta"]["handle"], {})
        agents.append({
            **{k: a["meta"].get(k) for k in ("handle", "name", "emoji", "tagline", "character", "risk_style")},
            "slot": i + 1,
            "color": PALETTE[i % 8][0],
            "color_dark": PALETTE[i % 8][1],
            "equity": [round(x) for x in a["equity"]],
            "sentiment": a["sentiment"],
            "metrics": a["metrics"],
            "trades": slim_trades(a["trades"]),
            "journal": sample_journal(a["journal"], events_dates),
            "holdings_monthly": condense_holdings(a["holdings_monthly"], res["meta"]["names"]),
            "dividends_received": a["dividends_received"],
            "commissions_paid": a["commissions_paid"],
            "letters": com.get("letters", []),
            "epitaph": com.get("epitaph", ""),
        })

    chat = res["chat"]
    extra_chat = []
    for h, com in commentary.items():
        for msg in com.get("extra_chat", []):
            extra_chat.append({**msg, "handle": h, "generated": True})
    chat = sorted(chat + extra_chat, key=lambda m: m["date"])

    payload = {
        "meta": res["meta"],
        "dates": res["dates"],
        "tasi": [round(x) for x in res["tasi"]],
        "tasi_metrics": res["tasi_metrics"],
        "events": res["events"],
        "chat": chat,
        "agents": agents,
    }

    template = (ROOT / "dashboard" / "template.html").read_text()
    data_js = "window.DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    html = template.replace("/*__DATA__*/", data_js)
    out = ROOT / "dashboard" / "index.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
