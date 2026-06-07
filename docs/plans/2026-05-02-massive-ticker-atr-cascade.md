# ATR Cascade Generalization -- Implementation Plan

## 1. Assumptions

- **Massive flat files** (Polygon-style minute aggregate dumps) are already on disk; nothing is fetched at runtime. Expected layout, configurable via env/flag (default below):
  - Per-day all-ticker minute aggregates: `data/massive/us_stocks_sip/minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
  - Per-day all-ticker daily aggregates: `data/massive/us_stocks_sip/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz`
  - Splits reference: `data/massive/reference/splits.csv` (or `.csv.gz`) -- columns `ticker, execution_date, split_from, split_to`.
- Schema (Massive minute/day flat files, validated empirically before first run): `ticker, volume, open, close, high, low, window_start, transactions` where `window_start` is a **UNIX nanosecond, period-start, UTC** timestamp.
- Flat files are **not split-adjusted** (raw tape). Pipeline must apply backward split adjustment.
- Tickers covered are common-share US equities and ETFs that Massive provides (SPY/QQQ/AAPL/etc.). Index tickers (SPX/NDX/VIX) are *not* in equity flat files -- they remain on the existing FirstRateData path.
- Nothing in this pipeline talks to a network or uses keys.
- Output schema and analysis math (LADDER, REPORT_LABELS, hour buckets, GG retrace, adjacent walk) are reused unmodified from `backtest_atr_cascade.py`.

## 2. Architecture

A small loader package + one generic backtest entry point. The existing SPY/SPX scripts stay untouched (regression baseline) and are re-implemented as thin wrappers later.

```
massive_pipeline/
  __init__.py
  flat_files.py       # discovery + chunked reading of minute/day flat files for one ticker
  splits.py           # split table loader + backward adjustment factor
  bars.py             # UTC -> America/New_York, RTH filter, 1m -> 3m aggregation
  atr.py              # Wilder/RMA ATR(14), shifted prev-close/prev-ATR, ladder build
  ticker_dataset.py   # build_ticker_3m(ticker) -> (df_3m_with_ladder, diag) -- the unified API
backtest_atr_cascade_generic.py  # CLI: --ticker XYZ [--start ... --end ...]
tests/
  test_splits.py
  test_atr.py
  test_bars.py
  test_pipeline_smoke.py
```

The generic backtest imports `analyse_day`, `analyse_adjacent_walk`, `analyse_gg_retrace_case`, `aggregate`, `aggregate_gg_retrace`, `build_json_payload`, `print_overall`, `print_by_hour_for_level`, `LADDER`, `LABELS`, `COLUMNS`, `REPORT_LABELS` from the existing `backtest_atr_cascade.py`. No fork of the analysis math.

Outputs:
- `analyst/atr_cascade_<TICKER>_table.csv`
- `site/data/atr-cascade-<ticker>.json` (lower-cased ticker; same payload schema as SPX path, with `metadata.symbol = TICKER` and `loader_diagnostics`).

## 3. Tasks

### 3.1 `massive_pipeline/flat_files.py`
- `discover_minute_files(root, start_date, end_date)` and `discover_day_files(...)`: glob `YYYY/MM/YYYY-MM-DD.csv.gz` between bounds.
- `read_ticker_minute(files, ticker) -> pd.DataFrame` and `read_ticker_day(files, ticker) -> pd.DataFrame`:
  - Stream each gz file with `pd.read_csv(..., usecols=["ticker","open","high","low","close","volume","window_start"], dtype={...})`, filter to `ticker == ticker` upfront, concat.
  - Convert `window_start` (ns UTC) → `pd.Timestamp(tz="UTC")` → `tz_convert("America/New_York")` → `tz_localize(None)`. Match the existing SPY DB convention (naive ET).
  - Return columns `timestamp, open, high, low, close, volume`, sorted, deduped on `timestamp`.
- Use `ProcessPoolExecutor` (small N workers) to parallelize the per-day reads -- each day file can be tens of millions of rows pre-filter; we only keep the ticker's ~390 minute rows.

### 3.2 `massive_pipeline/splits.py`
- `load_splits(path, ticker) -> pd.DataFrame[execution_date, ratio]` where `ratio = split_to / split_from` (e.g. 4-for-1 → 4.0).
- `build_adjustment_table(splits, all_dates) -> pd.Series` indexed by date:
  - For each date `d`, factor = ∏ `ratio` for splits with `execution_date > d` (i.e. only future splits, applied retroactively).
  - All dates ≥ most-recent split → factor = 1.0.
- `apply_split_adjustment(df, factor_by_date)`:
  - For OHLC: `price_adj = price / factor`.
  - For volume: `vol_adj = vol * factor`.
  - Apply on **both daily and minute frames using the same factor table keyed on the bar's session date**. The minute frame's session date is its ET calendar date (post tz conversion), which makes adjustment idempotent across timeframes.
- Single source of truth: ATR is computed **after** split adjustment so historical TR is in today's price scale.

### 3.3 `massive_pipeline/bars.py`
- `to_rth_3m(df_1m_et) -> df_3m`: identical logic to `aggregate_1m_to_3m` in the SPX script -- `between_time("09:30","15:59")`, group by date, `resample("3min", origin="start_day", offset="9h30min")`, drop empty, `between_time("09:30","15:57")`. Encapsulated so SPY/SPX/generic share the same canonical bar definition.
- Half-day calendar: keep the same `09:30..15:57` filter; truncated 1-pm closes naturally produce fewer bars per day. Do not special-case (matches existing scripts).

### 3.4 `massive_pipeline/atr.py`
- `wilder_atr(daily_df, period=14)`: copy verbatim from the SPX script (`atr_series` + `rma`).
- `attach_levels(df_3m, daily_df) -> df_3m_with_ladder`:
  - On daily frame: `prev_close = close.shift(1)`, `atr_14_prev = wilder_atr(daily).shift(1)`. The shift enforces "today's levels use only prior completed sessions" -- this is the Saty invariant.
  - Join by session date onto the 3m frame, drop rows missing either.
  - Build all `LADDER` columns: `df[col] = prev_close + mult * atr_14_prev` for each `(label, col, mult)` in `LADDER` (skipping `prev_close`, which already exists).
  - Returned frame has the exact column set `analyse_day` expects: `open, high, low, close, prev_close, atr_14`, all 27 ladder columns (incl. ±2.236 sentinels), and `date`.

### 3.5 `massive_pipeline/ticker_dataset.py`
- `build_ticker_3m(ticker, start=None, end=None, root=...) -> (df, diag)`:
  1. Discover minute + day files in range.
  2. Read & concat raw frames for ticker.
  3. Load splits, apply backward adjustment to **both** frames.
  4. RTH-filter + 1m→3m aggregate via `bars.to_rth_3m`.
  5. Compute Wilder ATR(14) on adjusted daily, shift, attach ladder via `atr.attach_levels`.
  6. Build `diag` dict mirroring the SPX `diag` shape: symbol, source_vendor=`Massive flat files`, source description, intraday + daily date ranges, row counts, bars_per_day stats, `splits_applied: [...]`, `adjustment_factor_first_bar`, `adjustment_factor_last_bar`.

### 3.6 `backtest_atr_cascade_generic.py`
- CLI: `--ticker <SYM>` (required), `--start YYYY-MM-DD`, `--end YYYY-MM-DD`, `--massive-root path` (default `data/massive`), `--splits path` (default `<root>/reference/splits.csv`), `--out-csv`, `--out-json`.
- Calls `build_ticker_3m`, then runs the same loop the SPX script runs (`analyse_day` / `analyse_adjacent_walk` / `analyse_gg_retrace_case`), `aggregate`, `aggregate_gg_retrace`, `build_json_payload`. Writes CSV + JSON with ticker-suffixed paths.
- Stamps `metadata.symbol`, `metadata.source = "Massive flat files (split-adjusted)"`, `metadata.loader_diagnostics = diag`.

### 3.7 Refactor opportunity (low-risk, explicit)
- Move `aggregate_1m_to_3m` from `backtest_atr_cascade_spx_firstrate.py` into `massive_pipeline/bars.py` and have the SPX script import it. Same for `rma`/`atr_series` → `massive_pipeline/atr.py`. This collapses three implementations of the canonical bar/ATR into one. Keep behaviour bit-identical and validate with the SPX regression test below.

## 4. Tests

All under `tests/`, using `pytest`. Synthetic fixtures, no network.

- `test_splits.py`
  - 2-for-1 split on day D applied to a 4-row daily frame → all dates < D have prices halved and volumes doubled; ≥ D unchanged.
  - Compounded splits (2-for-1 then 3-for-1) → factor at oldest date is 6.
  - Reverse split (1-for-10) → ratio = 0.1, prices *multiplied* by 10 historically.
  - Idempotent: applying twice with factor=1 (no future splits) is a no-op.
- `test_atr.py`
  - Wilder ATR matches a hand-computed reference vector (use the same 30-row synthetic series referenced in any existing ATR study; otherwise compute ATR by hand for ~20 rows).
  - `atr_14_prev[d]` equals `wilder_atr(daily)[d-1]` for all d (shift invariant).
  - Splits applied **before** ATR vs ATR computed **then** scaled → first path is correct, second path drifts. Test asserts the first.
- `test_bars.py`
  - Synthetic 1-minute frame across one RTH day produces exactly 130 three-minute bars labeled 09:30..15:57.
  - Half-day (early close 13:00) produces 70 bars labeled 09:30..12:57.
  - Pre/post-market 1m bars are dropped.
  - DST boundary day (March / November) yields 130 RTH bars (catches tz-conversion bugs).
- `test_pipeline_smoke.py`
  - Build a tiny synthetic Massive-shaped flat-file tree on `tmp_path` for ticker FAKE: 5 trading days of minute + daily aggregates, one split mid-range. Run `build_ticker_3m("FAKE")`. Assert: row counts, all ladder columns present and non-null where ATR is defined, prev_close on day d equals daily close on d-1 (post-adjustment).
- **Regression parity** (the most important test): re-run `backtest_atr_cascade_spx_firstrate.py` after refactor 3.7 and byte-compare the resulting `site/data/atr-cascade-spx.json` against the pre-refactor copy. Any diff is a bug in the move.

## 5. Verification

Run, in order:

1. `pytest tests/` -- green.
2. SPX regression: `python backtest_atr_cascade_spx_firstrate.py`, diff `site/data/atr-cascade-spx.json` against the committed baseline. Must be byte-identical.
3. SPY sanity (optional but cheap): produce `atr-cascade-spy-massive.json` from Massive flat files via the generic pipeline, then diff its `cells` block against the existing `atr-cascade.json` (DB-driven SPY). Differences should be bounded -- vendor seam (Massive vs Massive-derived DB) and any post-2025-10-22 freshness gap. Document expected delta; flag anything beyond a few tenths of a percent on `p_beyond` per cell as a real regression.
4. New ticker smoke: pick a ticker with a known split (e.g. NVDA 10-for-1 on 2024-06-10 -- verify date against the splits flat file before running). Spot-check: prev_close for 2024-06-11 ≈ adjusted prior session close; ATR ladder spacing for early-2020 bars is in tens-of-cents on adjusted scale, not hundreds.
5. Diagnostics block in the JSON payload includes `splits_applied` with each `(execution_date, ratio)` and the cumulative factor at the oldest bar.
6. Bar-count distribution: `bars_per_day_median == 130`, `full_130_bar_days / total_days > 0.9` outside half-days. Half-days appear with 70 bars.
7. Manual visual: render the existing `site/atr-cascade.html` against the new ticker's JSON (page is parameterized by `metadata.symbol`/data file name, or wire one up if not). Don't ship a new HTML page in this plan -- that is a follow-up.

## 6. Split-adjustment invariants and pitfalls

Invariants the pipeline must hold (each backed by a test):

- **I1** Adjustment is applied **before** ATR. ATR computed on raw then scaled gives a wrong answer because the daily TR straddling a split bar would otherwise be ~50% of the bar's true magnitude; backwards adjustment on the price level fixes both the bar and the prior close used in TR.
- **I2** Same factor table for daily and minute frames. Otherwise a 09:30 minute bar and the daily bar of the same session disagree, causing PDC ≠ daily close.
- **I3** Backward-only application: for any session ≥ most-recent split, factor = 1.0; the present-day price scale is the canonical reference.
- **I4** Adjustment is applied to OHLC and volume only; **not** to ATR derived afterward (that is implicit because ATR is recomputed post-adjustment).
- **I5** Adjustment factor for a session is `∏ {ratio : execution_date > session_date}`. Splits are applied **strictly before** their execution date (the execution date itself trades on the new scale).

Pitfalls:

- Massive `window_start` is **nanoseconds UTC**. Forgetting `unit="ns"` silently produces 1970 timestamps. Forgetting tz conversion shifts RTH by 4–5 hours and the ladder logic discards every day.
- DST: do not derive ET from a fixed UTC offset (the existing `fetch_massive.py` does an approximate offset -- do **not** copy that). Use IANA `America/New_York` via pandas `tz_convert`.
- Massive flat files include extended-hours minute bars. The `between_time("09:30","15:59")` RTH filter must run **after** ET conversion, not before.
- Daily flat files use `window_start` set to the session's start-of-day in UTC; converting to ET and taking `.dt.date` gives the correct session date for joining. Don't use UTC date -- it shifts ~30% of overnight sessions backward.
- Splits flat file dates are **execution date** (= the date the new shares trade). Off-by-one risk: a `>` comparison vs `>=` is the difference between an aligned and a one-day-shifted ATR ladder around every split. Fix the convention once in `splits.py` and assert it in tests.
- Reverse splits (ratio < 1) are real (e.g. failing tickers do them). The same `price / factor` formula handles them; assert the reverse-split test.
- Special distributions (spinoffs, special cash dividends) are **not** in the splits file and will leave residual gaps. Not in scope; document in the diagnostics block as `corporate_actions_applied: ["splits"]` so the limitation is explicit on the published page.
- Tickers that changed symbol (e.g. FB → META) won't reach back through the rename in Massive flat files. Document as a limitation; add a `--alias-history` flag only if a user actually requests it.
- Index tickers (SPX, NDX) are not in equity flat files. The generic CLI should fail fast with a clear message ("Index tickers are not available in Massive equity flat files; use the FirstRateData script") rather than silently producing an empty frame.
- Memory: a single day's all-ticker minute file can be 100M+ rows uncompressed. Always pre-filter on ticker during `read_csv` (PyArrow engine + `usecols` + push-down equality on `ticker` if available, else manual filter). Never `concat` raw all-ticker frames.
- Half-days: rely on natural bar count, not a hardcoded calendar. The existing scripts already handle this and the plan preserves it.

## 7. Out of scope (call out so it doesn't bleed in)

- A new HTML page per ticker, navigation, cheatsheet generation.
- Dividend adjustment.
- Live/incremental updates -- flat files are batch-only here.
- Refactoring `backtest_atr_cascade.py`'s analysis core. Imported as-is.