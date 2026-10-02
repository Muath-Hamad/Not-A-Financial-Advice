# 06 — Live operations runbook (the system as built)

Doc 05 is the plan; this is the machine that implements it; doc 07 is the
dated route to paper and real money. Everything lives in `NASDAQ/live/` plus
five live workflows on `main`. The system starts in **ghost mode**
(docs/05 Phase 1): cycles run live daily, orders are ledgered and the submit
step rehearses them against the twin's book but sends nothing, and the exit
gate is 10 consecutive sessions of provable determinism.

## The one idea everything hangs on: replay-as-state

There is no serialized agent state anywhere. Every Cycle A replays the frozen
`trend` file through the engine **from `LIVE_START` to today** on
that evening's data snapshot (`live/twin.py`). `LIVE_START` is the
repository variable of that name (default 2026-09-28 in `live/config.py`) and
is reset at each phase switch so the twin and the account start in cash on
the same session (docs/07). Because agent, engine and
feedback loop are deterministic, the replay reproduces exactly the internal
state an incremental process would carry — portfolio, adapted parameters,
cooldowns, pending orders — and is itself the documented
rebuild-from-corruption procedure. The engine runs with `SIM_DECIDE_LAST=1`
(a default-off flag added for this system; regression-proven byte-identical
to the committed OOS results when unset), so the final session's `decide()`
runs and today's orders are read off the agent's pending book.

Cycle A runs the twin **twice, in two processes, and compares output bytes**.
That comparison is the ghost gate: match → streak +1; mismatch → P1, streak
reset, no orders. `live/ledger/gate.json` tracks the streak (target 10).

## Components

| Piece | File | Role |
|---|---|---|
| Config | `live/config.py` | every threshold and path; changing it is change management |
| Calendar | `live/calendar_util.py` | NASDAQ sessions, half-days, "latest completed session" |
| Twin | `live/twin.py` | deterministic replay; emits state + today's orders + input hashes |
| Data gate | `live/data_gate.py` | coverage + benchmark checks + cross-check vs NASDAQ's own chart API (>0.5% close disagreement trips; Stooq was dropped — it challenges runner IPs) |
| Guardrails | `live/guardrails.py` | whitelist and exclusions (buys only: a sale is never blocked), long-only, 18% name cap, 75% daily turnover, 5% ADV |
| Broker | `live/broker.py` | `GhostBroker` now; `AlpacaPaperBroker` (MOO/OPG, REST, order lookup by client order id) dormant until keys |
| Cycle A | `live/cycle_a.py` | post-close: fetch → gate → twin×2 → rails → forced exits → ledger → cockpit; never sends orders |
| Submit | `live/cycle_submit.py` | 19:15 ET: sends the ledgered orders inside Alpaca's on-open window (19:00–09:28 ET); ghost mode rehearses against the twin's book |
| Execution rules | `live/execution.py` | pure functions: what the submit step sends, expected positions, reconciliation diffs, twin-vs-account drift |
| Cycle B | `live/cycle_b.py` | post-open: opening prints, ledger-vs-twin consistency; paper: fills traced by client order id, slippage, share-for-share reconciliation, halt on a break |
| Dead-man | `live/deadman.py` | separate workflow; P1 if no Cycle A record by 18:00 ET, or (paper) no submit record by 21:00 ET |
| Tests | `tests/` | 53 unit and end-to-end tests of the rules above (`nasdaq-tests.yml`) |
| Re-screen | `live/rescreen_report.py` | quarterly AAOIFI drift → dated report + harness exclusions |
| Alerts | `live/alert.py` | P1 → GitHub issue (label `live-p1`, deduped) + optional webhook; P2 → run summary |
| Cockpit | `live/cockpit/` | the live dashboard, rebuilt and committed after every Cycle A |
| Baselines | `live/baseline.json` | anomaly-panel distributions from the OOS record (`make_baseline.py`) |
| Controls | `live/controls.json` | kill / pause_entries / exclusions / gross cap — human-edited, commit = audit event |

## The daily rhythm (all ET; workflows cron in UTC with DST-safe double slots)

* **~17:00 — Cycle A** (`live-cycle-a.yml`): full re-fetch of the AAOIFI
  universe 2015→today into `data/raw_live/` (regenerated daily, gitignored),
  indicators truncated to the last completed session, data gate, twin ×2,
  guardrails, forced exits for held names on the exclusion list, order
  ledger with deterministic client-order-ids, cockpit rebuild, ledger
  commit. In paper mode it also reads the account and reports how far its
  book has drifted from the twin's. The full-history re-fetch
  is deliberate: Yahoo restates adjusted series on every dividend, so each
  day's replay must be internally consistent rather than appended.
* **~19:15 — submit** (`live-submit.yml`, retry slots every 30 minutes
  through the evening): sends what Cycle A ledgered as market-on-open
  orders. Sells are sized from the account's own holdings, excluded holdings
  are force-exited, buys are trimmed to the cash the night's sells free.
  Hard holds (kill switch, drawdown kill, reconciliation halt, blocked
  account, an account that is not the twin's book) stop the night with a P1;
  soft holds (approval mode, a portfolio-level guardrail) wait for a manual
  run. Record: `cycles/<date>-S.json`.
* **~09:50 — Cycle B** (`live-cycle-b.yml`): record the actual opening prints
  for every ordered symbol; verify the order ledger matches the twin's pending
  book. The evening's Cycle A compares those 09:50 prints against the opens
  its replay filled at — the **open-revision metric** (tolerance 0.2%, P2
  above it). In paper mode this cycle also looks up every submitted order
  by its client order id, measures realized slippage against the official
  open (P2 above 10 bps average), and reconciles the account share for
  share: positions before submission plus fills must equal positions now.
  A break writes `ledger/halt.json` and files a P1.
* **~18:15 — dead-man** (`live-deadman.yml`): no Cycle A record on a session
  day ⇒ P1 issue. **~21:30** (paper): orders ledgered but no submit record ⇒
  P1.
* **Quarterly** (`live-rescreen.yml`, 1st of Jan/Apr/Jul/Oct): fresh
  discovery + AAOIFI screen into `data/rescreen/<date>-*.json`, drift report
  to `live/ledger/compliance/`, newly non-compliant names appended to
  `controls.json` exclusions. `adapt()` needs no scheduler — it is inside the
  replay, firing on the 63-session boundaries automatically.

Every cycle is idempotent: re-running a recorded session exits immediately,
client-order-ids are content-hashes (a re-sent order is recognised by the
broker and re-read, never duplicated), and failed cycles still commit a
status record (`fetch_failed`, `data_gate_tripped`, `nondeterministic`,
`killed`, `held`, `broker_unreachable`, …) so the audit log has no silent
gaps.

## The ledger (`live/ledger/`)

```
cycles/YYYY-MM-DD-A.json   the full decision-cycle record: gate results, twin
                           summary + input hashes, determinism, guardrails,
                           drawdown, open-revision, duration
cycles/YYYY-MM-DD-S.json   the submit step: account before, the plan (sent,
                           skipped, trimmed), broker order ids, holds
cycles/YYYY-MM-DD-B.json   opening prints, consistency checks, (paper) fills,
                           slippage, share-for-share reconciliation
orders/YYYY-MM-DD.json     the orders for the next open, with client-order-ids,
                           reference closes, whole-share previews, the
                           guardrail rules that block them, forced exits
halt.json                  present after a reconciliation break; the submit
                           step sends nothing while "halted" is true
twin/twin_latest.json      complete twin state (positions, params, trades,
                           adaptations, journal)
twin/equity.csv            date,equity,cash,bench — the live curve
gate.json                  ghost-gate streak + 30-day history
compliance/YYYY-MM-DD.json quarterly re-screen reports
smoke/…                    same layout, written by push-triggered smoke runs
```

## Operating procedures

* **Kill switch:** set `"kill": true` in `live/controls.json`, commit, push.
  Next cycle records `killed`, alerts P1, issues nothing; the submit step
  holds every order. Auto-trigger: the cycle alerts P1 when drawdown ≤ −25%
  and the submit step holds while it lasts.
* **Exclude a symbol / pause entries / cap gross:** edit `controls.json`
  (harness-level; the twin is never edited). An excluded name cannot be
  bought, and if it is held it is sold in full at the next open (a forced
  exit). Sales are never blocked.
* **Release a held night:** approval mode (`APPROVAL_MODE=true`) and
  portfolio-level guardrails hold the night. Read `orders/<date>.json` and
  `cycles/<date>-S.json`, then run the `live-submit` workflow manually
  (Actions → Live submit → Run workflow) before 09:28 ET. A manual run
  cannot release a kill, a drawdown kill or a reconciliation halt.
* **Clear a reconciliation halt:** find the cause (a split, a manual trade in
  the account, a partial fill the ledger missed), write it into
  `live/ledger/halt.json`, set `"halted": false`, commit. The next submit
  slot trades again.
* **Retry a failed cycle:** run the workflow manually (Actions → Run
  workflow) any time after 16:45 ET for Cycle A, 19:00–09:28 ET for the
  submit step — `latest_completed_session()` still resolves the right day
  and idempotence makes double-runs harmless.
* **Change the universe:** only at a phase switch (docs/07 §3): edit
  `data/sharia_overrides.json`, run `pipeline/apply_screen_rules.py`, run the
  2023–26 regression, record it under `out/`.
* **Rebuild after corruption:** delete nothing; the next Cycle A replays from
  scratch by construction.
* **Change anything in `sim/` or the agent:** new regression first
  (docs/05 §7.4) — the `SIM_DECIDE_LAST` flag shipped with exactly that proof.

## Phase 2 switch (after the ghost gate passes; dated in docs/07 §7)

1. Create an Alpaca **paper** account; add `APCA_API_KEY_ID` /
   `APCA_API_SECRET_KEY` as repository secrets (paper keys only — real-money
   keys never enter this repository).
2. Optionally add `ALERT_WEBHOOK_URL` (Slack/Discord/Telegram-style JSON
   `{"text": …}` receiver) for pushed P1/P2s beyond GitHub issues.
3. Reset the paper account to $100,000 cash and no positions.
4. Before the first paper session, set the repository variables
   `LIVE_START=<first paper session>`, `LIVE_MODE=paper` and
   `APPROVAL_MODE=true`. The reset start makes the twin and the account both
   start in cash; the submit step refuses to trade if their books differ by
   more than 20% of equity.
5. Approval week: each evening review the held batch and release it with a
   manual `live-submit` run. Remove `APPROVAL_MODE` after five clean nights.
   Gate to steady state: two clean weeks (docs/05 §10).

## Declared fidelity gaps (measured, not hidden)

1. **Share-count estimation.** The engine sizes buys at the next open; a real
   OPG order must fix its quantity the evening before, so the harness
   estimates from the last close (`share_preview`). Observed in testing:
   85 estimated vs 84 filled on a gap day. Cycle B's reconciliation measures
   this drift; the twin remains the pure model.
2. **Frozen universe.** The twin's universe is the deployment screen, frozen
   for the whole evaluation (replay determinism requires it). Compliance
   drift acts through harness exclusions and forced exits; newly eligible
   names wait for a declared redeploy. IPO entry — which the backtests had —
   is therefore paused during the trial.
3. **Twin costs are venue actuals** (0 bps commission on Alpaca paper, 5 bps
   modeled slippage) — not the 2 bps backtest commission. The OOS record is
   the yardstick, not the twin's exact cost basis; Cycle B's slippage
   measurement is what eventually corrects the 5 bps assumption.
4. **Cash, not margin.** Buys are trimmed to the cash the account will have
   after the night's sells (minus a 0.2% buffer); the twin never trims. A
   trimmed buy is a P2 and shows up as drift. A real cash account is
   stricter still (docs/07, task R4).
5. **Forced exits.** When a held name is excluded, the account sells it and
   the twin (frozen universe) keeps it. The drift report labels those names
   `explained`; they never count as breaches.

## What "green" looks like

Ten straight sessions in `gate.json` with `match: true`, a submit record
every night whose rehearsal sends exactly the ledgered orders, zero open
`live-p1` issues, cockpit rebuilt nightly, open-revision worst < 0.2%, and
the anomaly panel's markers inside their bands. Then Phase 2 is a
configuration change — and the pre-registered evaluation (docs/05 §8)
starts counting. In paper mode add: every Cycle B reconciles `ok`, and
average slippage stays within 10 bps per side.
