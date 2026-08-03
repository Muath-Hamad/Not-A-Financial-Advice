"""Enrich raw ticker CSVs with technical indicators.

Reads data/raw/{code}.csv, writes data/enriched/{code}.csv.

Indicators are computed on the split/dividend-adjusted series (Adj*) so they are
continuous across corporate actions; raw prices stay untouched for execution.
All indicators at row t use data up to and including t (no lookahead).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "enriched"
LAST_DATE = "2026-08-02"  # "up to yesterday"; the Aug 3 session was live/incomplete at fetch time

TRADING_DAYS = 250  # Tadawul trades Sun-Thu, ~250 sessions/year


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0).where(close.notna())


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    c = df["AdjClose"]
    h = df["AdjHigh"]
    l = df["AdjLow"]

    out = df.copy()
    for w in (20, 50, 100, 200):
        out[f"sma{w}"] = c.rolling(w).mean()
    out["ema12"] = c.ewm(span=12, min_periods=12).mean()
    out["ema26"] = c.ewm(span=26, min_periods=26).mean()
    out["macd"] = out["ema12"] - out["ema26"]
    out["macd_signal"] = out["macd"].ewm(span=9, min_periods=9).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    out["rsi14"] = rsi(c, 14)

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    out["bb_mid"] = mid
    out["bb_up"] = mid + 2 * sd
    out["bb_low"] = mid - 2 * sd
    width = (out["bb_up"] - out["bb_low"])
    out["bb_pctb"] = ((c - out["bb_low"]) / width.replace(0, np.nan)).clip(-0.5, 1.5)

    out["atr14"] = atr(h, l, c, 14)
    out["atr_pct"] = out["atr14"] / c

    for w, name in ((1, "ret_1d"), (5, "ret_1w"), (21, "ret_1m"), (63, "ret_3m"),
                    (126, "ret_6m"), (252, "ret_12m")):
        out[name] = c.pct_change(w)

    out["vol_21"] = c.pct_change().rolling(21).std() * np.sqrt(TRADING_DAYS)
    peak = c.cummax()
    out["drawdown"] = c / peak - 1.0
    hi52 = c.rolling(252, min_periods=60).max()
    lo52 = c.rolling(252, min_periods=60).min()
    out["dist_52w_high"] = c / hi52 - 1.0
    out["dist_52w_low"] = c / lo52 - 1.0
    out["vol_sma20"] = df["Volume"].rolling(20).mean()
    out["turnover_sar"] = df["Close"] * df["Volume"]
    return out


def main() -> int:
    manifest = json.loads((RAW_DIR / "_manifest.json").read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tasi = pd.read_csv(RAW_DIR / "TASI.csv", index_col="Date", parse_dates=True)
    tasi = tasi.loc[:LAST_DATE]
    tasi_ret63 = tasi["AdjClose"].pct_change(63)

    n = 0
    for code, meta in manifest.items():
        if meta.get("status") == "failed":
            print(f"skip {code}: fetch failed", file=sys.stderr)
            continue
        df = pd.read_csv(RAW_DIR / f"{code}.csv", index_col="Date", parse_dates=True)
        df = df.loc[:LAST_DATE]
        df = enrich(df)
        if code != "TASI":
            df["rs_tasi_3m"] = df["ret_3m"] - tasi_ret63.reindex(df.index)
        df.to_csv(OUT_DIR / f"{code}.csv", float_format="%.6f")
        n += 1
    print(f"enriched {n} tickers -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
