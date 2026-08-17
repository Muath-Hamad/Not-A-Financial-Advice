# NASDAQ Arena — Technical Documentation

An election experiment: five lightweight AI investment agents, one AAOIFI
sharia-screened NASDAQ universe, a hard in-sample / out-of-sample split with a
cryptographic freeze between them, and a deterministic mid-simulation
back-propagation loop. The goal is to **elect one agent for a future live
virtual-account trial**.

| Document | Covers |
|---|---|
| [01 — Data & the AAOIFI screen](01-data-and-screen.md) | Universe discovery, the sharia screen, the two-stage fetch, split integrity |
| [02 — Engine & the back-propagation loop](02-engine-and-backprop.md) | v4 engine, the adapt() protocol, the agent contract |
| [03 — Agents](03-agents.md) | The five schools, their rules and their update laws |
| [04 — Election & results](04-election-and-results.md) | Scoring formula, both races, the elected agent, limitations |

## The experiment in one diagram

```
top 500 NASDAQ by mcap ──► AAOIFI screen (business + 30%/30% ratios) ──► 327 names
                                                                            │
             STAGE 1: fetch 2015→2022 ONLY  ◄───────────────────────────────┘
                          │
       5 Opus authors design + tune agents on 2016–2022
       (the OOS years are physically absent from the repo)
                          │
                 ❄ FREEZE COMMIT 7e8cdf1 ❄
                          │
             STAGE 2: fetch 2015→today (full history)
                          │
        IS race 2016–2022        OOS race 2023→today
        (context: tuned here)    (the ballot: first look at unseen data)
                          │
              Election score (OOS-dominant) ──► ELECTED AGENT
                          │
              future step: live virtual NASDAQ account
```

## Headline configuration

| Parameter | Value |
|---|---|
| Universe | 327 AAOIFI-compliant names from the top 500 NASDAQ by market cap |
| Benchmark | NASDAQ Composite (`^IXIC`), price index, rescaled to $100,000 |
| Capital | USD 100,000 per agent |
| In-sample | 2016-01-04 → 2022-12-30 (~1,762 sessions; 2015 = indicator warm-up) |
| Out-of-sample | 2023-01-03 → latest complete session |
| Freeze commit | `7e8cdf12f1a63e6e23f691ff1f01e580ca946acf` |
| Costs | 2 bps commission + 5 bps slippage per side |
| Execution | Decide at close of *t*, fill at open of *t+1*; long-only, integer shares |
| Back-propagation cadence | every 63 sessions (quarterly), in both periods |
| Metrics | 252 trading days/yr, 3% risk-free |
| Subagents | Opus 4.x-class ("opus"), effort high, for all authoring |
