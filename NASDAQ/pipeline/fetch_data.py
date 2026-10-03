"""Fetch daily OHLCV + dividends/splits for the AAOIFI-screened NASDAQ universe.

Designed to run on a GitHub Actions runner (open internet). Writes one CSV per
ticker into data/raw/ plus a _manifest.json describing what was fetched.

Columns written per ticker:
    Date, Open, High, Low, Close, Volume, Dividends, Splits,
    AdjOpen, AdjHigh, AdjLow, AdjClose

Raw prices are used by the simulation engine for order fills and cash accounting
(dividends credited as cash, splits adjust share counts); the Adj* series are
split/dividend-adjusted and used for indicators and return continuity.

Live mode (FETCH_EXPECT_LAST=<session>, set by the live Cycle A): Yahoo drops
the newest daily bar of every name that trades after hours for a while once
the post-market closes at 20:00 ET, and serves it again later that evening.
The benchmark and names with no extended-hours trading keep theirs. When too
few names reach the expected session, the lagging ones are re-polled for up
to FETCH_WAIT_MAX_MIN minutes rather than handing the data gate a stale
universe. Each round is logged to _fetch_wait.json.
"""

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

START = os.environ.get("FETCH_START", "2015-01-01")
_default_end = str(__import__("datetime").date.today() + __import__("datetime").timedelta(days=1))
END = os.environ.get("FETCH_END") or _default_end  # exclusive; empty env = through today
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / os.environ.get("FETCH_RAW_SUBDIR", "data/raw")
MIN_ROWS = 120   # newly-listed names are allowed short histories
MIN_OK_FRACTION = float(os.environ.get("FETCH_MIN_OK", "0.85"))
EXPECT_LAST = os.environ.get("FETCH_EXPECT_LAST", "")       # live: the session decided on
EXPECT_MIN = float(os.environ.get("FETCH_EXPECT_MIN", "0.95"))
WAIT_MAX_S = float(os.environ.get("FETCH_WAIT_MAX_MIN", "0")) * 60
WAIT_POLL_S = float(os.environ.get("FETCH_WAIT_POLL_S", "600"))
WAIT_PROBES = 5   # laggards re-polled per round until one shows the bar
BENCHMARK = "IXIC"


def yahoo_symbol(code: str) -> str:
    return code  # US tickers are used verbatim; the benchmark carries its own ^ symbol


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
    idx = pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
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
        day = pd.to_datetime(d["date"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
        if day in out.index:
            out.loc[day, "Dividends"] += d["amount"]
    for _, s in events.get("splits", {}).items():
        day = pd.to_datetime(s["date"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
        if day in out.index:
            out.loc[day, "Splits"] = s["numerator"] / s["denominator"]
    ratio = (pd.Series(adjclose, index=idx) / out["Close"]) if adjclose else 1.0
    for col in ["Open", "High", "Low", "Close"]:
        out[f"Adj{col}"] = out[col] * ratio
    out.index.name = "Date"
    return out.dropna(subset=["Close"])


def fetch_one(symbol: str):
    """yfinance with retries, then Yahoo's chart API. Returns (df, source, error)."""
    df, source, err = None, None, None
    for attempt in range(4):
        try:
            df = fetch_yfinance(symbol)
            source = "yfinance"
            break
        except Exception as exc:  # noqa: BLE001
            err = f"yfinance: {exc}"
            msg = str(exc)
            if "Rate" in msg or "Too Many" in msg or "429" in msg:
                print(f"  rate limited on {symbol}; cooling 75s", file=sys.stderr)
                time.sleep(75)
            else:
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
    return df, source, err


def store(code_safe: str, e: dict, symbol: str, df, source: str, err) -> dict:
    """Write one name's CSV and return its manifest entry."""
    if df is not None and not df.empty:
        df = df.dropna(subset=["Close"]).sort_index()
        df = df[~df.index.duplicated(keep="last")]
    if df is None or df.empty:
        return {"symbol": symbol, "name": e["name"], "sector": e["sector"],
                "rows": 0, "status": "failed", "error": err}
    df.to_csv(RAW_DIR / f"{code_safe}.csv.gz", float_format="%.6f")
    rows = len(df)
    return {
        "symbol": symbol,
        "name": e.get("name", code_safe),
        "sector": e.get("sector", "Other"),
        "rows": rows,
        "first": str(df.index[0].date()),
        "last": str(df.index[-1].date()),
        "source": source,
        "status": "ok" if rows >= MIN_ROWS else "short",
    }


def session_coverage(manifest: dict, expect: str) -> float:
    """Share of fetched names (the benchmark aside) whose last bar is `expect`:
    the coverage measure of Cycle A's data gate (live/data_gate.py)."""
    names = [c for c, m in manifest.items() if m.get("status") == "ok" and c != BENCHMARK]
    return sum(manifest[c].get("last") == expect for c in names) / max(1, len(names))


def lagging(manifest: dict, expect: str) -> list[str]:
    """Fetched names, the benchmark included, whose last bar predates `expect`,
    most recently updated first: a name one bar short is waiting for tonight's
    bar, one stale for weeks is halted or delisted and makes a useless probe."""
    lag = [c for c, m in manifest.items()
           if m.get("status") == "ok" and m.get("last", "") < expect]
    return sorted(lag, key=lambda c: manifest[c]["last"], reverse=True)


def wait_for_session(manifest: dict, expect: str, min_cov: float, max_wait_s: float,
                     poll_s: float, refetch, sleep=None, clock=None) -> dict:
    """Re-poll lagging names until the benchmark and at least `min_cov` of the
    names have a bar at `expect`.

    `refetch(code)` refetches one name, updates its manifest entry and returns
    whether it now reaches `expect`. Each round first re-polls a few probes and
    only refetches every laggard once a probe shows the bar, so a long wait
    costs Yahoo a handful of requests per round. After coverage passes, rounds
    continue only while they still bring names in; a name halted for the day
    never arrives and must not hold the cycle. Gives up when the next round
    would overrun `max_wait_s`, leaving the verdict to the data gate.
    """
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    t0 = clock()
    cov = session_coverage(manifest, expect)
    log = {"expect": expect, "min_coverage": min_cov, "coverage_before": round(cov, 4),
           "lagging_before": len(lagging(manifest, expect)), "rounds": []}
    caught = None
    while lagging(manifest, expect):
        enough = cov >= min_cov and BENCHMARK not in lagging(manifest, expect)
        if enough and caught in (None, 0):
            break
        if clock() - t0 + poll_s > max_wait_s:
            log["gave_up"] = True
            break
        sleep(poll_s)
        lag = lagging(manifest, expect)
        probes = lag[:WAIT_PROBES]
        caught = sum(bool(refetch(c)) for c in probes)
        polled = len(probes)
        if caught:
            for c in lag[WAIT_PROBES:]:
                caught += bool(refetch(c))
                polled += 1
        cov = session_coverage(manifest, expect)
        log["rounds"].append({"minute": round((clock() - t0) / 60, 1), "polled": polled,
                              "caught_up": caught, "coverage": round(cov, 4)})
        print(f"  waiting for {expect}: round {len(log['rounds'])}, {caught}/{polled} "
              f"caught up, coverage {cov:.1%}", flush=True)
    log.update(coverage_after=round(cov, 4), lagging_after=len(lagging(manifest, expect)),
               waited_min=round((clock() - t0) / 60, 1))
    return log


def main() -> int:
    screened = json.loads((ROOT / "data" / "universe_screened.json").read_text())
    benchmark = {"symbol": "^IXIC", "code": BENCHMARK,
                 "name": "NASDAQ Composite", "sector": "Index"}
    entries = [benchmark] + [
        {"code": u["code"], "name": u["name"], "sector": u.get("sector") or "Other"}
        for u in screened["universe"]]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for stale in RAW_DIR.glob("*.csv"):
        stale.unlink()
    (RAW_DIR / "_fetch_wait.json").unlink(missing_ok=True)
    manifest = {}
    by_code = {}
    for i, e in enumerate(entries):
        code = e.get("code") or e["symbol"]
        symbol = e.get("symbol") or yahoo_symbol(code)
        code_safe = code.replace("^", "").replace(".", "_")
        by_code[code_safe] = (e, symbol)
        df, source, err = fetch_one(symbol)
        m = manifest[code_safe] = store(code_safe, e, symbol, df, source, err)
        if m["status"] == "failed":
            print(f"[{i + 1}/{len(entries)}] {symbol} {e['name']}: FAILED ({err})")
        else:
            print(f"[{i + 1}/{len(entries)}] {symbol} {e['name']}: {m['rows']} rows "
                  f"({m['first']} → {m['last']}) via {source}")
        time.sleep(0.5)
        if (i + 1) % 40 == 0:
            time.sleep(15)  # periodic breather to stay under Yahoo's rate limits
    (RAW_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))

    if EXPECT_LAST:
        def refetch(code: str) -> bool:
            e, symbol = by_code[code]
            df, source, err = fetch_one(symbol)
            m = store(code, e, symbol, df, source, err)
            if m["status"] == "ok":  # a failed retry keeps the earlier fetch
                manifest[code] = m
            time.sleep(0.5)
            return manifest[code].get("last") == EXPECT_LAST

        wait = wait_for_session(manifest, EXPECT_LAST, EXPECT_MIN, WAIT_MAX_S,
                                WAIT_POLL_S, refetch)
        (RAW_DIR / "_fetch_wait.json").write_text(json.dumps(wait, indent=2))
        (RAW_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))
        if wait["rounds"]:
            print(f"Waited {wait['waited_min']} min for {EXPECT_LAST}: coverage "
                  f"{wait['coverage_before']:.1%} -> {wait['coverage_after']:.1%}")

    ok = sum(m["status"] == "ok" for m in manifest.values())
    print(f"\nFetched {ok}/{len(entries)} symbols with >= {MIN_ROWS} rows")
    if ok < MIN_OK_FRACTION * len(entries):
        print(f"ERROR: below {MIN_OK_FRACTION:.0%} success threshold", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
