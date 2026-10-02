# 09a — Prompt for Claude Design

Paste everything between the two rules into Claude Design. It is
self-contained; the full spec is in docs/09 and the architecture in docs/08.
If Claude Design accepts attachments, also attach `09-console-ui-spec.md`.

---

Design a complete, high-fidelity, clickable prototype of **NAFA Console**:
a private operations dashboard for an automated stock-trading agent. It is
self-hosted on a home server and used on desktop and on a phone.

## Context

* One automated, long-only agent called **"trend"** trades a
  **Sharia-compliant (AAOIFI-screened) universe of 319 NASDAQ stocks**
  through the broker Alpaca. It starts with $100,000 of capital.
* **Every weekday:**
  * after the close (17:05 ET), "Cycle A" decides tomorrow's orders
  * at 19:15 ET a "Submit" step sends them as market-on-open orders
  * at 09:30 they fill at the open
  * at 09:50 "Cycle B" checks the fills and reconciles the account
* People never pick trades. The owner's job is to **watch, verify, and
  override when needed**.
* There are always **two books**:
  * **Model**: the agent's simulated twin, what it wants to hold
  * **Account**: what the broker actually holds

  The gap between them is called **drift**.
* The system goes through phases, shown as an environment badge:
  **GHOST** (no broker, rehearsal; now), **PAPER** (paper account, from Nov
  2026), **LIVE** (real money, 2027).

## Users

* **Owner/operator:** does a 2-minute nightly check, sometimes from the
  phone; must be able to act fast.
* **Optional read-only viewer:** for example a Sharia reviewer.

## What the dashboard must do

1. Show **current holdings** in full detail:
   * shares, average cost, last price, value, weight
   * unrealized and realized P&L
   * days held vs a 35-session time stop
   * the **nearest exit trigger** (e.g. "Initial stop $80.10 · 1.1 ATR
     away")
   * any pending order on the name
2. Show **pending orders** for the next open. Each has:
   * side, shares or $ amount, reference close, estimated value
   * the agent's reason text
   * source: Agent / Forced exit (Sharia) / Manual (owner)
   * the guardrail result (passed, or blocked with a rule name such as
     `pause_entries`)
   * its lifecycle state
3. Show the **complete order history**:
   * decision close, official open, fill price, slippage and shortfall in
     bps, fees, realized P&L
   * an expandable **lifecycle timeline** per order: Intent 17:05 →
     Guardrails ✓ → Planned 19:15 → Accepted → Filled 09:30 → Reconciled
     09:50 ✓
   * a **Round trips** view with win rate, average win/loss, profit factor,
     and P&L by exit reason
4. Show **detailed Sharia compliance per holding**:
   * status: Compliant / Under review / Non-compliant – exit queued /
     Excluded
   * a **grade A/B/C/F**
   * debt/market-cap and cash/market-cap gauges against the 30% line, with
     headroom in percentage points
   * the business-activity verdict and an instrument check (common share)
   * the review flag and the owner's ruling with its due date
   * last screened on / next re-screen
   * purification due on dividends, and a data-source badge (currently
     "Unlicensed proxy")
   * Missing data (impermissible-income %) is shown honestly as "Not
     available – licensed data pending", never as zero.
5. Show a **confidence rating per holding**:
   * a 0–100 score, banded High (≥ 70) / Medium / Low
   * four sub-scores shown as a segmented micro-bar: **Signal** (agent's
     rank/momentum), **Risk room** (distance to stops), **Regime** (market
     backdrop), **Data** (input quality)
   * a "why" breakdown and a sparkline over the holding period
   * always captioned **"Model conviction, not a forecast."**
6. Provide an **executive control desk**:
   * **Pause entries** (sells still happen)
   * **STOP TRADING** (kill switch; cancels open orders now)
   * **Stop & flatten** (sell everything at the next open)
   * **Resume trading**, behind a **preflight checklist**
   * **Release a held night** (approval mode)
   * **Clear a reconciliation halt**, with a required cause
   * **per-holding overrides:** Lock (agent may not trade it), Trim/sell
     some, Force exit, and the excluded-symbols list
   * a gross exposure cap
   * Pause the agent's learning (`adapt()`)
   * re-run a cycle

   Every action shows an **"Effective:" line** saying when it takes effect
   ("Immediate", "Tonight's 19:15 ET submit", "Next Cycle A, Mon 17:05 ET").
   Every action goes through one **4-step confirm modal**:
   1. impact preview: before→after, orders added/blocked/canceled,
      estimated proceeds, P&L locked in, fidelity warning
   2. a required reason
   3. a 2FA code, plus typing STOP/FLATTEN/the symbol for destructive
      actions
   4. a result checklist (Validated ✓ · Committed `a1b2c3d` ✓ · Pushed ✓ ·
      Broker canceled 3 orders ✓). If anything fails, the result must say
      **"Not applied"** clearly.

## Screens (left nav; bottom tab bar on phone)

1. **Overview**
   * 6 KPI tiles: Equity, Today's P&L, Drawdown with a gauge to the −25%
     kill line, Exposure/cash, Positions x/15, Orders for next open
   * an equity chart (Model vs Account vs NASDAQ Composite) with the
     drawdown area beneath and markers for adaptations ◆, overrides ⚑ and
     halts ■
   * an "Attention" list of actionable items
   * a holdings snapshot
   * a phase/gate card
   * a compliance grade strip
2. **Holdings**
   * a table with a Model | Account | Side-by-side switch, filters and CSV
     export
   * a right **detail drawer** with:
     * a price chart with avg-cost and stop lines and buy/sell markers
     * FIFO lots
     * the confidence card and the Sharia card
     * the orders for that name
     * model vs account comparison
3. **Orders:** tabs Pending · History · Round trips.
4. **Performance:** tabs Equity (metrics table vs the out-of-sample
   reference: Sharpe 1.22, max drawdown −16.2%, CAGR 36.8%) · Returns
   (monthly heatmap, dividends/withholding) · Attribution (waterfall by
   holding, sector, exit reason; model-vs-account gap) · Execution quality
   (slippage scatter with a ±10 bps band, tracking error vs a 0.5%/month
   band).
5. **Compliance:** tabs Holdings (card grid) · Universe & watchlist (names
   within 3 pp of a threshold) · Re-screens (quarterly diff timeline) ·
   Purification (dividend ledger, yearly totals, zakat "planned").
6. **Controls** (executive desk): a visually distinct, serious screen with
   a thin red top rule. Panels:
   * trading state with 3 big buttons
   * night release (when held)
   * halt (when halted)
   * holding overrides table
   * risk limits: gross cap slider; read-only hard limits of max position
     18%, daily turnover 75%, drawdown kill −25%
   * agent learning toggle
   * maintenance
   * pending control changes with an effective time
7. **Agent:** parameters vs bounds (range bars), an adaptation timeline
   (every 63 sessions; next ~2 Feb 2027), a mood/sentiment journal chart,
   regime gauges, confidence calibration.
8. **Health:**
   * a cycle timeline for the last 40 cycles with status chips
   * data gate details
   * the ghost gate streak (1/10)
   * the determinism hash
   * broker status
   * heartbeats per scheduled step
   * indexer lag
9. **Alerts** (P1/P2 inbox with acknowledge/resolve), **Audit log**
   (immutable table of every control change: time, actor, before→after,
   reason, effective-at, commit SHA), **Roadmap** (phase stepper Ghost →
   Paper → Evaluation → Private build → Real money, with gate criteria;
   owner decisions D1–D8 with due dates; task list), **Settings**.

## Global chrome

* A top bar with:
  * an **environment badge**: GHOST grey, PAPER blue, LIVE solid red; live
    must be unmistakable
  * a **trading-state pill**: RUNNING green, ENTRIES PAUSED amber, NIGHT
    HELD amber pulsing, HALTED red, STOPPED red
  * a compact **tonight timeline**: Cycle A 17:05 ✓ · Submit 19:15 ⏳ 1h12m
    · Open 09:30 · Cycle B 09:50
  * an alerts bell with P1/P2 counts
  * a "Ledger synced 2 min ago" freshness indicator
* A ⌘K command palette.
* **Banners** stacked under the top bar.
* Every panel shows its **data age**, which turns amber or red when stale.

## Realistic sample data (use these; positions and prices are real)

Asof Fri 25 Sep 2026 · Model equity **$90,407.14** · cash **$4,696.00** ·
since-start −9.6% vs NASDAQ Composite +3.0% · 10 positions.

| Symbol | Name | Sector | Shares | Avg cost | Last | Value | Weight | Unrl % | Sharia |
|---|---|---|---|---|---|---|---|---|---|
| GSAT | Globalstar Inc. | Consumer Discretionary | 160 | 83.04 | 82.88 | 13,260.80 | 14.7% | −0.2% | A |
| CORT | Corcept Therapeutics | Health Care | 108 | 113.70 | 116.10 | 12,538.80 | 13.9% | +2.1% | A |
| TXG | 10x Genomics | Industrials | 135 | 64.04 | 85.71 | 11,570.85 | 12.8% | +33.8% | A |
| ROKU | Roku Inc. | Telecommunications | 75 | 155.39 | 152.68 | 11,451.00 | 12.7% | −1.7% | C · Under review: "streaming entertainment platform", ruling due 30 Oct |
| HALO | Halozyme Therapeutics | Health Care | 89 | 112.86 | 113.90 | 10,137.10 | 11.2% | +0.9% | A · debt/mcap 18.6% |
| TWST | Twist Bioscience | Health Care | 36 | 165.91 | 182.83 | 6,581.88 | 7.3% | +10.2% | A |
| MU | Micron Technology | Technology | 6 | 997.50 | 1,082.28 | 6,493.68 | 7.2% | +8.5% | A |
| ORKA | Oruka Therapeutics | Health Care | 75 | 98.23 | 84.46 | 6,334.50 | 7.0% | −14.0% | A |
| AMD | Advanced Micro Devices | Technology | 7 | 621.81 | 630.63 | 4,414.41 | 4.9% | +1.4% | A |
| KNSA | Kiniksa Pharmaceuticals | Health Care | 39 | 78.33 | 75.08 | 2,928.12 | 3.2% | −4.1% | A |

Recent trades and agent reasons:

* 23 Sep: BUY AMD 7 @ 621.81, "rank 6 momentum, 0% off the 52w high, ATR
  4.1% → 13% line"
* 23 Sep: SELL TVTX 56 @ 60.36, realized −$383.81, "initial stop: 60.28
  through 60.37 (3.0 ATR)", held since 3 Sep
* 22 Sep: BUY TWST 36 @ 165.91, "rank 6 momentum, 1% off the 52w high"
* 21 Sep: SELL RVMD 60 @ 192.51, realized −$1,586.44, "initial stop",
  held since 19 Aug
* 21 Sep: BUY HALO 89 @ 112.86

Agent journal:

* 15 Sep, mood "trending", sentiment 0.39: "Closed Arrowhead
  Pharmaceuticals at −18.6% — initial stop. Book now 80% invested."

Parameters:

* EXP_MAX 0.95
* RISK_PER_TRADE 0.016
* STOP_ATR 3
* TRAIL_ATR 5
* TIME_STOP 35
* TARGET_VOL 0.17

Re-screen 1 Oct 2026:

* 25 names newly non-compliant, e.g. "PEP debt/mcap 31% ≥ 30%", "BKR
  cash/mcap 31%"
* 13 newly eligible
* 0 held names affected

Health (a real failure, use it for the stale/error state):

* Cycle A has failed 4 sessions in a row (28 Sep → 1 Oct) with "data gate
  tripped: coverage at asof 0.6% < 95%".
* Fetch ok 96.9%; cross-source compared 1, unavailable 39.
* The model book is stuck at 25 Sep; the ghost gate streak is 1/10.
* Show this as a red banner: "Cycle A has failed 4 sessions in a row…
  Model book is from Fri 25 Sep" with the actions [View details] [Re-run
  Cycle A].

Confidence scores, stop levels and the purification figures are
illustrative; invent plausible values. Make ORKA (−14%) low confidence and
close to a stop, TXG high confidence, and ROKU medium.

## Visual direction

* A professional fintech **operations console**: calm, dense, precise.
  Closer to a trading-desk blotter than a consumer investing app.
  **Dark theme default**, with an equally polished light theme.
* Inter for the UI and JetBrains Mono for ids and hashes; tabular numerals
  in all numeric columns.
* Colour is reserved for meaning: P&L sign (green/red, always with +/−),
  severity (amber/red/blue), environment (grey/blue/red), Sharia grade
  (A teal, B green-teal, C amber, F red). Never rely on colour alone (WCAG
  AA, colour-blind safe).
* Friction scales with danger: reads are effortless; destructive controls
  feel deliberate (red, typed confirmation) without being garish.
* Charts are clean, with a shared crosshair tooltip.

## States to show

* For each main screen: loaded, loading (skeletons), empty (e.g. "Account
  starts in cash on Mon 2 Nov"), stale (the Cycle A failure above), and
  error (broker unreachable).
* For Controls: Running, Entries paused, Night held (approval mode),
  Halted (reconciliation break; the diffs table shows ROKU expected 75,
  actual 74), Stopped, plus every step of the confirm modal, including the
  "Not applied" failure.

## Responsive

* Desktop ≥ 1280 px: full layout.
* Tablet: collapsed nav rail.
* **Phone < 768 px:**
  * a bottom tab bar: Overview · Holdings · Orders · Controls · More
  * tables become cards
  * Controls fully usable with large tap targets
  * 16 px gutter and no horizontal page scroll

## Deliverables

1. A clickable prototype of all screens above, with the confirm-modal flow
   working for STOP TRADING, Force exit (ROKU), Lock (TXG), Release night,
   and Resume (with the preflight checklist).
2. The phone layouts for Overview, Holdings, a holding detail, Orders
   (pending) and Controls.
3. A small component sheet: KPI tile, status pill, environment badge,
   timeline stepper, lifecycle mini-timeline, data table, threshold gauge,
   confidence micro-bar, grade badge, freshness chip, banner, confirm
   modal, checklist modal, drawer.
4. Design tokens (colours for both themes, type scale, spacing, radii) in a
   form that is easy to hand to a React + Tailwind implementation.

---
