# 09 — Operations Console: UI specification

The screen-by-screen spec for the console designed in docs/08. It is
written so a designer, or Claude Design using the prompt in
[`09a-claude-design-prompt.md`](09a-claude-design-prompt.md), can produce
the full interface without reading the harness code. The data examples are
real twin values from 2026-09-25.

---

## 1. Product and users

**NAFA Console** is a private operations dashboard for one automated,
long-only, Sharia-screened NASDAQ trading agent ("trend"), trading through
Alpaca. The agent decides after the close and its orders fill at the next
open. People do not pick trades; they **watch, verify and override**.

| User | Needs | Access |
|---|---|---|
| **Owner / operator** (primary) | A two-minute nightly check (desktop or phone), act fast on a problem, a monthly review | everything, including executive controls (with TOTP step-up) |
| **Viewer** (optional, e.g. a Sharia reviewer) | Compliance pages, holdings, history | read-only, no controls |

## 2. Design principles

1. **State first.** Each screen answers "is everything OK?" before it
   shows detail. Trading state (Running / Entries paused / Stopped /
   Halted / Held) is always visible.
2. **Two books, never confused.** *Model* (the twin, what the agent wants)
   and *Account* (Alpaca, what you own) are labelled everywhere, with a
   segmented switch and a consistent icon or label. Drift between them is
   its own concept.
3. **Every control says when it bites.** Each action shows an "Effective"
   line, e.g. "Effective: tonight's 19:15 ET submit", "Immediate", or
   "Next Cycle A, 17:05 ET Mon".
4. **Friction scales with danger.** Read is free. Reversible controls need a
   reason. Destructive ones need a reason, TOTP and typed confirmation.
5. **Freshness is visible.** Each panel shows its data age, and stale data
   turns amber or red.
6. **Honest numbers.** Confidence is "model conviction, not a forecast".
   Missing Sharia data is shown as missing, never as zero.
7. **Calm by default.** Colour is reserved for state, P&L sign and severity.
   Charts are clean and tables are dense but readable.

## 3. Information architecture

```
┌ Top bar: logo · environment badge (GHOST/PAPER/LIVE) · trading-state pill · tonight timeline · alerts bell · user
├ Left nav (collapsible; bottom tab bar on mobile)
│  1 Overview
│  2 Holdings            → Holding detail (drawer + full page)
│  3 Orders              tabs: Pending · History · Round trips
│  4 Performance         tabs: Equity · Returns · Attribution · Execution quality
│  5 Compliance          tabs: Holdings · Universe & watchlist · Re-screens · Purification
│  6 Controls            (executive desk)
│  7 Agent               params · adaptations · journal · confidence calibration
│  8 Health              cycles · data gate · broker · heartbeats · indexer
│  9 Alerts
│ 10 Audit log
│ 11 Roadmap             phases, gates, decisions D1–D8, task list
└ Settings               users, 2FA, notifications, display (theme, density, currency format)
```

Global: command palette (⌘K) for searching symbols, screens and actions;
keyboard shortcuts `g o`, `g h`, `g p` …; and a "Sync now" button with the
last indexer sync time.

## 4. Global chrome

### 4.1 Top bar (always visible, 56 px)

* **Environment badge:**
  * `GHOST` grey
  * `PAPER` blue
  * `LIVE` solid red with a subtle pattern, so live mode can never be
    mistaken for anything else
* **Trading-state pill** (clicking it opens Controls):
  * `RUNNING` green
  * `ENTRIES PAUSED` amber
  * `NIGHT HELD – approval needed` amber, pulsing
  * `HALTED – reconciliation break` red
  * `STOPPED (kill)` red
  * `DRAWDOWN KILL` red
* **Tonight timeline** (compact, expands on hover):
  * Steps: `Cycle A 17:05 ✓ · Submit 19:15 ⏳ 1h12m · Open 09:30 · Cycle B 09:50`
  * Each step is done, running, late, failed or skipped (non-session day).
  * Clicking a step jumps to that cycle in Health.
* **Alerts bell** with an open-P1 count (red badge) and a P2 count (amber).
* **Sync indicator:** "Ledger 2 min ago · Broker live" with a dot.

### 4.2 Global banners (stack under the top bar)

* **Red:**
  * "Cycle A has failed 4 sessions in a row (data gate: coverage 0.6% < 95%).
    Model book is from Fri 25 Sep."
  * Actions: View details · Re-run Cycle A.
  * This is a real current condition and is the motivating example.
* **Amber:** "Non-compliant holding with no exit queued: ROKU."
* **Blue info:** "Approval mode: tonight's orders need your release before
  09:28 ET."

## 5. Screens

### 5.1 Overview

The layout is a 12-column grid. From top to bottom:

1. **KPI row** (6 tiles). Each tile shows a value, a delta, a sparkline, and
   a book tag:
   * Equity: $90,407 · −9.6% since start · vs IXIC +3.0%
   * Today's P&L ($ and %)
   * Drawdown from peak vs the −16.2% reference and the −25% kill line
     (mini gauge)
   * Exposure: 94.8% invested · cash $4,696
   * Positions: 10 of a 15 maximum
   * Orders for the next open: 0 (2 buys / 1 sell; 1 blocked)
2. **Equity chart** (8 columns):
   * Lines: Model vs Account vs NASDAQ Composite, rebased to $100k.
   * Range chips: 1W 1M 3M YTD Since start All.
   * The drawdown area chart sits underneath with a shared x-axis.
   * Markers for adaptations (◆), overrides (⚑) and halts (■).
3. **Attention list** (4 columns): sorted actionable items with a severity
   icon, a one-line cause and a primary action button. Examples:
   * "Cycle A failed: data gate"
   * "ROKU review-flagged, ruling due 30 Oct"
   * "KNSA near the initial stop (0.4 ATR)"
   * "Drift 2.1% > band"
4. **Holdings snapshot** (8 columns): the top 10 rows of the Holdings table
   (compact).
5. **Phase card** (4 columns):
   * "Phase 1 · Ghost — gate streak 1/10 (earliest pass Fri 9 Oct)"
   * a progress ring
   * the next owner decision due ("D1 Sharia rulings — 28 days")
6. **Compliance strip:**
   * book by Sharia grade (stacked bar A/B/C/F)
   * "1 holding under review"
   * "Next re-screen 1 Jan 2027"

### 5.2 Holdings

**Controls row:**

* Book switch: `Model | Account | Side-by-side`
* search
* filters: sector, Sharia grade, confidence band, P&L sign, "near an exit
  trigger"
* column chooser
* export CSV

**Table columns:**

| Column | Example (GSAT) | Notes |
|---|---|---|
| Symbol + name | GSAT · Globalstar Inc. | logo optional; click opens the detail drawer |
| Sector | Consumer Discretionary | |
| Shares | 160 | side-by-side: model 160 / acct 158 with a drift chip |
| Avg cost | $83.04 | |
| Last | $82.88 | with day change |
| Market value | $13,261 | |
| Weight | 14.7% | inline bar; cap marker at 18% |
| Unrealized P&L | −$26 · −0.2% | green or red |
| Realized (this name, since start) | $0 | |
| Held for | 6 sessions | time-stop progress bar to 35 |
| Nearest exit | Initial stop $80.10 · 1.1 ATR away | amber if under 1 ATR |
| Confidence | **72 High** | a 4-segment micro bar (Signal/Risk/Regime/Data); hover gives the breakdown |
| Sharia | **A** · Compliant | badge; ROKU shows **C** · Under review |
| Pending | "SELL all @ open (forced)" | if any order is queued for this name |
| ⋯ | row menu | Lock · Trim · Force exit · View orders |

Totals row: market value, cash, equity, total unrealized, weighted
confidence.

**Sample rows (Model book, 25 Sep 2026):**

| Symbol | Shares | Avg cost | Last | Value | Weight | Unrl % | Sharia |
|---|---|---|---|---|---|---|---|
| GSAT | 160 | 83.04 | 82.88 | 13,260.80 | 14.7% | −0.2% | A |
| CORT | 108 | 113.70 | 116.10 | 12,538.80 | 13.9% | +2.1% | A |
| TXG | 135 | 64.04 | 85.71 | 11,570.85 | 12.8% | +33.8% | A |
| ROKU | 75 | 155.39 | 152.68 | 11,451.00 | 12.7% | −1.7% | C · review: streaming entertainment |
| HALO | 89 | 112.86 | 113.90 | 10,137.10 | 11.2% | +0.9% | A (debt 18.6%: the highest in the book, 11.4 pp headroom) |
| TWST | 36 | 165.91 | 182.83 | 6,581.88 | 7.3% | +10.2% | A |
| MU | 6 | 997.50 | 1,082.28 | 6,493.68 | 7.2% | +8.5% | A |
| ORKA | 75 | 98.23 | 84.46 | 6,334.50 | 7.0% | −14.0% | A |
| AMD | 7 | 621.81 | 630.63 | 4,414.41 | 4.9% | +1.4% | A |
| KNSA | 39 | 78.33 | 75.08 | 2,928.12 | 3.2% | −4.1% | A |

Cash $4,696.00 · Equity $90,407.14. The positions and prices are real;
confidence scores and stop levels in the examples are illustrative until
`insights.py` exists.

**Holding detail** (opens as a right drawer from the table, 560 px; "open
full page" for a wider view):

1. **Header:**
   * symbol, name, sector
   * book switch
   * a large P&L figure
   * action buttons: `Lock` `Trim…` `Force exit…`
2. **Price chart:**
   * daily candles or a line since the entry minus 60 sessions
   * the avg-cost line
   * stop lines (initial, trailing, hard), labelled
   * SMA50 and SMA200
   * buy and sell markers with fills
3. **Position facts:**
   * lots (FIFO)
   * entry date and reason ("rank 6 momentum, 1% off the 52w high, ATR 6.1%
     → 9% line")
   * time-stop countdown
   * cap headroom
4. **Confidence card:**
   * overall score with its band
   * four sub-score bars, each with its plain-language "why"
   * trend of the score over the holding period (sparkline)
   * the caption "Model conviction, not a forecast"
   * calibration note, e.g. "High band historically: NN% of round trips
     profitable (OOS 2023–26)" (the figure is computed in M3, so use a
     placeholder)
5. **Sharia card** (see §5.5 for the fields):
   * status
   * grade
   * ratio gauges with the 30% threshold and headroom
   * business-activity classification
   * review flag and ruling
   * last screened on
   * purification estimate
   * data source badge ("Unlicensed proxy – yfinance")
6. **Orders & fills for this name:** a lifecycle mini-timeline per order.
7. **Model vs account:** shares, avg cost, P&L difference, drift
   explanation.

### 5.3 Orders

**Tab: Pending (next open).**

* **Header card:**
  * "Next open: Mon 5 Oct 09:30 ET · submit window closes 09:28 ET ·
    status: PLANNED (ghost rehearsal)"
  * if the night is held: the hold reasons and a **Release night** primary
    button (opens the confirm flow)
* **Table columns:**
  * symbol
  * side (BUY/SELL chip)
  * quantity: shares, or $ amount → share preview
  * type (`MOO / opg`)
  * reference close
  * estimated value
  * reason (agent text)
  * source: `Agent` · `Forced exit (Sharia)` · `Manual (owner)`
  * guardrail result: ✓, or a blocked chip with the rule name, e.g.
    `pause_entries`, `max_pos_weight`
  * lifecycle state
  * client order id (monospace, copy button)
  * row actions: cancel (manual orders only) · view lifecycle
* **Footer summary:** buys $, sells $, net cash need, turnover vs the 75%
  limit, cash left estimate.

**Tab: History.**

* **Filters:** date range, symbol, side, status, source.
* **Columns:**
  * decision date
  * fill date
  * symbol
  * side
  * qty
  * decision close
  * official open
  * fill price
  * slippage (bps)
  * shortfall (bps)
  * value
  * fees
  * realized P&L (sells)
  * holding days
  * status
  * source
  * reason
* **Row expansion:** the full lifecycle timeline
  (`Intent 17:05 → Guardrails ✓ → Planned 19:15 → Accepted 19:15:04 →
  Filled 09:30:01 → Reconciled 09:50 ✓`), plus the raw JSON viewer.

**Tab: Round trips.**

* **One row per closed position:**
  * entry date, exit date
  * days held
  * entry price, exit price
  * P&L $ / %
  * exit reason category: stop, trailing, SMA200, rank decay, time stop,
    forced, manual
  * the confidence at entry
* **Summary:** win rate, average win vs average loss, profit factor, P&L by
  exit reason (bar chart).
* **Real examples:**
  * RVMD: 19 Aug → 21 Sep, −$1,586.44, "initial stop"
  * TVTX: 3 Sep → 23 Sep, −$383.81, "initial stop"

### 5.4 Performance

* **Equity tab:**
  * equity and drawdown charts (large)
  * a metrics table for Model, Account and Benchmark: total return, CAGR,
    Sharpe, Sortino, max drawdown, Calmar, volatility, win rate, trades
  * a reference column with the OOS election record (Sharpe 1.22, max
    drawdown −16.2%, CAGR 36.8%)
* **Returns tab:**
  * a monthly returns heatmap (years × months)
  * a period selector with P&L in $ and %
  * dividends gross, withholding, net
* **Attribution tab:**
  * P&L by holding (waterfall)
  * P&L by sector
  * P&L by exit reason
  * model vs account difference decomposed into slippage, drift, forced
    exits and manual overrides
* **Execution quality tab:**
  * a slippage per fill scatter with the ±10 bps band
  * the average vs the pre-registered band
  * a list of missed fills
  * a tracking-error-to-twin monthly bar vs the 0.5% band

### 5.5 Compliance

* **Holdings tab:** a card grid, one card per holding. Each card has:
  * a status badge
  * a big grade letter
  * debt/mcap and cash/mcap gauges: the 30% line, the value marker, and
    headroom in percentage points
  * impermissible income: "Not available – licensed data pending (R3)",
    shown in muted italic
  * the business-activity line (sector/industry and the keyword verdict)
  * instrument: common share ✓
  * a review flag with the ruling (pending, or approved/excluded on a date)
    and its due date
  * last screened on / next re-screen
  * purification due (or "rate pending")
  * a source badge
* **Portfolio summary:** % of the book by grade, held names under review,
  watchlist count.
* **Universe & watchlist tab:**
  * a table of all 319 universe names: status, grade, debt and cash
    headroom, review flag, held?
  * a "watchlist" filter for names within 3 pp of a threshold
* **Re-screens tab:**
  * a timeline of quarterly re-screens
  * each opens its diff: newly non-compliant names with reasons (e.g. "PEP
    debt/mcap 31% ≥ 30%"), newly eligible names, held-and-flagged names,
    the exclusions added to controls, and the forced exits they caused
* **Purification tab:**
  * a ledger of dividends: date, symbol, gross, withholding, net,
    impermissible %, amount to purify, paid?
  * yearly totals
  * a zakat estimate (marked "Planned – Phase 5")

### 5.6 Controls (executive desk)

A deliberately distinct, serious screen with a thin red rule along its top
edge.

1. **Trading state panel:**
   * Shows the current state and its since-time, and when the next cycle
     will read it.
   * Three large buttons:
     * `Pause entries` (amber) / `Resume entries`
     * `STOP TRADING` (red; cancels open orders immediately)
     * `Stop & flatten…` (red outline, under "More")
   * When stopped, a **Resume trading** button appears and opens the
     preflight checklist modal.
2. **Night release panel** (visible when held):
   * the hold reasons (e.g. "approval mode", "turnover 82% > 75%")
   * the tonight orders summary
   * a **Release tonight's submission** button
   * a note that hard holds (kill, drawdown kill, halt) cannot be released
     here
3. **Halt panel** (visible when `halt.json` is halted):
   * the diffs table (symbol, expected, actual, diff)
   * a required "cause" text area
   * a **Clear halt** button
4. **Holding overrides:**
   * a table of held names with Lock toggle, Trim…, and Force exit…
   * the current excluded list, as chips with an "added by / reason / date"
     tooltip; remove with a reason
   * the current locked list
   * the manual order queue, with an expiry
5. **Risk limits:**
   * gross cap slider (off, or 0–100%)
   * read-only display of the hard guardrails: max position weight 18%,
     daily turnover 75%, ADV cap 5%, drawdown kill −25%
6. **Agent:** a `Pause adapt()` toggle, with a fidelity warning.
7. **Maintenance:** re-run Cycle A / Submit / Cycle B for a date (with the
   idempotence note); sync the ledger now.
8. **Pending control changes:** changes committed but not yet read by a
   cycle, each with an "Effective at" line.

**Confirm flow (modal, same pattern for every action):**

* **Step 1 — Impact preview:**
  * what changes (before → after)
  * orders added, blocked or canceled
  * estimated proceeds
  * realized P&L locked in
  * drift impact
  * **Effective** line
  * fidelity warning box (if any)
* **Step 2 — Reason:** a category select and a required text field.
* **Step 3 — Authenticate:** TOTP, and for destructive actions, typing
  `STOP`, `FLATTEN` or the symbol.
* **Step 4 — Result:** a progress list (`Validated ✓ · Committed a1b2c3d ✓ ·
  Pushed ✓ · Broker canceled 3 orders ✓`) with the final state. If a step
  fails, the modal says **"Not applied"** plainly and offers a retry.

**Resume preflight checklist:** a modal with checks, each green, red, or a
manual tick:

* no reconciliation halt
* last reconciliation OK
* last Cycle A OK (or acknowledged with a note)
* no open P1
* drawdown above the kill line
* broker reachable
* acknowledgment of the active deviations (locked / excluded / manual)

The Resume button is enabled only when every check passes.

### 5.7 Agent

* **Parameters table:** name, current value, bounds (as a range bar with a
  marker), and the value at freeze. Example: `EXP_MAX 0.95 [0.6–1.0]`,
  `STOP_ATR 3`, `TRAIL_ATR 5`, `TIME_STOP 35`.
* **Adaptation trail:** a timeline of each `adapt()` firing (every 63
  sessions; the next is shown as "Next adapt: ~2 Feb 2027"), with a
  parameter diff.
* **Journal:** mood and sentiment over time (a line from −1 to 1 with mood
  bands) and the agent's notes, e.g. "Closed Arrowhead Pharmaceuticals at
  −18.6% — initial stop… Book now 80% invested."
* **Regime gauges:** IXIC vs SMA200/50, breadth, the exposure dial.
* **Confidence calibration:** the hit rate and average return by confidence
  band from the backtest, alongside the live figures.

### 5.8 Health

* **Cycle timeline:** a calendar or list of the last 40 cycles (A/S/B/R)
  with status chips: ok, data gate tripped, held, killed, failed. Each has
  its duration and opens the raw record.
* **Data gate detail:**
  * the latest checks with pass/fail and values: IXIC at asof ✓, fetch ok
    96.9% ✓, **coverage at asof 0.6% ✗ (min 95%)**, cross-source compared
    1 / unavailable 39
  * the list of missing symbols
* **Ghost gate:** the streak bar 1/10 and the history of hashes.
* **Determinism:** the last sha256 and a match ✓.
* **Broker:** reachability, account status, buying power, last API
  latency.
* **Heartbeats:** each scheduled step's expected time, last ping and
  status.
* **Indexer:** last commit indexed, lag, errors.

### 5.9 Alerts, Audit, Roadmap, Settings

* **Alerts:**
  * an inbox with filters (P1, P2, open, acknowledged, resolved)
  * each alert has its source cycle, a linked GitHub issue, and
    acknowledge/resolve with a note
  * notification routing (ntfy topic) is configured in Settings
* **Audit log:** an immutable table of every control change and command
  with:
  * time
  * actor
  * action
  * before → after
  * reason
  * effective-at
  * commit SHA (links to the diff)
  * result
  * filters and CSV export
* **Roadmap:**
  * the docs/07 route as a horizontal phase stepper (Ghost → Paper →
    Evaluation → Private build → Real money), each with its dates and gate
    criteria showing live pass/fail
  * an owner decision table D1–D8 with due dates and status
  * the task list (G/P/E/U/R/S/X) with an owner, due date and status
  * a countdown chip for anything due within 14 days
* **Settings:**
  * users and roles
  * 2FA enrolment
  * notification preferences
  * theme: system / light / dark
  * table density
  * time zone: always shows ET for market times, with local time on hover
  * number formats

## 6. Components and visual language

* **Tone:** a professional fintech operations console. Calm, dense and
  precise; closer to a trading-desk blotter than a consumer investing app.
  Light and dark themes are both first-class, with dark as the default.
* **Type:**
  * Inter (UI) with JetBrains Mono for ids, hashes and tabular figures
  * tabular-nums throughout the numeric columns
* **Colour tokens:**
  * neutral greys
  * `positive` green, `negative` red (P&L sign only)
  * `warn` amber, `danger` red, `info` blue
  * environment colours: ghost grey, paper blue, live red
  * Sharia grades: A teal, B green-teal, C amber, F red
* **Accessibility:** colour is never the only signal. Use a sign (+/−),
  icons and text labels too. Meet WCAG AA contrast and support
  colour-blind-safe pairs.
* **Components:**
  * KPI tile with sparkline
  * status pill
  * environment badge
  * timeline stepper (horizontal and compact)
  * lifecycle mini-timeline
  * data table (sticky header, sortable, column chooser, row expansion,
    density toggle, virtualised to 5k rows)
  * gauge-with-threshold (for ratios, drawdown and the kill line)
  * sub-score micro-bar
  * grade badge
  * freshness chip ("2 min ago", amber/red when stale)
  * confirm modal (four steps)
  * checklist modal
  * right drawer
  * banner
  * empty, loading (skeleton) and error states for every panel
* **Charts:**
  * line (equity), area (drawdown)
  * heatmap (monthly returns)
  * waterfall (attribution)
  * scatter (slippage)
  * candles with overlays (holding detail)
  * a shared crosshair tooltip with exact values and dates

## 7. States to design

For each main screen: **loaded**, **loading**, **empty** (e.g. no
positions yet in a cold start, "Account starts in cash on 2 Nov"),
**stale** (cycle failed, amber or red freshness and the banner), and
**error** (indexer or broker down).

For Controls: **running**, **entries paused**, **night held**, **halted**,
**stopped**, and the confirm modal at each step, including **failure**
("Not applied").

## 8. Responsive behaviour

* **≥ 1280 px:** full grid with a left nav.
* **768–1279 px:** collapsed nav rail; the holding drawer becomes full
  page.
* **< 768 px (phone):**
  * a bottom tab bar: Overview, Holdings, Orders, Controls, More
  * KPI tiles in a 2-column grid
  * tables become cards: symbol, value, P&L, confidence and Sharia badges
  * **Controls stay fully usable on the phone:** big tap targets and the
    same confirm flow
  * 16 px side gutter and no horizontal page scroll (tables scroll inside
    their own container)

## 9. Out of scope for design

* login and TOTP enrolment screens: a simple standard pattern is enough
* charts library choice: the engineering decision is ECharts
