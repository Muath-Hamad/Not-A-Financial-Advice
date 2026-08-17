# Not A Financial Advice 📉📈

An agent-based trading simulation on the Saudi stock market (Tadawul). AI agents
with distinct investment philosophies each receive **SAR 100,000** and trade the
Tadawul main market from **2022-01-02 to 2026-08-02** (1,144 sessions), plus an
out-of-sample walk-back over **2016–2021**. Everything lives under [`TASI/`](TASI).

## Layout

```
TASI/
├── data/
│   ├── tickers.json          curated top-50 universe (v1) + TASI benchmark
│   ├── universe_full.json    full main-market universe (discovered)
│   ├── raw/                  daily OHLCV + dividends/splits, 2021 → 2026-08-02
│   ├── raw_oos/              out-of-sample history, 2015 → 2021-12-30
│   └── enriched*/            indicators (derived, git-ignored)
├── pipeline/
│   ├── discover_universe.py  find every main-market symbol (multi-source)
│   ├── fetch_data.py         fetch prices from Yahoo Finance
│   └── indicators.py         SMA/EMA/RSI/MACD/Bollinger/ATR/momentum/drawdown…
├── sim/
│   ├── strategy_base.py      the decide() contract agents implement
│   ├── engine.py             day-synchronized multi-agent backtest engine
│   ├── strategies/           the v3 agents (one file per agent)
│   ├── metrics.py            CAGR, Sharpe, Sortino, drawdowns, trade stats…
│   ├── run_sim.py            runs everyone, writes out/results.json
│   └── commentary_brief.py   per-agent dossiers for the letter writers
├── dashboard/
│   ├── template.html         dashboard shell (charts, tables, no data)
│   ├── build_dashboard.py    injects results → index.html
│   └── index.html            the self-contained dashboard (open this)
├── out/
│   ├── results.json          v3 in-sample results (2022–2026)
│   ├── results_oos.json      v3 out-of-sample results (2016–2021)
│   ├── briefs.json           per-agent dossiers
│   └── commentary.json       yearly letters + epitaphs
└── archive/
    ├── v1/                   top-50 universe, 8 personality agents
    └── v2/                   full market, 9 agents incl. the meta-agent

.github/workflows/            data-fetch Actions (must stay at the repo root)
```

## Reproduce

All scripts resolve paths relative to `TASI/`, so run them from anywhere:

```bash
# 1. fetch data (or let the GitHub Action do it — this box has no market access)
python TASI/pipeline/discover_universe.py
python TASI/pipeline/fetch_data.py
# 2. compute indicators
python TASI/pipeline/indicators.py
# 3. run the simulation
python TASI/sim/run_sim.py
# 4. rebuild the dashboard
python TASI/dashboard/build_dashboard.py
open TASI/dashboard/index.html
```

Out-of-sample walk-back (frozen agents on unseen 2016–2021 data):

```bash
IND_RAW_SUBDIR=data/raw_oos IND_OUT_SUBDIR=data/enriched_oos \
  IND_LAST_DATE=2021-12-31 python TASI/pipeline/indicators.py
SIM_ENRICHED_SUBDIR=data/enriched_oos SIM_RAW_SUBDIR=data/raw_oos \
  SIM_START=2016-01-01 python TASI/sim/run_sim.py --out TASI/out/results_oos.json
```

(`*_SUBDIR` values are relative to `TASI/`, not the repo root.)

## Model

Decisions are made at each session's close using only information available at
that close; orders fill at the **next** session's open with 5 bps slippage and an
8 bps commission per side. Long-only, integer shares, no margin. Dividends are
credited as cash on the ex-date, bonus issues handled via split-adjusted prices,
orders on halted names persist 5 sessions, and positions in names silent for 20+
sessions are force-exited. Agents see each other's public books (weights, cash,
trailing returns, fills) but do not communicate; each keeps a private journal.

## Results

| Season | Universe | Agents | Winner | Dashboard |
|---|---|---|---|---|
| v1 | top 50 | 8 personalities | Um Khalid +21.6% | `TASI/archive/v1/dashboard.html` |
| v2 | full market | 9 (+ meta-agent) | Lulu +82.0% | `TASI/archive/v2/dashboard.html` |
| v3 | full market | 8 profit-maximizers | Saqr +367.9% | `TASI/dashboard/index.html` |

TASI itself returned **−5.0%** over the same window.

**On the v3 numbers:** the agents' rules are general (no hardcoded dates or
per-stock trade scripts — audited), but their constants were tuned against this
same 2022–2026 tape, so treat those returns as the ceiling of in-sample
optimization. The walk-back test on unseen 2016–2021 data is the honest read:
Saqr's 40% CAGR fell to 10%, while **Raad** finished first out-of-sample (+178%,
best Sharpe) — structure generalized, parameters did not.

**Reproducibility note:** `data/raw` was last refetched with a 197-name universe,
while the committed v3 results were produced on a 160-name universe. Re-running
the simulation today will therefore not reproduce `out/results.json` exactly.

## Disclaimer

A simulation of fictional agents, for research and entertainment. Not investment
advice, not a recommendation, not a solicitation. Past performance of imaginary
people guarantees nothing.
