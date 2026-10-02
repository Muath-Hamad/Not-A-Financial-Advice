# NAFA Operations Console

The private web dashboard for the live harness, to run on the Unraid tower.
Design: [docs/08](../docs/08-console-system-design.md) (system),
[docs/09](../docs/09-console-ui-spec.md) (UI spec), and the Claude Design
prototype hand-off in [docs/09c](../docs/09c-console-prototype/HANDOFF.md)
with tokens in [docs/09b](../docs/09b-console-design-tokens/).

| Path | What | Status |
|---|---|---|
| `web/` | React + TypeScript + Vite SPA (Tailwind, TanStack Query/Table, ECharts) | **M0 read-only UI**, on a mocked API |
| `api/` | FastAPI read API, ledger indexer, SQLite read model, control service | not started (next) |
| `Dockerfile` | `nafa-console` image (Python + built static assets) | not started |

The console is separate from the executor. It never holds live broker keys,
and if it is down, trading is unaffected (docs/08 §3, §11).

## Milestones (docs/08 §12)

* **M0 Read-only (ghost):** UI done in `web/`. Still to do: the indexer and
  API over the public ledger, and the Unraid template.
* **M1 Controls:** the Controls screen, the 4-step confirm modal, the resume
  preflight, TOTP step-up, the Audit log, and the harness changes in
  docs/08 §7.2.
* **M2 Account:** the broker gateway (paper), the Account book, fills and
  slippage, drift, the Alerts inbox and ntfy, and Performance.
