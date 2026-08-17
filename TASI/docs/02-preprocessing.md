# 02 — Preprocessing & indicators

`pipeline/indicators.py` turns raw OHLCV into the feature matrix every agent
sees. It reads `data/raw/{code}.csv.gz`, writes `data/enriched/{code}.csv`.

## 1. The two-price model

Every ticker carries **two** price series, and the distinction is load-bearing:

| Series | Adjusted for | Used for |
|---|---|---|
| `Open/High/Low/Close` | splits only (Yahoo's raw series) | **Execution** — order fills, position marking, cash accounting |
| `AdjOpen/AdjHigh/AdjLow/AdjClose` | splits **and** dividends | **Indicators** — every moving average, momentum and volatility figure |

Why both:

* Indicators must be continuous. A 6% dividend creates a 6% gap in an unadjusted
  series that would fire trend and momentum signals for a non-event.
* Execution must be nominal. If you fill orders on a dividend-adjusted series you
  double-count income — once in the price path, once as cash credited on the
  ex-date.

Because Yahoo's raw series is already split-adjusted, share counts never need
retroactive fixing when a bonus issue occurs. The `Splits` column is carried
through for auditing, but the engine does not act on it; the price series has
already absorbed it. The `Dividends` column *is* acted on — see
[03](03-simulation-engine.md#4-corporate-actions).

## 2. Calendar normalization

Applied at fetch time, before indicators:

1. Index parsed to `datetime`.
2. Timezone stripped (`tz_localize(None)` after any tz-aware conversion).
3. Normalized to midnight, so every session is a clean date key.
4. Duplicates dropped, `keep="last"`.
5. Sorted ascending; rows with null `Close` dropped.

Then in preprocessing: `df = df.loc[:LAST_DATE]`, where `LAST_DATE` defaults to
`2026-08-02` (env: `IND_LAST_DATE`). This is the single truncation point that
enforces the "up to yesterday" boundary.

**No common calendar is imposed.** Each ticker keeps its own session index. The
engine unions them (see [03](03-simulation-engine.md#1-market-construction)),
so a name that did not trade on a given day is simply absent from that day's
view — which is exactly how a halt or a pre-IPO date should read to a strategy.

## 3. Indicator definitions

All computed on `AdjClose` (or `AdjHigh`/`AdjLow` where noted). Every value at
row *t* uses only rows ≤ *t*.

### Trend

| Column | Definition |
|---|---|
| `sma20`, `sma50`, `sma100`, `sma200` | `AdjClose.rolling(w).mean()` |
| `ema12`, `ema26` | `AdjClose.ewm(span=w, min_periods=w).mean()` |

### MACD

```
macd        = ema12 − ema26
macd_signal = macd.ewm(span=9, min_periods=9).mean()
macd_hist   = macd − macd_signal
```

### RSI (14) — Wilder's smoothing

```python
delta    = close.diff()
gain     = delta.clip(lower=0);  loss = −delta.clip(upper=0)
avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
rsi14    = 100 − 100 / (1 + avg_gain / avg_loss)
```

Zero average loss → NaN → filled with a neutral **50.0**, then masked back to NaN
wherever `close` itself is NaN. So `rsi14` is never a spurious 100 on a series
that has only risen.

### Bollinger (20, 2σ)

```
bb_mid  = sma20
bb_up   = bb_mid + 2 · std20
bb_low  = bb_mid − 2 · std20
bb_pctb = (close − bb_low) / (bb_up − bb_low), clipped to [−0.5, 1.5]
```

`std20` is the pandas default **sample** standard deviation (ddof=1). The clip
keeps extreme excursions from producing unbounded values.

### ATR (14) — Wilder

```
TR     = max(high − low, |high − prev_close|, |low − prev_close|)
atr14  = TR.ewm(alpha=1/14, min_periods=14).mean()
atr_pct = atr14 / AdjClose
```

`atr_pct` is the volatility unit most agents size positions with.

### Momentum

| Column | Lookback (sessions) |
|---|---|
| `ret_1d` | 1 |
| `ret_1w` | 5 |
| `ret_1m` | 21 |
| `ret_3m` | 63 |
| `ret_6m` | 126 |
| `ret_12m` | 252 |

All simple `pct_change(w)` on `AdjClose`. Note these are **session** counts, not
calendar periods.

### Volatility, drawdown, position in range

| Column | Definition |
|---|---|
| `vol_21` | `AdjClose.pct_change().rolling(21).std() · √250` — annualized realized vol |
| `drawdown` | `AdjClose / AdjClose.cummax() − 1` — from all-time high *within the loaded window* |
| `dist_52w_high` | `AdjClose / rolling(252, min_periods=60).max() − 1` |
| `dist_52w_low` | `AdjClose / rolling(252, min_periods=60).min() − 1` |

### Volume & liquidity

| Column | Definition |
|---|---|
| `vol_sma20` | `Volume.rolling(20).mean()` |
| `turnover_sar` | `Close · Volume` — **raw** close, so it is nominal SAR traded |

### Relative strength

```
rs_tasi_3m = ret_3m(stock) − ret_3m(TASI)
```

Computed against the index's own 63-session return, reindexed onto the stock's
calendar. Not written for the TASI row itself.

## 4. NaN policy

Indicators are emitted as NaN until their window fills. `sma200` needs 200
sessions, `ret_12m` needs 252, `dist_52w_*` needs at least 60. Consequences:

* The extra warm-up year in the fetch window means most names start the
  simulation with every indicator live.
* **Mid-period IPOs do not.** 35 of the 160 in-sample names listed after
  2022-01-01 and carry NaN long-window indicators for months.

The strategy contract makes NaN-handling the agent's responsibility, and every
v3 agent guards explicitly. Two idioms appear throughout the strategy files:

```python
def _f(x, default=float("nan")):
    try: v = float(x)
    except (TypeError, ValueError): return default
    return v if v == v else default        # NaN != NaN

if not (sma200 == sma200):  # NaN check without importing math
    continue
```

Most agents treat "long averages still NaN" as *not yet eligible* rather than as
a zero — which is the correct reading: a company with no trend history has no
trend signal, and imputing one manufactures trades.

## 5. Output

`data/enriched/{code}.csv` — the 12 raw columns plus 30 indicator columns, one
row per session, `%.6f` precision. In-sample: **161 files** (160 stocks + TASI).

This directory is **git-ignored**: it is fully derived, and regenerating it takes
one command. `data/raw/` is the committed source of truth.

## 6. Environment variables

| Variable | Default | Effect |
|---|---|---|
| `IND_RAW_SUBDIR` | `data/raw` | Input directory (relative to `TASI/`) |
| `IND_OUT_SUBDIR` | `data/enriched` | Output directory (relative to `TASI/`) |
| `IND_LAST_DATE` | `2026-08-02` | Inclusive truncation date |

Out-of-sample invocation:

```bash
IND_RAW_SUBDIR=data/raw_oos IND_OUT_SUBDIR=data/enriched_oos \
  IND_LAST_DATE=2021-12-31 python TASI/pipeline/indicators.py
```
