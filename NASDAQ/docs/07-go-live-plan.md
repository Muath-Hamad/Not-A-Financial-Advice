# 07 — Go-live plan: ghost → paper → a real account (GitHub + Unraid)

Docs 05 and 06 describe the live system as designed and as built. This
document is the executable route from here to a real-money account, with
dates, gates, owner decisions and a task list. It was written on
**2026-09-25**, after the NASDAQ track merged to `main` (PR #3).

Two deployments, one codebase:

| | **GitHub Actions (public)** | **Unraid home server (private)** |
|---|---|---|
| Role | the research record: ghost gate, paper evaluation, cockpit | the real-money executor |
| Broker | none (ghost) → Alpaca **paper** | Alpaca **live** (cash account) |
| Keys | paper keys as repository secrets | live keys in a local env file; never in any repository |
| Ledger | `NASDAQ/live/ledger/` on `main` (public audit log) | private ledger repository (see D6) |
| Scheduler | workflow crons (UTC, DST-safe double slots) | supercronic in a container set to `TZ=America/New_York` |
| Phase | now → evaluation verdict (~May 2027) | build Jan 2027, burn-in Feb 2027, pilot after the verdict |

## 1. Where things stand

* The harness (docs/06) ran push-triggered smoke drills, but its schedules
  never fired: GitHub runs scheduled workflows only from the default branch,
  and the workflows pointed at the feature branch. The ghost record has not
  started. `LIVE_START` moves from the never-used 2026-08-18 to
  **2026-09-28**.
* A review of the paper path found defects that would have broken the first
  paper night. They are fixed in this change (§2) and covered by tests
  (`NASDAQ/tests/`, 53 tests, run by `nasdaq-tests.yml` on every push).
* The back-propagation loop needs no scheduler: `adapt()` runs inside the
  twin's replay every 63 sessions. In a paper run starting 2 Nov 2026 the
  first live adaptation fires on **2 Feb 2027**, the second on **4 May 2027**.

## 2. What this change fixed

| # | Problem | Fix | Where |
|---|---|---|---|
| F1 | Cycle A sent on-open (`opg`) orders at 17:00 ET; Alpaca only accepts them from 19:00 to 09:28 ET, so every paper order would have been rejected | Cycle A only ledgers. A separate **submit step** sends at 19:15 ET, with retry slots every 30 minutes through the evening and a manual run until 09:28 ET | `live/cycle_submit.py`, `live-submit.yml` |
| F2 | Cycle B could not trace fills (fill activities carry Alpaca's order id, not ours) and had no real reconciliation | Every order is looked up by our client order id; slippage is measured against the official open; the account is reconciled **share for share** (positions before submission + fills = positions now). A break writes `ledger/halt.json`, and the submit step sends nothing until a human clears it | `live/cycle_b.py`, `live/execution.py`, `live/broker.py` |
| F3 | The compliance guardrails blocked **sales** of names that left the universe, the exact names that must be sold | Whitelist and exclusions block buys only. A held name on the exclusion list gets a **forced exit at the next open**, ledgered by Cycle A and re-derived from the account by the submit step; a partial sell of an excluded name becomes a full exit | `live/guardrails.py`, `live/cycle_a.py`, `live/execution.py` |
| F4 | Seven preferred/perpetual lines (BRKRP, SMCIP, MCHPP, STRF, STRC, STRK, SATA) passed on their issuers' ratios; a pork producer (SFD) escaped the keyword screen | Instrument screen (common shares only) and a curated overrides file with review flags; the universe drops **327 → 319**. Regression recorded (§3) | `pipeline/sharia_screen.py`, `data/sharia_overrides.json`, `pipeline/apply_screen_rules.py` |
| F5 | `LIVE_START` was hard-coded; switching ghost → paper without resetting it would send a months-old model book into an all-cash account | `LIVE_START` is a repository variable (default 2026-09-28). The submit step holds (P1) when the account and twin books differ by more than 20% of equity | `live/config.py`, `live/cycle_submit.py` |
| F6 | Sell quantities came from the twin's share count, not the account's | Sells are sized from the account's holdings; buys are trimmed to the cash the night's sells free (no reliance on margin) | `live/execution.py` |
| F7 | Nothing noticed a submission that never happened | Dead-man check at ~21:30 ET: orders ledgered, no submit record → P1 | `live/deadman.py`, `live-deadman.yml` |
| F8 | Portfolio-level breaches (daily turnover > 75%, gross cap) blocked nothing in paper mode | They **hold the night** (P1) until a human releases it with a manual run; kill switch, drawdown kill and reconciliation halts cannot be released that way | `live/cycle_submit.py` |
| F9 | Workflows pointed at the feature branch | All live workflows check out and commit to `main`; Cycle A/B and submit gained `workflow_dispatch` for manual re-runs | `.github/workflows/live-*.yml` |

## 3. The universe correction and its regression

Removing eight names changes the twin's world even though the agent never
traded any of them: `trend` reads market breadth (the share of the universe
above its 50-day average), computed over the whole universe. Same frozen
agent, same OOS window (2023-01-03 → 2026-08-04):

| | Election record (327) | Corrected universe (319) |
|---|---|---|
| Total return | +207.6% | +216.8% |
| CAGR | 36.8% | 38.0% |
| Sharpe | 1.22 | 1.26 |
| Max drawdown | −16.2% | −16.3% |
| Trades | 806 | 808 |

The paths first diverge on 2025-04-25. The difference is path noise from a
changed input, not an improvement; the election figures remain the official
out-of-sample record and the corrected run is the reference for the deployed
configuration. Full record: `out/regression_2026-09-25_universe.json`.

The universe is now frozen for the evaluation. Any later compliance change
acts through `controls.json` exclusions and forced exits, never through the
twin's universe (decision fidelity).

## 4. The route, with gates

| Phase | Dates | What runs | Gate to advance |
|---|---|---|---|
| **1 — Ghost** | Mon 28 Sep → Fri 30 Oct 2026 (25 sessions) | Cycle A, the submit step (rehearsal against the twin's book), Cycle B, dead-man, all on GitHub | 10 consecutive deterministic sessions (earliest **Fri 9 Oct**), zero open P1 issues, the nightly rehearsal sends what the ledger says |
| **2 — Paper** | from **Mon 2 Nov 2026** | Same, against an Alpaca paper account. First week in approval mode (a human releases each night) | 10 clean paper sessions (earliest **Fri 13 Nov**): no P1, no reconciliation break, average slippage ≤ 10 bps/side |
| **3 — Evaluation** | 2 Nov 2026 → **Tue 4 May 2027** (126 sessions, 2 live adaptations) | Steady state; quarterly re-screens (1 Jan, 1 Apr); monthly reviews | The pre-registered bands (docs/05 §8): tracking error to twin < 0.5%/month, slippage ≤ 10 bps/side, rolling 63-session Sharpe > 0.5 absent a bear market, zero unresolved P1 |
| **4 — Private build** (parallel) | Jan 2027 build; burn-in **Mon 1 Feb → Mon 1 Mar 2027** (20 sessions) | The Unraid container in ghost mode | 20 sessions in which the private twin's orders and book equal the public twin's |
| **5 — Real money** | pilot from **Mon 10 May 2027** at the earliest | The Unraid executor against a live cash account | Evaluation passed + burn-in passed + decisions D1–D6 made + tasks R1–R6 done |

Real money is gated on the evaluation verdict. An earlier **micro-pilot**
(a small live account from Tue 2 Mar 2027, after the burn-in) is an option
for testing the real execution path only (§7, R7); it is not a verdict on the
agent.

## 5. Private deployment on the Unraid server

### Why a private box

Real-money keys must never enter this public repository or its Actions
secrets (docs/05 §9). A home server keeps the keys, the real account's
ledger and its alert channel private, while GitHub stays the public research
record. The same pinned code runs in both places.

### Design

```
Unraid host (UPS + NUT, NTP)
└── container "nafa-live"  (python:3.12-slim + git + supercronic + tini)
    ├── /app      the repository at a pinned release tag (read-only)
    ├── /data     appdata volume: /mnt/user/appdata/nafa-live/
    │   ├── ledger/        LIVE_LEDGER_DIR — cycles, orders, twin, halt.json
    │   ├── raw_live/      daily re-fetch (regenerated)
    │   └── enriched_live/
    ├── /secrets/live.env  chmod 600: APCA keys (live), webhook, heartbeat URLs
    └── crontab (TZ=America/New_York + tzdata, so times are ET all year):
          5 17 * * 1-5       run-step cycle_a
          15 18 * * 1-5      run-step deadman
          15 19 * * 1-5      run-step cycle_submit
          45 19 * * 1-5      run-step cycle_submit    # retry slot (idempotent)
          30 21 * * 1-5      run-step deadman --submit
          50 9 * * 1-5       run-step cycle_b
          0 10 1 1,4,7,10 *  run-step rescreen
```

`run-step` is a small wrapper: run the step, ping the step's heartbeat
check (success or failure), then commit and push the ledger to the private
ledger repository. The harness already decides from the exchange calendar
whether a day is a session, so the cron lines stay simple.

### What the box needs from the code

| Need | Status |
|---|---|
| Ledger outside the repository checkout | done: `LIVE_LEDGER_DIR` |
| `LIVE_START` per deployment | done: environment variable |
| Idempotent steps, safe to re-run after a power cut | done |
| Push alerts without GitHub | done: `ALERT_WEBHOOK_URL` (ntfy, Telegram, Discord, Slack-style JSON) |
| A live broker class, armed only on the box | **to do (R2)** |
| Twin at the account's real capital | **to do (R3)** |
| Cash-account execution | **to do (R4)** |
| Container, crontab, `run-step`, heartbeat pings | **to do (U2, U4)** |
| Cross-check of private vs public twin decisions | **to do (U6)** |

### Failure handling on a home server

* **Power loss:** UPS + NUT shuts down cleanly; the container restarts with
  the array (`--restart unless-stopped`). A missed 17:05 Cycle A can be
  re-run any time that evening; a missed 19:15 submit can be re-run until
  09:28 ET. Beyond that the day is skipped, never guessed.
* **Internet loss:** the data gate or the broker call fails and the step
  records its failure; nothing trades on partial data.
* **The box itself dies:** an external heartbeat service (healthchecks.io,
  or Uptime Kuma hosted elsewhere) expects a ping from each step and alerts
  the phone when one is missing. A dead-man inside the box cannot see its
  own death.
* **Security:** no inbound ports; outbound only to Alpaca, Yahoo Finance,
  NASDAQ, the ledger remote and the heartbeat service. Secrets live in the
  env file, not in the image or the ledger. Broker key permissions: trading
  only, no transfers; rotate quarterly.

## 6. Decisions only the owner can make

| ID | Decision | Recommendation | Needed by |
|---|---|---|---|
| D1 | **Sharia policy in writing**: the standard (AAOIFI SS 21), a ruling on each of the 22 review-flagged names (media and entertainment, defense, hotels, MSTR, RPRX, CASY, TXRH, …), and the purification method | Rule on the review list **before 30 Oct 2026**: a universe change after the paper start breaks decision fidelity, so later rulings can only act as exclusions and forced exits | 30 Oct 2026 |
| D2 | Real-money account type | **Cash account** (no margin agreement), with the execution change in R4 | Feb 2027 |
| D3 | Real-money broker | **Alpaca live**: the same API as paper, so the evaluated path is the traded path. Alternative: Interactive Brokers (lower costs at size, a different API, a new adapter to write and test) | Jan 2027 |
| D4 | Pilot capital and hard limits | Start small; set a loss limit that halts the pilot. Note R3: very small accounts round positions coarsely | Apr 2027 |
| D5 | Cold or warm start at each switch | **Cold**: reset `LIVE_START` so the twin and the account both start in cash on the same session | at each switch |
| D6 | Private ledger remote | A **private GitHub repository** (off-site copy, issues for P1s); Gitea on the Unraid box keeps everything home but loses the off-site copy | Jan 2027 |

## 7. Task list

Owner **you** = the repository owner; **Claude** = a coding session like this
one; dates are the latest sensible completion.

### G — Ghost on GitHub

| ID | Task | Owner | Due | Status |
|---|---|---|---|---|
| G1 | Merge `claude/trading-agent-market-deploy-357d6j` into `main` | you | Sun 27 Sep 2026 | open |
| G2 | Check the post-merge push drills: `live-cycle-a`, `live-cycle-b`, `live-submit`, `live-rescreen`, `nasdaq-tests` all green | you / Claude | Sun 27 Sep | open |
| G3 | If the merge slips past 27 Sep, set the repository variable `LIVE_START` to the first session after the merge | you | at merge | conditional |
| G4 | First scheduled nights run on their own (Cycle A 17:00, submit rehearsal 19:15, Cycle B 09:50 ET) | automatic | Mon 28 Sep | open |
| G5 | Read the first quarterly re-screen report (`ledger/compliance/2026-10-01.json`) | you | Thu 1 Oct | open |
| G6 | Ghost gate passes: 10 deterministic sessions in `gate.json` | automatic | Fri 9 Oct | open |

### P — Paper on GitHub

| ID | Task | Owner | Due | Status |
|---|---|---|---|---|
| P1 | Open an Alpaca paper account; add `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` as repository secrets (paper keys only) | you | Fri 23 Oct | open |
| P2 | Optional: `ALERT_WEBHOOK_URL` secret for phone alerts | you | Fri 23 Oct | open |
| P3 | Reset the paper account to $100,000 cash and no positions | you | Fri 30 Oct | open |
| P4 | Set repository variables `LIVE_START=2026-11-02`, `LIVE_MODE=paper`, `APPROVAL_MODE=true` | you | Sat 31 Oct | open |
| P5 | Approval week: each evening read `orders/<date>.json` and the held submit record, then run `live-submit` manually | you | 2–6 Nov | open |
| P6 | Remove `APPROVAL_MODE` after five clean nights | you | Mon 9 Nov | open |
| P7 | Paper gate: 10 clean sessions | automatic | Fri 13 Nov | open |

### E — Evaluation

| ID | Task | Owner | Due | Status |
|---|---|---|---|---|
| E1 | Monthly review: tracking error to twin, slippage, fills missed, P1 count, cockpit anomaly panel | you + Claude | monthly | open |
| E2 | Check the first live adaptation record (parameters moved within bounds, ledgered) | you + Claude | Wed 3 Feb 2027 | open |
| E3 | Quarterly re-screens: rule on anything flagged (exclusions act as forced exits) | you | 1 Jan, 1 Apr 2027 | open |
| E4 | Verdict against the pre-registered bands; publish it in the repository | you + Claude | Fri 7 May 2027 | open |

### U — Unraid private deployment

| ID | Task | Owner | Due | Status |
|---|---|---|---|---|
| U1 | Decide the ledger remote (D6) and create it | you | Mon 4 Jan 2027 | open |
| U2 | Container image, crontab (ET) and `run-step` wrapper under `NASDAQ/deploy/unraid/`; Unraid template notes | Claude | Fri 15 Jan 2027 | open |
| U3 | Appdata share, `live.env` (chmod 600), container autostart | you | Fri 22 Jan 2027 | open |
| U4 | Heartbeat checks per step (A, submit, B, dead-man) with phone alerts | you + Claude | Fri 22 Jan 2027 | open |
| U5 | UPS + NUT graceful shutdown; NTP; restart policy | you | Fri 22 Jan 2027 | open |
| U6 | Twin cross-check: each night compare the private twin's orders and book with the public twin's; any difference is a P1 | Claude | Fri 29 Jan 2027 | open |
| U7 | Box runbook: power loss, network loss, disk full, key rotation, restore from the ledger remote | Claude | Fri 29 Jan 2027 | open |
| U8 | Burn-in: 20 ghost sessions matching the public twin | automatic | Mon 1 Mar 2027 | open |

### R — Real money

| ID | Task | Owner | Due | Status |
|---|---|---|---|---|
| R1 | Open the live account (cash, individual); W-8BEN; fund it only at pilot start | you | Apr 2027 | open |
| R2 | Live broker class: `LIVE_MODE=live`, base URL from the environment, refuses to start unless an arming variable is set, per-order and per-night notional caps, never configured on GitHub | Claude | Feb 2027 | open |
| R3 | Twin capital: make the starting capital configurable (`sim/engine.py` change, byte-identical when unset, proven by regression) and run the OOS window at the pilot's capital to measure rounding cost | Claude | Feb 2027 | open |
| R4 | Cash-account execution. In a cash account, buying power at 19:15 ET does not include proceeds from sells that fill at the next open. Options: (a) keep a cash reserve and accept that rotation buys wait a day (measured drift); (b) send rotation buys as market orders after the open once the sells fill; the new position must then not be sold before the sale proceeds settle (T+1), or it is a good-faith violation. Verify Alpaca's cash-account rules on the live account, then implement the chosen option with tests | Claude + you | Mar 2027 | open |
| R5 | Purification ledger: dividends received × each name's impermissible-income share (source per S2), reported quarterly | Claude | Mar 2027 | open |
| R6 | Tax and estate check with a professional: 30% withholding on US dividends for a Saudi resident (no treaty), US estate tax on US assets above $60,000 for non-residents | you | Apr 2027 | open |
| R7 | Optional micro-pilot on the box from Tue 2 Mar 2027: small capital, tests the live execution path only | you | Mar 2027 | option |
| R8 | Go/no-go for the pilot (evaluation passed, burn-in passed, D1–D6 made, R1–R6 done); pilot start Mon 10 May 2027 at the earliest | you | May 2027 | open |

### S — Sharia

| ID | Task | Owner | Due | Status |
|---|---|---|---|---|
| S1 | Written policy (D1), optionally reviewed by a scholar | you | Fri 30 Oct 2026 | open |
| S2 | Revenue-based 5% impermissible-income test from a Shariah data API (Zoya or Musaffa) for held names, quarterly. The free-data screen can only proxy it | Claude (needs an API key on the box) | Mar 2027 | open |
| S3 | Quarterly cross-check of the universe against a Shariah ETF's holdings (HLAL, SPUS); investigate disagreements | Claude | 1 Jan 2027 | open |
| S4 | Apply D1 rulings: before 30 Oct via `data/sharia_overrides.json` + `apply_screen_rules.py` + regression; after that only through `controls.json` exclusions | Claude | Fri 30 Oct 2026 | open |

## 8. Risks and how the plan answers them

| Risk | Answer |
|---|---|
| GitHub cron delays (often 10–60 min at busy times) | Submit slots every 30 minutes; a late Cycle A is picked up by the next slot; manual runs until 09:28 ET; dead-man checks |
| Data-source outage or bad prints | The data gate trips and nothing trades that day; the second source cross-checks up to 40 names |
| Paper fills flatter than real auction fills | The micro-pilot (R7) or the pilot measures real slippage; the 10 bps band applies to both |
| Splits or other corporate actions between submit and reconcile | They show up as a reconciliation break, which halts until a human writes the cause into `halt.json` and clears it |
| Twin/account drift from whole-share estimates | Measured nightly (`account_drift`), tolerance ±2 shares or 5%; persistent drift is a P1 |
| Forced exits make the account differ from the twin | Expected and labelled (`explained`) in the drift report; not a breach |
| Frozen universe: newly eligible names and IPOs wait | Declared fidelity gap; they enter at the next declared redeploy |
| Dividend withholding (30%) not modelled in the twin | Small (the portfolio yields little); declared gap, visible in the real account's tracking error |

---

*Not financial advice. Real-money trading carries the risk of loss; the
evaluation exists to find out whether this agent deserves any.*
