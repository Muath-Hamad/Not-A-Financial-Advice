# 06 — Results & validation

## 1. In-sample results (2022-01-02 → 2026-08-02)

160 stocks, 1,144 sessions, SAR 100,000 each.

| Rank | Agent | Final SAR | Return | CAGR | Sharpe | maxDD | Trades | Turnover |
|---|---|---|---|---|---|---|---|---|
| 1 | 🦅 Saqr | 467,937 | +367.9% | 40.1% | 1.36 | −20.7% | 248 | 11.9× |
| 2 | ⚡ Raad | 300,291 | +200.3% | 27.1% | 1.22 | −14.5% | 164 | 5.7× |
| 3 | 👑 Malik | 283,513 | +183.5% | 25.6% | 1.08 | −16.5% | 413 | 12.1× |
| 4 | 🛡️ Dira | 243,930 | +143.9% | 21.5% | 0.97 | −23.8% | 249 | 4.2× |
| 5 | ⏳ Waqt | 240,582 | +140.6% | 21.1% | **1.39** | −13.3% | 563 | 13.1× |
| 6 | 🏛️ Hikma | 231,991 | +132.0% | 20.2% | 0.98 | −18.4% | 2,343 | 12.2× |
| 7 | 🌗 Badr | 230,263 | +130.3% | 20.0% | 0.92 | −24.6% | 376 | 11.5× |
| 8 | ⚖️ Mizan | 221,705 | +121.7% | 19.0% | 0.80 | −24.1% | 167 | **3.5×** |
| — | ⚪ TASI | 95,024 | −5.0% | −1.1% | −0.31 | −27.8% | — | — |

Every agent beat the index by more than 125 percentage points. **That result
alone should have been treated as suspicious**, and it was: the agents were
designed by LLM subagents with read access to this exact period.

## 2. Why in-sample results overstate everything

Three distinct problems, in descending order of severity:

### a) Parameter selection on the evaluation set

Every agent's constants — thresholds, weights, ATR multiples, breadth floors —
were chosen by running variants against the 2022–2026 tape and keeping what
scored best. Their design summaries say so explicitly:

> *"Widening the trail from 3-ATR to 5-ATR took the backtest from +44% to +125%."* — raad
>
> *"Parameter sweeps against the real engine showed the two highest-value rules were removing rank-decay selling entirely and reviewing entries every three sessions."* — saqr

The rules are general; the *dosages* are fitted. This is textbook overfitting,
and it is why an out-of-sample test was necessary rather than optional.

### b) Survivorship bias

The universe was discovered in 2026, so it contains only names still listed
then. Companies delisted mid-period are absent from the tradeable set — the
agents could never buy the market's worst outcomes. This inflates both windows.

### c) Benchmark asymmetry

TASI here is a **price index**: it excludes dividends, while agent portfolios
collect them (SAR 3k–21k per agent). Roughly 3–4 percentage points per year of
the measured outperformance is this artifact, not skill.

## 3. The out-of-sample walk-back

**Design.** Take the eight v3 strategy files exactly as committed — no retuning,
no re-authoring, not one constant changed — and run them on **2016-01-03 →
2021-12-30**: 1,538 sessions, 125 names with usable history. Neither the agents
nor their authors ever saw this data; the archives they studied only cover 2022+.

The window is a genuine stress test containing regimes absent from the training
period: the 2016 oil-crash trough, the 2018–19 MSCI-inclusion rally, the **COVID
crash**, and the 2021 boom. The index *rose* 63.2% here versus falling 5.0%
in-sample, so it also flips the market's direction.

**Command:**

```bash
IND_RAW_SUBDIR=data/raw_oos IND_OUT_SUBDIR=data/enriched_oos \
  IND_LAST_DATE=2021-12-31 python TASI/pipeline/indicators.py
SIM_ENRICHED_SUBDIR=data/enriched_oos SIM_RAW_SUBDIR=data/raw_oos \
  SIM_START=2016-01-01 python TASI/sim/run_sim.py --out TASI/out/results_oos.json
```

### Results

| Agent | IS return | IS rank | **OOS return** | **OOS rank** | IS CAGR | OOS CAGR | OOS Sharpe | OOS maxDD |
|---|---|---|---|---|---|---|---|---|
| ⚡ Raad | +200.3% | 2 | **+178.0%** | **1** | 27.1% | 18.6% | **0.94** | −22.5% |
| 👑 Malik | +183.5% | 3 | +168.0% | 2 | 25.6% | 17.9% | 0.64 | −39.2% |
| 🛡️ Dira | +143.9% | 4 | +151.8% | 3 | 21.5% | 16.7% | 0.70 | −26.4% |
| ⚖️ Mizan | +121.7% | 8 | +137.9% | 4 | 19.0% | 15.6% | 0.62 | −33.4% |
| 🏛️ Hikma | +132.0% | 6 | +135.5% | 5 | 20.2% | 15.4% | 0.68 | −34.4% |
| ⏳ Waqt | +140.6% | 5 | +122.5% | 6 | 21.1% | 14.3% | 0.80 | **−12.6%** |
| 🦅 Saqr | **+367.9%** | **1** | +77.5% | 7 | 40.1% | 10.1% | 0.37 | −31.6% |
| 🌗 Badr | +130.3% | 7 | +36.8% | 8 | 20.0% | 5.4% | 0.15 | −28.8% |
| ⚪ TASI | −5.0% | — | +63.2% | — | −1.1% | 8.5% | 0.33 | −36.3% |

### Findings

**1. The in-sample champion was curve-fit.** Saqr fell from 1st to 7th, 40.1% →
10.1% CAGR, Sharpe 1.36 → 0.37. Its trade count nearly tripled (248 → 712): the
binary regime switch that fired cleanly on 2022–26 chopped repeatedly on
2016–21. Its ranking was an artifact of tuning.

**2. The real best agent is Raad.** 2nd in-sample, **1st out-of-sample**, the
best OOS Sharpe, second-best OOS drawdown, and the smallest CAGR decay of any
agent. It is the only one that was near the top in both regimes, across a bull
market, a crash and a bear leg.

**3. Six of eight still beat the index out-of-sample** on an absolute basis, and
seven of eight beat it risk-adjusted (OOS Sharpe > 0.33). The *signal* —
disciplined trend-following with asymmetric exits on this market — is real. The
*magnitude* was not: honest expectations are 14–19% CAGR, not 40%.

**4. Rank correlation is moderate, not zero.** Six agents stayed within two
places; the two that collapsed (Saqr, Badr) were the two whose mechanisms are
most finely calibrated. Robustness tracked structural simplicity.

**5. Risk control transferred better than return.** Waqt's return decayed but its
drawdown discipline held completely: −12.6% through a window in which the index
fell −36.3%. Conversely Malik generalized in *return* while posting the worst
OOS drawdown (−39.2%) — an ensemble offers no protection when the whole field is
wrong at once.

### What this test still cannot rule out

* **Survivorship bias persists** — the OOS universe is also today's survivors.
* **Author knowledge leakage** — the subagents were trained on public data that
  includes 2016–2021 market history. They did not see this project's OOS files,
  but general knowledge of Saudi market history is not fully excluded.
* **One market, one path.** These are eight strategies on a single 10-year price
  path of a single exchange. It is one sample.

The only fully clean test is forward: freeze the agents and score them on data
that does not exist yet. The pipeline is parameterized to support this — see
[07](07-dashboard-and-reproduction.md).

## 4. Reproducibility status

`data/raw` currently holds a **197-name** universe (a later discovery run found
more symbols), while `out/results.json` was produced on the **160-name**
universe. Re-running the simulation today will therefore **not** reproduce the
committed results — a spot re-run yielded Saqr at +86.3% instead of +367.9%,
purely from the wider universe.

Options to restore exact reproducibility:

1. **Pin the universe** — commit the 160-code list used for the v3 run and have
   `fetch_data.py` read it instead of re-discovering.
2. **Refresh v3** — re-run the sim, letters and dashboard on the 197-name
   universe and publish it as a new season.

Neither has been done; the committed results, dashboard and artifact are all
internally consistent with each other and with the 160-name dataset.
