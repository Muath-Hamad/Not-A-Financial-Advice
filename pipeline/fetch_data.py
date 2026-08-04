"""Fetch daily OHLCV + dividends/splits for the top-50 TASI universe from Yahoo Finance.

Designed to run on a GitHub Actions runner (open internet). Writes one CSV per
ticker into data/raw/ plus a _manifest.json describing what was fetched.

Columns written per ticker:
    Date, Open, High, Low, Close, Volume, Dividends, Splits,
    AdjOpen, AdjHigh, AdjLow, AdjClose

Raw prices are used by the simulation engine for order fills and cash accounting
(dividends credited as cash, splits adjust share counts); the Adj* series are
split/dividend-adjusted and used for indicators and return continuity.
"""

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

START = os.environ.get("FETCH_START", "2021-01-01")
END = os.environ.get("FETCH_END") or "2026-08-03"  # exclusive; last row 2026-08-02
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
MIN_ROWS = 120   # newly-listed names are allowed short histories
MIN_OK_FRACTION = 0.85


def yahoo_symbol(code: str) -> str:
    return code if code.startswith("^") else f"{code}.SR"


def fetch_yfinance(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    t = yf.Ticker(symbol)
    raw = t.history(start=START, end=END, auto_adjust=False, actions=True)
    adj = t.history(start=START, end=END, auto_adjust=True, actions=False)
    if raw is None or raw.empty or adj is None or adj.empty:
        raise RuntimeError("empty frame")

    def flatten(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df.index = df.index.normalize()
        return df

    raw, adj = flatten(raw), flatten(adj)
    out = pd.DataFrame(index=raw.index)
    out["Open"] = raw["Open"]
    out["High"] = raw["High"]
    out["Low"] = raw["Low"]
    out["Close"] = raw["Close"]
    out["Volume"] = raw["Volume"]
    out["Dividends"] = raw.get("Dividends", pd.Series(0.0, index=raw.index))
    out["Splits"] = raw.get("Stock Splits", pd.Series(0.0, index=raw.index))
    for col in ["Open", "High", "Low", "Close"]:
        out[f"Adj{col.replace(' ', '')}"] = adj[col].reindex(out.index)
    out.index.name = "Date"
    return out


def fetch_chart_api(symbol: str) -> pd.DataFrame:
    """Fallback: hit Yahoo's v8 chart endpoint directly."""
    import requests

    p1 = int(pd.Timestamp(START).timestamp())
    p2 = int(pd.Timestamp(END).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={p1}&period2={p2}&interval=1d&events=div%7Csplit"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    idx = pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Riyadh").tz_localize(None).normalize()
    out = pd.DataFrame(
        {
            "Open": q["open"],
            "High": q["high"],
            "Low": q["low"],
            "Close": q["close"],
            "Volume": q["volume"],
        },
        index=idx,
    )
    out["Dividends"] = 0.0
    out["Splits"] = 0.0
    events = result.get("events", {})
    for _, d in events.get("dividends", {}).items():
        day = pd.to_datetime(d["date"], unit="s", utc=True).tz_convert("Asia/Riyadh").tz_localize(None).normalize()
        if day in out.index:
            out.loc[day, "Dividends"] += d["amount"]
    for _, s in events.get("splits", {}).items():
        day = pd.to_datetime(s["date"], unit="s", utc=True).tz_convert("Asia/Riyadh").tz_localize(None).normalize()
        if day in out.index:
            out.loc[day, "Splits"] = s["numerator"] / s["denominator"]
    ratio = (pd.Series(adjclose, index=idx) / out["Close"]) if adjclose else 1.0
    for col in ["Open", "High", "Low", "Close"]:
        out[f"Adj{col}"] = out[col] * ratio
    out.index.name = "Date"
    return out.dropna(subset=["Close"])


def main() -> int:
    full = ROOT / "data" / "universe_full.json"
    cfg = json.loads((ROOT / "data" / "tickers.json").read_text())
    if full.exists():
        entries = [cfg["benchmark"]] + json.loads(full.read_text())["universe"]
    else:
        entries = [cfg["benchmark"]] + cfg["universe"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for stale in RAW_DIR.glob("*.csv"):
        stale.unlink()
    manifest = {}
    ok = 0
    for i, e in enumerate(entries):
        code = e.get("code") or e["symbol"]
        symbol = e.get("symbol") or yahoo_symbol(code)
        df, source, err = None, None, None
        for attempt in range(3):
            try:
                df = fetch_yfinance(symbol)
                source = "yfinance"
                break
            except Exception as exc:  # noqa: BLE001
                err = f"yfinance: {exc}"
                time.sleep(2 * (attempt + 1))
        if df is None or df.empty:
            for attempt in range(3):
                try:
                    df = fetch_chart_api(symbol)
                    source = "chart_api"
                    break
                except Exception as exc:  # noqa: BLE001
                    err = f"{err} | chart_api: {exc}"
                    time.sleep(2 * (attempt + 1))
        code_safe = code.replace("^", "").replace(".", "_")
        if df is not None and not df.empty:
            df = df.dropna(subset=["Close"]).sort_index()
            df = df[~df.index.duplicated(keep="last")]
            df.to_csv(RAW_DIR / f"{code_safe}.csv.gz", float_format="%.6f")
            rows = len(df)
            status = "ok" if rows >= MIN_ROWS else "short"
            if status == "ok":
                ok += 1
            manifest[code_safe] = {
                "symbol": symbol,
                "name": e.get("name", code),
                "sector": e.get("sector", "Other"),
                "rows": rows,
                "first": str(df.index[0].date()),
                "last": str(df.index[-1].date()),
                "source": source,
                "status": status,
            }
            print(f"[{i + 1}/{len(entries)}] {symbol} {e['name']}: {rows} rows "
                  f"({df.index[0].date()} → {df.index[-1].date()}) via {source}")
        else:
            manifest[code_safe] = {
                "symbol": symbol, "name": e["name"], "sector": e["sector"],
                "rows": 0, "status": "failed", "error": err,
            }
            print(f"[{i + 1}/{len(entries)}] {symbol} {e['name']}: FAILED ({err})")
        time.sleep(0.35)

    (RAW_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nFetched {ok}/{len(entries)} symbols with >= {MIN_ROWS} rows")
    if ok < MIN_OK_FRACTION * len(entries):
        print(f"ERROR: below {MIN_OK_FRACTION:.0%} success threshold", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
