# 04 — Election & results

## The two races

Universe: 327 AAOIFI-compliant names. Benchmark: NASDAQ Composite (price
index) rescaled to $100,000. Freeze: `7e8cdf1`, between the two fetches.

### In-sample (2016-01-04 → 2022-12-30 — agents were tuned here)

| Agent | Final | Return | maxDD | Trades |
|---|---|---|---|---|
| trend | $439,824 | +339.8% | −26.5% | 1,270 |
| factor | $435,564 | +335.6% | −34.4% | 1,683 |
| breakout | $415,364 | +315.4% | −23.8% | 406 |
| defense | $350,877 | +250.9% | −27.5% | 961 |
| regime | $262,634 | +162.6% | −31.0% | 1,394 |
| IXIC | $213,467 | +113.5% | — | — |

### Out-of-sample (2023-01-03 → 2026-08-04 — first look at unseen data)

| Agent | Final | Return | CAGR | Sharpe | maxDD | Trades |
|---|---|---|---|---|---|---|
| **factor** | $385,258 | **+285.3%** | ~45% | 1.20 | −29.5% | 835 |
| **regime** | $323,383 | +223.4% | ~39% | **1.24** | −23.4% | 765 |
| **trend** | $307,558 | +207.6% | ~37% | 1.22 | **−16.2%** | 806 |
| defense | $237,884 | +137.9% | ~27% | 1.05 | −25.5% | 583 |
| breakout | $184,458 | +84.5% | ~19% | 0.70 | −24.8% | 335 |
| IXIC | $255,945 | +156.0% | ~30% | — | −36%* | — |

Three of five beat the Composite on unseen data; four of five beat it
risk-adjusted.

## The election

Formula (declared before the out-of-sample run; weights in
`sim/elect.py`): **40 OOS Sharpe · 20 OOS CAGR · 15 OOS drawdown · 15
robustness (rank consistency + CAGR retention) · 10 tradability (low
turnover)**, each min-max normalized across the field.

| Rank | Agent | Score | IS# → OOS# | The story |
|---|---|---|---|---|
| 🏆 1 | **trend** | **78.4** | 1 → 3 | Best drawdown, near-best Sharpe, most consistent ranks — the profile you hand a live account |
| 2 | regime | 74.8 | 5 → 2 | Best OOS Sharpe; penalized only for the rank jump (unpredictability cuts both ways) |
| 3 | factor | 73.2 | 2 → 1 | Biggest OOS return; worst OOS drawdown (−29.5%) |
| 4 | defense | 58.0 | 4 → 4 | Perfectly consistent, under-returned the index |
| 5 | breakout | 25.3 | 3 → 5 | The TASI-winning school decayed hardest here |

**Elected: `trend`** — cross-sectional momentum with a fully continuous
exposure dial and adaptive horizon weights. It never led the out-of-sample
field on raw return, and that is precisely why it wins the election: the
formula pays for risk-adjusted, consistent, tradable performance, and trend is
the only agent near the top of every component.

## What the back-propagation loop did

The audit trails (`results_*.json → agents[].adaptations`, rendered in the
dashboard) show all five loops firing quarterly through both periods —
26 in-sample and ~14 out-of-sample events per agent. Observed behaviours:

* **factor** is the cleanest vindication: its sleeve weights visibly migrated
  through the OOS years (momentum-slow and trend-quality gaining, reversal
  shrinking), and it converted that into the field's best OOS return — the
  sleeve-attribution learning rule worked on data nobody tuned against.
* **regime** used its loop to fix its own in-sample weakness: last IS, second
  OOS. Its adapt() re-centred the exposure ramp after under-participating in
  rising windows.
* **trend** drifted modestly (trail widening, 12-month weight up) and mostly
  banked its structural design — consistent with its election-winning
  stability.
* **breakout's** mean-reversion-to-defaults device kept its parameters sane,
  but could not rescue a school whose edge (fresh-high breakouts in a
  liquidity band) simply paid less on 2023-26 NASDAQ, where the advance was
  concentrated in a handful of mega-caps rather than broad breakout cohorts.

The TASI → NASDAQ comparison is instructive: there, the *structures* that
generalized were fixed rulebooks; here, the two best OOS performers were the
two whose adaptation rules did the most work. A quarterly bounded feedback
loop appears to buy real regime resilience.

## Limitations (read before trusting any number)

1. **Survivorship bias** — today's listings, both windows.
2. **AAOIFI screen is as-of-today**, not point-in-time (see doc 01).
3. **Author prior knowledge** — the Opus authors' training data includes
   NASDAQ history through their cutoffs. No 2023+ prices were available *in
   the repository*, and the fairness audit found no memorized trades, but
   general knowledge of "what kind of market 2023-24 was" cannot be fully
   excluded. The freeze protocol is a strong control, not a perfect one.
4. **One market, one path, 3.6 OOS years.**
5. **Price-index benchmark** — the Composite excludes dividends; agent curves
   include them (small flattery, NASDAQ yields are low).

## The next step (kept in mind, as requested)

The elected agent is designed to be dropped onto a **live virtual NASDAQ
account**:

* `trend` trades liquid names only ($8M+ daily turnover floor), ~15 positions,
  ~2 decisions/week pace (806 trades / 3.6 years ≈ 4.3 fills/week), executable
  at next-open — all compatible with paper-trading APIs (e.g. Alpaca paper,
  IBKR paper).
* Its `adapt()` loop continues working forward without any retraining
  infrastructure — it only needs its own realized fills.
* Suggested wiring for the future step: a scheduled GitHub Action fetches the
  AAOIFI universe's daily bars after each close, feeds the frozen `trend`
  agent, and submits next-open orders to the paper account; the election
  dashboard becomes the live monitor. The engine's env-parameterized costs
  (`SIM_COMMISSION`, `SIM_SLIPPAGE`) should be set to the venue's actuals.
* Re-run the AAOIFI screen quarterly — compliance drifts with balance sheets.

## Lab addendum — factor2, the drawdown-hardened variant

After the election, `factor`'s drawdowns were diagnosed (it entered the COVID
crash at 89% exposure; its risk response is entirely slow-path) and a guarded
variant was built in `sim/strategies_lab/factor2.py` — sleeve engine untouched,
risk valve rebuilt: same-session circuit breaker, continuous own-drawdown
governor off a bleeding high-water mark, a one-sided index-vol *acceleration*
term in the vol target, a re-risk ratchet (cut instantly, rebuild ≤4%/session),
and breadth-as-risk-control (13 names @ 13% cap). Designed and tuned on
in-sample evidence only (ensemble medians over micro-perturbed runs — the
surface is chaotic); the OOS check is semi-clean since the original's OOS
results were already known when the fix was commissioned.

| Solo runs | factor IS | factor2 IS | factor OOS | factor2 OOS |
|---|---|---|---|---|
| Final | $435,564 | **$472,248** | **$385,258** | $321,312 |
| Max drawdown | −34.4% | **−24.1%** | −29.5% | **−23.7%** |
| Sharpe | 0.77 | **0.95** | 1.20 | **1.21** |
| Calmar | 0.68 | **1.03** | 1.55 | **1.63** |
| Recovered | — | — | 2025-10-29 | **2025-09-12** |

Per-episode (IS): COVID −34.4% → −17.7%, 2018 Q4 −29.8% → −21.6%, 2021 unwind
−32.2% → −24.1%. Two findings worth keeping: **past a modest point, cutting
exposure makes max drawdown worse** (a de-risked book stays underwater longer
and meets the next shock unrecovered — gross floors of 0.35/0.28 tested worse
than 0.50), and **diversification bought more drawdown relief than
de-leveraging**. Out-of-sample the guard is a genuine trade, not a free lunch:
~20% of the max drawdown removed for ~17% of terminal wealth, with equal
Sharpe, better Calmar, and a six-week-faster recovery. The frozen five and the
election result are unchanged.
