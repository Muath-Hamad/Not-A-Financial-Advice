"""Discover every Tadawul MAIN-market listed symbol (stocks + REITs, no Nomu).

Runs on the GitHub Actions runner (open internet). Sources, in order:
1. TradingView scanner (symbol + name + sector)
2. Mubasher public API
3. Wikipedia's list of Tadawul-listed companies
4. Throttled brute-force probe of Tadawul code ranges via batched yfinance
Results are unioned; the curated top-50 file overrides names/sectors.

Writes data/universe_full.json. If every source fails but a previous
universe_full.json exists, keeps it and exits 0.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "universe_full.json"

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

CODE_RE = re.compile(r"^[1-8]\d{3}$")


def sector_for(code: int) -> str:
    for rng, name in SECTOR_BY_PREFIX:
        if code in rng:
            return name
    return "Other"


def in_probe_ranges(n: int) -> bool:
    return any(lo <= n < hi for lo, hi in PROBE_RANGES)


def from_tradingview():
    import requests

    body = {
        "filter": [{"left": "exchange", "operation": "equal", "right": "TADAWUL"}],
        "columns": ["name", "description", "sector", "type"],
        "range": [0, 800],
    }
    r = requests.post(
        "https://scanner.tradingview.com/saudi/scan",
        json=body, timeout=40,
        headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
            "Accept": "application/json",
        },
    )
    print(f"tradingview status={r.status_code} bytes={len(r.content)}", file=sys.stderr)
    r.raise_for_status()
    out = []
    for row in r.json().get("data", []):
        d = dict(zip(body["columns"], row.get("d", [])))
        code = str(d.get("name", ""))
        if not CODE_RE.fullmatch(code) or not in_probe_ranges(int(code)):
            continue
        typ = (d.get("type") or "").lower()
        if typ and typ not in ("stock", "fund", "dr"):
            continue
        out.append({"code": code,
                    "name": (d.get("description") or code).strip(),
                    "sector": d.get("sector") or sector_for(int(code))})
    return out


def from_mubasher():
    import requests

    out, start = [], 0
    while start < 1000:
        r = requests.get(
            "https://www.mubasher.info/api/1/stocks",
            params={"country": "sa", "start": start, "size": 200},
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Accept": "application/json"},
        )
        print(f"mubasher start={start} status={r.status_code}", file=sys.stderr)
        r.raise_for_status()
        rows = r.json().get("rows", [])
        if not rows:
            break
        for row in rows:
            code = re.sub(r"\D", "", str(row.get("symbol", "")))[:4]
            if CODE_RE.fullmatch(code) and in_probe_ranges(int(code)):
                out.append({"code": code,
                            "name": (row.get("name") or code).strip(),
                            "sector": sector_for(int(code))})
        start += 200
    return out


def from_wikipedia():
    import requests

    r = requests.get(
        "https://en.wikipedia.org/wiki/List_of_companies_listed_on_the_Saudi_Stock_Exchange",
        timeout=30, headers={"User-Agent": "Mozilla/5.0 (research script)"})
    print(f"wikipedia status={r.status_code}", file=sys.stderr)
    r.raise_for_status()
    html = r.text
    out = []
    # table rows: code cell followed by a linked company name cell
    for m in re.finditer(r"<td>(\d{4})\s*</td>\s*<td[^>]*>\s*(?:<a[^>]*>)?([^<]{2,80})", html):
        code, name = m.group(1), m.group(2).strip()
        if CODE_RE.fullmatch(code) and in_probe_ranges(int(code)):
            out.append({"code": code, "name": name, "sector": sector_for(int(code))})
    return out


def from_probe():
    import yfinance as yf

    candidates = [str(c) for lo, hi in PROBE_RANGES for c in range(lo, hi)]
    found = []
    B = 150
    for i in range(0, len(candidates), B):
        batch = [f"{c}.SR" for c in candidates[i:i + B]]
        for attempt in range(2):
            try:
                df = yf.download(batch, period="5d", interval="1d", progress=False,
                                 group_by="ticker", threads=8)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"probe batch {i}: {exc}; cooling off", file=sys.stderr)
                time.sleep(90)
                df = None
        if df is None:
            continue
        for sym in batch:
            try:
                sub = df[sym]["Close"].dropna()
            except Exception:  # noqa: BLE001
                continue
            if len(sub) > 0:
                code = sym.replace(".SR", "")
                found.append({"code": code, "name": code, "sector": sector_for(int(code))})
        print(f"probe {i + B}/{len(candidates)}: {len(found)} found so far", file=sys.stderr)
        time.sleep(40)
    return found


def main() -> int:
    merged = {}
    for label, fn in [("tradingview", from_tradingview), ("mubasher", from_mubasher),
                      ("wikipedia", from_wikipedia)]:
        try:
            rows = fn()
            print(f"{label}: {len(rows)} symbols", file=sys.stderr)
            for u in rows:
                merged.setdefault(u["code"], u)
        except Exception as exc:  # noqa: BLE001
            print(f"{label} failed: {exc}", file=sys.stderr)
        if len(merged) >= 180:
            break
    if len(merged) < 150:
        print("falling back to throttled probe", file=sys.stderr)
        try:
            for u in from_probe():
                merged.setdefault(u["code"], u)
        except Exception as exc:  # noqa: BLE001
            print(f"probe failed: {exc}", file=sys.stderr)

    if len(merged) < 150:
        if OUT.exists():
            print(f"discovery weak ({len(merged)}); keeping existing universe_full.json",
                  file=sys.stderr)
            return 0
        print(f"ERROR: only {len(merged)} symbols discovered", file=sys.stderr)
        return 1

    cfg = json.loads((ROOT / "data" / "tickers.json").read_text())
    curated = {e["code"]: e for e in cfg["universe"]}
    uni = []
    for code in sorted(merged):
        u = merged[code]
        if code in curated:
            u = {"code": code, "name": curated[code]["name"], "sector": curated[code]["sector"]}
        uni.append(u)
    OUT.write_text(json.dumps({"count": len(uni), "universe": uni},
                              ensure_ascii=False, indent=1))
    print(f"discovered {len(uni)} main-market symbols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
