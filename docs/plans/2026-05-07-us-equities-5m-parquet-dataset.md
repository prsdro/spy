# US Equities 5-Minute Parquet Dataset Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a shareable, backtest-efficient market data lake for current active NASDAQ common stocks plus current S&P 500 names while keeping storage under 50% of remaining disk space on this server.

**Architecture:** Pull adjusted Massive/Polygon aggregate bars via REST, store 5-minute and daily bars as partitioned Parquet, and query directly with DuckDB. Keep corporate actions and ticker metadata as separate Parquet/CSV manifests. Do not store trades, quotes, or raw JSON.

**Tech Stack:** Massive/Polygon REST API, Python, pandas/pyarrow, DuckDB, partitioned Parquet, ZSTD compression, checksum manifests.

---

## Decisions

### Dataset scope

- Universe: current active NASDAQ common stocks (`type=CS`, `exchange=XNAS`) plus current S&P 500 constituents.
- Survivorship-bias policy: current stocks only. Do not reconstruct historical index membership.
- Bars: adjusted 5-minute OHLCV/VWAP/trade-count and adjusted daily OHLCV/VWAP/trade-count.
- Corporate actions: store splits and dividends as metadata.
- Exclusions: trades, quotes, options, raw JSON response archives, CSV as primary storage.

### Adjustment policy for ATR levels

Use `adjusted=true` aggregate bars from Massive/Polygon. This adjusts prices for stock splits. Store dividends separately but do **not** dividend-adjust OHLC bars.

Rationale:

- Saty-style ATR levels are based on previous close plus/minus Wilder ATR(14), where ATR is calculated from daily high/low/previous-close true range.
- TradingView-style stock charts and most intraday trading workflows commonly use split-adjusted, non-dividend-adjusted OHLC for stocks unless explicitly showing total-return series.
- Dividend-adjusting OHLC creates synthetic price gaps around ex-dividend dates that are not the traded chart price, which can distort intraday levels for discretionary/chart-based systems.
- Dividend metadata remains available for analysis filters, validation, and future total-return research, but ATR levels for execution/backtests should use split-adjusted price bars only.

Important validation rule discovered in the NVDA pilot: vendor daily bars can contain split-date anomalies even when `adjusted=true` is used. Example: NVDA daily bar on 2024-06-10 returned high `195.95`, while the 5-minute adjusted bars for that same date had max high `123.10`. Therefore:

- Store vendor daily bars for validation/reference.
- Build a canonical `daily_from_5m_rth` table from adjusted 5-minute regular-session bars for ATR calculations.
- Compare vendor daily vs `daily_from_5m_rth` and flag days where high/low/close diverge beyond tolerance.
- ATR levels for backtests should use the validated/canonical daily series, not blindly trust vendor daily bars.

### Storage guardrail

Current available disk on 2026-05-07:

```text
Available: ~354 GB
50% of available: ~177 GB
```

Rules:

- Target final dataset: <100 GB.
- Soft stop: `/srv/market-data/massive/us_equities` >140 GB.
- Hard stop: >160 GB.
- Never exceed 177 GB without explicit approval.
- Delete temp files after each symbol/year succeeds.

### Layout

```text
/srv/market-data/massive/us_equities/
  README.md
  manifest/
    universe.csv
    coverage.csv
    ingestion_runs.jsonl
    checksums.sha256
    schema.md
  bars_5m_adjusted/
    year=YYYY/
      SYMBOL.parquet
  bars_1d_adjusted/
    year=YYYY/
      SYMBOL.parquet
  corporate_actions/
    splits.parquet
    dividends.parquet
  duckdb/
    market.duckdb
    views.sql
```

### Bar schema

```text
symbol: string
metric_ts_utc: timestamp[UTC]
metric_ts_et: timestamp or string
open: double
high: double
low: double
close: double
volume: double
vwap: double
transactions: int64
source: string, e.g. massive_rest
adjusted: bool
multiplier: int, 5 for 5m, 1 for daily
span: string, minute/day
```

## Task 1: Build NVDA pilot pull

**Objective:** Prove Massive REST adjusted 5-minute and daily bars can be written to compact Parquet and queried with DuckDB.

**Files:**

- Create: `/root/spy/scripts/pilot_nvda_5m_parquet.py`
- Output: `/srv/market-data/massive/us_equities_pilot/`

**Steps:**

1. Load `POLYGON_API_KEY` from `/root/spx-chart-app/.env`.
2. Pull NVDA adjusted 5-minute bars by year from first available date through latest complete trading day.
3. Pull NVDA adjusted daily bars for the same range.
4. Pull NVDA splits and dividends metadata.
5. Write Parquet with ZSTD compression.
6. Write a coverage manifest with row counts, first/last timestamp, and byte sizes.
7. Query with DuckDB:
   - count rows
   - min/max timestamps
   - recent daily ATR(14) sample
8. Confirm total pilot size.

## Task 2: Build universe manifest

**Objective:** Produce a deterministic universe list.

**Files:**

- Create: `/srv/market-data/massive/us_equities/manifest/universe.csv`

**Steps:**

1. Fetch active NASDAQ common stocks from Massive reference tickers.
2. Fetch/maintain current S&P 500 constituents from a stable source.
3. Normalize tickers for Massive symbol conventions.
4. Deduplicate.
5. Mark source flags: `in_nasdaq`, `in_sp500`.
6. Keep all S&P 500 names even if liquidity filters are later applied.

## Task 3: Implement restartable ingestion

**Objective:** Pull the full universe safely without exceeding disk limits.

**Steps:**

1. Iterate `symbol -> year`.
2. Before each symbol/year, check dataset directory size and free disk.
3. Pull 5-minute adjusted bars using `adjusted=true`.
4. Pull daily adjusted bars using `adjusted=true`.
5. Write directly to Parquet.
6. Update `coverage.csv` after each successful symbol/year.
7. Retry transient `429`/`5xx` with exponential backoff.
8. Record permanent failures without stopping the full run.

## Task 4: Add DuckDB views and sample backtest queries

**Objective:** Make the dataset easy to query for internal backtests and external users.

**Files:**

- Create: `/srv/market-data/massive/us_equities/duckdb/views.sql`
- Create: `/srv/market-data/massive/us_equities/README.md`

**Views:**

```sql
CREATE OR REPLACE VIEW bars_5m_adjusted AS
SELECT * FROM read_parquet('/srv/market-data/massive/us_equities/bars_5m_adjusted/year=*/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW bars_1d_adjusted AS
SELECT * FROM read_parquet('/srv/market-data/massive/us_equities/bars_1d_adjusted/year=*/*.parquet', hive_partitioning=true);
```

Sample ATR query:

```sql
WITH daily AS (
  SELECT
    symbol,
    metric_ts_utc::DATE AS d,
    high,
    low,
    close,
    lag(close) OVER (PARTITION BY symbol ORDER BY metric_ts_utc) AS prev_close
  FROM bars_1d_adjusted
  WHERE symbol = 'NVDA'
), tr AS (
  SELECT *, greatest(high-low, abs(high-prev_close), abs(low-prev_close)) AS true_range
  FROM daily
)
SELECT * FROM tr ORDER BY d DESC LIMIT 20;
```

## Task 5: Package for sharing

**Objective:** Create shareable artifacts without making one fragile monster archive.

**Steps:**

1. Create one archive per year for 5-minute bars: `bars_5m_adjusted_YYYY.tar.zst`.
2. Create one archive for daily bars and metadata.
3. Generate `checksums.sha256`.
4. Include `README.md`, `schema.md`, `coverage.csv`, and sample queries.
5. Publish via token-gated static download only after local checksum verification.

## Cutdown policy if storage trends too high

Cut in this order:

1. NASDAQ names with very low median daily dollar volume.
2. Recent IPOs with short histories and low liquidity.
3. Non-core edge-case symbols that pass `type=CS` but have sparse or irregular data.

Never cut current S&P 500 names without explicit approval.
