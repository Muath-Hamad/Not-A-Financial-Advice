# 02 — Engine & the back-propagation loop

`sim/engine.py` is the TASI v3 engine (see `TASI/docs/03` for order lifecycle,
corporate actions, halts, and the peer channel — all identical) with four
changes:

| Change | Value |
|---|---|
| Benchmark key | `IXIC` (NASDAQ Composite) |
| Costs | commission `SIM_COMMISSION` = 2 bps, slippage `SIM_SLIPPAGE` = 5 bps per side (~14 bps round trip — US retail reality) |
| Default sim start | `SIM_START` = 2016-01-01 |
| **The adapt() loop** | `SIM_ADAPT_EVERY` = 63 sessions |

## The back-propagation protocol

"Back-propagation" here is the honest engineering version of the metaphor: a
**quarterly feedback loop that propagates realized error signals into bounded
parameter updates**, entirely deterministic and auditable — not a neural
network.

### What the engine computes

Every 63 sessions, after that day's decisions, the engine builds one feedback
packet per agent from its own realized history:

```python
{
  "date": iso, "window_sessions": 63,
  "window": {
    "ret", "bench_ret",          # own vs Composite over the window
    "sharpe",                    # annualized, window daily returns
    "max_dd",                    # within-window peak-to-trough
    "hit_rate", "profit_factor", # window's closed trades
    "n_sells", "turnover",       # traded value / avg equity
    "avg_exposure",              # 1 - mean(cash/equity)
  },
  "cumulative": {"equity", "ret", "dd_from_peak", "sessions"},
  "trades":  [window's sells: {code, realized_pnl, held_since, reason}],
  "peers":   current public books of the other agents,
}
```

Everything in the packet describes the **past**. The engine then calls
`strategy.adapt(feedback)`.

### What the agent must do with it

The contract (in `sim/strategy_base.py`) imposes four laws:

1. **Deterministic** — same inputs, same updates.
2. **Bounded** — every adaptable parameter is declared in
   `meta["param_space"] = {NAME: [lo, hi]}` and every update is clamped.
3. **Small steps** — gradient-descent-like nudges, never a jump to an extreme
   on one window's evidence.
4. **No lookahead** — adapt() sees the packet and nothing else.

The strategy mutates its own parameters and returns
`{"changes": {name: new_value}, "note": "one line of reasoning"}`. The engine
logs every event into `results.agents[*].adaptations`, so the dashboard can
show the complete parameter trail — an audit requirement, not decoration.

### Why the loop runs out-of-sample too

The adaptation machinery is **part of the frozen agent**. The TASI walk-back
showed that hand-tuned constants rot when the regime changes; the hypothesis
v4 tests is that an agent whose constants are *rules for updating constants*
degrades more gracefully. Freezing the code but letting its internal loop keep
running on unseen data is precisely the live-trading situation the elected
agent will face.

### Design patterns the authors converged on

Worth recording, since they amount to a small grammar of safe online tuning:

* **Error-signal → dial mappings**: hit-rate below target → widen stops;
  payoff ratio below target → widen trails; realized Sharpe strong and
  exposure low in a rising tape → raise exposure caps; window drawdown beyond
  threshold → cut risk budget.
* **Attribution-weighted signal blending**: record which momentum horizon (or
  factor sleeve) motivated each entry; every window, shift the blend weights a
  few percent toward whichever actually paid, then renormalize.
* **Mean-reversion to shipped defaults** (the standout anti-overfit device):
  before applying any gradient step, pull every parameter a few percent back
  toward its shipped value — so a long OOS run can drift but never ratchet
  into a corner, and a quiet market slowly restores the design baseline.
* **EMA smoothing of the error signals themselves**, so one violent window
  cannot whipsaw the parameters.

## Lightweight agent contract

No personas, no chat, no letters. `meta` carries `handle`, `name`, `style`
(one line), `risk_style`, `color` (dashboard overrides), `param_space`.
Journal notes are optional and sparse (regime shifts, adaptations, notable
exits). Everything else in the decide() contract — view columns, portfolio
snapshot, ctx, order formats, peers — is identical to TASI v3
(`TASI/docs/03 §5-6`).
