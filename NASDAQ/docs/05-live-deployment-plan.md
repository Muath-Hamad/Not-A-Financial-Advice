# 05 — Live deployment plan: `trend` on a virtual NASDAQ account

The next step is not another simulation. This is the operating plan for running
the elected agent against a **live paper-trading account** — real market hours,
real quotes, real fills from a broker's paper venue — with the monitoring and
management tooling to run it safely and to judge it honestly. Plan only; no
code yet.

---

## 1. Governing principle: decision fidelity

Everything in the backtest was built around one contract: *decide on the
completed close of day t, fill at the open of day t+1*. The live system must
replicate that contract **exactly** — same indicators, same universe, same
order semantics — because the moment the live loop diverges from the sim loop,
live results stop being comparable to the 10 years of evidence behind the
election. Every design choice below serves that principle.

A corollary: the agent needs **no intraday daemon**. `trend` is a
daily-cadence strategy (~4 fills/week). The live system is two short scheduled
jobs per day, not a stream processor. This keeps the infrastructure on the
stack we have already proven (GitHub Actions + the repo as audit log).

## 2. Venue

**Primary: Alpaca paper trading.**
- API-first, free, no running terminal required (unlike IBKR's gateway).
- Supports **market-on-open orders** (`time_in_force: OPG`) — the exact
  mechanical twin of the engine's "fill at next open".
- Own market-data API — using the *same vendor* for data and execution
  removes a whole class of price-mismatch bugs.
- Paper account is resettable; fills include realistic queue/price simulation.

The execution layer is specified as a thin **broker abstraction** (submit,
cancel, positions, fills, account state) so IBKR paper or another venue can be
swapped in without touching the agent. The agent itself is never modified: it
is the frozen `trend` file, driven by an adapter that feeds it the same
`view/portfolio/ctx` it saw in simulation.

## 3. The daily cycle

**Cycle A — decision (post-close, ~17:00 ET, weekdays):**
1. Fetch the day's completed bars for the AAOIFI universe + `^IXIC`
   (primary: broker data API; cross-check: independent second source).
2. **Data gate:** if any cross-source close disagrees > 0.5%, or coverage is
   incomplete, or the exchange calendar says today was a half-day and bars
   look wrong → *no trading tomorrow*, alert, hold state.
3. Append bars, recompute indicators (existing pipeline).
4. Load persisted agent state (portfolio, adapted parameters, cooldowns,
   pending orders) and run `decide()` on today's close.
5. Translate orders to **MOO orders for tomorrow's open**, with deterministic
   client-order-IDs (date + symbol hash) so a re-run can never double-submit.
6. Commit the full cycle record to the repo: inputs hash, decisions, orders,
   state snapshot, and the agent's journal note. The repo remains the audit
   log, as it was for the whole experiment.

**Cycle B — reconciliation (post-open, ~09:50 ET):**
1. Pull actual fills; match against submitted orders.
2. Update agent state from *actual* fills (not assumed ones).
3. Measure realized slippage vs the modeled 5 bps and log it — this is the
   number that validates or corrects the cost model.
4. Reconcile broker positions vs the agent's book share-for-share. Any
   unexplained difference is a **P1 incident** (see §6): trading halts until a
   human clears it.

**Quarterly cycles**, mirroring the sim:
- `adapt()` fires every 63 live sessions on the same feedback packet format;
  every adaptation is committed to the audit log exactly as in the backtest.
- The **AAOIFI re-screen** re-runs (existing pipeline). Names that fall out of
  compliance: blocked from new buys immediately, existing position exited in
  an orderly window (≤ 5 sessions) — a declared policy, not a judgment call.
- Universe membership refresh (new listings enter once their indicators warm
  up, exactly as IPOs did in the sim).

**Calendar-awareness:** NYSE/NASDAQ holiday and half-day calendar drives the
scheduler; half-days shift Cycle A after the 13:00 ET close. If Cycle A fails
and cannot complete before the next open, the day is **skipped** (no stale
orders), never guessed.

## 4. The shadow twin — the most important monitor

From day one, the identical frozen agent also runs in the **existing
simulator** on the same daily bars. Every day we get two equity marks:

- **Paper account equity** (real venue, real fills), and
- **Sim-twin equity** (our engine's model of the same decisions).

Their divergence — *tracking error* — is the single most diagnostic signal in
the whole system:
- Twin ≈ paper → the engine's assumptions (costs, fills) were honest, and 10
  years of backtest evidence remains predictive.
- Twin ≠ paper → either an implementation drift (bug) or an execution-reality
  gap (slippage, partial fills). Both demand attention before performance is
  even discussed.

Alert threshold: cumulative tracking error > 0.5% in a month → investigate;
decisions differing *at all* between twin and live (same inputs) → P1, because
determinism is broken.

## 5. Monitoring & dashboard

Extend the existing self-contained dashboard into a **live cockpit**,
republished automatically after every cycle (same artifact-publishing flow;
optionally GitHub Pages later):

- **Performance:** live equity vs sim twin vs IXIC; drawdown from peak vs the
  −16.2% OOS precedent; rolling Sharpe vs the OOS 1.22 baseline.
- **Book:** positions, weights, sector exposure, gross vs the regime dial's
  current target, cash.
- **Execution quality:** per-fill expected-vs-actual slippage, cumulative cost
  drag vs model.
- **Agent internals:** current adapted parameter values vs their
  `param_space` bounds (with the full adaptation trail), regime/dd-governor
  state, cooldowns in force.
- **Compliance:** AAOIFI status per holding, date of last re-screen, any names
  in forced-exit windows.
- **System health:** timestamps of last successful Cycle A/B, data-gate
  status, broker API status, next scheduled adapt window.
- **Anomaly panel:** today's turnover / position count / exposure vs their
  historical backtest distributions — anything outside the 5th–95th percentile
  band gets flagged automatically.

## 6. Alerting — tiered, with a dead-man's switch

- **P1 — immediate push/message** (act now): cycle failure before open; data
  gate tripped; order rejected; reconciliation break; decision nondeterminism;
  drawdown crossing declared limits; broker API auth failures; kill-switch
  activation.
- **P2 — daily digest:** cycle summary, fills and slippage, equity/tracking
  numbers, upcoming events (adapt window, re-screen date, holidays).
- **P3 — weekly/monthly report:** auto-generated performance letter with the
  same metrics vocabulary as the election, archived in the repo.
- **Dead-man's switch:** an external heartbeat monitor that alerts if Cycle A
  has *not* pinged by 18:00 ET — catching the classic silent failure where the
  scheduler itself dies and nothing seems wrong.

Channels: email + a messaging webhook (Telegram/Discord/Slack — your pick) for
P1/P2; the dashboard carries everything at all times.

## 7. Management controls (the human side)

All controls are **outside the agent** — defense in depth; the frozen agent is
never edited live:

1. **Kill switch:** one command → cancel all open orders, optionally flatten
   to cash, freeze cycles. Manual trigger, plus automatic triggers: account
   drawdown beyond a declared hard limit (proposal: −25%, comfortably beyond
   the −16.2% OOS precedent), repeated data-gate failures, unresolved
   reconciliation break.
2. **Harness guardrails**, enforced before any order reaches the broker:
   whitelist = current AAOIFI universe only; max position weight; max daily
   turnover; long-only / no margin verified at the account level; order-size
   sanity cap (no order > X% of the name's average daily dollar volume).
3. **Manual overrides, all logged as first-class audit events** (same
   discipline as adaptations): exclude a symbol; force gross to a ceiling;
   pause/resume `adapt()`; pause new entries while allowing exits.
4. **Change management:** the live code is pinned to a release tag descending
   from freeze `7e8cdf1`. Any change — even a bugfix — means: new tag, full
   regression re-run over both historical windows proving decisions are
   unchanged (or the change is documented as behavioral), then redeploy.
   Parameters move only through the audited `adapt()` loop.

## 8. Evaluation protocol — pre-registered, before the first order

Declared now so success cannot be redefined afterwards:

- **Duration:** minimum two quarters (≥ 2 live adapt cycles); target four.
- **Primary questions:** (1) does the live paper account track the sim twin
  (validates the whole methodology)? (2) does the agent's live risk-adjusted
  performance stay within the band its OOS record predicts?
- **Success bands** (from the OOS record): tracking error to twin < 0.5%/mo;
  realized slippage ≤ 10 bps/side average; rolling 63-session Sharpe > 0.5
  through the period absent an index bear market; drawdown behavior consistent
  with the governor's design; zero unresolved P1s.
- **Failure protocol:** miss the bands → back to the lab, publicly logged.
  No silent parameter surgery on a live agent.

**Recommended addition:** run **`factor2` as a second paper account** on the
same infrastructure (marginal cost ≈ one more state file and dashboard
column). The trend-vs-guarded-factor question then gets settled on data
neither has ever seen — a live election, which is the cleanest one we can run.

## 9. Ops, security, integrity

- Paper-trading API keys only, stored as GitHub Actions secrets, least
  privilege, rotated; **real-money keys never enter this repository**.
- Idempotent cycles (deterministic client-order-IDs; re-runs are safe).
- All timestamps in exchange time (ET) internally.
- State snapshots committed daily; a documented rebuild-from-fills procedure
  covers state corruption.
- The repo remains the single source of truth: every input, decision, fill,
  adaptation, override, and incident is a commit. Anyone can replay any day.

## 10. Phased rollout

| Phase | Duration | Gate to advance |
|---|---|---|
| **0 — Setup** | ~week | Broker account + keys; calendar; broker abstraction spec; state-persistence format; alert channels wired |
| **1 — Ghost mode** | 2 weeks | Cycles run live but orders are **logged, not submitted**. Gate: ghost decisions match the sim twin byte-for-byte on identical bars, 10 consecutive sessions |
| **2 — Paper live** | from day 1 of month | Orders flow to the paper account; full monitoring, reconciliation, alerts. Gate: 2 clean weeks (no P1s, slippage within band) |
| **3 — Steady state** | ≥ 2 quarters | Quarterly adapt + re-screen; monthly reports; the pre-registered evaluation runs its course |
| **4 — Review** | after 2–4 quarters | Formal verdict against the pre-registered bands; decide: extend, promote a challenger (factor2), or return to the lab |

Real-money trading is explicitly **out of scope** for this plan; it would
carry regulatory, brokerage and sizing questions this document does not
address.

---

*This plan operationalizes the same three disciplines that made the
experiments trustworthy: decision fidelity (live = sim, provably), audit
trails (everything is a logged event), and pre-registration (success defined
before the first order). Not financial advice.*
