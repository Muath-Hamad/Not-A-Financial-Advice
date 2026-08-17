# 03 — The simulation engine

`sim/engine.py` — a day-synchronized, multi-agent, long-only backtest engine.
Every agent trades the same calendar simultaneously, each with an independent
portfolio, and can observe the others' public books.

## 1. Market construction

`Market.__init__` loads every non-`failed` ticker from the manifest into a
numpy-backed store rather than a dict of DataFrames — at 160+ tickers × 1,144
sessions, per-row pandas lookups dominate runtime.

```python
self._cols[code]  # list of column names
self._vals[code]  # ndarray (n_rows, n_cols), float64
self._pos[code]   # {Timestamp: row_index}
```

Row access materializes a plain dict lazily, and the whole-market `view()` for a
date is cached, so a session that all 8 agents query costs one construction:

```python
def view(self, date):
    if self._cache_date != date:
        self._cache_view = self._build_view(date)
        self._cache_date = date
    return self._cache_view
```

### The trading calendar

```python
dates = union of every stock's session index      # not the index's calendar
self.dates = [d for d in dates if d >= SIM_START]
```

Using the **union of stocks** rather than the index calendar matters: the TASI
series is missing 32 sessions that stocks traded in the in-sample window. The
benchmark is reindexed onto the union and forward-filled, so a missing index
print never creates a phantom return.

### Benchmark

```python
tasi = tasi_adjclose.reindex(union).ffill().reindex(self.dates)
tasi_ret = tasi.pct_change().fillna(0.0)
```

In results the index is rescaled to start at SAR 100,000, making it directly
comparable to the agent equity curves. **It is a price index** — it pays no
dividends, while agent portfolios do collect them. This modestly favors the
agents; a total-return TASI would be the stricter benchmark.

### Breadth

```python
breadth(date) = (# names with AdjClose > sma50) / (# names with a valid sma50)
```

Computed vectorized across the whole universe for every date at construction
time, defaulting to 0.5 where undefined. Exposed to agents as
`ctx["breadth_sma50"]`; it is the most-used regime input in the arena.

## 2. The daily loop

For each session *i* (date *t*), in this exact order:

```
FOR EACH AGENT:
  1. Credit dividends       — any held name with Dividends > 0 on t
  2. Execute pending orders — fills at TODAY's open (queued at t−1's close)
  3. Mark to market         — last_price ← today's close; force-exit stale names
  4. Snapshot equity        — append to equity_hist / cash_hist
  5. Monthly holdings       — on month change or final session

MARKET-WIDE:
  6. Record event           — if |TASI return| ≥ 2%

DECISIONS (skipped on the final session):
  7. Build peers snapshot   — every agent's public book as of this close
  8. FOR EACH AGENT: decide(date, view, portfolio, ctx)
  9. Record sentiment / mood / journal note; queue returned orders
```

The critical property: **step 8 sees only data through the close of *t*, and its
orders execute in step 2 of session *t+1*, at that session's open.** There is no
path by which a strategy can act on information it could not have had. Agents
are also called in a fixed order and cannot see each other's *current-day*
decisions — only books as of the close.

## 3. Order lifecycle

### Order format

Strategies return a list of dicts. Buys size four ways, sells five:

```python
{"code": "1120", "side": "buy",  "sar": 25000,    "reason": "..."}  # absolute SAR
{"code": "1120", "side": "buy",  "weight": 0.25,  "reason": "..."}  # fraction of equity
{"code": "1120", "side": "buy",  "shares": 100,   "reason": "..."}  # share count
{"code": "1120", "side": "sell", "all": True,     "reason": "..."}
{"code": "1120", "side": "sell", "fraction": 0.5, "reason": "..."}  # of held shares
{"code": "1120", "side": "sell", "shares": 100,   "reason": "..."}
{"code": "1120", "side": "sell", "sar": 5000,     "reason": "..."}
```

Validation is minimal by design (`code` coerced to string, `side` must be
`buy`/`sell`); anything malformed increments `rejected_orders` instead of
crashing the run.

### Buy execution

```python
px     = open × (1 + SLIPPAGE)                    # 5 bps
budget = min(requested_budget, cash)              # never exceeds cash
n      = int(budget / (px × (1 + COMMISSION)))    # integer shares, floor
if n < 1: reject
cost = n × px
fee  = cost × COMMISSION                          # 8 bps
cash -= cost + fee
avg_cost = (avg_cost × prev_shares + cost) / (prev_shares + n)
```

`weight` orders resolve against a locally recomputed equity (cash + marked
positions), so a weight is a fraction of the book at fill time.

### Sell execution

```python
px     = open × (1 − SLIPPAGE)
n      = min(requested, held)
gross  = n × px
fee    = gross × COMMISSION
cash  += gross − fee
realized_pnl = (px − avg_cost) × n
```

Average cost is **not** reduced on partial sells, so realized P&L on the
remainder stays measured against the original basis.

### Cost model

| Component | Value | Rationale |
|---|---|---|
| Commission | **8 bps per side** | Saudi discount-broker rate. v1/v2 used Tadawul's 15.5 bps + 15% VAT ≈ 17.8 bps; lowered for v3 at the user's request |
| Slippage | **5 bps per side** | Applied against the trader: buys fill above the open, sells below |

Round-trip friction is therefore ~26 bps. There is no market-impact model beyond
slippage — agents that self-cap position size against `turnover_sar` are
modelling impact themselves, and most do.

### Order TTL and halts

A queued order whose ticker has **no row** on the fill date (halted, suspended,
or not yet listed) is not cancelled — its `ttl` decrements from
`ORDER_TTL = 5` and it retries each session until it fills or expires.

## 4. Corporate actions

**Dividends.** On the ex-date, `cash += shares × Dividends`. The amount is
split-adjusted like the price series, so it stays consistent across bonus
issues. Tracked per agent as `dividends_received`. No withholding tax is
modelled (Saudi equities pay no dividend withholding to domestic investors).

**Splits and bonus issues.** Absorbed by Yahoo's split-adjusted raw series;
share counts are never rewritten. The `Splits` column is carried for audit only.

**Delisting / long suspension.** A held name with no price row for **20
consecutive sessions** is force-liquidated at its last known price minus
slippage, logged with:

```
reason = "forced exit: name suspended/delisted (20 sessions without prices)"
```

Without this, a dead position would mark at a stale price forever and quietly
inflate terminal equity.

## 5. The `decide()` contract

```python
decide(date, view, portfolio, ctx) -> dict
```

**`view`** — `{code: {column: value}}` for every ticker trading today, plus
`view["TASI"]`. All 42 columns from [02](02-preprocessing.md). A missing key
means the name did not trade.

**`portfolio`** —
```python
{"cash": float, "equity": float,
 "positions": {code: {shares, price, value, weight, avg_cost, unrealized_pct}}}
```

**`ctx`** —

| Key | Contents |
|---|---|
| `day_index` | 0-based session number |
| `breadth_sma50` | Fraction of universe above its 50-day SMA |
| `tasi_ret_1d` | Index return today |
| `equity_history` | This agent's own daily equity list so far |
| `names`, `sectors` | `{code: str}` lookups |
| `peers` | The other agents' public books — see below |

**Return value** —

| Key | Meaning |
|---|---|
| `orders` | List of order dicts (may be empty) |
| `sentiment` | Float in [−1, 1], clamped by the engine |
| `mood` | Short label, truncated to 40 chars |
| `note` | One private journal line, truncated to 500 chars |

An exception inside `decide()` is caught, counted in `decide_errors`, and
treated as "no decision today" — one agent cannot abort a run. All eight v3
agents finish with `errors = 0`.

## 6. The peer channel

Built fresh each session from every agent's close-of-day snapshot:

```python
peers[handle] = {
  "equity":       float,
  "ret_21":       equity[-1]/equity[-22] − 1,     # 0.0 until 22 sessions exist
  "ret_63":       equity[-1]/equity[-64] − 1,
  "cash_frac":    cash / equity,
  "positions":    {code: weight},
  "today_trades": [{code, side, value, realized_pnl}],
}
```

Each agent receives all handles **except its own**. This is public
track-record information — the kind a fund-of-funds could observe — and enables
copy-trading (`malik`), a "learn from the field's realized losses" ledger, and
small ranking tilts.

Two invariants every v3 agent respects, verified in their self-tests:

1. **Peers are empty in a solo run.** Each strategy was tested standalone, where
   `ctx["peers"] == {}`, and must work unchanged.
2. **The peer term is bounded.** No agent lets peer information define its book;
   it only tilts a ranking that already cleared every gate.

### v3 removed the chat

v1 and v2 had a "majlis" — a shared board where agents posted messages that
others read the next day. v3 removed it entirely at the user's request. Agents
still keep **private journals** (`note`, `mood`, `sentiment`), which are stored
and rendered in the dashboard, but there is no inter-agent messaging. Competition
runs purely through the peer books.

## 7. Configuration

| Constant | Value | Env override |
|---|---|---|
| `START_CASH` | 100,000.0 | — |
| `COMMISSION_RATE` | 0.0008 | — |
| `SLIPPAGE` | 0.0005 | — |
| `SIM_START` | `2022-01-01` | `SIM_START` |
| `ORDER_TTL` | 5 sessions | — |
| Forced-exit threshold | 20 silent sessions | — |
| Enriched data dir | `data/enriched` | `SIM_ENRICHED_SUBDIR` |
| Raw/manifest dir | `data/raw` | `SIM_RAW_SUBDIR` |

Env paths resolve relative to `TASI/`, not the repo root.

## 8. Output — `out/results.json`

```
meta      start_cash, sim_start, sim_end, sessions, universe_size, names, sectors
dates     [ISO date per session]
tasi      [index rescaled to 100k]
events    [{date, type: crash|rally, tasi_ret}]   for |return| ≥ 2%
tasi_metrics  full metric block for the benchmark
agents[]  meta, equity[], cash[], sentiment[], trades[], journal[],
          holdings_monthly[], final_positions, dividends_received,
          commissions_paid, rejected_orders, decide_errors, metrics{}
```

Array lengths: `equity` and `cash` have one entry per session (1,144);
`sentiment` and `journal` have one per *decision* session (1,143 — no decision is
made on the final day).
