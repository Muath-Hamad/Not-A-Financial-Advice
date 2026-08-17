"""Discover the top-N NASDAQ-listed companies by market capitalization.

Runs on a GitHub Actions runner (open internet).

Primary source: NASDAQ's own screener API (one call, gives symbol, name,
market cap, sector, industry for every listed company).
Fallback: the nasdaqtrader.com symbol directory + batched yfinance market caps.

Writes NASDAQ/data/universe_top.json.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "universe_top.json"
TOP_N = int(__import__("os").environ.get("DISCOVER_TOP_N", "500"))

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

# common-stock symbols only: no warrants (W), rights (R), units (U) on 5-letter
# SPAC-style tickers, no test issues, no ^ / . / ~ share classes beyond plain
SYMBOL_OK = re.compile(r"^[A-Z]{1,5}$")


def parse_mcap(raw) -> float:
    if raw in (None, "", "NA"):
        return 0.0
    s = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def from_nasdaq_screener():
    import requests

    url = "https://api.nasdaq.com/api/screener/stocks"
    params = {"exchange": "NASDAQ", "download": "true"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    print(f"nasdaq screener status={r.status_code} bytes={len(r.content)}", file=sys.stderr)
    r.raise_for_status()
    rows = r.json()["data"]["rows"]
    out = []
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        if not SYMBOL_OK.fullmatch(sym):
            continue
        if len(sym) == 5 and sym[-1] in ("W", "R", "U"):
            continue
        mcap = parse_mcap(row.get("marketCap"))
        if mcap <= 0:
            continue
        out.append({
            "code": sym,
            "name": (row.get("name") or sym).strip(),
            "mcap": mcap,
            "sector": (row.get("sector") or "").strip(),
            "industry": (row.get("industry") or "").strip(),
            "country": (row.get("country") or "").strip(),
        })
    return out


def from_symbol_directory():
    """Fallback: full symbol list without market caps, then yfinance for mcap."""
    import requests
    import yfinance as yf

    r = requests.get("https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
                     headers={"User-Agent": HEADERS["User-Agent"]}, timeout=60)
    r.raise_for_status()
    symbols = []
    for line in r.text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 7 or parts[0] == "File Creation Time":
            continue
        sym, name, _cat, test_issue, _status, _lot, etf = parts[:7]
        sym = sym.strip().upper()
        if test_issue.strip() == "Y" or etf.strip() == "Y":
            continue
        if not SYMBOL_OK.fullmatch(sym) or (len(sym) == 5 and sym[-1] in ("W", "R", "U")):
            continue
        symbols.append((sym, name.strip()))
    print(f"symbol directory: {len(symbols)} candidates", file=sys.stderr)

    out = []
    for i, (sym, name) in enumerate(symbols):
        try:
            fi = yf.Ticker(sym).fast_info
            mcap = float(fi.market_cap or 0)
        except Exception:  # noqa: BLE001
            mcap = 0.0
        if mcap > 0:
            out.append({"code": sym, "name": name, "mcap": mcap,
                        "sector": "", "industry": "", "country": ""})
        if i % 50 == 0:
            print(f"  fast_info {i}/{len(symbols)}: kept {len(out)}", file=sys.stderr)
            time.sleep(4)
        time.sleep(0.15)
    return out


def main() -> int:
    uni = []
    try:
        uni = from_nasdaq_screener()
    except Exception as exc:  # noqa: BLE001
        print(f"nasdaq screener failed: {exc}", file=sys.stderr)
    if len(uni) < 300:
        print("falling back to symbol directory + yfinance", file=sys.stderr)
        try:
            uni = from_symbol_directory()
        except Exception as exc:  # noqa: BLE001
            print(f"fallback failed: {exc}", file=sys.stderr)
    if len(uni) < 300:
        if OUT.exists():
            print("discovery weak; keeping existing universe_top.json", file=sys.stderr)
            return 0
        print(f"ERROR: only {len(uni)} symbols discovered", file=sys.stderr)
        return 1

    uni.sort(key=lambda u: -u["mcap"])
    top = uni[:TOP_N]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"count": len(top), "as_of": "runner fetch date", "universe": top},
        ensure_ascii=False, indent=1))
    print(f"discovered {len(uni)} NASDAQ names; kept top {len(top)} by market cap "
          f"(floor: ${top[-1]['mcap']/1e9:.2f}B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
