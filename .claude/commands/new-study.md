---
description: Create a new backtest study for the Saty indicator system on SPY data
argument-hint: [study description]
---

# New Study: Saty Indicator Backtest

Create a new backtest study based on the user's description: **$ARGUMENTS**

---

## Project Context

This project analyzes 25 years of SPY data (Jan 2000 -- Oct 2025) using three indicators by Saty Mahajan. The database, scripts, and existing studies are in this repo's root directory.

### Read these files before starting:

1. Read `KNOWLEDGE.md` for indicator definitions, validated backtest results, implementation notes, and database schema.
2. Read `backtest_atr_probabilities.py` as a reference for how existing backtests are structured.
3. Read `backtest_gg_with_po.py` as a reference for cross-indicator studies (conditioning one indicator on another).

---

## Database: `spy.db` (SQLite)

If `spy.db` does not exist yet, tell the user to run `python3 ingest.py && python3 indicators.py` first.

### Candle Tables (raw OHLCV)

| Table | Rows | Description |
|-------|------|-------------|
| `candles_1m` | 4.5M | 1-minute bars, all hours (4am–8pm ET), NOT cleaned |
| `candles_3m` | 1.7M | 3-minute bars, all hours excluding 20:00 |
| `candles_10m` | 540K | 10-minute bars, all hours excluding 20:00 |
| `candles_1h` | 94K | Hourly bars, 4am–7pm ET (excluding 20:00 to match TradingView) |
| `candles_4h` | 25K | 4-hour bars |
| `candles_1d` | 6.5K | Daily bars, **RTH only** (9:30am–4pm), bad ticks clipped at 2% |
| `candles_1w` | 1.3K | Weekly bars, RTH only, bad ticks clipped |

Columns for all candle tables: `timestamp, open, high, low, close, volume`

### Indicator Tables (OHLCV + all indicator columns)

| Table | Description |
|-------|-------------|
| `ind_1m` through `ind_1w` | Same timeframes as candle tables, with 56 columns |

**Pivot Ribbon columns** (computed on the table's own timeframe):
- `ema_8, ema_13, ema_21, ema_48, ema_200` — EMA values
- `fast_cloud_bullish` — 1 if EMA8 >= EMA21
- `slow_cloud_bullish` — 1 if EMA13 >= EMA48
- `pivot_bias_bullish` — 1 if EMA8 >= EMA21
- `longterm_bias_bullish` — 1 if EMA21 >= EMA200
- `conviction_bull, conviction_bear` — 1 on the bar where EMA13/EMA48 cross
- `compression` — 1 when BB squeeze is active (BB width < 2×ATR)
- `candle_bias` — 1=bull up, 2=bearish up (orange), 3=bullish down (blue), 4=bear down, 5=compress up, 6=compress down

**ATR Levels columns** (daily reference for intraday tables, own-timeframe for daily/weekly):
- `atr_14` — ATR(14) using Wilder's RMA
- `prev_close` — Previous period close
- `atr_upper_trigger, atr_lower_trigger` — ±23.6% of ATR from prev_close
- `atr_upper_0382, atr_lower_0382` — ±38.2% (Golden Gate entry)
- `atr_upper_050, atr_lower_050` — ±50%
- `atr_upper_0618, atr_lower_0618` — ±61.8% (Golden Gate exit / Midrange)
- `atr_upper_0786, atr_lower_0786` — ±78.6%
- `atr_upper_100, atr_lower_100` — ±100% (full ATR)
- `atr_upper_1236` through `atr_upper_200` — Extension levels
- `atr_trend` — 1=bullish (price>=EMA8>=EMA21>=EMA34), -1=bearish, 0=neutral
- `range_pct_of_atr` — Current bar range as % of ATR

**Phase Oscillator columns** (computed on the table's own timeframe):
- `phase_oscillator` — The oscillator value: `EMA(((close - EMA21) / (3 * ATR14)) * 100, 3)`
- `phase_zone` — One of: extended_up, distribution, neutral_up, neutral, neutral_down, accumulation, extended_down
- `leaving_accumulation` — 1 when oscillator crosses above -61.8
- `leaving_distribution` — 1 when oscillator crosses below +61.8
- `leaving_extreme_down` — 1 when oscillator crosses above -100
- `leaving_extreme_up` — 1 when oscillator crosses below +100
- `po_compression` — 1 when BB squeeze is active (same logic as Pivot Ribbon compression)

---

## Indicator System Terminology

### Saty ATR Levels (Day Mode)
The ATR Levels indicator plots Fibonacci-scaled support/resistance zones around the previous day's close, using the daily 14-period ATR (Wilder's RMA).

- **Trigger** (±23.6%): Entry signal level. "Calls above upper trigger, puts below lower."
- **Golden Gate** (38.2% to 61.8%): The key completion zone. Entry at 38.2%, completion at 61.8%.
- **Midrange** (±61.8%): The exit of the Golden Gate.
- **Full ATR** (±100%): A full ATR move from the previous close — only happens ~14% of days.
- **Extensions** (±123.6% through ±300%): Extreme move levels.

Trading modes (which timeframe the ATR references):
- Day = Daily ATR, Multiday = Weekly, Swing = Monthly, Position = Quarterly, Long-term = Yearly

### Saty Pivot Ribbon Pro
A multi-layer EMA cloud system:
- **Fast Cloud**: EMA8/EMA21 — green=bullish, red=bearish
- **Slow Cloud**: EMA13/EMA48 — blue=bullish, orange=bearish
- **Conviction Arrows**: EMA13/EMA48 crossover signals
- **Candle Bias**: Colors candles based on position relative to EMA48
- **Compression**: BB squeeze detection (BB width < 2×ATR)

### Saty Phase Oscillator
A range-normalized momentum oscillator measuring deviation from the 21-period mean:
- **Formula**: `EMA(((close - EMA21) / (3 * ATR14)) * 100, 3)`
- **Zones**: Extended Up (>100), Distribution (61.8–100), Neutral Up (23.6–61.8), Neutral (±23.6), Neutral Down (-23.6 to -61.8), Accumulation (-61.8 to -100), Extended Down (<-100)
- **Mean reversion signals**: Yellow circles when oscillator crosses back from extremes

---

## How to Write a Study

### Step 1: Define the hypothesis
State clearly what you're testing. Example: "Does the Phase Oscillator zone at the time of Golden Gate entry predict completion rate?"

### Step 2: Write the analysis script
Save to `backtest_<study_name>.py` in the project root. Follow the pattern in existing scripts:

```python
import os, sqlite3, pandas as pd, numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
conn = sqlite3.connect(DB_PATH)

# Load the appropriate indicator table
df = pd.read_sql_query("SELECT * FROM ind_10m ORDER BY timestamp", conn, parse_dates=["timestamp"])
df = df.set_index("timestamp").sort_index()

# Filter to RTH for day-trading studies
df = df.between_time("09:30", "15:59")
df = df.dropna(subset=["prev_close", "atr_14"])
df["date"] = df.index.date

# Group by day, iterate, compute stats
for date, group in df.groupby("date"):
    first = group.iloc[0]
    # Access ATR levels: first["atr_upper_0382"], first["atr_lower_0618"], etc.
    # Access indicators: group["phase_oscillator"], group["ema_21"], etc.
    # ... your analysis logic ...
```

**Key patterns:**
- Use `ind_10m` for intraday studies (best balance of resolution and data quality)
- Use `ind_1d` for daily/swing studies
- ATR levels are constant within a day (daily reference) — use `first = group.iloc[0]` to get them
- Phase Oscillator and EMAs change every bar
- For cross-timeframe studies (e.g., 60m PO with 10m entries), use `pd.merge_asof()`:

```python
df60 = pd.read_sql_query("SELECT timestamp, phase_oscillator, compression FROM ind_1h ORDER BY timestamp", conn, parse_dates=["timestamp"])
merged = pd.merge_asof(df10.reset_index()[["timestamp"]], df60.reset_index(), on="timestamp", direction="backward")
df10["po_60m"] = merged["phase_oscillator"].values
```

### Step 3: Run and validate
Run the script, check the output makes sense. Compare against known results where possible.

### Step 4: Show results
Present the findings clearly with tables and key statistics. Ask the user if they want a visualization page built.

### Step 5: Update KNOWLEDGE.md
Add findings to the Analysis section of `KNOWLEDGE.md`.

---

## Existing Studies

| Study | Description | Script |
|-------|-------------|--------|
| Level-to-Level Probabilities | ATR level cascade probabilities | `backtest_atr_probabilities.py` |
| Bilbo Golden Gate | GG conditioned on 60m Phase Oscillator | `backtest_gg_with_po.py` |
| Call Trigger Confirmation | 3-min close above trigger hit rates | `backtest_call_trigger_confirmation.py` |
| Compression Expansion | 10m squeeze release patterns | `backtest_compression_expansion.py` |
| Trigger Box | Open inside trigger box outcomes | `backtest_trigger_box.py` |
| Trigger Box Spreads | Credit spread win rates from box | `backtest_trigger_box_spreads.py` |
| Gap Fill | Midpoint fill probability by gap size | `backtest_gap_fill_cumulative.py` |
| GG Entries | Entry optimization (immediate vs pullback) | `backtest_gg_entries.py` |
| GG Invalidation | Trigger break as stop level | `backtest_gg_invalidation.py` |
| Multi-Day GG | Weekly ATR Golden Gate | `backtest_multiday_gg.py` |
| Swing GG | Monthly ATR Golden Gate | `backtest_swing_gg.py` |
| EMA21 Reversion | Price deviation from daily 21 EMA | `backtest_ema21_reversion.py` |
| VIX Expiration | VIX expiration day patterns | `backtest_vix_expiration.py` |

See `analyst/studies_reference.md` for the complete results catalog.

---

## Common Pitfalls

1. **Golden Gate is 38.2% → 61.8%**, not trigger → 38.2%. The trigger (23.6%) is a separate level.
2. **ATR levels are constant within a day** on intraday tables (daily reference). Don't recompute per bar.
3. **Use RTH hours (9:30–15:59) for day-trading studies.** Extended hours data has different characteristics.
4. **Phase Oscillator on hourly bars** has known accuracy limitations due to extended-hours ATR inflation. Use 10-minute PO or 60-minute PO (with full history warmup) for best accuracy.
5. **Bad tick data exists** in the raw 1-minute data. Daily/weekly candles are clipped, but intraday candles are not. Be cautious with extreme values.
6. **Sample size matters.** Flag results with n < 50. Don't draw conclusions from n < 20.
7. **The `candles_1m` table is NOT filtered** — it contains all bars including 20:00. The aggregated tables (3m, 10m, 1h, etc.) exclude the 20:00 bar.

---

Now create the study described in the arguments. Start by reading KNOWLEDGE.md, then write the analysis script, run it, show results, and ask the user if they want a visualization page built.
