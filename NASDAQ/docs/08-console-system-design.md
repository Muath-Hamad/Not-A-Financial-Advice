# 08 — Operations Console: system design

The **console** is a private web dashboard for the live trading harness
(docs/05–07). It runs on the Unraid tower and has two jobs:

1. **See everything:** current holdings, pending orders, the full order
   history with profit and loss, the Sharia status and a confidence rating
   for every holding, system health, and how far the account has drifted
   from the twin.
2. **Decide and override:** stop and resume trading, pause entries, force an
   exit or lock a holding, release a held night, and clear a halt. Every
   action is recorded as an audit event, in the same way the harness records
   human control today (the commit is the audit event).

It replaces the static cockpit page (`live/cockpit/`) as the operator's main
screen. The cockpit stays as a public, read-only page. The UI is specified
in docs/09.

Written 2026-10-02, during Phase 1 (ghost). *Not financial advice.*

---

## 1. Goals and non-goals

| Goals | Non-goals |
|---|---|
| One screen that answers "what do I own, what am I about to trade, how am I doing, is it halal, is the system healthy" | Replacing the harness's decision logic. The console never decides a trade. |
| Executive controls that take effect at a clear, stated moment, with a written reason, recorded as an audit event | Discretionary trading terminal: manual orders are a narrow, labelled override |
| Two books side by side: the **model** (twin) and the **account** (Alpaca), plus the drift between them | Public internet exposure |
| Works today in ghost mode from the public ledger; grows into paper (Nov 2026) and the private real-money box (2027) without a rewrite | Holding real-money broker keys inside the web app |
| A per-holding confidence rating that is honest about what it measures | A promise of profit; ratings are descriptive, not predictive |

## 2. Constraints from the harness

These facts about the existing system drive the design (paths are under
`NASDAQ/live/`):

* **Replay-as-state.** Cycle A re-runs the frozen `trend` agent from
  `LIVE_START` every night. `ledger/twin/twin_latest.json` is the complete
  model state: positions with `avg_cost` and `unrealized_pct`, `trades[]`
  with `realized_pnl`, `adaptations[]`, `journal[]`, `params`, `metrics`.
  There is no per-day position history; it can be rebuilt from git history
  or by replaying `trades`.
* **The ledger is git.** Records are written as files and committed:
  `cycles/<d>-A|S|B.json`, `orders/<d>.json`, `gate.json`, `twin/equity.csv`,
  `compliance/<d>.json`, `halt.json`. Today they live on `main` in the
  public repository. On the Unraid box they will live in a private ledger
  repository (decision D6).
* **Controls are files.** `controls.json` (`kill`, `pause_entries`,
  `excluded_symbols`, `gross_cap`) is changed by hand-editing and committing
  it. Cycle A and the re-screen job also commit to it, so writes can collide.
* **Timing is fixed.** Cycle A at 17:05 ET ledgers orders. The submit step
  runs at 19:15 ET with retry slots, and orders can be sent until 09:28 ET.
  They fill as market-on-open (`opg`). Cycle B at 09:50 ET traces fills and
  reconciles. A control change is therefore only useful if the UI says
  **when** it takes effect.
* **The account side is barely persisted.** Alpaca's cost basis, P&L and
  equity history are not stored. Only `S.account` and `positions_before`
  (quantities only), the B record's `fills`, and `account_drift` are kept.
* **Sharia data is a snapshot.** `data/universe_screened.json` holds
  per-name debt and cash ratios, the business, instrument and override
  layers, `review_flags`, and `pass`. It has no per-name date, no
  impermissible-income percentage, and no purification figure. Those
  arrive with licensed data (task R3). Review-flagged names wait for the
  owner's rulings (D1, due 30 Oct 2026).
* **No stored confidence.** The agent's score and rank exist only inside
  `trend.py` and in free-text `reason` strings. Changing the strategy breaks
  the freeze hash (`7e8cdf1`), so any rating must be computed outside it.
* **Security rule (docs/05 §9, docs/07 §5).** Real-money keys never enter
  the public repository. The Unraid box allows **no inbound ports from the
  internet**.

## 3. Architecture

```
                         ┌──────────────── Unraid tower ─────────────────────────────┐
                         │                                                           │
 phone / laptop ──VPN──► │  nafa-console  (container, LAN + Tailscale only)          │
 (Tailscale / WireGuard) │  ┌──────────────┐   ┌─────────────────────────────────┐   │
                         │  │ Web UI (SPA) │◄──│ API (FastAPI)                   │   │
                         │  └──────────────┘   │  • read model (SQLite)          │   │
                         │         ▲  SSE      │  • indexer  (ledger → SQLite)   │   │
                         │         └───────────│  • insights (confidence, P&L)   │   │
                         │                     │  • control service (audited)    │   │
                         │                     └──────┬───────────────┬──────────┘   │
                         │                            │               │              │
                         │           ledger clone ◄───┘               │ HTTP (internal docker net)
                         │           (git pull / commit)              ▼              │
                         │                            ┌─────────────────────────────┐│
                         │                            │ broker gateway              ││
                         │                            │ (in nafa-live from Phase 4; ││
                         │                            │  in nafa-console for paper) ││
                         │                            └──────────────┬──────────────┘│
                         └───────────────────────────────────────────┼───────────────┘
                                   │ git push/pull                   │ HTTPS
                                   ▼                                 ▼
                   ledger remote (GitHub main now;          Alpaca (paper → live)
                   private ledger repo from Phase 4)
                   + GitHub Actions (cycles, workflow_dispatch)
```

### 3.1 Components

| Component | Responsibility | Tech |
|---|---|---|
| **Web UI** | Screens in docs/09, live updates over server-sent events (SSE) | React + TypeScript + Vite, Tailwind, TanStack Query/Table, ECharts (or lightweight-charts for price panes) |
| **API** | REST for reads, POST for commands, SSE for events, authentication | Python 3.12 + FastAPI + Uvicorn. Python so it can import `live/config.py`, `execution.py` and `guardrails.py` directly and stay in step with the harness rules |
| **Indexer** | Pulls the ledger every 60 s (and on a webhook or manual "sync"), parses new or changed files, upserts them into the read model, and emits SSE events. Idempotent and resumable from the last indexed commit. | Python worker in the same container |
| **Read model** | Queryable copy of the ledger plus broker snapshots. It is disposable: if deleted, it is rebuilt from the ledger and the broker. | SQLite (WAL) at `/data/console.db` |
| **Insights engine** | Builds the derived views: position lots and FIFO P&L, round trips, confidence ratings, Sharia grades, drift and tracking error | Python. Pure functions with tests in `NASDAQ/tests/console/` |
| **Control service** | Validates an action, writes the control file, commits with a structured audit message, pushes with optimistic concurrency, and triggers a workflow or gateway command when the action is immediate | Python, using the git CLI or the GitHub REST API |
| **Broker gateway** | The only process that holds broker keys. It exposes read endpoints (account, positions, open orders, activities, portfolio history) and a small set of immediate commands (cancel all, flatten), and records each command in the ledger. | Python, small FastAPI app on an internal Docker network, never published on a host port |

### 3.2 Deployment by phase

| Phase (docs/07) | Ledger source | Broker data | Controls are written to | Immediate commands |
|---|---|---|---|---|
| **1 Ghost** (now → 30 Oct 2026) | read-only clone of the public repository, `main` | none (the twin is the book) | `main` through the GitHub contents API (fine-grained PAT) | none needed; `workflow_dispatch` re-runs |
| **2–3 Paper** (2 Nov 2026 → May 2027) | same | gateway in `nafa-console`, Alpaca **paper** keys | same | gateway with paper keys, plus a new `live-control.yml` workflow so GitHub-side runs see the same command |
| **4 Private burn-in** (Feb 2027) | private ledger repository, local clone shared with `nafa-live` | gateway moves into `nafa-live` | local commit to the ledger repository, which `nafa-live` reads; push to the remote | gateway in `nafa-live` |
| **5 Real money** (May 2027 →) | same | gateway in `nafa-live`, **live** keys, armed only there (R2) | same | same; the console never sees live keys |

The console is a separate container from the executor `nafa-live`, so a UI
bug or crash cannot stop a trading cycle, and the web-facing process never
holds live keys.

### 3.3 Container layout

```
nafa-console   (python:3.12-slim + node build stage → static assets)
├── /app            console code at a pinned tag (read-only)
├── /data           /mnt/user/appdata/nafa-console/
│   ├── console.db          read model (rebuildable)
│   ├── ledger/             git clone (Phases 1–3) or bind mount of nafa-live's ledger (Phase 4+)
│   └── backups/            nightly SQLite snapshot (not authoritative)
├── /secrets/console.env    chmod 600: GH_PAT, SESSION_SECRET, TOTP seed hash,
│                           ALPACA_PAPER_* (Phases 2–3 only), NTFY/ALERT_WEBHOOK_URL
└── port 8080 → bound to the LAN IP / tailscale0 only
```

Use an Unraid Community Applications–style template with
`--restart unless-stopped`. The health endpoint `/healthz` is polled by
Uptime Kuma.

## 4. Data model (read model)

All tables carry `source` (`ledger` | `broker` | `derived`) and `as_of`.

| Table | Grain | Built from |
|---|---|---|
| `cycles` | one row per cycle record (A/S/B/rescreen) | `cycles/*.json`: status, timings, gate, guardrail and hold summaries; raw JSON kept |
| `model_positions` | (asof, symbol) | `twin_latest.json` per night. History is backfilled by walking the git log of that file. |
| `model_trades` | one row per twin trade | `twin_latest.json.trades` (deduplicated by date, symbol, side and shares) |
| `equity_curve` | (date, book) where book ∈ model, account, bench | `twin/equity.csv`, plus Alpaca `/v2/account/portfolio/history` |
| `order_intents` | one row per ledgered order | `orders/<d>.json`: side, amount, reason, `blocked[]`, `forced`, `client_order_id`, share preview |
| `order_events` | lifecycle events keyed by `client_order_id` | intent (A) → guardrail result → plan/skip/adjust/hold (S) → broker accepted/rejected → fill(s) (B and the broker) → reconciled (B) |
| `account_positions` | (snapshot_ts, symbol) | gateway `/positions`: qty, `avg_entry_price`, market value, `unrealized_pl`, `unrealized_plpc` |
| `fills` | one per broker fill | Alpaca FILL activities, plus B `fills` |
| `lots` | FIFO tax-lot per buy fill | derived from `fills` (account) or `model_trades` (model) |
| `round_trips` | one per closed lot portion | derived: entry/exit dates and prices, holding days, gross and net P&L, fees, slippage, entry and exit reasons |
| `cash_events` | dividends, withholding, fees, transfers | Alpaca DIV / DIVNRA / FEE / CSD activities |
| `sharia_status` | (symbol, effective_date) | `universe_screened.json`, `rescreen/*`, `compliance/*`, `sharia_overrides.json`, `controls.excluded_symbols`, licensed vendor later (R3) |
| `confidence` | (asof, symbol) | insights engine (§6) |
| `controls_history` | one per commit touching a control file | `git log -p` of `controls.json` and `halt.json`, plus console-originated audit records |
| `alerts` | P1/P2 events | GitHub issues labelled `live-p1`, the cycle records, and the console's own checks |
| `gate` | per night | `gate.json` |

### 4.1 Profit and loss

* **Model P&L:** unrealized = `(price − avg_cost) × shares`; realized is
  `realized_pnl` per sell. Both are already in the twin. Lots are rebuilt
  FIFO from `trades` so each round trip has its own row.
* **Account P&L:** FIFO lots built from fills.
  * **Realized** = Σ (exit fill − lot cost) × qty − fees.
  * **Unrealized** comes from the gateway's current positions and is
    cross-checked against the console's own lots. A difference greater than
    $1 is a P2 data warning.
  * **Dividends** are reported gross, minus the 30% withholding, to give
    net.
  * **Purification** is shown separately (§5).
* **Attribution per order:**
  * **slippage** = fill − official open (bps, signed by side)
  * **implementation shortfall** = fill − the decision close (`ref_close`)
  * **drift cost** = account P&L − model P&L for the same window
* **Periods:** today, MTD, QTD, YTD, since `LIVE_START`, since the phase
  start, and custom. Returns are time-weighted (NAV-based) so deposits do
  not distort them.

### 4.2 Order lifecycle (one order, every state the UI can show)

```
INTENT (17:05 A) ─► BLOCKED (guardrail/control)             terminal
       │
       ├─► HELD (night held: approval / portfolio guardrail / halt / kill) ─► RELEASED ─┐
       ▼                                                                               │
 PLANNED (19:15 S) ─► SKIPPED | ADJUSTED (qty trimmed to cash, partial→full exit) ◄────┘
       ▼
 SUBMITTED (broker accepted, opg) ─► REJECTED | CANCELED (kill / manual)   terminal
       ▼
 FILLED | PARTIAL | MISSED (09:30 auction) ─► RECONCILED ok | BREAK (halt.json)
```

The pending-orders view lists everything in a non-terminal state for the
next open. In ghost mode, SUBMITTED means "rehearsed".

## 5. Sharia compliance model

Each holding (and each universe name) gets a **compliance card**:

| Field | Source today | Later (R3) |
|---|---|---|
| Status: `Compliant` · `Under review` · `Non-compliant — exit queued` · `Excluded` | `pass`, `review_flags`, `controls.excluded_symbols`, forced exits in the orders ledger | vendor status with a date |
| Business activity: sector and industry, matched keywords, `business_pass` | `universe_screened.json` | vendor revenue breakdown |
| Debt / market cap vs 30%, with **headroom** in percentage points | `debt_ratio` | vendor, quarterly |
| Cash / market cap vs 30%, with headroom | `cash_ratio` | vendor |
| Impermissible income vs 5% | *not available* (shown as "proxy: business screen only") | vendor |
| Instrument: common share | `instrument_reasons` | — |
| Overrides and review flag, with the owner's ruling (D1) and its date | `sharia_overrides.json` | ruling log in the ledger |
| Screened on / next re-screen | file and correction dates; re-screen schedule (1 Jan/Apr/Jul/Oct) | per-name dated status log |
| Purification due | dividends received × impermissible-income %. Until that % exists, show the dividend amount with "rate pending" | per-dividend entry |
| Data quality | `yfinance` proxy, **unlicensed** badge | licensed badge |

**Sharia grade** (shown with the status, never instead of it):

* **A:** passes every layer, both ratios have ≥ 10 pp headroom, no review
  flag, data under 100 days old.
* **B:** passes, but headroom is under 10 pp, or the data is 100–200 days
  old.
* **C:** passes, but is review-flagged, has under 3 pp headroom, or the data
  is stale.
* **F:** fails a layer or is excluded. A held F name must show a forced exit
  in the pending orders; if none is queued, raise a P1 ("non-compliant
  holding with no exit queued").

Portfolio-level items:

* percentage of the book by grade
* a **watchlist** of names within 3 pp of a threshold
* a re-screen diff viewer (`compliance/<d>.json`)
* a purification ledger and a yearly zakat estimate (Phase 5; shown as
  "planned" until then)

## 6. Confidence ratings

The strategy file stays frozen. A new wrapper module,
`live/insights.py`, runs after the twin in Cycle A. It reads the same
enriched data and calls the strategy's **pure** scoring helpers read-only
(no strategy-file edit, so the freeze hash is unchanged). It writes
`ledger/insights/<asof>.json`. The console only displays this file. For
history before the module existed, the console backfills by re-running the
wrapper locally.

Per holding, four sub-scores from 0 to 100 and one overall rating:

| Sub-score | Measures | Inputs |
|---|---|---|
| **Signal** | How strongly the agent still wants the name | universe rank percentile of `_score()`, rank vs the exit threshold (30), SMA 50/100/200 stack, distance to the 52-week high |
| **Risk room** | Distance to the nearest exit trigger | distance to the initial, trailing and hard stop in ATRs; distance to SMA200; sessions left before the 35-session time stop |
| **Regime** | Market backdrop the agent uses for sizing | IXIC vs SMA200/SMA50, breadth, the agent's `sentiment` (−1..1) and `mood` |
| **Data** | Trust in the night's inputs for this name | data-gate status, cross-source check for this name (agree / unavailable / disagree), open revision, fetch age |

**Overall = Signal 40% · Risk room 30% · Regime 20% · Data 10%.** Bands:
**High ≥ 70 · Medium 40–69 · Low < 40.**

Rules:

* A rating is labelled **"model conviction, not a forecast."** It is
  backtested only for calibration: docs/09 shows the hit-rate per band from
  the out-of-sample (OOS) record when it is available.
* Every number links to its inputs (the "why" drawer).
* The free-text `reason` from the orders ledger is shown next to it.
* The rating never feeds back into trading.

The same file carries `nearest_exit` (the trigger and price level), which is
the most useful single fact for an override decision.

## 7. Executive controls

### 7.1 Control set

| Action | Effect | When it takes effect | Mechanism | Fidelity impact |
|---|---|---|---|---|
| **Pause entries** / resume | Blocks buys; exits still flow | The next Cycle A. If tonight's orders are already ledgered, the submit step re-checks `controls.json`. | `controls.pause_entries` | Declared deviation |
| **STOP TRADING (kill)** | No orders are ledgered or sent. Open `opg` orders are **canceled now**. | Immediately for open orders; all later cycles are frozen | `controls.kill=true` + gateway `cancel_all` (`DELETE /v2/orders`) + `live-control.yml` in the GitHub phase | Trading halts; the twin keeps running for comparison |
| **Stop & flatten** | Kill, plus sell every position | At the next open (`opg` market sells; also `cls` if before 15:50 ET) | Kill + gateway `flatten` (new) | Large deviation; needs a second confirmation |
| **Resume trading** | `kill=false` | The next Cycle A | Allowed only after a preflight checklist (§7.3) | — |
| **Exclude / force exit** (per holding) | Sells the whole position at the next open; blocks re-entry | Tonight's submit if before 19:15 ET, otherwise the next | `controls.excluded_symbols` (existing semantics) | `explained` in drift |
| **Lock holding** (new) | The agent may neither sell nor add; the position is frozen | Next submit | `controls.locked_symbols` (new); `plan_submissions` skips orders for locked names with reason `locked` | Declared deviation, shown in drift |
| **Trim / manual sell** (new) | Sell N shares or X% at the next open | Next submit | `controls.manual_orders[]` (new): `{id, symbol, side:"sell", qty or fraction, reason, created_by, expires}` | Explained deviation |
| **Manual buy** (new, off by default) | Buy a whitelisted, compliant name | Next submit | Same queue, `side:"buy"`, passes every guardrail. Enabled only by the `allow_manual_buys` setting | Explained deviation |
| **Gross cap** | Caps gross exposure | Next Cycle A | `controls.gross_cap` | — |
| **Release held night** | Approves tonight's soft-held submission | Now (runs the submit with `--approved`) | `workflow_dispatch` of `live-submit` (GitHub) / `run-step cycle_submit --approved` (box) | — |
| **Clear halt** | Ends a reconciliation halt | Next submit | Writes the cause into `halt.json` and sets `halted:false` | Requires a reason |
| **Pause adapt()** (X2) | Freezes the agent's parameters | Next Cycle A | `controls.pause_adapt` (new). It changes the twin path, so the UI warns that it ends comparability with the frozen record. | Large; second confirmation |
| **Re-run a cycle** | Re-runs A, S or B for a date | Now | `workflow_dispatch` / `run-step` | — |

`kill`, the drawdown kill and halts **cannot** be released by a manual
submit run. This rule already exists in `cycle_submit.py` and the UI keeps
it.

### 7.2 Harness changes needed (small, tested)

1. `controls.json` schema v2: add `version`, `locked_symbols`,
   `manual_orders`, `pause_adapt` and `allow_manual_buys`. Old keys are
   unchanged, and missing keys mean "off", so the harness stays
   backward-compatible.
2. `execution.plan_submissions`: skip locked names, and add unexpired manual
   orders, each tagged with its id. Sells are capped at the account
   holding; manual buys pass the guardrails.
3. `cycle_submit.py` re-reads `controls.json` at submit time, not only Cycle
   A's snapshot, so a 17:30 ET pause still stops tonight's buys.
4. `broker.flatten()`: a market-on-open sell of every position. A kill
   triggers `cancel_all()`.
5. A new `live-control.yml` workflow (`workflow_dispatch`, inputs `action`
   and `reason`) runs `cancel_all` / `flatten` with the paper keys and writes
   `ledger/commands/<ts>.json`.
6. `live/insights.py` (§6) and a per-name `screened_on` field written by the
   re-screen.
7. Tests in `NASDAQ/tests/` for each item, and an update to docs/06.

### 7.3 Safety design of a control action

Every action goes through the same pipeline:

```
UI form ─► preview ─► step-up auth ─► server validate ─► write + commit ─► push ─► (immediate cmd) ─► confirm
```

* **Preview (impact):** shows what changes, which orders tonight are added,
  blocked or canceled, the estimated proceeds or cost at the last close, the
  drift impact, the effective time ("applies at 19:15 ET submit, tonight"),
  and fidelity warnings.
* **Mandatory reason**, at least 10 characters, plus an optional category
  (compliance, risk, operational, test).
* **Step-up authentication:** a TOTP code is required again if the last one
  is older than 5 minutes. Destructive actions (kill, flatten, manual buy,
  pause adapt) also require typing the symbol or the word `STOP` / `FLATTEN`.
* **Validation server-side** against the schema and current state, for
  example: you can't lock a name that isn't held; you can't resume while
  `halt.json` is halted; a manual sell can't exceed the holding.
* **Optimistic concurrency:**
  * The write is based on the control file's current blob SHA. If Cycle A or
    the re-screen committed in between, the server rebases the single
    change and re-validates; it never overwrites.
  * Writes go through the GitHub contents API `PUT` with a `sha`, or a local
    `git pull --rebase` on the box.
* **Audit commit message** (machine-parseable):

  ```
  control: pause_entries=true
  Actor: owner@console
  Reason: FOMC tomorrow; no new risk
  Effective: next-submit 2026-11-04T19:15-05:00
  Console-Action-Id: 01J…
  ```

  The commit SHA is shown in the UI's audit log. For gateway commands
  (cancel, flatten), the gateway also writes `ledger/commands/<ts>.json`
  with the broker's response.
* **Confirmation:** the UI waits for the push and, for immediate commands,
  the broker's acknowledgement. If either fails, it shows the action as
  **not applied**, never as optimistic success.
* **Resume preflight checklist** (all must pass, shown as a list):
  * no `halt.json` halt
  * the last reconciliation is OK
  * the last Cycle A is ok or the reason is understood (a tick box with a
    note)
  * no open P1
  * the drawdown is above the kill line
  * broker reachable
  * the operator acknowledges the deviations that will apply

## 8. Value-adding features

| Feature | Why |
|---|---|
| **Health & freshness panel** with "last good Cycle A N sessions ago" in red | Today's real failure (Cycle A `data_gate_tripped` 28 Sep → 1 Oct, 0.6% coverage, cockpit frozen at 25 Sep) went unnoticed because nothing shows staleness |
| **Phase & gate tracker** (ghost streak 1/10, paper gate, evaluation bands, D1–D8 decisions with due dates, task list G/P/E/U/R/S/X) | The go-live route in docs/07 becomes a live checklist |
| **Tonight timeline** | A strip with A 17:05 → S 19:15 → open 09:30 → B 09:50, each step marked done, late or failed, and a countdown to the next step |
| **Twin vs account drift & tracking error** | Pre-registered band < 0.5%/month (docs/05 §8) |
| **Execution quality** | Slippage per fill vs the 10 bps band, missed fills, implementation shortfall |
| **Anomaly panel** | Exposure, turnover and position count vs `baseline.json` p5–p95 |
| **Agent internals** | Parameters vs bounds, the adaptation trail with diffs, the next adapt date, mood and sentiment journal |
| **Alerts inbox** | P1/P2 with acknowledge-and-resolve notes; push to the phone through ntfy (`ALERT_WEBHOOK_URL`) |
| **Event calendar** | Sessions, half days, re-screens, adapt dates, owner decisions; ex-dividend dates of holdings (from Alpaca corporate actions) |
| **Monthly review pack** (task E1) | One-click PDF/HTML of the month: performance, drift, slippage, P1s, compliance changes, overrides with reasons |
| **Exports** | CSV of orders, fills, round trips, cash events, audit log |
| **What-if on overrides** | Before a forced exit, show the realized P&L and the estimated purification it will lock in |
| **Second agent ready** | Every view is keyed by `agent`, so `factor2` (D8) slots in as a second account |

## 9. Security

* **Network:** bind to the LAN interface and `tailscale0` only; no router
  port-forward, consistent with docs/07 §5. Optionally serve TLS through
  Tailscale certs or a LAN reverse proxy (Nginx Proxy Manager / Caddy) with
  local TLS.
* **Authentication:**
  * One **owner** account (argon2id password + TOTP); optional **viewer**
    accounts (read-only).
  * Sessions are httpOnly, SameSite=Strict, with a 12 h idle timeout.
  * CSRF token on every POST.
  * Rate-limited login, with lockout after 5 failures.
* **Secrets:**
  * `/secrets/console.env`, mounted read-only.
  * The GitHub PAT is fine-grained to this one repository: `contents:write`,
    `actions:write`, `issues:read`.
  * Paper keys only in Phases 2–3. **Never live keys:** live keys stay in
    `nafa-live`, behind the gateway.
* **Gateway surface:** reads plus `cancel_all`, `flatten`, `health`. It has
  no arbitrary-order endpoint; manual orders go through the ledgered
  `controls.json` path only.
* **Audit:** everything is in git. The console's own log of logins and
  failed step-ups is kept in SQLite and copied nightly to
  `ledger/console-audit/<month>.jsonl` (no secrets, no IPs beyond the
  LAN/Tailscale label).

## 10. API surface (v1)

```
GET  /api/overview                      KPIs, phase, health, tonight timeline
GET  /api/holdings?book=model|account   positions + P&L + confidence + sharia grade
GET  /api/holdings/{sym}                detail: lots, trades, chart series, compliance card, confidence why
GET  /api/orders/pending                non-terminal lifecycle rows for the next open
GET  /api/orders?from&to&sym&side&status  history with lifecycle + P&L attribution
GET  /api/round-trips?…                 closed trades
GET  /api/performance?period&book       equity curves, drawdown, metrics, monthly table
GET  /api/compliance                    portfolio grade mix, watchlist, rescreen diffs, purification
GET  /api/agent                         params, bounds, adaptations, journal
GET  /api/health                        cycles, gate, data gate detail, broker, heartbeats, indexer lag
GET  /api/alerts   POST /api/alerts/{id}/ack
GET  /api/controls                      current controls + effective-at + pending changes
POST /api/controls/preview              body: action → impact preview (no side effects)
POST /api/controls/apply                body: action + reason + preview_hash + totp → audit commit
GET  /api/audit                         control history (git) + console events
GET  /api/events  (SSE)                 indexer.updated, alert.new, control.applied, broker.order_update
```

`preview_hash` binds `apply` to the preview the operator saw. If the state
changed in between, the server returns `409` with a fresh preview.

## 11. Freshness and failure behaviour

* Every panel shows its data age. More than 1 trading session behind
  expectations turns it amber; more than 2 turns it red.
* The indexer failing or the ledger remote being unreachable gives a global
  banner. The UI still serves the last read model, read-only.
* With the broker gateway unreachable, the account panels show the last
  snapshot timestamp, and immediate commands are disabled with an
  explanation. Control-file actions still work: they are applied by the next
  cycle.
* The console being down has **no effect on trading**. The harness never
  depends on it.

## 12. Build plan

| Milestone | Scope | Target |
|---|---|---|
| **M0 Read-only (ghost)** | Indexer over the public ledger, overview, holdings (model), orders and history, P&L from the twin, compliance cards (today's data), health and freshness, phase tracker. Unraid template. | before the ghost gate decision, mid-Oct 2026 |
| **M1 Controls** | Control service plus the harness changes in §7.2 (with tests), auth with TOTP, preview/apply/audit, resume checklist | before paper start, **Fri 30 Oct 2026** |
| **M2 Account** | Broker gateway (paper), account book, FIFO lots, fills, slippage, drift, `live-control.yml`, alerts inbox and ntfy | first paper week, 2–6 Nov 2026 (supports approval mode, task P5) |
| **M3 Insights** | `insights.py` confidence, Sharia grades, purification placeholders, monthly review pack | Dec 2026 |
| **M4 Private box** | Gateway moves into `nafa-live`; ledger repository bind mount; burn-in views (private vs public twin, U6) | Jan 2027 (with U2–U7) |
| **M5 Real money** | Live-mode hardening: notional caps shown, pilot capital (D4), purification and zakat from licensed data (R3), withholding | Apr 2027 |

**Status, 3 Oct 2026:** M0–M3 are built and tested (`console/`, the harness
changes in §7.2, `live/insights.py`, `live/calibration.py`). Still to do on
the box: test-build the image, create the owner user, set
`CONSOLE_WRITE=git`, and configure the gateway and ntfy before paper start.

## 13. Open questions for the owner

1. Viewer accounts: anyone besides you (for example a Sharia reviewer with
   read-only access to the compliance pages)?
2. Should **manual buys** exist at all (`allow_manual_buys`), or should
   overrides be exits, locks and trims only? The recommendation is
   **exits and locks only** until the verdict, to protect the evaluation.
3. Should **stop & flatten** also be allowed intraday (market orders during
   the session), or only at the open/close auctions? The recommendation is
   auctions only for paper; review this for real money.
4. Remote access: Tailscale (recommended) or WireGuard on the Unraid host?
