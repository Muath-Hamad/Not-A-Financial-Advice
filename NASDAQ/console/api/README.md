# NAFA Console: API

The console's backend (docs/08 §3.1). It is FastAPI and serves:

* the v1 **API** ([`web/src/api/types.ts`](../web/src/api/types.ts) is the
  contract): reads, sign-in, and the control service
* an **indexer** loop that pulls the ledger clone, reloads when a file
  changes, and pushes new P1 alerts to ntfy
* the built **web UI**, on the same port

A second, separate app, the **broker gateway** (`nafa_console.gateway:app`),
holds the broker keys. The console only talks to it over HTTP with a token
and never sees the keys (docs/08 §3.2).

Milestones **M0–M3 done** (docs/08 §12): read API, controls with TOTP,
audit, account book over the gateway, alerts with ntfy, performance,
agent and the monthly review pack.

```sh
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # (bin/ on Linux)
.venv/Scripts/python -m uvicorn nafa_console.app:app --port 8080
# then http://localhost:8080  (build the UI first: cd ../web && npm run build)
python -m pytest ../../tests/console -q

# users (argon2id password + TOTP; prints the authenticator secret once)
.venv/Scripts/python -m nafa_console.users add NAME --role owner
.venv/Scripts/python -m nafa_console.users list

# local development without sign-in
CONSOLE_AUTH=off .venv/Scripts/python -m uvicorn nafa_console.app:app --port 8080

# the broker gateway (paper), on the box only
APCA_API_KEY_ID=… APCA_API_SECRET_KEY=… CONSOLE_GATEWAY_TOKEN=…   .venv/Scripts/python -m uvicorn nafa_console.gateway:app --port 8090
```

## Controls (M1)

Every action runs the same pipeline (docs/08 §7):

1. **Preview** (`POST /api/controls/preview`) returns the exact impact and
   a `previewHash` of the change.
2. **Apply** (`POST /api/controls/apply`) needs the hash, a category, a
   reason of at least 10 characters, a fresh TOTP code (each code works
   once) and the typed word for destructive actions. A hash that no longer
   matches returns **409** with the new preview.
3. The change is validated against `live/controls_schema.py`, committed with
   a structured message (`Actor`, `Reason`, `Effective`, `Console-Action-Id`
   trailers) and pushed.
4. Immediate commands (cancel all, flatten) go to the gateway, which writes
   `live/ledger/commands/<ts>-<action>.json`. Re-runs and releases dispatch
   the GitHub workflow.
5. Any failed step is reported as **Not applied**; earlier steps are listed.

`CONSOLE_WRITE` picks the writer: `dry` (default; validates and logs, writes
nothing), `git` (commit and push in the clone) or `github` (the contents
API). The **Audit log** reads the git history of `controls.json` and
`halt.json`, the console's control events and broker commands.

## What it reads

The ledger is the source of truth, and the API only reads it:

| File | Used for |
|---|---|
| `live/ledger/twin/twin_latest.json` | Model book: positions, trades (history, round trips, FIFO lots), equity curve, journal |
| `live/ledger/cycles/*-A/S/B.json` | Health grid, the data gate, the Cycle A failure streak, heartbeats |
| `live/ledger/gate.json` | Ghost gate streak and hash history |
| `live/ledger/orders/<asof>.json` | Pending orders for the next open, with guardrail blocks |
| `live/ledger/compliance/<date>.json` | Re-screen diffs |
| `live/ledger/halt.json` | Reconciliation halt |
| `live/controls.json` | Trading state (kill, pause), exclusions, forced exits, locks, manual orders, gross cap, adapt pause (v2) |
| `live/ledger/insights/<asof>.json` | Confidence, stops, rank, regime (M3, written by Cycle A) |
| `live/ledger/commands/*.json` | Immediate broker commands (audit) |
| `out/oos_metrics.json`, `out/confidence_calibration.json` | OOS reference metrics and confidence calibration |
| `data/universe_screened.json`, `data/rescreen/*-screened.json` | Universe, debt and cash ratios, review flags, reasons for exclusions |
| `data/sharia_overrides.json` | Review flags and their wording |
| git log | Head commit, control-change markers, the previous day's prices (for day change) |

**Nothing is estimated.** Anything the ledger does not yet hold is returned
as `null`, and the UI shows it as pending: confidence and stops before the
first insights file, broker figures in Ghost, account metrics before the
first paper fill.

### Insights file (milestone M3)

Cycle A runs `live/insights.py` after the twin and writes
`live/ledger/insights/<asof>.json`; the console fills confidence and stops
from it:

```json
{"positions": {"TXG": {"signal": 88, "risk_room": 84, "regime": 62, "data": 92, "at_entry": 72,
                       "atr": 3.10, "initial_stop": 54.74, "trailing_stop": 72.90, "high": 88.40,
                       "rank": 2, "off_high_pct": 3, "sma_stack": "above SMA 50, 100 and 200",
                       "cross_source": "agree"}}}
```

## Settings (environment)

| Variable | Default | Meaning |
|---|---|---|
| `CONSOLE_PKG_DIR` | this repository's `NASDAQ/` | Where `live/` and `data/` are; `/data/repo/NASDAQ` in the container |
| `LIVE_LEDGER_DIR` | `<pkg>/live/ledger` | Ledger override, the same as the harness's |
| `CONSOLE_DB` | `api/console.db` | SQLite file for alert acknowledgements and indexer runs |
| `CONSOLE_STATIC_DIR` | `../web/dist` | The built UI |
| `CONSOLE_GIT_PULL` | `0` | `1`: `git pull --ff-only` on every indexer pass |
| `CONSOLE_INDEX_EVERY_S` | `60` | Seconds between indexer passes |
| `CONSOLE_AUTH` | `on` | `off` skips sign-in and TOTP (development only); the role then comes from `CONSOLE_ROLE` |
| `CONSOLE_ROLE`, `CONSOLE_USER` | `owner`, `owner@console` | Role and name when `CONSOLE_AUTH=off` |
| `CONSOLE_SECURE_COOKIE` | `0` | `1` behind HTTPS |
| `CONSOLE_WRITE` | `dry` | `dry`, `git` or `github` (see Controls) |
| `CONSOLE_GIT_PUSH` | `1` | With `git`: push after the commit |
| `CONSOLE_GH_TOKEN`, `CONSOLE_GH_REPO`, `CONSOLE_GH_BRANCH` | —, —, `main` | GitHub writer and workflow dispatch (re-run, release) |
| `CONSOLE_GATEWAY_URL`, `CONSOLE_GATEWAY_TOKEN` | — | Broker gateway; unset in Ghost |
| `CONSOLE_NTFY_URL` | — | ntfy topic URL for P1 push |

Gateway only: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `GATEWAY_MODE`
(`paper`), `CONSOLE_GATEWAY_TOKEN`.

## Endpoints

| Method and path | What it does |
|---|---|
| `GET /api/overview` | Overview data |
| `GET /api/holdings` | All holdings |
| `GET /api/holdings/{sym}` | One holding |
| `GET /api/orders/pending` | Orders for the next open |
| `GET /api/orders` | Order history |
| `GET /api/round-trips` | Closed round trips |
| `GET /api/compliance` | Sharia compliance |
| `GET /api/alerts` | Alerts |
| `POST /api/alerts/{id}/ack` | Acknowledge an alert |
| `POST /api/alerts/{id}/resolve` | Resolve an alert with a note |
| `GET /api/health` | System health |
| `GET /api/roadmap` | Roadmap |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Sign-in (password + TOTP), session cookie and CSRF token |
| `GET /api/controls` | controls.json, pending changes, halt, limits, writer mode |
| `POST /api/controls/preview` | Impact of one action |
| `POST /api/controls/apply` | Apply it (step-up TOTP, reason, typed word) |
| `POST /api/controls/preflight` | Resume checklist |
| `GET /api/audit` | Control changes, commands and sign-ins |
| `GET /api/performance` | Metrics vs OOS, monthly returns, attribution, execution |
| `GET /api/agent` | Parameters vs bounds, regime, journal, adaptations, calibration |
| `GET /api/review`, `GET /api/review/{YYYY-MM}` | Monthly review pack (printable HTML) |
| `POST /api/sync` | Run one indexer pass now |
| `GET /healthz` | Liveness, for Uptime Kuma |
| `GET /api/docs` | OpenAPI docs |

`nafa_console/roadmap.json` holds the docs/07 route (phases, decisions D1–D8
and tasks), maintained by hand.
