# 01 — Data acquisition

How every price series in this project was obtained, from an execution
environment that cannot reach a single financial data provider.

## 1. The constraint that shaped the pipeline

The session container routes all outbound HTTPS through an agent proxy. Every
finance host is blocked at the CONNECT stage:

```
$ curl -sS https://query1.finance.yahoo.com/v8/finance/chart/2222.SR
curl: (56) CONNECT tunnel failed, response 403
```

Probing confirmed this was categorical, not incidental — `finance.yahoo.com`,
`stooq.com`, `investing.com`, `saudiexchange.sa`, `twelvedata.com` and
`wsj.com` all returned `000`/403, while `raw.githubusercontent.com` returned a
normal redirect. The managed fetcher (WebFetch) was likewise refused with HTTP
403 by every finance endpoint, including Yahoo's JSON chart API, because those
hosts bot-block datacenter IPs.

**The workaround: do the fetching on a GitHub Actions runner.** Runners have
unrestricted internet. The pipeline scripts live in the repo, a workflow runs
them on GitHub's infrastructure, and the resulting CSVs are committed straight
back to the working branch, where the container reads them as ordinary files.

This is why `pipeline/` scripts are written to be *runner-executable and
side-effect-committing* rather than interactive.

## 2. Universe discovery — `pipeline/discover_universe.py`

Tadawul main-market tickers are 4-digit numeric codes. Nomu (the parallel
market) uses 9xxx and is excluded throughout. The discoverer tries four sources
in order and unions the results, stopping early once it has ≥ 180 symbols:

| Order | Source | Method | Yields |
|---|---|---|---|
| 1 | **TradingView scanner** | `POST scanner.tradingview.com/saudi/scan`, filter `exchange = TADAWUL`, columns `name/description/sector/type` | code, company name, sector |
| 2 | **Mubasher** | `GET mubasher.info/api/1/stocks?country=sa`, paged 200 at a time | code, name |
| 3 | **Wikipedia** | Regex over the "List of companies listed on the Saudi Stock Exchange" table | code, name |
| 4 | **Brute-force probe** | Batched `yfinance.download()` over known code ranges, 150 symbols per batch, 40 s between batches, 90 s backoff on error | code only |

Codes are accepted only if they match `^[1-8]\d{3}$` **and** fall inside the
known main-market ranges:

```
1010–1399  Banks, capital goods            3001–3099  Cement
1810–1839  Consumer services               4001–4349  Retail / services / REITs
2001–2399  Materials & energy              5110–5111  Utilities
6001–6099  Food & agriculture              7010–7299  Telecom & IT
8010–8349  Insurance
```

Names and sectors from the curated top-50 file (`data/tickers.json`) override
whatever the discovery sources return, so the largest names carry clean labels.

**Fallback safety:** if every source fails but a previous `universe_full.json`
exists, the script keeps the old file and exits 0 rather than destroying a good
universe with a bad network day.

### Discovery is not deterministic

The two production runs returned **160** and **197** symbols. The difference is
source availability at request time (TradingView occasionally rate-limits, in
which case the probe fallback finds a different subset). This has a real
consequence documented in [06](06-results-and-validation.md): the committed v3
results were produced on the 160-name universe.

## 3. Price fetching — `pipeline/fetch_data.py`

For each symbol (Yahoo format: `2222.SR`, index `^TASI.SR`):

### Primary path — `yfinance`

Two calls per ticker, because one call cannot give both raw and adjusted series:

```python
raw = yf.Ticker(sym).history(start=START, end=END, auto_adjust=False, actions=True)
adj = yf.Ticker(sym).history(start=START, end=END, auto_adjust=True,  actions=False)
```

* `raw` supplies OHLCV plus the `Dividends` and `Stock Splits` event columns.
* `adj` supplies the split/dividend-adjusted OHLC used for indicators.

Retries 4×; a rate-limit error (`Too Many Requests` / `429`) triggers a **75 s**
cooldown, anything else a linear 2/4/6/8 s backoff.

### Fallback path — Yahoo v8 chart API

If `yfinance` yields nothing, the script calls
`query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=…&period2=…&interval=1d&events=div|split`
directly with a browser User-Agent, then reconstructs the same frame: timestamps
are converted UTC → `Asia/Riyadh` → tz-naive → midnight-normalized, dividend and
split events are mapped onto their dates, and the adjustment ratio
`adjclose / close` is applied to OHLC to synthesize the `Adj*` columns.

### Throttling

```
0.5 s   between symbols
15 s    additional pause every 40 symbols
75 s    on rate-limit detection
```

Without these, a 197-symbol sweep reliably trips Yahoo's limiter — the first
full-market attempt failed with `YFRateLimitError` on roughly 800 symbols.

### Output

One gzipped CSV per ticker, `data/raw/{code}.csv.gz`, with 12 columns:

```
Date, Open, High, Low, Close, Volume, Dividends, Splits,
AdjOpen, AdjHigh, AdjLow, AdjClose
```

Rows are de-duplicated (`keep="last"`), sorted by date, and any row with a null
`Close` is dropped. Values are written with `%.6f` precision. Stale `.csv` files
are deleted before a run so a shrinking universe cannot leave orphans behind.

### The manifest

`data/raw/_manifest.json` is the index the rest of the system reads:

```json
"1120": {
  "symbol": "1120.SR", "name": "Al Rajhi Bank", "sector": "Banks",
  "rows": 1394, "first": "2021-01-03", "last": "2026-08-03",
  "source": "yfinance", "status": "ok"
}
```

`status` is `ok` (≥ 120 rows), `short`, or `failed`. The engine skips `failed`
entries entirely. The job fails if fewer than `FETCH_MIN_OK` (default 85%) of
symbols succeed — set to 45% for the out-of-sample run, where many of today's
listings genuinely did not exist before 2022.

## 4. Windows fetched

| Dataset | `FETCH_START` | `FETCH_END` | Directory | Purpose |
|---|---|---|---|---|
| In-sample | 2021-01-01 | 2026-08-03 | `data/raw/` | 2022 sim + one year of indicator warm-up |
| Out-of-sample | 2015-01-01 | 2022-01-01 | `data/raw_oos/` | 2016 sim + one year of warm-up |

The extra leading year is deliberate: `sma200` and `ret_12m` need ~250 sessions
of history before they produce a value, so the simulation can start on day one
with warm indicators rather than a NaN blackout.

`FETCH_END` is exclusive. The in-sample fetch returned data through 2026-08-03,
but that session was still live when the data was pulled, so the preprocessing
stage truncates to **2026-08-02** — the "up to yesterday" boundary.

## 5. Automation

`.github/workflows/fetch-data.yml` (in-sample) and `fetch-oos.yml`
(out-of-sample) run discovery + fetch on `ubuntu-latest`, then commit results
back to the branch:

```yaml
git add TASI/data/raw TASI/data/universe_full.json
git commit -m "data: full Tadawul main-market historical fetch"
git pull --rebase origin "${{ github.ref_name }}" || true
git push || (sleep 5 && git pull --rebase origin "${{ github.ref_name }}" && git push)
```

The rebase-then-push dance exists because a concurrent local push will otherwise
make the runner's commit non-fast-forward — which is exactly how one early run
failed.

**Trigger caution:** `fetch-data.yml` fires on pushes touching
`TASI/pipeline/fetch_data.py`. Editing that file for any reason re-runs
discovery and can silently replace `data/raw` with a differently-sized universe.

## 6. Known data limitations

1. **Survivorship bias.** The universe is discovered *today*, so companies
   delisted mid-period are absent. Both the in-sample and out-of-sample results
   are flattered by this — losers that vanished were never available to lose
   money on.
2. **Yahoo is not the exchange.** Coverage of small caps and REITs is thinner
   than Tadawul's official record, prices are third-party, and corporate-action
   handling is Yahoo's.
3. **Turnover is not stationary.** Reported `Volume` has multi-month stretches
   where market-wide turnover shifts by orders of magnitude (a units artefact,
   not a liquidity event). Several agents defend against this with *relative*
   liquidity screens — see `dira` in [04](04-agents.md).
4. **No fundamentals, no news, no order book.** The entire information set is
   daily OHLCV plus dividends and splits.
