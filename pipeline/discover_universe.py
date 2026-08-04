"""Discover every Tadawul MAIN-market listed symbol (stocks + REITs, no Nomu).

Runs on the GitHub Actions runner (open internet). Primary source: TradingView's
saudi scanner (symbol, name, sector). Fallback: brute-force probe of the known
Tadawul code ranges with batched yfinance downloads.

Writes data/universe_full.json: [{"code","name","sector"}...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Tadawul main-market code ranges (Nomu is 9xxx and excluded)
PROBE_RANGES = [
    (1010, 1400), (1810, 1840), (2001, 2400), (3001, 3100),
    (4001, 4350), (5110, 5112), (6001, 6100), (7010, 7300), (8010, 8350),
]

SECTOR_BY_PREFIX = [
    (range(1010, 1200), "Banks"),
    (range(1200, 1400), "Capital Goods / Industry"),
    (range(1810, 1840), "Consumer Services"),
    (range(2001, 2400), "Materials & Energy"),
    (range(3001, 3100), "Cement"),
    (range(4001, 4100), "Retail & Consumer"),
    (range(4100, 4300), "Diversified / Services"),
    (range(4300, 4330), "Real Estate"),
    (range(4330, 4350), "REITs"),
    (range(5110, 5112), "Utilities"),
    (range(6001, 6100), "Food & Agriculture"),
    (range(7010, 7300), "Telecom & IT"),
    (range(8010, 8350), "Insurance"),
]


def sector_for(code: int) -> str:
    for rng, name in SECTOR_BY_PREFIX:
        if code in rng:
            return name
    return "Other"


def from_tradingview():
    import requests

    body = {
        "filter": [{"left": "exchange", "operation": "equal", "right": "TADAWUL"}],
        "columns": ["name", "description", "sector", "type", "market_cap_basic"],
        "range": [0, 800],
    }
    r = requests.post(
        "https://scanner.tradingview.com/saudi/scan",
        json=body, timeout=40,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    r.raise_for_status()
    out = []
    for row in r.json().get("data", []):
        d = dict(zip(body["columns"], row.get("d", [])))
        code = str(d.get("name", ""))
        if not re.fullmatch(r"\d{4}", code):
            continue
        n = int(code)
        if n >= 9000:  # Nomu parallel market
            continue
        typ = (d.get("type") or "").lower()
        if typ and typ not in ("stock", "fund", "dr"):
            continue
        out.append({
            "code": code,
            "name": (d.get("description") or code).strip(),
            "sector": d.get("sector") or sector_for(n),
        })
    return out


def from_probe():
    import pandas as pd
    import yfinance as yf

    candidates = [str(c) for lo, hi in PROBE_RANGES for c in range(lo, hi)]
    found = []
    B = 200
    for i in range(0, len(candidates), B):
        batch = [f"{c}.SR" for c in candidates[i:i + B]]
        try:
            df = yf.download(batch, period="5d", interval="1d", progress=False,
                             group_by="ticker", threads=True)
        except Exception as exc:  # noqa: BLE001
            print(f"batch {i} failed: {exc}", file=sys.stderr)
            continue
        for sym in batch:
            try:
                sub = df[sym]["Close"].dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(sub) > 0:
                code = sym.replace(".SR", "")
                found.append({"code": code, "name": code, "sector": sector_for(int(code))})
    return found


def main() -> int:
    uni, source = [], None
    try:
        uni = from_tradingview()
        source = "tradingview"
    except Exception as exc:  # noqa: BLE001
        print(f"tradingview failed: {exc}", file=sys.stderr)
    if len(uni) < 150:
        print(f"tradingview returned {len(uni)}; falling back to probe", file=sys.stderr)
        probed = from_probe()
        known = {u["code"] for u in uni}
        uni = uni + [p for p in probed if p["code"] not in known]
        source = f"{source}+probe" if source else "probe"
    if len(uni) < 150:
        print(f"ERROR: only {len(uni)} symbols discovered", file=sys.stderr)
        return 1
    # merge names/sectors from the curated top-50 file where available
    cfg = json.loads((ROOT / "data" / "tickers.json").read_text())
    curated = {e["code"]: e for e in cfg["universe"]}
    for u in uni:
        if u["code"] in curated:
            u["name"] = curated[u["code"]]["name"]
            u["sector"] = curated[u["code"]]["sector"]
    uni.sort(key=lambda u: u["code"])
    (ROOT / "data" / "universe_full.json").write_text(
        json.dumps({"source": source, "count": len(uni), "universe": uni},
                   ensure_ascii=False, indent=1))
    print(f"discovered {len(uni)} main-market symbols via {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
