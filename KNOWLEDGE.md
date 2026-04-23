# Saty Indicator System — Knowledge Base

## Overview

This project uses three indicators by Saty Mahajan applied to 25 years of SPY 1-minute data
(Jan 2000 — Oct 2025). The indicators form an integrated system: the Pivot Ribbon provides
trend structure, ATR Levels provide price targets, and the Phase Oscillator provides
momentum/timing context.

---

## Indicator 1: Saty ATR Levels

### How It Works
- Takes the **previous period's close** and the **14-period ATR** from a higher timeframe
- Plots Fibonacci-scaled ATR levels above and below as support/resistance zones
- Timeframe mapping: Day mode uses Daily ATR, Multiday uses Weekly, Swing uses Monthly,
  Position uses Quarterly, Long-term uses Yearly

### Key Levels
| Level | Distance from Previous Close |
|-------|------------------------------|
| Trigger | ±23.6% of ATR |
| Golden Gate entry | ±38.2% of ATR |
| Golden Gate exit / Midrange | ±61.8% of ATR (Golden Gate = the zone from 38.2% to 61.8%) |
| Full ATR | ±100% of ATR |
| Extensions | ±123.6%, ±161.8%, ±200%, ±261.8%, ±300% |

### Trend Filter
Uses an 8/21/34 EMA stack:
- **Bullish**: price >= EMA8 >= EMA21 >= EMA34
- **Bearish**: price <= EMA8 <= EMA21 <= EMA34
- **Neutral**: anything in between

### Trading Logic
- **Calls/Longs** when price breaks above the upper trigger (+23.6%)
- **Puts/Shorts** when price breaks below the lower trigger (-23.6%)
- All levels act as potential support/resistance, not just the triggers

---

## Indicator 2: Saty Pivot Ribbon Pro

### How It Works
A multi-layer EMA cloud system that visualizes trend structure at a glance.

### EMA Layers
| EMA | Role |
|-----|------|
| 8 | Fast EMA — top/bottom of the fast cloud |
| 13 | Pullback Overlap EMA — used in slow cloud variant |
| 21 | Pivot EMA — middle of ribbon, core trend reference |
| 34 | Bottom of fast cloud (when using 8/21/34 structure) |
| 48 | Slow EMA — defines the slow cloud with 13 or 21 |
| 200 | Long-term trend anchor |

### Cloud Structure
- **Fast Cloud**: Between EMA 8 and EMA 21
  - Green = EMA8 >= EMA21 (bullish)
  - Red = EMA8 < EMA21 (bearish)
- **Slow Cloud**: Between EMA 13 and EMA 48 (with pullback overlap) or EMA 21 and EMA 48
  - Blue/Aqua = bullish
  - Orange = bearish
- **Ribbon Flip**: When fast cloud changes color = trend change signal

### Conviction Arrows
- 13/48 EMA crossover
- Bullish arrow: EMA13 crosses above EMA48
- Bearish arrow: EMA13 crosses below EMA48
- Confirms "conviction" in the trend change (slower, higher-confidence signal)

### Candle Bias
Colors candles based on position relative to EMA 48:
- **Green**: Up candle, above EMA48 (bullish trend + bullish candle)
- **Red**: Down candle, below EMA48 (bearish trend + bearish candle)
- **Blue**: Down candle, above EMA48 (pullback in bullish trend)
- **Orange**: Up candle, below EMA48 (bounce in bearish trend)
- **Gray/Violet**: Compression candles (BB squeeze active)

### Bollinger Band Compression
Detects squeeze conditions:
- BB width (2 * stdev(21)) compared against 2 * ATR(14)
- When BB width < 2*ATR → compression (squeeze) is active
- Expansion confirmed when BB width grows AND exceeds 1.854 * ATR threshold
- Compression candles are colored differently to signal "coiled spring" conditions

---

## Indicator 3: Saty Phase Oscillator

### How It Works
A range-normalized momentum oscillator:
```
raw_signal = ((price - EMA21) / (3 * ATR14)) * 100
oscillator = EMA(raw_signal, 3)
```
Measures how far price has deviated from its 21-period mean, normalized by volatility (ATR).

### Phase Zones
| Zone | Oscillator Range | Meaning |
|------|-----------------|---------|
| Extended Up | > +100 | Overbought extreme |
| Distribution | +61.8 to +100 | Potential topping, profit-taking zone |
| Neutral Up | +23.6 to +61.8 | Healthy uptrend territory |
| Neutral | -23.6 to +23.6 | No clear momentum |
| Neutral Down | -61.8 to -23.6 | Healthy downtrend territory |
| Accumulation | -100 to -61.8 | Potential bottoming, buying zone |
| Extended Down | < -100 | Oversold extreme |

### Mean Reversion Signals
Yellow circle signals when oscillator crosses back inside a zone boundary:
- **Leaving Accumulation**: crosses above -61.8 (potential long entry)
- **Leaving Distribution**: crosses below +61.8 (potential short entry / take profit)
- **Leaving Extreme Down**: crosses above -100 (strong reversal signal)
- **Leaving Extreme Up**: crosses below +100 (strong reversal signal)

### Compression Detection
Same BB compression logic as the Pivot Ribbon — shared across both indicators.

---

## Validated Backtest Results

### 1. Level-to-Level Probabilities (within same period)

Source: `validated-backtests/Saty ATR Levels Level-to-Level Probabiltiles.jpeg`

These probabilities apply within the same period (Day within Day, Multiday within Week, etc.):

| From → To | Probability |
|-----------|-------------|
| Previous Close → ±Trigger (23.6%) | **80%** |
| Trigger → ±Golden Gate (38.2%) | **80%** |
| Golden Gate → ±Midrange (61.8%) | **69%** |
| Midrange → ±78.6% | **60%** |
| 78.6% → ±Full ATR (100%) | **55%** |
| Previous Close → ±1 ATR (cumulative) | **14%** |
| Previous Close → ±2 ATR (cumulative) | **0.7%** |
| Extension levels (±123.6% to ±200%) | **64%** level-to-level ("Momentum Golden Gate") |

**Key insight**: The system is designed for level-to-level trading, not close-to-ATR trading.
Each individual hop is high probability (55-80%), but the cumulative probability of a full
ATR move is only 14%.

### 2. Gap Fill Probabilities (same day)

Source: `validated-backtests/gap fills.webp`

| Gap Size | Gap Up Fill | Gap Down Fill |
|----------|------------|---------------|
| < 0.1% (tiny) | 92.0% | 92.9% |
| 0.1 – 0.25% | 76.5% | 78.9% |
| 0.25 – 0.5% | 58.6% | 62.9% |
| 0.5 – 0.75% | 44.6% | 47.7% |
| 0.75 – 1.0% | 40.2% | 34.2% |
| 1.0 – 1.5% | 28.3% | 36.7% |
| 1.5 – 2.0% | 20.0% | 31.1% |
| 2.0 – 3.0% | 27.5% | 41.5% |
| 3.0%+ | 43.8% | 15.0% |

**Key insights**:
- Tiny gaps (< 0.1%) fill ~93% of the time — near-certain mean reversion
- Gap downs fill slightly more often than gap ups in mid-range sizes
- Very large gap downs (3%+) only fill 15% — panic selling persists
- Very large gap ups (3%+) fill 44% — some profit-taking reversion

### 3. Golden Gate Subway Stats — Timing of Completion

Source: `validated-backtests/Golden_Gate_Statistics_Subway_Bullish (1).webp`
and `validated-backtests/Golden_Gate_Statistics_Subway_Bearish.webp`

These show the probability that the Golden Gate setup (trigger → 38.2% level) completes
by end of day, broken down by **when the trigger fires**.

#### Bullish Golden Gate (Trigger → +38.2%)

| Trigger Time | Completion Rate by Close | Fastest Completion Window |
|-------------|--------------------------|--------------------------|
| At Open | **90.9%** | 79.7% within first hour |
| 0900 | **70.2%** | 35.1% same hour |
| 1000 | **55.0%** | Spread across afternoon |
| 1100 | **49.6%** | ~coin flip |
| 1200 | **46.8%** | ~coin flip |
| 1300 | **50.0%** | Afternoon push |
| 1400 | **40.9%** | Running out of time |
| 1500 | **9.1%** | Almost never completes |

#### Bearish Golden Gate (Trigger → -38.2%)

| Trigger Time | Completion Rate by Close | Fastest Completion Window |
|-------------|--------------------------|--------------------------|
| At Open | **91.1%** | 81.3% within first hour |
| 0900 | **69.7%** | 36.3% same hour |
| 1000 | **58.8%** | Spread across day |
| 1100 | **58.9%** | Better than bullish |
| 1200 | **55.6%** | Better than bullish |
| 1300 | **48.4%** | ~coin flip |
| 1400 | **48.6%** | Still decent |
| 1500 | **36.6%** | Much better than bullish (9%) |

**Key insights**:
- **Early triggers are high conviction** — Open triggers complete >90% of the time
- Most completions happen in the same hour or next hour after the trigger fires
- Bearish Golden Gates complete more reliably than bullish across all trigger times
- Bearish late-day triggers (1500) still complete 37% vs only 9% for bullish — 
  selling pressure is faster and more violent than buying pressure
- Midday triggers (1100-1300) are roughly coin flips — lower conviction

### 4. Call Trigger Confirmation — 3-Minute Close Study

Source: `backtest_call_trigger_confirmation.py` — 3-minute bars, RTH only, 6,582 trading days

**Setup**: Open inside trigger box (between ±23.6%), then first 3-minute close above the
call trigger. Target: does price hit the 38.2% ATR level?

**Universe**: 49.4% of days open inside the box → 62.3% of those get a confirmed trigger close.

| Metric | Value |
|--------|-------|
| Overall hit rate (trigger close → 38.2%) | **73.8%** (1,496 / 2,027) |
| Clean run hit rate (no close back below trigger) | **97.1%** (747 / 769) |
| Invalidated hit rate (closed back below trigger) | **59.5%** (749 / 1,258) |
| Edge from invalidation filter | **+37.6 percentage points** |
| Median time to target | **18 minutes** (6 bars) |

**By trigger time (half-hour)**:

| Time | Hit% | Clean% | Inval% | n |
|------|------|--------|--------|---|
| 09:30 | 81.4% | 100.0% | 69.5% | 834 |
| 10:00 | 76.2% | 100.0% | 61.2% | 328 |
| 10:30 | 73.0% | 100.0% | 57.5% | 189 |
| 11:00 | 73.3% | 100.0% | 59.8% | 131 |
| 14:00 | 74.0% | 100.0% | 45.9% | 77 |
| 15:30 | 29.1% | 43.3% | 12.0% | 55 |

**Key insights**:
- **The invalidation filter is the single strongest edge**: clean trades before 14:00 are
  effectively 100%. A 3-minute close back below the trigger is a powerful kill signal.
- **Time decay is real**: first-hour triggers are 81.4%, last half-hour drops to 29%.
- **62% of trigger days see invalidation** — most days are messy, but the clean 38% are gold.
- **Speed**: Half of all winners arrive within 18 minutes. 75% within 1 hour.

---

## Implementation Notes & Validation Results

### Validated against TradingView export (10-minute and 60-minute bars, Oct 2025)

| Component | Accuracy | Notes |
|-----------|----------|-------|
| Pivot Ribbon EMAs (8/13/21/48/200) | **0.000%** on 10m | Perfect match |
| ATR Levels (daily reference) | **0.00-0.07%** on 10m | Tiny closing-auction diff |
| Phase Oscillator (10m) | **0.5-3.5%** after warmup | Converges within days |
| Phase Oscillator (60m) | **~20-45% lower** | Extended-hours ATR inflation |

### Key Implementation Decisions

1. **ATR uses RMA (Wilder's smoothing)**, not SMA — matches TradingView's `ta.atr()`.
   Formula: `ewm(alpha=1/period, adjust=False)`

2. **ATR Levels always use Daily reference** for intraday tables — matches TradingView's
   `request.security(ticker, 'D', ta.atr(14))`. The daily ATR and previous close are
   broadcast to every intraday bar by date.

3. **Daily/weekly candles use RTH data only** (9:30 AM - 4:00 PM ET) — TradingView forms
   daily bars from regular session regardless of `session.extended` setting.

4. **Bad tick clipping** on RTH data: bar wicks capped at 2% beyond the candle body.
   Catches phantom prints (e.g., July 3 2025: $581 low on a $625 stock) while preserving
   legitimate volatile bars.

5. **Phase Oscillator on hourly bars** has a known accuracy gap because our extended-hours
   1-minute data has wider high-low ranges than TradingView's data feed, inflating the
   hourly ATR denominator. On 10-minute bars this effect is diluted and accuracy is good.

6. **Pivot Ribbon and Phase Oscillator compute on each table's own timeframe** (matching
   TradingView's default behavior with Time Warp = "off").

---

## Database Schema

### Raw Candle Tables
`candles_1m`, `candles_3m`, `candles_10m`, `candles_1h`, `candles_4h`, `candles_1d`, `candles_1w`

Columns: `timestamp, open, high, low, close, volume`

### Indicator Tables
`ind_1m`, `ind_3m`, `ind_10m`, `ind_1h`, `ind_4h`, `ind_1d`, `ind_1w`

56 columns per table including:

**Pivot Ribbon columns**: `ema_8, ema_13, ema_21, ema_48, ema_200, fast_cloud_bullish,
slow_cloud_bullish, pivot_bias_bullish, longterm_bias_bullish, conviction_bull,
conviction_bear, compression, candle_bias`

**ATR Levels columns**: `atr_14, prev_close, atr_upper_trigger, atr_lower_trigger,
atr_upper_0382, atr_lower_0382, atr_upper_050, atr_lower_050, atr_upper_0618,
atr_lower_0618, atr_upper_0786, atr_lower_0786, atr_upper_100, atr_lower_100,
atr_upper_1236 ... atr_upper_200, atr_lower_200, range_pct_of_atr, atr_trend`

**Phase Oscillator columns**: `phase_oscillator, phase_zone, leaving_accumulation,
leaving_distribution, leaving_extreme_down, leaving_extreme_up, po_compression`

### Date Range
2000-01-03 through 2025-10-21 (~25 years)

---

## Analysis Results

### 5. Price vs Daily 21 EMA — Reversion Study

Source: `backtest_price_vs_ema21.py`, `backtest_ema21_reversion.py`, `backtest_ema21_reversion_4h_po.py`
Published: `/ema21-reversion.html`

**Absolute extremes** (close vs daily 21 EMA):
- Maximum above: **+7.21%** (2009-03-23, post-GFC bounce)
- Maximum below: **-18.53%** (2008-10-09, GFC crash)
- Median: **+0.68%** — SPY's natural resting state is slightly above EMA21
- 83.7% of days close within ±2% of EMA21

**Mean reversion returns by deviation bucket**:

| Deviation | 1-Day | 5-Day | 10-Day | 20-Day |
|-----------|-------|-------|--------|--------|
| > +5% | -0.73% | -0.88% | -0.58% | +0.43% |
| < -5% | +0.24% | +0.78% | +0.97% | **+3.31%** |
| < -7% | +0.50% | +1.75% | +2.64% | **+5.36%** |

**>4% above EMA21 zone** (50 episodes in 25 years):
- 100% reverted to touch EMA21 within 28 days (median 8 days)
- Forward returns: 1d -0.30%, 3d -0.43% (38% green), 5d -0.42%
- Peak day of each episode: 1d -0.83% (26% green), 3d -1.02% (30% green)

**4h PO as reversion filter** (while >4% above daily EMA21):
- Daily PO declining fires only 12% of the time; 4h PO declining fires 46%
- Daily leaving_distribution fires 0 times — too lagging for this zone
- Best practical signal: **4h PO declining while daily PO still rising** (n=38):
  1d -0.42% (39%g), 2d -0.81% (34%g), 3d -0.85% (37%g)
- Strongest signal: **4h PO big drop (delta < -10)** (n=7):
  1d -1.64% (14%g), 2d -1.29% (29%g)
- 4h PO zone matters: Distribution zone → 10d return -1.38%; Neutral Up → +0.36%

### 6. Call Trigger to Put Trigger Morning Reversal

Source: `backtest_call_to_put_reversal.py` — 1-minute RTH bars, 6,582 trading days

**Setup**: SPY reaches the daily call trigger before noon, later crosses below PDC, then
reaches the daily put trigger before noon. Outcomes are measured from the first put-trigger
touch through the RTH close.

| Outcome after put trigger | Rate |
|---------------------------|------|
| Back to PDC | **73.7%** (481 / 653) |
| Back to call trigger | **43.3%** (283 / 653) |
| Downside GG opens (-38.2%) | **75.3%** (492 / 653) |
| Downside GG completes (-61.8%) | **43.6%** (285 / 653) |
| Reaches -1 ATR | **18.5%** (121 / 653) |

**1h PO state filter** (latest fully completed hourly bar at the put-trigger touch):

| 1h state | N | PDC | Call | GG open | GG complete | -1 ATR | Close below put |
|----------|---|-----|------|---------|-------------|--------|-----------------|
| Bullish expansion | 148 | 77.7% | 39.2% | 69.6% | 32.4% | 14.2% | 34.5% |
| Compression | 331 | 67.1% | 38.7% | 75.8% | 46.8% | 19.6% | **44.7%** |
| Bearish expansion | 174 | **82.8%** | **55.7%** | **79.3%** | **47.1%** | **20.1%** | 40.2% |

**First major outcome**:
- Bearish GG before PDC recovery: **32.3%**
- Bearish GG with no PDC recovery: **25.9%**
- PDC recovery before bearish GG: **17.2%**
- PDC recovery with no bearish GG: **24.2%**

**Key insights**:
- This reversal usually does not mean one clean outcome: both PDC recovery and downside
  GG open are around 3-in-4 by close.
- Getting all the way back to the call trigger is much less reliable than a PDC mean
  reversion: **43.3% vs 73.7%**.
- Closing below the put trigger is the largest close bucket: **41.2%**.
- Earlier completion of the reversal is more explosive: put-trigger touches before 10:30
  reached -1 ATR **23.6%** of the time versus **18.5%** overall.
- Hourly PO compression is the most bearish filter: lowest PDC recovery (**67.1%**),
  highest close-below-put rate (**44.7%**), and bearish GG first/only in **61.9%** of events.
- Bullish hourly expansion suppresses downside follow-through: GG completion drops to
  **32.4%** and -1 ATR drops to **14.2%**.

---

## Analysis TODO
- [ ] Validate level-to-level probabilities against our SPY data
- [ ] Validate gap fill probabilities
- [ ] Validate Golden Gate subway stats (timing of completions)
- [ ] Analyze Phase Oscillator zone transitions as entry/exit signals
- [ ] Study compression → expansion breakout statistics
- [ ] Cross-reference conviction arrows with ATR level behavior
- [ ] Multi-timeframe confluence analysis
