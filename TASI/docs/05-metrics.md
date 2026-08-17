# 05 — Metrics

`sim/metrics.py`. Two families: **series metrics** computed from the daily equity
curve, and **trade metrics** computed from the fill log.

## Constants

```python
TRADING_DAYS = 250    # Tadawul trades Sunday-Thursday, ~250 sessions/year
RF_ANNUAL    = 0.04   # approximate average SAR risk-free (SAIBOR) 2022-2026
```

`RF_ANNUAL / TRADING_DAYS` is the daily risk-free used in Sharpe and Sortino.

## Series metrics

Let `eq` be the daily equity series and `ret = eq.pct_change().dropna()`.

### Return and growth

| Metric | Definition |
|---|---|
| `final_equity` | `eq[-1]` |
| `total_return` | `eq[-1] / eq[0] − 1` |
| `cagr` | `(eq[-1] / eq[0])^(1/years) − 1`, `years = (last − first).days / 365.25` |

CAGR uses **calendar** years while volatility annualizes by **250 sessions** —
standard practice, but it means the two are not derived from an identical clock.

### Risk

| Metric | Definition |
|---|---|
| `ann_vol` | `ret.std() · √250` (sample std, ddof=1) |
| `sharpe` | `mean(ret − rf_d) / std(ret) · √250` |
| `sortino` | `mean(ret − rf_d) / std(ret[ret < rf_d]) · √250` |
| `var95_daily` | 5th percentile of daily returns |
| `skew` | `ret.skew()` |

Note the Sharpe denominator uses **total** std while the numerator is excess
return — the conventional form. Sortino's denominator is the std of returns
*below the daily risk-free*, so it is a true downside deviation.

### Drawdown

```python
dd  = eq / eq.cummax() − 1
mdd = dd.min()
```

| Metric | Definition |
|---|---|
| `max_drawdown` | `dd.min()` |
| `mdd_trough` | Date of the minimum |
| `mdd_peak` | Date of the running maximum *preceding* the trough |
| `mdd_recovery` | First date at or after the trough where `dd ≥ 0`; `null` if never |
| `longest_underwater_sessions` | Longest consecutive run with `dd < 0` |
| `calmar` | `cagr / |max_drawdown|` |

`longest_underwater_sessions` is measured over the **whole** series, not just the
maximum drawdown — it answers "what is the longest I went without a new high".

### Benchmark-relative

Regressing daily agent returns on daily benchmark returns over their common index:

| Metric | Definition |
|---|---|
| `beta_tasi` | `cov(r, b) / var(b)` |
| `alpha_annual` | `(1 + [mean(r) − β·mean(b)])^250 − 1` |
| `corr_tasi` | Pearson correlation of `r` and `b` |

Requires > 10 overlapping observations and non-zero benchmark variance;
otherwise all three are 0.0.

**Caveat:** the benchmark is a **price index** — it excludes dividends, while
agent equity includes them. Alpha is therefore overstated by roughly the market's
dividend yield (~3–4%/yr on Tadawul).

### Monthly

`monthly_returns` is a `{YYYY-MM: return}` map built by resampling equity to
month-end and taking `pct_change()`, with the first month computed against the
starting equity so it is not dropped. `positive_months_pct` is the share of
months with a positive return. These drive the dashboard heatmap.

`best_day` / `worst_day` record the date and size of the extreme daily returns.

## Trade metrics

Computed from the fill log; "closed trade" means a **sell** with a realized P&L.

| Metric | Definition |
|---|---|
| `n_trades` / `n_buys` / `n_sells` | Fill counts |
| `win_rate` | `wins / n_sells`, where a win is `realized_pnl > 0` |
| `profit_factor` | `Σ(wins) / |Σ(losses)|` |
| `realized_pnl` | `Σ(wins) − |Σ(losses)|` |
| `avg_win` / `avg_loss` | Mean realized P&L of winners / losers |
| `turnover_annual` | `Σ(trade value) / mean(equity) / years` |

`turnover_annual` counts **both sides**, so a full round-trip of the book scores
as 2.0. It is the fee-drag proxy: at 8 bps/side, 12× turnover costs roughly
0.96%/yr in commission alone.

### Attribution

| Metric | Meaning |
|---|---|
| `favorite_stock` | Most-traded ticker by fill count |
| `most_profitable_stock` / `most_painful_stock` | Best / worst cumulative realized P&L by ticker |
| `best_trade` / `worst_trade` | Single fills with extreme realized P&L |
| `longest_hold` | Longest completed holding period, in calendar days |

## Interpretation notes

1. **Win rate and profit factor are near-independent.** Badr wins 29.8% of
   closed trades and still returns +130% in-sample, because his average win
   dwarfs his average loss. Reading win rate alone inverts the ranking.

2. **Unrealized P&L is invisible to trade metrics.** A position still open at the
   final session never appears in `win_rate` or `profit_factor` — it shows only
   in `final_equity`. Agents holding large open winners look worse on trade
   statistics than they performed.

3. **The benchmark's own metrics** are computed by running the same function on
   the rescaled TASI series, so every column in the dashboard's comparison table
   is like-for-like — with the dividend caveat above.
