# 03 — The agents

Five lightweight agents, one per school, all purely profit-maximizing. Each was
authored by an independent Opus subagent (effort: high) with access to
**2016–2022 data only**, required to study the TASI experiment's out-of-sample
autopsy first, and required to implement the `adapt()` back-propagation loop
with a declared `param_space`. Frozen at `7e8cdf1` before any out-of-sample
data existed in the repository.

Fairness audit across all five files: **zero date literals, zero ticker
literals** — every rulebook is a pure function of indicators, prices and peer
books.

The full parameter sets live in the strategy files and every adaptable
parameter's bounds are in `meta["param_space"]`; the tables below list the
load-bearing ones.

---

## trend — cross-sectional momentum with a continuous dial

Volatility-adjusted 3m/6m/12m momentum blend (1m excluded as reversal noise) +
relative strength vs the Composite + 52-week-high proximity + MA-stack bonus,
over a liquid universe (price ≥ $5, turnover EMA ≥ $8M, **no market-cap
ceiling** — on NASDAQ the mega-caps *are* the trend). Top-20 pool, 15 slots,
inverse-ATR sizing clamped to 0.5–2× equal weight.

The TASI lesson applied: **no binary regime switch.** Target gross =
`EXP_MAX × regime × vol_scalar × dd_scalar`, all three continuous ramps
(index vs 200d/50d + breadth; realized-vol targeting; own-drawdown slider whose
high-water mark *bleeds 0.15%/session* so a stale peak cannot suppress the book
through a recovery). De-risking sells weakest-ranked lines first; winners last.

Exits: −20% hard stop, ATR initial stop, wide trail armed at +10%, sma200
structural break, rank decay, dead-money time stop.

| Key defaults | | Adaptable (param_space) |
|---|---|---|
| `TARGET_N` 15, `ENTRY_POOL` 20 | | `EXP_MAX` [0.55, 1.0] |
| `LIQ_MIN` $8M, `PX_MIN` $5 | | `RISK_PER_TRADE` [0.008, 0.030] |
| `HARD_STOP` −20% | | `STOP_ATR` [2.0, 4.5], `TRAIL_ATR` [3.0, 8.0] |
| `PEAK_DECAY` 0.0015/session | | `TIME_STOP` [20, 60], `RANK_BUFFER` [1.3, 3.0] |
| `CRASH_DAY` −3% (3-session cool) | | `TARGET_VOL` [0.10, 0.30], `W3/W6/W12` [0.12, 0.60] |

**adapt():** aggression tracks EMA-smoothed realized Sharpe (up when
under-participating in a rising benchmark, cut after a −18% window drawdown);
stop width follows hit rate (<35% → wider, >55% → tighter); trail follows
payoff ratio; time stop follows loser-holding asymmetry; momentum-horizon
weights nudge 6% toward whichever horizon's entries actually paid
(attribution recorded at trade time).

---

## breakout — Raad's skeleton, four organs replaced

Entries: close within 3% of the 52-week high, above sma50 and sma200,
`ret_3m ≥ 0`, `rs_bench_3m ≥ RS_MIN` (index-relative strength was the
strongest forward-return discriminator in the author's panel study; volume
subtracted value and has **no term**). Sizing `RISK / (STOP_ATR × ATR%)`
clamped [6%, 15%], nine slots.

The four deliberate departures from the TASI winner, each justified by a
panel study rather than a backtest score:

1. **No liquidity ceiling** — only a floor (deep NASDAQ names print the
   cleanest trends); adapt() steers the floor from winners' vs losers'
   turnover.
2. **The 200-day outranks the 50-day** — a four-rung exposure ladder
   (0/30%/95%/100%) scored two points for the index's 200d, one for its 50d;
   a regime error costs size, never the whole book.
3. **A dead-money clock is not an exit** — flat positions recycle only when
   the clock runs out AND leadership is gone (a pure time stop halved
   in-sample equity — compounders consolidate for months).
4. **Nothing takes profit but the trail** — no scale-outs, no targets, no
   pyramiding (tested, rejected); the 6-ATR trail's ATR reference is clamped
   to [0.6×, 1.25×] of entry so volatility spikes cannot balloon the stop.

| Key defaults | | Adaptable (param_space) |
|---|---|---|
| `LIQ_FLOOR0` $25M | | `LIQ_FLOOR` [$5M, $300M] |
| `MAX_POS` 9, `HARD_STOP` −12% | | `RISK_PER_TRADE` [0.006, 0.020] |
| `TRAIL_ATR0` 6.0, arm +12% | | `STOP_ATR` [1.8, 3.6], `TRAIL_ATR` [3.5, 8.0], `TRAIL_ARM` [0.04, 0.20] |
| `REG_CAP` (0, 0.30, 0.95, 1.0) | | `RS_MIN` [−0.05, 0.20], `D52_MAX` [−0.06, −0.005], `ATR_HI` [0.03, 0.10] |
| `CRASH_DAY` −3% | | `EXPO` [0.55, 1.0], `TIME_STOP` [15, 45], `W3/W6/W12` [0.10, 0.70] |

**adapt():** eleven dials; the standout device is **mean-reversion to shipped
defaults** — every parameter is pulled 6% toward its default before each
gradient step, so no bound can be ratcheted into. Over 26 in-sample windows
every parameter oscillated in a narrow band and none pinned.

---

## regime — how much and which, fully separated

Four-signal regime score → [−1, +1] (index trend vs 20/50/100/200d, w 0.34;
breadth level + slope, w 0.28; index momentum, w 0.12; subtractive stress,
w 0.26), ramped into gross over [`gross_floor` 0.42, 1.0], quantised to 25%
rungs with 9% hysteresis. The floor is deliberately non-zero — on a secular
uptrend, full cash is a fee. Risk is carried by same-session overrides:
circuit breaker (air-pocket on thin breadth → gross ≤ 35% for 3 sessions),
breadth thrust (34% → 58% inside 20 sessions → forced 100%, cancels the
equity stop), own-equity stop (−13% drawdown caps the book).

Name selection: 1m/3m/6m/12m momentum blend, vol-adjusted, 52w-high credit,
sector-momentum tilt that swings defensive below full exposure.

| Key defaults | | Adaptable (param_space) |
|---|---|---|
| `MIN_LIQ_ABS` $10M, `PX_MIN` $5 | | `ramp_lo` [−0.60, −0.10], `ramp_hi` [0, 0.40] |
| rungs 25% with 9% bands | | `gross_floor` [0.20, 0.70], `exposure_scale` [0.70, 1.12] |
| defensive sectors list | | `panic_ret` [−0.04, −0.012], `panic_breadth` [0.30, 0.58] |
| `RSI_MAX` 93 entry veto | | `thrust_hi` [0.50, 0.70], `eq_stop_dd` [−0.22, −0.06] |
| | | `hard_stop` [−0.20, −0.07], `trail_k` [2.4, 5.6], `w_m1..m12`, `rebal_every` [6, 18] |

**adapt():** tunes the ramp endpoints, override triggers, and momentum-horizon
weights from realized regime-call accuracy (was the book heavy in windows that
rose, light in windows that fell) and trade-level attribution.

---

## factor — five sleeves, re-weighted by what pays

Cross-sectional z-blend over the whole universe: trend-quality, fast momentum,
slow momentum, low-vol, short-term reversal — conviction-tilted inverse-vol
weights, ~9–10 names, weekly rebalance behind bands, vol-targeted gross with a
floor at 55%.

| Key defaults | | Adaptable (param_space) |
|---|---|---|
| `LIQ_MIN` $20M, `PX_MIN` $5 | | `W_TREND` [0.05, 0.60], `W_MOM_FAST` [0.02, 0.50] |
| `REBAL_EVERY` 5 sessions | | `W_MOM_SLOW` [0.05, 0.60], `W_LOWVOL` [0, 0.40], `W_REVERSAL` [0, 0.45] |
| `MAX_GROSS` 0.99, floor 0.55 | | `TARGET_VOL` [0.30, 0.62], `N_POS` [6, 14] |
| `HIT_TARGET` 0.45, `PF_TARGET` 1.5 | | `STOP_LOSS` [0.15, 0.35], `TRAIL_ATR` [4, 10], `MAX_W` [0.12, 0.26] |

**adapt():** the most literal back-propagation in the arena — each sleeve's
weight moves with learning rate `LR_SLEEVE` = 0.22 toward the sleeves whose
picks realized profit in the window (per-entry sleeve attribution recorded at
trade time, minimum 6 attributed trades before updating), then renormalizes;
book size, stop distance and vol target follow hit-rate/PF targets.

---

## defense — the shield is what you own

Near-fully invested (~94%); defense lives in selection (dual liquidity test —
smoothed turnover ≥ 30% of market median OR ≥ $10M absolute; ATR band; price
floor) and exits (regime-scaled trails `TRAIL_K × ATR` bounded [`TRAIL_LO`,
`TRAIL_HI`], tightened by a smoothed fear index; escalating own-drawdown
brakes DD_L1/L2/L3 with a bleeding high-water mark and refractory periods).
Scoring: medium-term momentum (w 2-ish) + trend quality + low-vol, spike
penalty on parabolic months.

| Key defaults | | Adaptable (param_space) |
|---|---|---|
| `N_SLOTS` 11, `MAX_W` 17.5% | | `TRAIL_K` [5, 13], `TRAIL_LO` [0.09, 0.22], `TRAIL_HI` [0.18, 0.38] |
| dual liquidity test | | `FEAR_SCALE` [0.30, 0.85], `HARD_STOP` [−0.22, −0.08] |
| `PEAK_BLEED` 0.0008/session | | `DD_L1/L2/L3` ladders, `TARGET_GROSS` [0.80, 0.99] |
| `SECTOR_CAP` 5 | | `ENTRY_POOL` [14, 45], `RANK_BUFFER` [6, 40], `MAX_OFF_HIGH` [0.16, 0.40], `W_MT`/`W_LT` |

**adapt():** trail widths and brake ladders follow realized drawdown behaviour
(shallow realized DD → let winners breathe more; deep → tighten), entry-pool
breadth follows opportunity-count, weights follow attribution.

---

## In-sample results (2016–2022, five together, peers live)

| Agent | Final | Return | maxDD | Trades |
|---|---|---|---|---|
| trend | $439,824 | +339.8% | −26.5% | 1,270 |
| factor | $435,564 | +335.6% | −34.4% | 1,683 |
| breakout | $415,364 | +315.4% | −23.8% | 406 |
| defense | $350,877 | +250.9% | −27.5% | 961 |
| regime | $262,634 | +162.6% | −31.0% | 1,394 |
| IXIC | $213,467 | +113.5% | −36%* | — |

*Composite drawdown from its own metrics. In-sample numbers are context, not
the ballot — the election is decided out-of-sample (see
[04](04-election-and-results.md)).
