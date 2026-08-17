# 01 — Data & the AAOIFI screen

## Universe discovery

`pipeline/discover_universe.py`, run on a GitHub Actions runner (the session
container has no access to financial hosts — same constraint and same
workaround as the TASI experiment, see `TASI/docs/01`).

* **Primary:** NASDAQ's own screener API (`api.nasdaq.com/api/screener/stocks`,
  one call) — symbol, name, market cap, sector, industry for every listing.
* **Fallback:** the `nasdaqtrader.com` symbol directory + batched yfinance
  market caps.
* Filters: common-stock symbols only (`^[A-Z]{1,5}$`; no warrants/rights/units,
  no test issues, no ETFs), market cap > 0.
* Kept: **top 500 by market cap** → `data/universe_top.json`.

## The AAOIFI screen — `pipeline/sharia_screen.py`

Reference: **AAOIFI Shari'ah Standard No. 21**. Two layers, both must pass.

### 1. Business-activity screen

The core business must not be prohibited. Implemented as a curated keyword
screen over the screener's sector/industry labels (supplemented by yfinance's
classification), catching: conventional banking and insurance, interest-based
finance (brokers, consumer lenders, mortgage, credit services, asset managers),
REITs, SPAC shells, alcohol, tobacco, recreational cannabis, gambling
(casinos/lotteries/betting — **not** video games), pork, and adult
entertainment. Defense is not excluded (AAOIFI does not prohibit it).

### 2. Financial-ratio screen

Using current yfinance fundamentals (`totalDebt`, `totalCash`, `marketCap`):

| Rule | Threshold |
|---|---|
| Interest-bearing debt / market cap | **< 30%** |
| Cash + interest-bearing securities / market cap | **< 30%** |
| Impermissible income / revenue | < 5% — **not computable from free data**; proxied by the business screen |

Names missing debt data are rejected rather than assumed compliant.

### Results

**500 screened → 327 passed, 173 rejected.** Rejection reasons: interest-based
finance (55), conventional banking (40), debt ratio ≥ 30% (25), REITs (14),
cash ratio ≥ 30% (13), no debt data (9), insurance (9), gambling (5), and the
remainder alcohol/tobacco/other. Largest passers: NVDA, AAPL, GOOGL, MSFT,
AMZN, AVGO, META, TSLA — consistent with commercial AAOIFI screens.

### Honest limitations

1. **Point-in-time violation.** Fundamentals are today's snapshot; compliance
   is held constant across all history. A company that was over-leveraged in
   2018 but deleveraged by 2026 appears compliant throughout.
2. **The 5% rule is proxied**, not measured. A production screen needs
   income-statement lines and periodic scholar review.
3. **Cash ratio is conservative** — `totalCash` includes non-interest-bearing
   operating cash, so we over-exclude.
4. **Survivorship bias** — today's listings only; both backtest windows are
   inflated by the absence of the era's failures.

## The two-stage fetch and split integrity

The single most important design decision in this experiment:

* **Stage 1** (`fetch-data` step of `nasdaq-data.yml`): 2015-01-01 → 2023-01-01
  into `data/raw_is/`. 2015 exists only to warm up the 200-day indicators. The
  agent authors worked against `data/enriched_is/` — **the out-of-sample years
  were not present in the repository in any form**.
* **Freeze**: the five strategy files were committed
  (`7e8cdf12f1a63e6e23f691ff1f01e580ca946acf`) after a fairness audit (zero
  hardcoded dates, zero ticker literals).
* **Stage 2** (`nasdaq-oos.yml`, pushed only after the freeze): 2015-01-01 →
  today into `data/raw_full/`. The out-of-sample run starts 2023-01-03 with
  indicators warmed on the overlap.

The authors' *general* market knowledge (their training data includes NASDAQ
history) cannot be erased — but no author queried, tested against, or observed
a single 2023+ price from this repository before freezing. Parameter tuning is
therefore cleanly in-sample, which was exactly the failure mode the TASI
walk-back exposed.

Per-ticker format, manifest, and gzip conventions are identical to the TASI
pipeline (`TASI/docs/01`, `02`); the indicator set is identical with two
changes: 252-day annualization and `rs_bench_3m` (relative strength vs the
Composite) replacing `rs_tasi_3m`.
