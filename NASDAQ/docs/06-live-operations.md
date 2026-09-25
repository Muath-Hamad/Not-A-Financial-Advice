# 06 — Live operations runbook (the system as built)

Doc 05 is the plan; this is the machine that implements it. Everything lives
in `NASDAQ/live/` plus four workflows. The system launched in **ghost mode**
(docs/05 Phase 1): cycles run live daily, orders are ledgered but never
submitted, and the exit gate is 10 consecutive sessions of provable
determinism.

## The one idea everything hangs on: replay-as-state

There is no serialized agent state anywhere. Every Cycle A replays the frozen
`trend` file through the engine **from `LIVE_START` (2026-08-18) to today** on
that evening's data snapshot (`live/twin.py`). Because agent, engine and
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
| Guardrails | `live/guardrails.py` | whitelist, exclusions, long-only, 18% name cap, 75% daily turnover, 5% ADV |
| Broker | `live/broker.py` | `GhostBroker` now; `AlpacaPaperBroker` (MOO/OPG, REST) dormant until keys |
| Cycle A | `live/cycle_a.py` | post-close: fetch → gate → twin×2 → rails → ledger → cockpit |
| Cycle B | `live/cycle_b.py` | post-open: opening prints, ledger-vs-twin consistency, (paper: fills + slippage + positions) |
| Dead-man | `live/deadman.py` | separate workflow; P1 if no Cycle A record by 18:00 ET on a session day |
| Re-screen | `live/rescreen_report.py` | quarterly AAOIFI drift → dated report + harness exclusions |
| Alerts | `live/alert.py` | P1 → GitHub issue (label `live-p1`, deduped) + optional webhook; P2 → run summary |
| Cockpit | `live/cockpit/` | the live dashboard, rebuilt and committed after every Cycle A |
| Baselines | `live/baseline.json` | anomaly-panel distributions from the OOS record (`make_baseline.py`) |
| Controls | `live/controls.json` | kill / pause_entries / exclusions / gross cap — human-edited, commit = audit event |

## The daily rhythm (all ET; workflows cron in UTC with DST-safe double slots)

* **~17:00 — Cycle A** (`live-cycle-a.yml`): full re-fetch of the AAOIFI
  universe 2015→today into `data/raw_live/` (regenerated daily, gitignored),
  indicators truncated to the last completed session, data gate, twin ×2,
  guardrails (report-only in ghost), order ledger with deterministic
  client-order-ids, cockpit rebuild, ledger commit. The full-history re-fetch
  is deliberate: Yahoo restates adjusted series on every dividend, so each
  day's replay must be internally consistent rather than appended.
* **~09:50 — Cycle B** (`live-cycle-b.yml`): record the actual opening prints
  for every ordered symbol; verify the order ledger matches the twin's pending
  book. The evening's Cycle A compares those 09:50 prints against the opens
  its replay filled at — the **open-revision metric** (tolerance 0.2%, P2
  above it). In paper mode this cycle also pulls real fills, measures
  realized slippage vs the 5 bps model, and reconciles positions
  share-for-share (break ⇒ P1, halt).
* **~18:15 — dead-man** (`live-deadman.yml`): no Cycle A record on a session
  day ⇒ P1 issue.
* **Quarterly** (`live-rescreen.yml`, 1st of Jan/Apr/Jul/Oct): fresh
  discovery + AAOIFI screen into `data/rescreen/<date>-*.json`, drift report
  to `live/ledger/compliance/`, newly non-compliant names appended to
  `controls.json` exclusions. `adapt()` needs no scheduler — it is inside the
  replay, firing on the 63-session boundaries automatically.

Every cycle is idempotent: re-running a recorded session exits immediately,
client-order-ids are content-hashes, and failed cycles still commit a status
record (`fetch_failed`, `data_gate_tripped`, `nondeterministic`, `killed`, …)
so the audit log has no silent gaps.

## The ledger (`live/ledger/`)

```
cycles/YYYY-MM-DD-A.json   the full decision-cycle record: gate results, twin
                           summary + input hashes, determinism, guardrails,
                           drawdown, open-revision, duration
cycles/YYYY-MM-DD-B.json   opening prints, consistency checks, (paper) fills
orders/YYYY-MM-DD.json     the orders for the next open, with client-order-ids
                           and whole-share previews
twin/twin_latest.json      complete twin state (positions, params, trades,
                           adaptations, journal)
twin/equity.csv            date,equity,cash,bench — the live curve
gate.json                  ghost-gate streak + 30-day history
compliance/YYYY-MM-DD.json quarterly re-screen reports
smoke/…                    same layout, written by push-triggered smoke runs
```

## Operating procedures

* **Kill switch:** set `"kill": true` in `live/controls.json`, commit, push.
  Next cycle records `killed`, alerts P1, issues nothing. Auto-trigger: the
  cycle alerts P1 when drawdown ≤ −25% (and in paper mode stops submitting).
* **Exclude a symbol / pause entries / cap gross:** edit `controls.json`
  (harness-level; the twin is never edited). Ghost mode reports what the
  controls *would* block; paper mode actually blocks it.
* **Retry a failed cycle:** re-run the workflow (Actions → run → re-run), any
  time after 16:45 ET — `latest_completed_session()` still resolves the right
  day and idempotence makes double-runs harmless.
* **Rebuild after corruption:** delete nothing; the next Cycle A replays from
  scratch by construction.
* **Change anything in `sim/` or the agent:** new regression first
  (docs/05 §7.4) — the `SIM_DECIDE_LAST` flag shipped with exactly that proof.

## Phase 2 switch (after the ghost gate passes)

1. Create an Alpaca **paper** account; add `APCA_API_KEY_ID` /
   `APCA_API_SECRET_KEY` as repository secrets (paper keys only — real-money
   keys never enter this repository).
2. Set the repository variable `LIVE_MODE=paper`.
3. Optionally add `ALERT_WEBHOOK_URL` (Slack/Discord/Telegram-style JSON
   `{"text": …}` receiver) for pushed P1/P2s beyond GitHub issues.
4. From then on Cycle A submits guardrail-filtered MOO (`OPG`) orders with the
   ledgered client-order-ids, and Cycle B reconciles real fills. Gate to
   steady state: two clean weeks (docs/05 §10).

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
4. **Scheduled workflows fire from the repository's default branch.** Until
   these workflow files are merged there, only the push-triggered smoke runs
   execute; the crons stay dark. The workflows check out and commit to the
   live branch either way.

## What "green" looks like

Ten straight sessions in `gate.json` with `match: true`, zero open `live-p1`
issues, cockpit rebuilt nightly, open-revision worst < 0.2%, and the anomaly
panel's markers inside their bands. Then Phase 2 is a two-line configuration
change — and the pre-registered evaluation (docs/05 §8) starts counting.
