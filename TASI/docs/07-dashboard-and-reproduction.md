# 07 — Dashboard & reproduction

## 1. Dashboard architecture

Two files produce one self-contained artifact:

```
dashboard/template.html      shell: CSS, markup, all chart/table JS, no data
dashboard/build_dashboard.py injects a slimmed payload at /*__DATA__*/
     ↓
dashboard/index.html         ~1.1 MB, zero external requests
```

The output has **no CDN links, no external fonts, no fetch calls** — everything
including the data is inline, so it works offline, from a USB stick, or as an
email attachment.

### Payload slimming

`out/results.json` is 3.8 MB; the dashboard payload is ~1.1 MB. Three reductions:

| Field | Treatment |
|---|---|
| `trades` | Dicts → positional arrays `[date, code, side, shares, price, value, pnl, reason]`, reason truncated to 140 chars |
| `journal` | 1,143 entries → ≤ 160, scored by event-day proximity, sentiment swing size and note length, with regular-spacing fillers so the timeline stays continuous |
| `holdings_monthly` | Top 9 positions by value + an "other" bucket |

Equity, cash and sentiment arrays are kept at full daily resolution.

### Charts

All hand-rolled SVG — no charting library, which is what keeps the page
self-contained and the payload small.

| Section | Form | Interaction |
|---|---|---|
| Agent roster | Sparklines | Click to focus one agent everywhere |
| Superlatives | Award cards | — |
| Boring numbers | Full metric table | Sticky header/first column |
| Risk map | Scatter (CAGR vs vol) | Per-point tooltip, TASI reference rules |
| The race | Multi-line equity | Crosshair snapping to nearest session, all-series tooltip, log toggle, table twin |
| Drawdowns | Small multiples | One panel per agent |
| Monthly returns | Diverging heatmap | Cell tooltip, table twin |
| Sentiment | Diverging heatmap + field average | Cell tooltip |
| Journals | Timeline | Per-agent filter |
| Trade explorer | Paged table | Agent / side / sort filters |
| Letters | Accordion | — |

### Design system

Colors come from the validated `dataviz` categorical palette — eight hues whose
ordering was checked for colorblind separation (adjacent CVD ΔE ≥ 8 in OKLab,
normal-vision ΔE ≥ 15) against both light and dark surfaces:

```
blue #2a78d6/#3987e5   orange #eb6834/#d95926   aqua #1baf7a/#199e70
yellow #eda100/#c98500  magenta #e87ba4/#d55181  green #008300/#008300
violet #4a3aa7/#9085e9  red #e34948/#e66767
```

Theming is token-level: the palette is defined on `:root`, redefined under
`@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`,
and again under `:root[data-theme="dark"]` so the in-page toggle wins in both
directions. Every chart re-renders on theme change rather than relying on CSS
alone, because SVG fills are set from resolved token values.

Three colors in the light palette fall below 3:1 contrast on the light surface,
so the **relief rule** applies: every chart ships direct labels or a table twin,
and no value is reachable only by hovering.

## 2. Commands

All scripts resolve paths relative to `TASI/`, so they run from anywhere.

### Full rebuild

```bash
# 1. data (needs open internet — normally the GitHub Action)
python TASI/pipeline/discover_universe.py
python TASI/pipeline/fetch_data.py

# 2. indicators
python TASI/pipeline/indicators.py

# 3. simulation
python TASI/sim/run_sim.py

# 4. dossiers for the letter writers (optional)
python TASI/sim/commentary_brief.py

# 5. dashboard
python TASI/dashboard/build_dashboard.py
open TASI/dashboard/index.html
```

### Testing a single strategy

`run_sim.py` takes a strategy directory, so a candidate can be run alone.
`ctx["peers"]` is empty in that mode, which is the correct standalone check:

```bash
mkdir -p /tmp/solo && cp TASI/sim/strategies/raad.py /tmp/solo/
python TASI/sim/run_sim.py --strategies /tmp/solo --out /tmp/solo/results.json
```

### Out-of-sample run

```bash
IND_RAW_SUBDIR=data/raw_oos IND_OUT_SUBDIR=data/enriched_oos \
  IND_LAST_DATE=2021-12-31 python TASI/pipeline/indicators.py

SIM_ENRICHED_SUBDIR=data/enriched_oos SIM_RAW_SUBDIR=data/raw_oos \
  SIM_START=2016-01-01 python TASI/sim/run_sim.py --out TASI/out/results_oos.json
```

## 3. Environment variables

**All `*_SUBDIR` values are relative to `TASI/`, not the repository root.**
Prefixing them with `TASI/` produces `TASI/TASI/...` and fails.

| Variable | Default | Consumer |
|---|---|---|
| `FETCH_START` | `2021-01-01` | `fetch_data.py` |
| `FETCH_END` | `2026-08-03` (exclusive) | `fetch_data.py` |
| `FETCH_RAW_SUBDIR` | `data/raw` | `fetch_data.py` |
| `FETCH_MIN_OK` | `0.85` | `fetch_data.py` — job fails below this success fraction |
| `IND_RAW_SUBDIR` | `data/raw` | `indicators.py` |
| `IND_OUT_SUBDIR` | `data/enriched` | `indicators.py` |
| `IND_LAST_DATE` | `2026-08-02` | `indicators.py` — inclusive truncation |
| `SIM_ENRICHED_SUBDIR` | `data/enriched` | `engine.py` |
| `SIM_RAW_SUBDIR` | `data/raw` | `engine.py` — manifest location |
| `SIM_START` | `2022-01-01` | `engine.py` |

## 4. Adding an agent

1. Create `sim/strategies/<handle>.py` defining a module-level `STRATEGY`
   instance of a `Strategy` subclass (see `sim/strategy_base.py`).
2. `meta` must include `handle`, `name`, `emoji`, `tagline`, `character`,
   `risk_style`, `color`.
3. `decide()` must NaN-guard everything, stay deterministic (seed any
   randomness), use stdlib only, avoid file/network I/O, and run in a few
   milliseconds — it is called ~1,144 times per agent.
4. Self-test solo first (peers empty), then run the full arena.
5. The dashboard assigns colors by finishing order from the 8-slot palette; a
   9th agent reuses slot 1. If you exceed eight, fold the tail or extend the
   palette through the validator rather than inventing a hue.

## 5. Runtime

On the session container (no GPU, ordinary CPU):

| Stage | Time |
|---|---|
| Fetch 161 symbols (Actions runner) | ~17 min, discovery ~13 min of it |
| Indicators, 161 tickers | ~35 s |
| Simulation, 8 agents × 1,144 sessions | ~4–6 min |
| Dashboard build | ~5 s |

The engine's numpy-backed market store and per-date view cache exist because a
naïve pandas implementation was several times slower at this universe size.

## 6. Known caveats

1. **Universe drift** — `data/raw` (197 names) no longer matches the committed
   results (160 names). See [06 §4](06-results-and-validation.md#4-reproducibility-status).
2. **Workflow trigger sensitivity** — editing `pipeline/fetch_data.py` re-runs
   the fetch Action and can replace the dataset.
3. **`data/enriched*/` are git-ignored** — derived, regenerate with one command.
4. **The dashboard is a snapshot.** It embeds its data; there is no live
   refresh. Rebuild and republish to update.
5. **Artifacts are versioned by file path** — republishing the same scratchpad
   path updates the same URL; a new path mints a new one. v1, v2 and v3 each
   hold their own frozen URL.

## 7. Forward testing (not yet implemented)

The cleanest validation would be a scheduled workflow that:

1. Extends `data/raw` past 2026-08-02 monthly.
2. Re-runs the **frozen** v3 agents from 2026-08-03 forward.
3. Appends to a live out-of-sample leaderboard.

Everything needed is already parameterized (`SIM_START`, `FETCH_START/END`,
directory overrides); only the scheduled workflow and a results-append step are
missing. This is the only test that would eliminate every bias catalogued in
[06](06-results-and-validation.md).
