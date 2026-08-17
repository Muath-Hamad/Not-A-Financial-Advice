# 04 — The agents

Eight independent rulebooks, one objective: **maximize terminal equity**. Each
was assigned a starting philosophy (a school of investing) but was explicitly
free to blend techniques, and each was required to study the archived v2 season
before designing. All eight are pure functions of indicators, prices and peer
books.

## Fairness audit

Every strategy was checked for lookahead-by-memorization before the results were
accepted:

```
$ grep -E '20(2[2-6])-[0-9]{2}|datetime\(20' strategies/*.py   → no matches in logic
$ ticker-literal count per file                                → 0 across all eight
```

No hardcoded dates, no per-ticker trade plans, no memorized tape. Universe
screens, regime rules, and recurring-calendar rules (turn-of-month, Ramadan) are
permitted and used.

## Results at a glance

In-sample = 2022-01-02 → 2026-08-02 (160 names). Out-of-sample = 2016-01-03 →
2021-12-30 (125 names), **frozen agents, no retuning**.

| Agent | School | IS return | IS Sharpe | IS maxDD | **OOS return** | OOS Sharpe | OOS maxDD |
|---|---|---|---|---|---|---|---|
| 🦅 Saqr | Trend & momentum | **+367.9%** | 1.36 | −20.7% | +77.5% | 0.37 | −31.6% |
| ⚡ Raad | Small/mid-cap breakouts | +200.3% | 1.22 | −14.5% | **+178.0%** | **0.94** | −22.5% |
| 👑 Malik | Meta-ensemble | +183.5% | 1.08 | −16.5% | +168.0% | 0.64 | −39.2% |
| 🛡️ Dira | Adaptive defense | +143.9% | 0.97 | −23.8% | +151.8% | 0.70 | −26.4% |
| ⏳ Waqt | Regime & rotation | +140.6% | **1.39** | −13.3% | +122.5% | 0.80 | **−12.6%** |
| 🏛️ Hikma | Quality compounding | +132.0% | 0.98 | −18.4% | +135.5% | 0.68 | −34.4% |
| 🌗 Badr | Mean reversion | +130.3% | 0.92 | −24.6% | +36.8% | 0.15 | −28.8% |
| ⚖️ Mizan | Multi-factor quant | +121.7% | 0.80 | −24.1% | +137.9% | 0.62 | −33.4% |
| ⚪ TASI | Benchmark | −5.0% | −0.31 | −27.8% | +63.2% | 0.33 | −36.3% |

---

# 🦅 Saqr — concentrated trend momentum

> *"The falcon does not chase every bird — only the one already climbing."*

**Lineage.** Built on the strongest finding of two prior seasons: cross-sectional
momentum with trend gates and asymmetric exits beat everything on this market.
Explicitly fixes v2's two failures — Lulu held through −16% dips, and Abu
Shanab's binary "bunker" sat out entire years.

### Rulebook

1. **Screen** — price ≥ SAR 2, turnover ≥ SAR 3m, and full trend alignment
   `AdjClose > sma50 > sma200`. NaN long averages (IPOs) are skipped silently.
2. **Rank** — cross-sectional percentile of four momentum reads: 1-month and
   3-month returns each *damped by 21-day vol* (`ret / (1 + VOL_DAMP·vol_21)`, so
   a quiet advance outranks a violent one), classic 12m−1m momentum, and
   `rs_tasi_3m`. The bar is the flock, never an absolute number.
3. **Regime switch (binary, decisive)** — TASI above *both* its 50- and 200-day
   lines with breadth ≥ 30% ⇒ **6 slots**. Any other state ⇒ book cut to its
   **2 best-ranked names**, remainder to cash. Reduced, never bolted shut.
4. **Size** — inverse volatility: `w = RISK_TARGET / atr_pct`, clamped to
   [6%, 50%], capped again at 35% of the name's daily turnover, max 2 per sector.
   Buys are funded from cash *plus the same morning's sell proceeds*.
5. **Exits, checked every session in order** — (a) −15% catastrophe stop from
   average cost, (b) chandelier trail at 3.5×ATR below the highest close seen
   while held, (c) the workhorse: exit the session a name closes below
   `0.985 × sma50`. **Nothing is ever trimmed for being up.**
6. **Peers** — names held by better-performing agents get a +0.3 percentile
   ranking bonus. Tiebreak only; never an entry reason.

### Parameters

| Constant | Value | Role |
|---|---|---|
| `MIN_PRICE` | 2.0 SAR | Universe floor |
| `MIN_TURNOVER` | 3,000,000 SAR | Liquidity floor |
| `TURNOVER_CAP` | 0.35 | Max position as fraction of daily turnover |
| `VOL_DAMP` | 0.5 | Volatility damping on momentum reads |
| `N_FULL` / `N_REDUCED` | 6 / 2 | Slots in open-sky / reduced regime |
| `BREADTH_FLOOR` | 0.30 | Breadth required for open sky |
| `RISK_TARGET` | 0.015 | Numerator of inverse-vol sizing |
| `MAX_W` / `MIN_W` | 0.50 / 0.06 | Position weight clamps |
| `SECTOR_CAP` | 2 | Max names per sector |
| `HARD_STOP` | −0.15 | Catastrophe stop from cost |
| `TRAIL_ATR` | 3.5 | Chandelier trail multiple |
| `SMA_EXIT` | 0.985 | Exit trigger as fraction of sma50 |
| `MIN_HOLD` | 6 sessions | Minimum hold before trend exit |
| `REVIEW_EVERY` | 3 sessions | Entry-review cadence (turnover control) |
| `REENTRY_COOL` | 10 sessions | Ban after a trend failure |
| `NO_BUY_DROP` | −0.035 | No new buys the day after this index drop |
| `MIN_TICKET` | 1,500 SAR | Minimum order value |
| `PEER_BONUS` | 0.3 | Ranking bonus for peer-held names |

**Result:** 248 trades, 46.3% win rate, profit factor 2.42, 11.9× annual
turnover, SAR 20,997 dividends, SAR 11,593 commissions.

**Out-of-sample verdict:** collapsed. 40.1% → 10.1% CAGR, Sharpe 1.36 → 0.37,
and trade count nearly tripled (248 → 712) — the regime switch that fired
cleanly on 2022–26 chopped repeatedly on 2016–21. The single clearest case of
in-sample parameter fitting in the arena.

---

# ⚡ Raad — selective small/mid-cap breakouts

> *"I don't predict the storm. I trade the strike."*

**Lineage.** Thesis: the index is a decoy — mid-liquidity names printing fresh
52-week highs earn a large spread over the market's base rate. Season 2's
degen (−32%, 29× turnover) is the explicit anti-pattern: same hunting ground,
opposite discipline.

### Rulebook

1. **Liquidity band, not a floor** — trailing turnover EMA in
   **[SAR 8m, SAR 70m]**. The floor kills the illiquid tail (breakouts there have
   *negative* forward drift); the ceiling excludes mega-caps, which are index
   proxies rather than breakout vehicles. Plus: today's turnover ≥ SAR 1.5m,
   price ≥ SAR 2, `atr_pct` ∈ [1.5%, 7%].
2. **Trigger (all must hold)** — close within **2% of the 52-week high**, above
   `sma50`, and `ret_3m ≥ 0`.
3. **Rank** — composite of 52w-high proximity, 3m/6m thrust, `rs_tasi_3m`, and
   today's volume vs its 20-day average. Volume *confirms*; it does not veto (a
   hard volume gate tested worse). Max **2 new names per session**.
4. **Regime gate** — no new risk unless TASI > `sma50` **and** breadth ≥ 44%,
   and never the session after TASI drops 2.5%.
5. **Size by volatility** — `w = 2.2% / (2.4 × atr_pct)`, clamped [6%, 25%],
   gross ≤ 95%.
6. **Exits (asymmetric)** — 2.4×ATR initial stop, −12% hard backstop, **5.0×ATR
   trail** armed at +10%, 25-session time stop for dead money, and a 45%
   scale-out at +45%. Widening the trail from 3-ATR to 5-ATR moved the backtest
   from +44% to +125% — the single highest-value parameter in the file.
7. **Own-drawdown brakes** — half size below −13%, full stand-down below −15%,
   5-session freeze after any −4% day.

### Parameters

| Constant | Value | Role |
|---|---|---|
| `LIQ_LO` / `LIQ_HI` | 8m / 70m SAR | Turnover band (EMA) |
| `TURN_TODAY_MIN` | 1,500,000 SAR | Same-session turnover floor |
| `PX_MIN` | 2.0 SAR | Price floor |
| `TURN_ALPHA` | 0.05 | Turnover EMA speed |
| `D52_MAX` | −0.02 | Max distance below 52-week high to trigger |
| `RET3M_MIN` | 0.0 | Minimum 3-month return |
| `MAX_POS` | 6 | Position count cap |
| `ENTRIES_PER_DAY` | 2 | New names per session |
| `RISK_PER_TRADE` | 0.022 | Equity risked per position |
| `STOP_ATR` | 2.4 | Initial stop multiple |
| `MAX_GROSS` | 0.95 | Gross exposure cap |
| `HARD_STOP` | −0.12 | Backstop from cost |
| `TRAIL_ATR` | 5.0 | Trail multiple |
| `TRAIL_ARM` | 0.10 | Gain at which the trail arms |
| `TIME_STOP` / `TIME_MIN` | 25 sessions / +2% | Dead-money exit |
| `PARTIAL_AT` / `PARTIAL_FRAC` | +45% / 45% | Scale-out trigger and size |
| `BREADTH_MIN` | 0.44 | Regime gate |
| `TASI_CRASH` | −0.025 | No-buy-tomorrow trigger |
| `DD_TRIM` / `DD_FLAT` | −0.13 / −0.15 | Own-drawdown brakes |
| `FLAT_DAYS` | 10 | Stand-down duration |
| `DAYLOSS` / `DAYLOSS_COOL` | −0.04 / 5 | Bad-day freeze |
| `REENTRY_COOL` | 8 sessions | Post-exit ban |
| `ORDER_GUARD` | 4 sessions | Duplicate-order guard |
| `MIN_BUY` | 3,500 SAR | Minimum ticket |
| `PEER_BONUS_CAP` | 0.25 | Max peer ranking bonus |
| `PEER_DUMP_PENALTY` | 0.40 | Penalty for peer-dumped names |

**Result:** 164 trades (~36/year), 51.7% win rate, profit factor 2.69, **5.7×
turnover** — the second-lowest in the arena.

**Out-of-sample verdict: the winner.** +178.0%, best Sharpe (0.94), second-best
drawdown, and only a 27.1% → 18.6% CAGR decay — the smallest of any agent. It
finished 2nd in-sample and **1st out-of-sample**, through a bull market, the
COVID crash and a bear leg. This is the arena's best investment agent.

---

# 👑 Malik — meta-ensemble

> *"I grade the field every night. Then I try to beat it."*

**Lineage.** Successor to v2's Zahab (+39%, 2nd), which proved copy-trading
graded peers works and proved its ceiling: pure imitation runs a day behind and
can never finish above its best source. Malik keeps the bookkeeping and adds an
independent engine that runs whether peers exist or not.

### Rulebook

1. **Momentum core (own signal)** — every name ranked on percentile blend:
   1m 10%, 3m 20%, 6m 30%, 12m 40%. Ranks not raw returns, so one 400% small-cap
   cannot hijack the scorecard. Screens: 20-day traded value ≥ SAR 5m, price
   above both `sma50` and `sma100`, real 3-month history.
2. **Seven names, equal weight**, 20% cap, max 3 per sector. Shortfall stays in
   cash — that *is* the regime filter. Deliberately **no index overlay**: gating
   on TASI's trend cost money in every test.
3. **Turn of the month** — full re-rank on the first session of each calendar
   month (the recurring window when institutional flows and salary money hit),
   behind a 4% drift band.
4. **The break rule** — any holding closing >8% below its own `sma100` triggers
   an immediate full re-rank, selling the break and redeploying.
5. **Peer panel** — top 4 peers by a blended score (`ret_63`/`ret_21` minus
   charges for equity-curve vol `λ=0.10` and book churn `λ=0.35`) get softmax
   weights (τ=0.15); their conviction map tilts Malik's ranking up to +0.22.
6. **Tuition ledger** — decayed realized P&L *and* decayed gross flow per code
   across the whole field; a name where the field lost more than 2.5% of
   deployed capital is penalized, past 10% it is boxed out.
7. **Stress valve** — when the field's blended 21-day return turns negative,
   gross is cut toward 40% cash.

### Parameters

| Constant | Value | Role |
|---|---|---|
| `MAX_POS` / `MAX_W` | 7 / 0.20 | Book shape |
| `SECTOR_CAP` / `GROSS` | 3 / 0.97 | Concentration limits |
| `MIN_LIQ` | 5,000,000 SAR | 20-day traded value floor |
| `BREAK_SMA100` | 0.08 | Break-rule threshold |
| `BAND` | 0.04 | Rebalance drift band |
| `MIN_ORDER` / `EXIT_DUST` | 2,500 / 1,200 SAR | Ticket floors |
| `CASH_BUFFER` | 0.005 | Reserve |
| `PANEL_K` / `TAU` | 4 / 0.15 | Peer panel size, softmax temperature |
| `LAMBDA_VOL` / `LAMBDA_CHURN` | 0.10 / 0.35 | Peer-grading penalties |
| `CHURN_A`, `SCORE_A`, `CONV_A`, `FLOW_A`, `STRESS_A` | 0.03, 0.12, 0.10, 0.10, 0.10 | EMA smoothing speeds |
| `CONV_FULL` / `CONV_QUORUM` | 0.18 / 1.6 | Conviction scaling and quorum |
| `PEER_MAX` | 0.22 | Max peer tilt (z-units) |
| `FOLLOW_K` / `FOLLOW_MARGIN` | 1.0 / 0.05 | Follow-vs-lead switch |
| `GAP_A` / `LEAD_FLOOR` | 0.04 / 0.01 | Lead-mode thresholds |
| `FLOW_W` / `FLOW_FULL` | 0.08 / 0.01 | Peer-flow tilt |
| `SHORTLIST` | 3 | Candidate shortlist depth |
| `BURN_DECAY` | 0.995 | Tuition-ledger decay per session |
| `TUIT_FLOOR` | 150,000 SAR | Minimum flow before a name is judged |
| `TUIT_SOFT` / `TUIT_FULL` | −0.025 / −0.10 | Penalty / ban thresholds |
| `TUIT_MIN_ABS` | −5,000 SAR | Absolute loss floor |
| `TUIT_MAX` | 0.08 | Max tuition penalty |
| `STRESS_R21` / `STRESS_FULL` | −0.025 / −0.08 | Stress ramp |
| `STRESS_FIELD` / `STRESS_CASH` / `STRESS_CUT` | −0.02 / 0.40 / 0.18 | Field stress, cash target, cut size |
| `HIST_CAP` | 80 sessions | Peer-history memory |

**Result:** 413 trades, 52.4% win rate, profit factor 1.86, 12.1× turnover.

**Out-of-sample verdict: generalized well** (+168.0%, 2nd), which is the
expected behaviour of an ensemble — averaging independent judges is robust by
construction. Its weakness showed elsewhere: a **−39.2% drawdown**, the worst in
the arena, because copying a crowd that is all wrong at once offers no diversification.

---

# 🛡️ Dira — adaptive defense

> *"The shield is what you own and when you leave — not how much cash you hold."*

**Lineage.** v2's Saleh proved half a thesis: he never lost much (−11% maxDD) and
never made anything (+3%), because he bought safety with permanent idle cash.
Dira keeps every risk limit and pays for none of them with exposure — the book
runs ~94% invested and the defense lives entirely in selection and exit timing.

### Rulebook

1. **Index timing is a fee, not a hedge** — measured, not assumed. Gating the
   same book on TASI vs its 200/100/50-day lines, breadth thresholds 0.35–0.50,
   index drawdown bands and own-equity ladders each cut return by a third to a
   half and left drawdown roughly unchanged. The only market-wide read kept is
   the **opportunity count**, and it acts solely by leaving slots unfilled.
2. **Dual liquidity test** — because reported turnover is non-stationary (median
   daily turnover falls ~60% across the sim, with stretches where the whole
   market's turnover shifts by orders of magnitude), a name is liquid if
   **either** its smoothed turnover clears a relative bar (40% of the market
   median) **or** an absolute SAR 3m floor. A purely relative screen once dumped
   five good positions in one session; a purely absolute one empties the universe
   for entire quarters.
3. **Wide book** — 11 slots at 1/11 target weight, 10% hard cap, 3 per sector,
   with a 30-rank hysteresis buffer so a name is not sold for slipping one place.
4. **Score** — long-term trend (w 1.0), medium-term momentum (w 2.0), low
   volatility (w 0.5).
5. **Trailing exits** — 28% trail normally, tightened to **12% in fear regimes**
   (index drawdown ≤ −12% or breadth ≤ 25%).
6. **Escalating brakes** — own drawdown past −18% tightens the rank buffer to 25;
   past −22% pauses new risk for 12 sessions, with a 90-session refractory period
   so the brake cannot chatter.

### Parameters

| Constant | Value | Role |
|---|---|---|
| `LIQ_MIN` / `LIQ_ABS` | 0.40 × market median / 3,000,000 SAR | Dual liquidity test |
| `LIQ_ALPHA` | 1/20 | Turnover EMA speed |
| `LIQ_MIN_OBS` | 5 | Observations before the screen is trusted |
| `PRICE_FLOOR` | 1.0 SAR | Universe floor |
| `N_SLOTS` / `TARGET_W` | 11 / 1/11 ≈ 9.1% | Book shape |
| `MAX_W` / `SECTOR_CAP` | 0.10 / 3 | Concentration limits |
| `RANK_BUFFER` | 30 | Hold hysteresis (ranks) |
| `W_LT` / `W_MT` / `W_LV` | 1.0 / 2.0 / 0.5 | Score weights |
| `TRAIL` / `TRAIL_FEAR` | 0.28 / 0.12 | Trailing stops by regime |
| `FEAR_DD` / `FEAR_BREADTH` / `FEAR_MIN_DD` | −0.12 / 0.25 / −0.10 | Fear-regime triggers |
| `DD_TIGHTEN` / `DD_TIGHT_RANK` | −0.18 / 25 | First brake |
| `DD_BRAKE` / `BRAKE_PAUSE` / `BRAKE_REFRACTORY` | −0.22 / 12 / 90 | Second brake |
| `REORDER_GAP` | 4 sessions | Re-entry spacing |
| `MIN_TICKET` / `CASH_BUFFER` | 1,500 SAR / 0.985 | Execution hygiene |
| `PEER_MAX` | 0.25 | Max peer tilt |

**Result:** 249 trades, 47.6% win rate, profit factor 1.97, **4.17× turnover**.

**Out-of-sample verdict: improved.** +151.8% OOS vs +143.9% IS — one of only
three agents to score higher on unseen data, evidence that its thesis
("don't time the index, defend through selection") is structural rather than fitted.

---

# ⏳ Waqt — regime & rotation

> *"The regime decides the size. The tape decides the names."*

**Lineage.** v2's Noura made +31%/+22% owning sectors rather than stories, but
her gate was slow. Waqt sharpens the turns in both directions.

### Rulebook

1. **Four-signal regime model → one score in [−1, +1]:**
   * *trend* (w 0.34) — TASI vs its 20/50/100/200-day averages
   * *breadth* (w 0.30) — share above `sma50`, plus the 5-vs-20 slope of it
   * *momentum* (w 0.10) — 1m and 3m index returns scaled by their own vol
   * *stress* (w 0.17, subtractive) — realized vol vs trailing norm, distance
     from the 52-week high, consecutive down-day counter
2. **Exposure ramp, quantised** — the score maps onto three decisive rungs
   (full / half / cash) with 6% dead-bands, so the book moves in real steps.
3. **Three overrides that fire same-session, no confirmation:**
   * *Circuit breaker* — index air-pocket (≤ −1.8%) on breadth < 46% ⇒ gross to 20%
   * *Thrust* — breadth vaulting 34% → 55% within 18 sessions ⇒ gross to 100%,
     ahead of the slow trend signals ("bottoms do not ring a bell; participation
     is the closest thing to one")
   * *Equity stop* — own drawdown past −7% halves the book until the regime score
     prints clean
4. **Rotation** — sectors ranked on median 3m/6m member momentum; that rank
   becomes a **tilt** on every name's score, not a gate. Below full exposure the
   tilt swings toward defensives (Healthcare, Food & Staples, Telecom & IT,
   Utilities).
5. **Names** — 1m/3m/6m/12m momentum blend (0.10/0.25/0.35/0.30), risk-adjusted
   by realized vol, with credit for trading near the 52-week high. Max 8 names,
   20% each, 2 per sector.
6. **Exits** — 4×ATR trail bounded to [9%, 24%], −11% hard stop, 6-session break
   rule, 25-session benchmark-relative review.

### Parameters (54 total in `P`)

**Regime weights & divisors**

| Key | Value | | Key | Value |
|---|---|---|---|---|
| `w_trend` | 0.34 | | `t_gap_div` | 0.03 |
| `w_breadth` | 0.30 | | `b_div` / `b_slope_div` | 0.14 / 0.09 |
| `w_mom` | 0.10 | | `mom_div1` / `mom_div3` | 0.035 / 0.07 |
| `w_stress` | 0.17 | | `dd_div` / `vol_div` | 0.13 / 0.50 |

**Exposure**

| Key | Value | Role |
|---|---|---|
| `ramp_lo` / `ramp_hi` | −0.26 / 0.20 | Score→gross ramp endpoints |
| `gross_step` | 0.50 | Quantisation rung size |
| `up_band` / `down_band` | 0.06 / 0.06 | Hysteresis dead-bands |
| `panic_ret` / `panic_breadth` / `panic_gross` | −0.018 / 0.46 / 0.20 | Circuit breaker |
| `thrust_lo` / `thrust_hi` / `thrust_win` / `thrust_gross` | 0.34 / 0.55 / 18 / 1.0 | Thrust override |
| `eq_stop_dd` / `eq_stop_gross` / `eq_stop_clear` | −0.07 / 0.50 / 0.20 | Equity stop |

**Book & selection**

| Key | Value | | Key | Value |
|---|---|---|---|---|
| `max_names_on` | 8 | | `s_m1` / `s_m3` / `s_m6` / `s_m12` | 0.10 / 0.25 / 0.35 / 0.30 |
| `max_w` | 0.20 | | `vol_pow` / `vol_floor` | 0.5 / 0.16 |
| `max_per_sector` | 2 | | `hi_bonus` | 0.30 |
| `rebal_every` | 10 sessions | | `sec_tilt` / `def_tilt` | 0.18 / 0.25 |
| `trim_band` | 0.06 | | `rsi_max` | 88.0 |
| `hold_buffer` | 50 ranks | | `min_order` | 3,000 SAR |

**Liquidity & exits**

| Key | Value | | Key | Value |
|---|---|---|---|---|
| `min_liq` | 3,000,000 SAR | | `trail_k` | 4.0 |
| `liq_rel` | 0.60 | | `trail_min` / `trail_max` | 0.09 / 0.24 |
| `liq_mult` | 25× position | | `hard_stop` | −0.11 |
| `peer_gross` / `peer_name` | 0.06 / 0.10 | | `break_days` / `bench_days` | 6 / 25 |

**Result:** 563 trades, **56.7% win rate** (highest), profit factor 2.44, and the
**best in-sample Sharpe in the arena (1.39)**.

**Out-of-sample verdict: the best risk manager.** Only −12.6% maxDD across a
window containing the COVID crash — while TASI fell −36.3% — and the second-best
OOS Sharpe. Its return decayed (21.1% → 14.3% CAGR) but its *risk control*
transferred completely.

---

# 🏛️ Hikma — quality compounding that learned to steer

> *"Own the compounders. Steer the exposure. Collect the cash."*

**Lineage.** v1's Um Khalid won on dividend patience (+21.6%) but stalled at
+1.1% in v2 because she never adapted exposure. Hikma keeps the philosophy and
adds a quality definition the tape must keep re-earning, an accumulation
schedule, and a breadth valve.

### Rulebook

1. **Quality gate** — a full year of history, price above its own `sma200`,
   60-session average turnover clearing both an absolute floor **and** 50× the
   intended position size, and `atr_pct ≤ 6%` (no volatility carnivals).
2. **Ranking** — percentile blend:
   `0.50·rank(ret_12m) + 0.50·rank(ret_6m) + 0.20·rank(trailing dividend yield)
   + 0.30·rank(persistence above sma200)`. The dividend and persistence terms are
   accumulated as rolling internal state and **fade in from neutral** while their
   windows fill, so early-sim noise cannot distort the book.
3. **Accumulation, not rebalancing** — weekly, targets are equal-weight across
   the top 9 scaled by allowed exposure, and the book moves only **70% of the way
   up / 50% down** each week. Compounders are added to on strength and released
   gradually, never whipsawed on one print.
4. **Breadth valve** — full gross at breadth ≥ 40%, tapering linearly to 70%
   gross by breadth 24%; plus a hard 60% gross cap whenever the book is more than
   18% below its own high-water mark.
5. **Harvest** — trim 35% on extreme overextension: RSI > 82, above the upper
   Bollinger band, or > 45% above `sma200`.
6. **Week detection** — uses a ≥3-day calendar gap rather than a weekday test,
   because Tadawul weeks start on Sunday and naive weekday logic misfires.

### Parameters

| Constant | Value | Role |
|---|---|---|
| `N_SLOTS` / `MAX_W` | 9 / 0.16 | Book shape |
| `MIN_TURNOVER` / `TURNOVER_MULT` | 3,000,000 SAR / 50× | Dual liquidity test |
| `MAX_ATR_PCT` | 0.06 | Volatility ceiling |
| `W_R12` / `W_R6` / `W_DY` / `W_PERS` | 0.50 / 0.50 / 0.20 / 0.30 | Ranking weights |
| `TV_WIN` / `PERS_WIN` / `DIV_WIN` / `PERS_MIN` | 60 / 252 / 252 / 40 | Rolling-state windows |
| `A_UP` / `A_DN` | 0.70 / 0.50 | Move-toward-target fractions |
| `BAND` | 0.10 | Exposure redeployment band |
| `BREADTH_FULL` / `BREADTH_MIN` / `EXPO_MIN` | 0.40 / 0.24 / 0.70 | Breadth valve |
| `DD_TRIGGER` / `EXPO_DD` | −0.18 / 0.60 | Drawdown gross cap |
| `HARVEST_RSI` / `HARVEST_EXT` / `HARVEST_CUT` | 82.0 / 1.45× sma200 / 0.35 | Overextension harvest |
| `DUST_W` / `MIN_BUY` / `MIN_SELL` | 0.008 / 1,200 / 900 SAR | Execution hygiene |
| `PEER_TILT` / `PEER_TILT_CAP` | 0.60 / 0.10 | Peer tilt (exactly 0 with no peers) |

**Result:** **2,343 trades** — by far the most, a direct consequence of partial
weekly moves toward target. 50.1% win rate, profit factor 1.81, SAR 16,767
dividends.

**Out-of-sample verdict: improved slightly** (+135.5% vs +132.0%), but with a
−34.4% drawdown: the breadth valve does not react fast enough for a COVID-style
gap-down.

---

# 🌗 Badr — quality mean reversion

> *"Buy the dip — but only the dips that come back."*

**Lineage.** v2's contrarian lost 20% by inverting every rule that matters: he
bought names 30–55% below their highs sitting on 52-week lows, averaged down,
sold winners the moment they healed, and let a rotting position run 200 sessions.
His win rate was 65% and his profit factor 0.65 — right often, and paying for it,
because his average loss was 3× his average win. Badr is the same school with the
asymmetry turned the right way up.

### Rulebook

1. **Quality gate first** — `AdjClose ≥ 1.10 × sma200`, `sma50 > sma200`,
   `ret_12m > 5%`, `rs_tasi_3m ≥ 0`, drawdown shallower than −30%, real turnover,
   `atr_pct ≤ 9%`. **Anything below its 200-day line is invisible** — that is
   where knives live. The gate is self-regulating: in a broad bear market almost
   nothing qualifies, so the book empties into cash with no macro forecast.
2. **Then discomfort** — inside that healthy set: price under `sma20`, **plus**
   one of RSI ≤ 45, one-week drop ≤ −5%, or `bb_pctb ≤ 0.20`. Quality *plus*
   discomfort — never discomfort alone.
3. **Scale in, never average down** — 75% of target on the signal; the second
   tranche is a **confirmation add**, only when the name reclaims `sma20` with
   structure intact. If it keeps falling he stops out rather than adding. One
   pyramid add is allowed on a position already +10% that returns to its 20-day line.
4. **Exit stack** — a young entry (< 25 sessions) losing `0.96 × sma50` is killed
   immediately; −22% hard stop; trend exit at `0.90 × sma200`; 60-session time
   stop if under +3%; trail giving back 12% once armed at +18%.
5. **Bear mode** — 2 positions max, trail tightened to 70% of normal.

### Parameters (36 in `PARAMS`)

**Quality gate**

| Key | Value | | Key | Value |
|---|---|---|---|---|
| `SMA200_BUF` | 1.10 | | `DD_FLOOR` | −0.30 |
| `MOM_MIN` | 0.05 | | `LIQ_MIN` | 3,000,000 SAR |
| `RS_MIN` | 0.0 | | `PX_MIN` / `ATR_MAX` | 2.0 / 0.09 |

**Entry trigger**

| Key | Value |
|---|---|
| `RSI_BUY` | 45.0 |
| `WK_DROP` | −0.05 |
| `BBP_BUY` | 0.20 |

**Sizing**

| Key | Value | | Key | Value |
|---|---|---|---|---|
| `MAX_POS` | 6 | | `MAX_ADDS` / `PYR_MIN` / `PYR_FRAC` | 1 / +10% / 0.70 |
| `BASE_W` | 0.22 | | `SECTOR_CAP` / `W_CAP` | 3 / 0.26 |
| `TRANCHE1` | 0.75 | | `TURN_CAP` | 0.02 of daily turnover |
| `MAX_BUYS_DAY` | 2 | | `MIN_TICKET` / `CASH_MIN` | 1,200 / 1,500 SAR |

**Exits**

| Key | Value | Role |
|---|---|---|
| `FAST_EXIT_D` / `FAST_EXIT_S50` | 25 sessions / 0.96 | Kill a failed young entry |
| `STOP` | −0.22 | Hard stop |
| `TREND_EXIT` | 0.90 × sma200 | Structure break |
| `TIME_STOP_D` / `TIME_STOP_MIN` | 60 sessions / +3% | Dead money |
| `TRAIL_ARM` / `TRAIL_GIVE` | +18% / 12% | Trailing exit |
| `COOL_D` / `REENTRY_BAN` | 20 sessions / 2 | Re-entry control |
| `BEAR_POS` / `BEAR_TRAIL` | 2 / 0.70 | Bear-mode limits |
| `PEER_TILT` / `PEER_SCORE` | 0.06 / 0.06 | Peer influence |

**Result:** 376 trades, **29.8% win rate** — the lowest in the arena — but a
profit factor of 1.94, which is the whole design: the inverted asymmetry means
being right less than a third of the time still compounds.

**Out-of-sample verdict: worst decay.** +130.3% → **+36.8%**, CAGR 20.0% → 5.4%,
Sharpe 0.92 → 0.15 — below the index on unseen data. Mean reversion's edge on
this market appears to be the most regime-dependent of the eight schools.

---

# ⚖️ Mizan — aggressive multi-factor quant

> *"Four sleeves, nine names, one balance sheet. Turnover is a tax."*

**Lineage.** v2's Dr. Muteb had the right shape and wrong dosage: over-diversified,
under-deployed, and taxed to death by 16× annual turnover. Mizan keeps the
science and fixes the engineering.

### Rulebook

1. **Universe** — whole main market; investable at ~3 months of history
   (`sma50` and `ret_3m` present) and ≥ SAR 2m per session.
2. **Score — cross-sectional z-blend, four sleeves (weekly):**

   | Sleeve | Inputs | Effective weight |
   |---|---|---|
   | Trend quality | `z(drawdown)`, `z(px/sma200 − 1)`, `z(dist_52w_high)` | ~0.51 |
   | Momentum | `z(ret_6m − ret_1m)`, `z(ret_6m)` | ~0.41 |
   | Low volatility | `z(−vol_21)` | ~0.04 |
   | Mean reversion | `z(−ret_1w)` | ~0.04 |

   Plus execution overrides: −0.30 for a parabolic week (`ret_1w > 18%`) and
   −0.20 for `RSI > 85` — paying up into a vertical print is a cost, not a factor.
   The low-vol sleeve is deliberately small in *selection* and carries its real
   weight in *sizing*.
3. **Book** — top 9 ranks, conviction-tilted inverse-vol weights (rank 1 carries
   ~2× the tilt of rank 9), 22% cap per name, 40% cap per sector, position value
   ≤ 10% of the name's daily turnover.
4. **Gross** — vol-targeted to a 34% annualized book-sigma budget, letting gross
   sit at 100% in a normal tape and trimming only when the *holdings themselves*
   are turbulent, floored at 45%.
5. **Two brakes** — a crisis gate (breadth < 8% or TASI 3m < −12% ⇒ gross 70%)
   and an equity-drawdown gate (past −28% ⇒ gross 60%).
6. **Turnover control** — 10% drift band, minimum 4 sessions between rebalances,
   31-rank hold buffer.

### Parameters

| Constant | Value | Role |
|---|---|---|
| `N_TARGET` / `RANK_BUFFER` | 9 / 31 | Book size, hold hysteresis |
| `MAX_W` / `SECTOR_CAP` | 0.22 / 0.40 | Concentration caps |
| `DRIFT_BAND` / `MIN_REBAL_GAP` | 0.10 / 4 sessions | Turnover control |
| `MIN_TURNOVER` / `LIQ_CAP` | 2,000,000 SAR / 0.10 | Liquidity screen and impact cap |
| `CONV_TILT` / `VOL_POW` | 1.0 / 0.5 | Conviction and inverse-vol exponents |
| `VOL_BUDGET` / `RHO` | 0.34 / 0.45 | Vol target, assumed average correlation |
| `GROSS_FLOOR` | 0.45 | Minimum gross |
| `CRISIS_GROSS` / `CRISIS_BREADTH` / `CRISIS_TASI_3M` | 0.70 / 0.08 / −0.12 | Crisis gate |
| `EQUITY_DD_LIMIT` / `EQUITY_DD_GROSS` | −0.28 / 0.60 | Equity brake |
| `DISASTER_TRAIL` / `BLOCK_SESSIONS` | 0.40 / 15 | Catastrophe exit and ban |
| `SPIKE_RET1W` / `SPIKE_PENALTY` | 0.18 / 0.30 | Parabolic-week penalty |
| `HOT_RSI` / `HOT_PENALTY` | 85.0 / 0.20 | Overbought penalty |
| `PEER_TILT` | 0.22 | Max peer tilt (winners only) |

**Result:** 167 trades and **3.52× annual turnover — the lowest in the arena**,
which was the explicit design goal.

**Out-of-sample verdict: improved.** +137.9% OOS vs +121.7% IS (4th), the largest
*positive* surprise. Broad factor blends are the classic robust construction, and
it behaved accordingly.

---

## Cross-cutting observations

**What generalized:** structure — selectivity, liquidity floors, wide trailing
exits on winners with fast small losses, and ensemble/factor averaging. Raad,
Malik, Dira and Mizan all held up or improved.

**What did not:** finely-tuned regime switches. Saqr's binary sky/no-sky rule and
Badr's mean-reversion thresholds were the two most precisely fitted mechanisms in
the arena, and they are exactly the two that collapsed.

**Turnover is not destiny.** Hikma traded 2,343 times and Mizan 167; both landed
mid-table. What mattered was the *shape of the exit rule*, not the frequency of
trading — Raad's 5-ATR trail versus a 3-ATR trail was worth more than any entry
filter in its file.
