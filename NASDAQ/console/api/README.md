# NAFA Console: API

The console's backend (docs/08 §3.1). It is FastAPI and serves:

* the v1 **read API** ([`web/src/api/types.ts`](../web/src/api/types.ts) is the
  contract)
* an **indexer** loop that pulls the ledger clone and reloads when a file
  changes
* the built **web UI**, on the same port

Milestone **M0: read-only.**

```sh
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # (bin/ on Linux)
.venv/Scripts/python -m uvicorn nafa_console.app:app --port 8080
# then http://localhost:8080  (build the UI first: cd ../web && npm run build)
python -m pytest ../../tests/console -q
```

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
| `live/controls.json` | Trading state (kill, pause), exclusions, forced exits |
| `data/universe_screened.json`, `data/rescreen/*-screened.json` | Universe, debt and cash ratios, review flags, reasons for exclusions |
| `data/sharia_overrides.json` | Review flags and their wording |
| git log | Head commit, control-change markers, the previous day's prices (for day change) |

**Nothing is estimated.** Anything the ledger does not yet hold is returned
as `null`, and the UI shows it as pending. That covers:

* confidence sub-scores
* ATR and stop levels
* momentum rank
* live daily prices
* broker account figures in Ghost

### Insights file (milestone M3)

When `live/ledger/insights/<asof>.json` exists, the console fills confidence
and stops from it:

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
| `CONSOLE_ROLE` | `owner` | `owner` or `viewer`. M1 replaces this with login + TOTP. |

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
| `GET /api/health` | System health |
| `GET /api/roadmap` | Roadmap |
| `POST /api/sync` | Run one indexer pass now |
| `GET /healthz` | Liveness, for Uptime Kuma |
| `GET /api/docs` | OpenAPI docs |

`nafa_console/roadmap.json` holds the docs/07 route (phases, decisions D1–D8
and tasks), maintained by hand.
