# Not A Financial Advice 📉📈

An agent-based trading simulation on the Saudi stock market (Tadawul). Eight AI
agents with distinct personalities each received **SAR 100,000 on 2022-01-01**
and traded the **top-50 TASI universe** through **2026-08-02** (1,144 sessions),
communicating daily in a shared "majlis" chat. None of this is financial advice.

## How it works

```
data/tickers.json            the 50-stock universe + TASI benchmark
.github/workflows/fetch-data.yml   fetches Yahoo Finance data on a GitHub runner
pipeline/fetch_data.py       daily OHLCV + dividends/splits, 2021 → 2026-08-02
pipeline/indicators.py       SMA/EMA/RSI/MACD/Bollinger/ATR/momentum/drawdown...
sim/engine.py                day-synchronized multi-agent backtest engine
sim/strategy_base.py         the strategy contract agents implement
sim/strategies/*.py          the 8 agent personalities (agent-authored)
sim/metrics.py               CAGR, Sharpe, Sortino, drawdowns, trade stats...
sim/run_sim.py               runs everyone, writes out/results.json
dashboard/                   self-contained comparison dashboard
```

Realism model: fills at next session's open with 10 bps slippage, Tadawul
commission (15.5 bps + 15% VAT) per side, long-only, integer shares, dividends
credited as cash on ex-date, bonus issues handled via split-adjusted prices,
orders survive trading halts up to 5 sessions. Decisions use only data available
at the close of the prior session — no lookahead.

The "majlis": after every close each agent posts sentiment, mood, and optional
messages to a shared board that all agents can read the next day — so the
contrarian genuinely fades the crowd and the influencer genuinely follows it.

## Reproduce

```bash
# 1. fetch data (run the GitHub Action, or locally with open internet)
python pipeline/fetch_data.py
# 2. compute indicators
python pipeline/indicators.py
# 3. run the simulation
python sim/run_sim.py
# 4. open the dashboard
open dashboard/index.html
```

## Disclaimer

This is a simulation for entertainment and research. Past performance of
fictional characters is not indicative of future results of anyone. Not
financial advice.
