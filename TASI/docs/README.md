# TASI Arena — Technical Documentation

Full technical reference for the agent-based Tadawul trading simulation: how the
market data was acquired and cleaned, how the backtest engine executes orders,
what every agent's rulebook and parameters actually are, how performance is
measured, and what the results do and do not prove.

## Contents

| Document | Covers |
|---|---|
| [01 — Data acquisition](01-data-acquisition.md) | Sources, universe discovery, the fetch pipeline, rate limits, failure modes, the manifest |
| [02 — Preprocessing & indicators](02-preprocessing.md) | Price adjustment model, calendar normalization, every indicator formula, NaN policy |
| [03 — Simulation engine](03-simulation-engine.md) | Order lifecycle, cost model, corporate actions, halts, the decide() contract, peer channel |
| [04 — The agents](04-agents.md) | All eight v3 agents: philosophy, rulebook, and complete parameter tables |
| [05 — Metrics](05-metrics.md) | Exact definitions of every performance and trade statistic |
| [06 — Results & validation](06-results-and-validation.md) | In-sample results, the out-of-sample walk-back, biases, what generalized |
| [07 — Dashboard & reproduction](07-dashboard-and-reproduction.md) | Dashboard build, commands, environment variables, known caveats |
| [08 — Version history](08-version-history.md) | v1 → v2 → v3: what changed and why |

## The system in one page

```
             GitHub Actions runner (open internet)
   ┌──────────────────────────────────────────────────────┐
   │ discover_universe.py   → data/universe_full.json     │
   │ fetch_data.py          → data/raw/*.csv.gz           │
   │                          data/raw/_manifest.json     │
   └───────────────────────────┬──────────────────────────┘
                               │ committed back to the branch
                               ▼
   ┌──────────────────────────────────────────────────────┐
   │ indicators.py  → data/enriched/*.csv                 │
   │   OHLCV + dividends/splits + 30 indicator columns    │
   └───────────────────────────┬──────────────────────────┘
                               ▼
   ┌──────────────────────────────────────────────────────┐
   │ engine.py  (Market → Engine → Portfolio per agent)   │
   │   for each session: dividends → fills at open →      │
   │   mark to close → each agent decides → queue orders  │
   │ strategies/*.py  (8 independent rulebooks)           │
   └───────────────────────────┬──────────────────────────┘
                               ▼
   ┌──────────────────────────────────────────────────────┐
   │ metrics.py → out/results.json → build_dashboard.py   │
   │                              → dashboard/index.html  │
   └──────────────────────────────────────────────────────┘
```

## Headline configuration

| Parameter | Value |
|---|---|
| Starting capital | SAR 100,000 per agent |
| In-sample window | 2022-01-02 → 2026-08-02 (1,144 sessions) |
| Out-of-sample window | 2016-01-03 → 2021-12-30 (1,538 sessions) |
| Universe | Full Tadawul main market (160 names in-sample, 125 out-of-sample) |
| Benchmark | TASI index (`^TASI.SR`), normalized to SAR 100,000 |
| Commission | 8 bps per side |
| Slippage | 5 bps per side |
| Execution | Decide at close of *t*, fill at open of *t+1* |
| Constraints | Long-only, integer shares, no margin, no shorting |
| Risk-free rate (metrics) | 4.0% annual |
| Trading days per year | 250 (Tadawul trades Sunday–Thursday) |

## A note on interpretation

The v3 agents were authored by LLM subagents that could read the 2022–2026 data
while designing their rules. Their **rules** are general — audited for hardcoded
dates and per-ticker trade scripts, of which there are none — but their
**constants** were selected knowing how that period played out. The in-sample
returns are therefore an upper bound on what the method would have produced live.
[Document 06](06-results-and-validation.md) quantifies exactly how much of the
performance survived on unseen data.
