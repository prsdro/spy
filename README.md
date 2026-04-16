# Saty Indicator System — 25 Years of SPY Backtests

Quantitative trading research platform built around three indicators by [Saty Mahajan](https://x.com/SatyMahajan), applied to **25 years of S&P 500 (SPY) 1-minute data** (January 2000 — October 2025). Includes 26 backtesting studies, a SQLite database with precomputed indicators across 7 timeframes, and an interactive charting interface.

**All statistics are historical and have not been independently verified. This is research, not trading advice.**

---

## The Three Indicators

### 1. Saty ATR Levels
Fibonacci-scaled ATR bands above and below the previous period's close. Key levels:

| Level | Distance |
|-------|----------|
| Trigger | ±23.6% ATR |
| Golden Gate Entry | ±38.2% ATR |
| Golden Gate Completion | ±61.8% ATR |
| Full ATR | ±100% ATR |
| Extensions | ±123.6%, ±161.8%, ±200% |

### 2. Saty Pivot Ribbon Pro
Multi-layer EMA cloud system (8/13/21/48/200) showing trend structure, compression/expansion states, and conviction signals via 13/48 EMA crossovers.

### 3. Saty Phase Oscillator
Range-normalized momentum oscillator: `EMA(((price - EMA21) / (3 * ATR14)) * 100, 3)`. Zones: Extended Up (>100), Distribution (61.8–100), Neutral Up (23.6–61.8), Neutral (±23.6), Neutral Down, Accumulation (-100 to -61.8), Extended Down (<-100).

See [KNOWLEDGE.md](KNOWLEDGE.md) for full indicator documentation and implementation details.

---

## Key Findings (26 Studies)

### Level-to-Level Probabilities
Each hop is high probability, but cumulative full-ATR moves are rare:
- Close → Trigger: **80%** | Trigger → 38.2%: **80%** | 38.2% → 61.8%: **69%** | 61.8% → 78.6%: **60%** | 78.6% → 100%: **55%**
- Close → Full ATR (cumulative): only **14%**

### Bilbo Golden Gate (1h Phase Oscillator filter)
The 60-minute PO is 5–12x more predictive than the 10-minute for GG completion:
- **Bull GG + PO High+Rising: 77.7%** (n=372) vs 63% baseline
- **Bear GG + PO Low+Falling: 90.2%** (n=265) vs 65% baseline

### Call Trigger Confirmation (3-min bars)
- Overall hit rate: **73.8%** (n=2,027)
- Clean run (no invalidation): **97.1%** — the strongest edge in the system
- Invalidation filter adds **+37.6 percentage points**
- Median time to target: **18 minutes**

### Trigger Box Credit Spreads
When price opens inside the trigger box and holds:
- Sell calls from bearish box, held 1hr: **93.6% win** at ±61.8%, **98.7% win** at ±100%
- Sell puts from bullish box, held 1hr: **92.0% win** at ±61.8%, **97.5% win** at ±100%

### 10-Minute Compression → Expansion
- Expansion direction correct **91%** of the time
- EMA 21/48 trend predicts direction: **84% accuracy** at 180+ min compression duration
- Longer squeezes produce bigger moves (0.68% avg profit at 180+ min vs 0.61% at 30–50 min)

### GG Timing (Subway)
- Open triggers: **~90% completion** | 15:00 bull triggers: **9%** | 15:00 bear: **37%**
- Bearish GGs complete more reliably at every time of day

### Multi-Day & Swing GG
- **Weekly ATR Bear Bilbo: 94% day-1 completion** (n=54) — strongest signal across all studies
- Monthly ATR moves take weeks; bearish is 3x faster than bullish on day 1

See [analyst/studies_reference.md](analyst/studies_reference.md) for the complete study catalog with all statistics.

---

## Repository Structure

```
├── Data
│   ├── spy_contents/spy/          # 312 monthly CSV files, 1-minute candles (2000–2025)
│   ├── spy_contents/AMEX_SPY, *.csv  # Aggregated 10m and 60m data
│   ├── AMEX_SPY, 60 (1-8).csv    # TradingView hourly exports with extended history
│   └── *.json                     # Precomputed study results
│
├── Backtests (26 studies)
│   ├── backtest_atr_probabilities.py
│   ├── backtest_call_trigger_confirmation.py
│   ├── backtest_compression_expansion.py
│   ├── backtest_gg_*.py           # Golden Gate studies (entries, invalidation, chop, PO filter)
│   ├── backtest_gap_*.py          # Gap fill studies
│   ├── backtest_po_sustained_*.py # Phase Oscillator studies
│   ├── backtest_trigger_box*.py   # Trigger box & credit spread studies
│   ├── backtest_ema21_reversion*.py
│   ├── backtest_multiday_*.py     # Weekly/monthly ATR studies
│   ├── backtest_premarket_ath.py
│   ├── backtest_vix_expiration.py
│   ├── backtest_vomy.py
│   └── backtest_swing_gg.py
│
├── Core
│   ├── indicators.py              # Compute all indicators for all timeframes
│   ├── ingest.py                  # Load CSV data into SQLite
│   ├── aggregate.py               # Data aggregation utilities
│   ├── import_tv_data.py          # TradingView data import pipeline
│   └── import_tv_1h.py            # TradingView hourly import
│
├── Web Interface
│   ├── server.py                  # FastAPI backend (10+ charting modes)
│   └── static/index.html          # Interactive candlestick chart
│
├── Analyst (live analysis server + Chrome extension)
│   ├── analyst/server.py          # Live indicator computation + LLM analysis
│   ├── analyst/studies_reference.md
│   └── analyst/extension/         # Chrome extension for TradingView overlay
│
├── Reference
│   ├── KNOWLEDGE.md               # Full indicator documentation
│   └── validated-backtests/       # Source images for validated statistics
│
└── Config
    ├── .env.example               # Required environment variables
    └── .gitignore
```

---

## Setup

### Prerequisites
- Python 3.10+
- ~4 GB disk space (for the rebuilt database)

### 1. Clone and install dependencies

```bash
git clone https://github.com/prsdro/spy.git
cd spy
pip install pandas numpy fastapi uvicorn requests python-dotenv openai
```

### 2. Build the database from source CSVs

The SQLite database (~3.7 GB) is not included in the repo. Rebuild it from the 1-minute CSV data:

```bash
# Load 1-minute candles into SQLite
python3 ingest.py

# Compute all indicators across all timeframes (1m, 3m, 10m, 1h, 4h, 1d, 1w)
python3 indicators.py
```

This creates `spy.db` with 7 candle tables and 7 indicator tables (56 columns each).

### 3. Run backtests

Each backtest is a standalone script that reads from the database and prints results:

```bash
python3 backtest_atr_probabilities.py
python3 backtest_call_trigger_confirmation.py
python3 backtest_compression_expansion.py
# ... etc
```

### 4. Launch the charting interface (optional)

```bash
# Copy .env.example to .env and fill in your API keys
cp .env.example .env

# Start the chart server
python3 server.py
# Visit http://localhost:8000
```

### 5. Run the analyst server (optional)

Requires a MASSIVE API key (for live data) and an OpenAI API key (for LLM analysis):

```bash
cd analyst
python3 server.py
# API available at http://localhost:8899
```

---

## Database Schema

### Candle Tables
`candles_1m`, `candles_3m`, `candles_10m`, `candles_1h`, `candles_4h`, `candles_1d`, `candles_1w`

Columns: `timestamp, open, high, low, close, volume`

### Indicator Tables
`ind_1m`, `ind_3m`, `ind_10m`, `ind_1h`, `ind_4h`, `ind_1d`, `ind_1w`

56 columns including all three indicators. Key columns:

- **Pivot Ribbon**: `ema_8, ema_13, ema_21, ema_48, ema_200, fast_cloud_bullish, slow_cloud_bullish, compression, candle_bias`
- **ATR Levels**: `atr_14, prev_close, atr_upper_trigger, atr_lower_trigger, atr_upper_0382, ..., atr_upper_200, atr_lower_200, range_pct_of_atr, atr_trend`
- **Phase Oscillator**: `phase_oscillator, phase_zone, leaving_accumulation, leaving_distribution, leaving_extreme_down, leaving_extreme_up, po_compression`

### Data Range
~4.6M 1-minute bars across 6,500+ trading days (2000-01-03 to 2025-10-21).

---

## Creating New Studies with Claude Code

This repo includes a `/new-study` slash command for [Claude Code](https://claude.ai/code) that automates creating backtest studies. It gives Claude full context on the database schema, indicator system, and existing study patterns.

### Quick start

```bash
git clone https://github.com/prsdro/spy.git
cd spy
pip install pandas numpy
python3 ingest.py && python3 indicators.py   # build the database (~5 min)
claude                                         # launch Claude Code
```

Then in Claude Code:

```
/new-study does the Phase Oscillator zone at GG entry predict completion rate?
```

Claude will read the knowledge base, write a backtest script, run it against the database, and present the results.

### What the skill does

1. Reads `KNOWLEDGE.md` and existing backtest scripts for context
2. Writes a new `backtest_<name>.py` using the same patterns as the 26 existing studies
3. Runs it against the 25-year database
4. Presents findings and offers to build a visualization

### Example prompts

```
/new-study what happens when both bull and bear triggers fire on the same day?
/new-study does compression duration predict the size of the expansion move?
/new-study is there a day-of-week effect on Golden Gate completion rates?
/new-study how does overnight gap direction correlate with intraday ATR range?
```

---

## Implementation Notes

- ATR uses **Wilder's RMA** (not SMA) — matches TradingView's `ta.atr()`
- Daily/weekly candles use **RTH data only** (9:30 AM – 4:00 PM ET)
- ATR Levels always use **Daily reference** for intraday tables
- Bad tick clipping: bar wicks capped at 2% beyond candle body
- Phase Oscillator on hourly bars has a known accuracy gap due to extended-hours ATR inflation; 10-minute bars are accurate

See [KNOWLEDGE.md](KNOWLEDGE.md) for full validation results against TradingView exports.

---

## License

This project is provided for educational and research purposes. The Saty indicator system was created by [Saty Mahajan](https://x.com/SatyMahajan). All backtested statistics are historical and not independently verified.
