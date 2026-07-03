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

### 7. SPX Double Golden Gate — "both gates open, neither closes" (HYPOTHESIS REJECTED)

Source: `backtest_spx_double_gg_revert.py` — FirstRateData **SPX index** 1-minute RTH bars,
2008-01 → 2026-05 (4,612 sessions). Levels from prior daily close + one-session-lagged
Wilder ATR(14). Timezone: cutoff is **12pm Central = 1:00pm ET**.

**Setup**: SPX opens the downside Golden Gate (low reaches −38.2% ATR) before noon CT,
then *later* opens the upside Golden Gate (high reaches +38.2%) — also before noon CT.
Reaching +38.2% from −38.2% means a full reversal back up through PDC.

**Hypothesis**: neither gate completes (no ±61.8%); price reverts to PDC.

**Result — rejected.** The down→up reversal tends to *keep going up*, not revert:

| Outcome (n = 102 setups) | Rate |
|--------------------------|------|
| Upside gate **closes** (+61.8%) after 2nd open | **63.7%** |
| Neither gate ever closes (no ±61.8% all day) | 29.4% |
| Pulls back to PDC after 2nd open | 46.1% |
| Both (neither close **and** PDC revert) | 20.6% |
| First resolution = upside closes first | **63.7%** |
| First resolution = downside closes first | 2.0% |
| RTH close above PDC | ~71% (median close **+0.44 ATR** above PDC) |

**Clean subset** (downside only *poked* −38.2% without closing to −61.8% before reversing,
n=75): upside still closes **57.3%**, neither-closes 40.0%, PDC revert 42.7%, median close
**+0.45 ATR** above PDC. Same conclusion.

**Key insights**:
- The setup is **rare**: 40.5% of days open the downside gate before noon CT, but only
  **5.5% of those** (2.2% of all days, n=102) then reopen the upside gate before noon CT.
- The **second move wins**. Once price whipsaws down then reclaims +38.2%, the upside
  gate completes ~58–64% of the time and the downside gate completing first is almost
  never the outcome (2.0%).
- "Revert to PDC" is a **minority** outcome (~46%) and is dominated by upside continuation;
  the day closes *above* PDC ~71% of the time.
- **Caveat**: n=102 over 18 years (modest), but events are well-distributed across years
  (no single-year clustering); all time-of-day buckets are n<30.

#### 7b. Generalized: both orderings, full session, time-segmented

Source: `backtest_spx_double_gg_full.py` → published page `/spx-double-gg.html`
(data `site/data/spx-double-gg.json`). Drops the noon cutoff and detects **both
orderings** of the first two opposite-gate opens anywhere in RTH, segmented by the
half-hour the **second** gate opens. 504 double-gate days (209 down-first, 295 up-first).

Outcomes measured from the second gate's open through the RTH close:

| Case (2nd gate) | n | 2nd completes | Reverts PDC | Neither closes | Close vs PDC | After completion |
|-----------------|---|---------------|-------------|----------------|--------------|------------------|
| **Down→Up** (upside is 2nd) | 209 | 45.5% | 29.2% | 35.4% | **+0.41 ATR** | cont 49% / side 32% / rev 19% |
| **Up→Down** (downside is 2nd) | 295 | **58.6%** | 41.0% | 25.8% | **−0.39 ATR** | **cont 68%** / side 12% / rev 20% |

**Key insights (extend 7)**:
- **Asymmetry**: the up→down whipsaw completes its second (downside) gate more often
  (58.6% vs 45.5%) and continues much harder once it does (68% vs 49% continuation) —
  consistent with selling pressure being faster than buying (see Study #3).
- **Up-first is more common** (295 vs 209) — an early pop that later flushes is the more
  frequent SPX pattern than an early flush that later rips.
- **Time-of-day is the dominant control.** Both cases complete best when the second gate
  opens late-morning (10:00–12:00, ~60–89%) and decay sharply into the close (down→up
  drops to 11% at 15:30; up→down to 33%). PDC reversion fades even faster — near-zero
  (3–4%) once the second gate opens after 15:00 (price just keeps going where it broke).
- **Occurrence is bimodal**: a late-morning whipsaw burst (10:00–11:30) plus a
  late-afternoon tail (14:30–15:30) where the gate opens but the day closes before it
  resolves.
- In both orderings PDC reversion stays a minority outcome and the day closes in the
  direction of the **second** move — reinforcing the rejection of the original hypothesis.

**Completion & continuation timing**:
- Up→down completes **~2× faster** than down→up: median **25 min** (p25–p75 10–59) from
  the downside gate opening to −61.8%, vs **50 min** (14–94) for the upside case. Selling
  resolves faster than buying.
- Once a gate completes, the continuation to ±78.6% is **quick and symmetric**: median
  **14 min** in both directions — when it runs, it runs immediately.

**Greatest edge — morning up→down** (2nd/downside gate opens before noon CT, n=142):
- Completes **66.2%**; of those, **76.6%** continue to −78.6% → **~51%** of these setups
  both complete *and* continue.
- Timing: median **30 min** (p25–p75 11–81) to −61.8%, then a further median **16 min**
  to −78.6%.
- Although every setup is *valid* before noon CT, the actual −61.8% completion **clusters
  10:30–13:00 ET** (late-morning/lunch); few complete in the first 30 min and the tail
  past 14:00 is thin. Surfaced as the headline "edge" card on `/spx-double-gg.html`.

---

### 8. Multi-Day GG by weekday (SPX, weekly ATR) — completion & continuation by open day

`backtest_spx_multiday_gg_dow.py` · FirstRateData SPX cash daily, 2000-11→2026-05,
**1,313 weeks**. Multiday-mode levels = prior weekly close + 1-week-lagged weekly Wilder
ATR(14). For each week and each direction independently: find the first weekday the gate
**opens** (±38.2%), then whether it **completes** (±61.8%) by that week's Friday, and how
far it continues (±78.6%, full weekly ATR). Upside gate opens in 54% of weeks, downside
50%, both 14%.

- **Completion decays with later open day** — largely the clock confound (Mon≈5 sessions
  left, Fri=1). Completion is fast when it happens (median ~1 session open→complete):
  Up Mon **78%** → Fri **16%**; Down Mon **74%** → Fri **39%**. Overall up 60.2% / down 65.2%.
- **NOT symmetric — downside is faster and harder.** Same-day completion (time-independent)
  is **~35–38% on every weekday** for the downside vs **~15–25%** upside. Late-week the down
  gate survives better (Thu/Fri 55%/39% vs up 41%/16%).
- **Continuation, given completion:** down **70.6%** push to ±78.6% and **41.4%** to a full
  weekly ATR, vs up **64.0%** / **32.7%**. Continuation is strongest for early-week opens
  (Mon up→full ATR 46%, down 54%; by Thursday almost none). "Stairs up, elevator down" holds
  on the weekly frame. Published interactive at `/spx-multiday-gg-dow.html`.

---

### 9. Cross-timeframe GG conflict — downside Swing GG (monthly) vs upside Multi-Day GG (weekly)

`backtest_spx_cross_tf_gg_conflict.py` · FirstRateData SPX cash daily, 2002-01→2026-05,
**293 months / 126 fair downside-swing episodes**. Swing levels = prior-month close +
1-month-lagged monthly Wilder ATR(14); Multiday levels = prior-week close + 1-week-lagged
weekly Wilder ATR(14). Setup: the downside **Swing** gate opens (low ≤ −38.2% monthly) and
while still **live** — not closed to −61.8% monthly and not retraced above the −23.6%
monthly put trigger — the upside **Multi-Day** gate opens (high ≥ +38.2% weekly). That day
starts the race. Daily resolution (intraday H/L order unknown); same-day transitions flagged.

- **Rare**: only **17 setups** (15 fair) in 24 years, but well-distributed across **13
  different years** (no single-regime clustering). Median gap swing-open → weekly-up trigger
  is **1 session** — sharp V-bottom whipsaws: monthly downside gate cracks open, price
  bounces hard enough to open the weekly upside gate ~1 day later.
- **The second (upside) move wins ~2:1.** Weekly-up closes first **64.7%**, swing-down
  first **29.4%**, neither **5.9%** — the weekly gate wins despite a *shorter* horizon (its
  week vs the swing gate's whole month). Echoes intraday double-GG (Study #7): once price
  whipsaws down then reclaims, the up move keeps going.
- **Swing-down completion COLLAPSES vs baseline.** With a coexisting opposite weekly-up the
  downside swing gate completes only **43.8%** (n=16) vs **69.1%** with no coexisting
  weekly-up (n=110) / **65.9%** baseline (n=126) — a ~22pp drop. It also **retraces above
  its put trigger 94%** of the time after the weekly gate opens. *Confound (honest):*
  coexisting episodes are pre-selected for NOT plunging straight through, biasing downside
  completion lower.
- **Weekly-up completion is essentially unchanged** by the opposite headwind: **69.2%**
  with a live swing-down (n=13) vs **60.7%** without / **60.8%** baseline — within noise at
  n=13. The monthly downside conflict does **not** suppress the weekly upside gate.
- **Net:** when these two opposite-timeframe gates coexist, bet the **weekly upside** gate,
  not the monthly downside one. n is small — directional, not precise. Data at
  `site/data/cross-tf-gg-conflict.json`.

---

### 10. PO dots as a long-term accumulation strategy (vs SPY benchmarks)

`backtest_po_dots_buyhold.py` · SPY daily `ind_1d`, 2000-01-03 → 2026-04-09 (6,583
sessions), **102 leaving-accumulation (buy) dots / 164 leaving-distribution (sell) dots**.
Dots execute at the next session's open. Real SPY dividends (110 ex-dates from Yahoo,
`spy_dividends.json`) reinvested at the ex-date close while holding shares. Cash run under
two regimes: 0% and the prevailing 13-week T-bill yield (^IRX daily, `tbill_irx.json`,
mean 2.00% over the period); headline numbers below are the 0% regime.
Three capital models, each with its own like-for-like benchmark; strategies unitized like
a fund so TWR/vol/Sharpe/maxDD are contribution-clean. Data: `analyst/po_dots_buyhold.json`.

| Model ($ flow) | Benchmark | Accumulate-only | Full exit on sell dot | Sell one lot |
|---|---|---|---|---|
| A: $1k/month → cash, deploy all on buy dot | DCA XIRR **11.20%** (5.49x) | XIRR **11.11%** (5.41x) | XIRR 6.72% (2.65x) | XIRR 8.95% (3.79x) |
| B: $10k fresh per buy dot | even-spaced DCA XIRR 11.18% | XIRR **11.17%** | XIRR 6.48% | XIRR 9.12% |
| C: $100k lump, deploy 20% of cash per dot | lump-sum **7.87%/yr** (7.30x) | **8.46%/yr** (8.44x) | 0.76%/yr (1.22x) | 5.12%/yr (3.71x) |

**Key findings**:
- **Buy dots ≈ DCA, no timing alpha.** Waiting for the dot to deploy cash matches
  immediate monthly investing almost exactly (model A: 11.11% vs 11.20% XIRR; model B
  per-dollar: 11.17% vs 11.18%). The dip-buying benefit is fully offset by 0%-cash drag
  while waiting (~4 buy dots/yr, clustered in bear years: 2002 had 12, 2008/2022 had 8).
- **Selling on the opposite dot destroys 2–6 pp/yr.** Full exit cuts time-in-market to
  42% and the XIRR from ~11.2% to ~6.5–6.7%; one-lot selling lands in between. Sharpe
  drops too (0.60 → 0.35–0.37 full exit) — lower vol does not pay for the lost return.
- **The sell→rebuy round trip has no edge.** Actual full-exit round trips (first sell dot
  while long → next buy dot, n=38): rebuy cheaper only **47.4%** of the time, median price
  change **+0.21%** (mean **+2.74%** against you), median **116 days** out of the market.
  Worst: exited 2020-06-12, re-entered 2021-09-23 **+42.7%** higher after 468 days out.
  (A naive pairing using the *last* sell dot before each buy shows rebuys 95% cheaper at
  −4% median — an artifact; the strategy exits at the *first* sell dot, which fires early
  in ongoing uptrends as momentum merely cools below +61.8.)
- **Model C's lump-tranching win is start-date luck.** The +0.60 pp/yr edge over lump-sum
  exists only for the 2000 (dot-com top) start; starting 2003/2010/2013/2016 the dots
  strategy loses by 0.33–2.44 pp/yr. Time in market dominates.

**Start-year sensitivity** (`backtest_po_dots_start_sensitivity.py`, all 22 start years
2000–2021, every window ending 2026-04; `analyst/po_dots_start_sensitivity.csv`):

| Variant (accumulate-only edge vs its benchmark, pp/yr) | Median | Wins | Range |
|---|---|---|---|
| A: hold monthly cash for the dot (vs immediate DCA) | **−0.23** | **0/22** | −1.73 (2020) … −0.09 (2000) |
| B: per-dollar price timing (vs even-spaced, XIRR) | **+0.39** | **19/22** | −0.22 (2001) … +2.18 (2020) |
| C: lump in 20% tranches (vs lump-sum day one) | **−0.55** | **5/22** | −5.51 (2019) … +1.26 (2008) |
| Full exit on sell dot (any model) | −4.9 to −10.5 | **0/22 ×3** | never positive, any start, any model |

- **Clean decomposition**: the dot genuinely *selects good prices* — dollars deployed at
  dots beat even-spaced dollars in 19 of 22 start years (model B, median +0.39 pp/yr,
  rising to +1–2.2 pp for 2017–2021 starts). But *waiting in 0% cash for the dot costs
  more than the better price saves* — model A loses in **all 22** start years, and the
  loss grows the more bull-heavy the window (−0.09 pp for 2000 → −1.73 pp for 2020).
- **Model C wins only when the window starts just before a major crash** (2000, 2008
  +1.26 pp; 2001/2002/2007 marginal) — it is crash insurance, not expected-value edge.
- **Selling never works from any starting point**: full exit loses 4.4–13.8 pp/yr in all
  66 start-year × model combinations.
- **T-bill interest on cash changes no conclusion.** Accruing idle cash at the daily ^IRX
  yield: model A still loses **all 22** start years (median edge −0.20 vs −0.23 pp/yr at
  0%; full-period XIRR 11.13% vs DCA 11.20%); model C flips only 2005 marginally positive
  (6/22 wins, median −0.54 pp/yr); full exit gains ~1.0–1.6 pp/yr (it sits 58–90% in cash)
  but stays negative in all 66 combinations (median −3.3 to −8.4 pp/yr vs benchmark).
  Rates were near-zero exactly when the sell variants were in cash longest (2009–2015,
  2020–2021), so interest can't buy back the missed equity returns.
- **Net**: leaving-accumulation is a *harmless* deployment trigger (psychologically nice —
  it buys real dips and matches DCA), but leaving-distribution is **not** a sell signal on
  the daily timeframe. The asymmetry mirrors the zones' design: accumulation-exit marks
  washed-out bottoms; distribution-exit mostly marks pauses in bull trends.

---

### 11. Gap up to +1 ATR that holds the full-ATR line — "how far does it go?"

`backtest_spx_gap_above_full_atr.py` · primary: FirstRateData **SPX index**
1-minute RTH resampled to **10-minute** bars (2008-01→2026-05, 4,612 sessions);
cross-check: SPY `ind_10m` (2000-01→2026-04, 6,582 sessions). Levels = prior
daily close + one-session-lagged daily Wilder ATR(14). Data:
`site/data/spx-gap-above-full-atr.json`, events `analyst/spx_gap_above_full_atr_events.csv`.

**Setup**: the session **opens at or just above +1 ATR** (full daily ATR above
PDC; headline band open ∈ [+1.000, +1.236) ATR), i.e. a large gap up that prints
right at the full-ATR line. **Hold condition**: *every* 10-minute RTH close stays
≥ +1 ATR (price never gives the full-ATR level back on a closing basis). "How far"
= intraday peak high and extension hit-rates (+123.6% … +300%) measured in ATR
units above PDC.

- **The setup is RARE.** Opening in the +1 ATR band happens on **~0.17% of SPX
  sessions** (8 days in 18 yr, headline band; SPY ~0.59%, 39 days in 26 yr).
  Even pooled, n is small — treat as **directional, not precise** (SPX headline
  holders n=4; SPY headline holders n=11).
- **Holding the line ≈ a coin flip** — SPX **50%** of these gap-ups never close
  below +1 ATR (4/8 headline; 11/18 wide), SPY **28–39%**. But the two branches
  go to *completely different places*, so the hold is the discriminator, not noise.
- **When it HOLDS, it's a continuation day.** Intraday peak **median ≈ +1.85 ATR**
  (SPX +1.84, SPY +1.85, near-identical); reaches **+123.6% ~100%** of the time,
  **+161.8% ~75–82%**, and only tags **+200%** when the gap *opened* well past
  +1 ATR (wide band: SPX 36%, SPY 46%). So from a +1 ATR open it typically adds
  **another ~+0.6–0.85 ATR**, with ~**+2 ATR the practical ceiling** for at-the-line
  opens. The close is strong — **median ≈ +1.5–1.66 ATR and at/above the open
  ~100%** of holder days. It does not give the day back.
- **When it does NOT hold, the gap fades.** Median **trough falls back to ≈ PDC**
  (≈0 ATR; some go negative), the close is weak (**median ~+0.6–0.8 ATR**) and
  **below the open ~70–100%** of the time. Losing the +1 ATR line on a 10-minute
  close is an early, reliable tell that the gap-up is failing.
- **Net**: a gap that opens at +1 ATR and *holds it on closing 10m bars* tends to
  grind to **~+1.85 ATR** (tagging +123.6% almost always, +161.8% ~3-in-4) and
  close near its highs; one that loses the line round-trips toward PDC. The
  10m-close hold is the single discriminating filter. SPX and SPY agree closely
  on the conditional outcome despite different gap mechanics (SPX index open is
  the futures-driven gap; SPY ETF gaps slightly more often) — but **sample is
  too thin to publish as a hard probability**.

#### 11b. Widened to +0.786 ATR opens — ATR progress by time of day

`backtest_spx_gap_above_0786_intraday.py` · same data/levels as §11. Lowering the
open threshold from +1 ATR to **+0.786 ATR** widens the universe ~5× (SPX **43**
events / 19 holders; SPY **163** / 68 holders) and lets the intraday *path* be
measured. Hold condition re-anchored to the opening level: every 10m close ≥
+0.786 ATR. Data: `site/data/spx-gap-above-0786-intraday.json`.

- **Wider universe, same conditional split.** Gap-up open ≥ +0.786 ATR occurs on
  **0.93% of SPX sessions** (SPY 2.48%); **~42–44% hold** the line. Holders again
  peak **median +1.66/+1.84 ATR** (SPY/SPX), close **+1.50/+1.66 ATR**, close ≥
  open **90–100%**, tag +123.6% ~99–100% and +161.8% ~54–74%. Non-holders fade:
  trough back toward PDC, close **+0.72/+0.80 ATR**, close ≥ open only ~29–37%.
  The §11 result survives the 5× larger sample.
- **The move is front-loaded.** Holders do most of their work in the first
  ~30–90 min: SPX held-median climbs +1.27 ATR (09:30 bar) → +1.48 (10:00) →
  ~+1.66 plateau by 12:30–13:00, then a flat grind into the close (~+1.65). SPY
  held: +1.10 → +1.25 (10:00) → ~+1.45–1.50 plateau. **Roughly two-thirds of the
  holder day's eventual gain is in by 10:00**; the afternoon is a hold, not a push.
- **The fork is visible by ~10:00–10:30.** Held and not-held branches open close
  together (SPX +1.27 vs +1.04 median at 09:30) but diverge within the first hour:
  the not-held branch **bleeds monotonically** from ~+1.0 ATR down to a +0.55–0.80
  ATR afternoon trough (decline begins ~10:20), while holders keep climbing. The
  day's character — continuation vs failed gap — is **set in the first ~60 min**,
  consistent with the Golden Gate "early triggers are high-conviction" pattern
  (Study #3). A 10m close back below the opening level early is the actionable tell.

---

### 12. Buy Every IPO? — 5 years of US listings, day-1 vs delayed entry (2026-07-03)

Universe: every operating-company IPO (CS + ADR) on NASDAQ/NYSE/AMEX listed
2021-07-01 → 2026-06-30, from the Massive IPO reference feed. 882 qualifying
listings (707 SPAC unit offerings and 276 OTC listings excluded); 705 with usable
price history (delistings **included** — terminal value = last trade). Valued at
2026-05-07. Benchmark: SPY over identical dates per position. Page: `/ipo-5yr.html`,
script `backtest_ipo_5yr.py`, data `site/data/ipo-5yr.json` + `analyst/ipo_study/`.

- **Buying every IPO at day-1 open: XIRR 3.4%/yr vs 15.6%/yr** for the same
  cashflows in SPY. Median IPO −61% one year after listing; only 19% beat SPY
  over year 1. 54% of IPOs lost ≥half to date, 26% lost ≥90%, 10% doubled.
- **The bleed is slow, not a first-week flush**: median vs day-1 close is −2%
  (+1w), −6% (+1m), −23% (+3m), −40% (+6m), −60% (+1y); 78% below day-1 close
  a year out. So waiting 1w/1m barely helps; **waiting ~6 months (post-lockup)
  lifts XIRR to 17.3% vs 17.2% SPY — market-matching, zero alpha**. The median
  IPO underperforms from *any* entry; the tail carries the portfolio.
- **Deal size is the strongest filter (monotonic)**: median 1-y raw return
  −78% (<$25M, a third of all IPOs), −48% ($25–100M), −28% ($100–500M),
  −12% (≥$500M). Even ≥$500M lags SPY at the median (−15pp excess).
  $100M+ portfolio: day-1 XIRR 7.8% vs 14.2%; +6m entry 16.0% vs 15.8%.
- **Industry is predictive (Kruskal–Wallis p=0.0005) but mostly a size proxy**:
  banks/finance (−19pp median 1-y excess) and mining/energy best; wholesale,
  transport, services micro-caps worst (−90 to −104pp). Biotech, the largest
  sector (n=90), medians −60% in year 1.
- **The IPO pop is not capturable**: median +8.3% issue→day-1 open (mean +46%,
  micro-cap skewed) goes to allocated buyers; retail starts after it.
- Every listing-year cohort 2021–2025 looks the same (median 1-y −58% to −66%,
  beat-SPY 17-25%) — this is structural, not just the 2021–22 bust.
- **Caveats**: ~144 delisted names (median deal $58M) still lack price history
  (Stooq IP-block pending) → published numbers are *optimistic*, especially
  sub-$100M buckets; $100M+ segment missing 76 delisted names (~21%). Price
  returns both legs (no dividends). Data: local parquet + Massive API (2-yr cap
  on current tier) + Yahoo (validated to-the-cent) + SEC EDGAR SIC codes.

**Angle 2 (added 2026-07-03): size thresholds, tech split, equity curves**
(script `backtest_ipo_size_tech_curves.py`, data `site/data/ipo-5yr-curves.json`;
tech = SIC 3570-79/3660-99/7370-79; XIRR = $1/IPO held to 2026-05-07 or delisting,
same cashflows into SPY):

- **Big-deal counts (with usable bars)**: ≥$250M n=179 (~36/yr; 46·7·15·35·52·24
  by year 2021H2→2026H1), ≥$500M n=88 (~18/yr), ≥$1B n=36 (~7/yr).
- **Raising the size bar does NOT rescue day-1 buying**: day-1 XIRR 8.6% (≥$250M),
  9.6% (≥$500M), 6.6% (≥$1B) vs SPY ~14.3-14.6% — ≥$1B is *worse* than ≥$500M
  (Rivian-class 2021 mega-deals −65 to −76% year 1). Every threshold lags 5-8pp/yr.
- **The 6-month wait converges every size bucket to ~market**: +6mo XIRR 16.0/16.9/15.1%
  vs SPY 15.9/16.0/15.9%. Best cell: $500M–1B range +6mo = 18.2% vs 16.0%.
- **Wait ladder is monotonic in all buckets** (median 1-y excess roughly halves
  day-1→+6mo, e.g. ≥$1B −24%→−5%) — but nothing before +3 months moves the needle.
- **Tech is the slice waiting can't fix**: tech ≥$250M day-1 XIRR 1.4%, +6mo still
  4.2% vs SPY 15.2% (n=37). All-tech +6mo 10.9% vs 16.6%. **Non-tech ≥$250M +6mo
  is the only index-beating cell: 20.6% vs 16.3%** (n=114 curve positions; read as
  a lean given sample sizes, not a law).
- Scatter (1-y IPO return vs SPY same window, all 530 completed windows): cloud
  sits below the y=x diagonal in every filter; size filters tighten dispersion but
  don't lift the median above the line.

**Angle 3 (2026-07-03): entry-timing sweep, issue-price rules, stop-loss overlay**
(scratch_ipo_pop_dip.py, scratch_ipo_wait_sweep_stop.py, scratch_ipo_6mo_above_issue.py;
headline strategy on page via backtest_ipo_strategy_curve.py):

- **Wait-window sweep** (monthly steps to 12mo): benefit knees at **~5 months**,
  flat 5→12; "6 months" is convention. <3 months doesn't move the needle.
- **Pop-then-dip-to-issue entry**: beats day-1, loses to plain +6mo everywhere.
  Dip-to-issue = adverse selection — never-dipped big-pop ≥$100M names went
  median +82% yr-1 with 100% beating SPY, but that's only knowable ex-post.
- **Buy-pop-with-stop-at-issue**: disaster (stop ~30% below popped entry, fires
  on ~75%). **"Above issue at 6mo" filter**: unreliable — helps ≥$100M ~+1.7pp,
  HURTS nontech≥250M (its below-issue half did 22.3% vs 16.1%). Never-dipped-
  through-6mo bought at 6mo is uniformly bad: winners front-load months 0-6.
- **Tight stop on the +6mo entry: value depends entirely on redeployment.**
  −10% daily-close stop on nontech≥250M e126 (n=114, 84 stopped, median exit
  ≈ −12%). Per external $1 held/reinvested to 2026-05-07: proceeds **reinvested
  equally into remaining open positions $1.69 (26.8%/yr)** > no-stop $1.50
  (20.7%/yr) > proceeds→SPY $1.52 > SPY-hold $1.38 (16.3%/yr) > **proceeds→cash
  $1.27 (12.3%/yr, WORSE than no stop)**. The naive dated-flow XIRR (28.6% vs
  14.5% "mirror") is a deployment-window artifact — a rate while deployed, not
  extra wealth; don't quote it standalone. Beat-rate collapses 45%→30% and the
  book concentrates as stops fire. Promising-not-proven (rule iterated on the
  same window).
- **Curve convention (angle-3 rebuild)**: ALL equity curves in
  ipo-5yr-curves.json are self-financing — exit proceeds (stops + delistings)
  redeployed equally across that portfolio's open positions same-day (cash only
  while nothing is open); SPY leg = same external dollars, held to sample end.
  Simulator in backtest_ipo_size_tech_curves.py (sim/build_positions);
  strat curve = curves['strat_stop10'].

---

## Analysis TODO
- [ ] Validate level-to-level probabilities against our SPY data
- [ ] Validate gap fill probabilities
- [ ] Validate Golden Gate subway stats (timing of completions)
- [ ] Analyze Phase Oscillator zone transitions as entry/exit signals
- [ ] Study compression → expansion breakout statistics
- [ ] Cross-reference conviction arrows with ATR level behavior
- [ ] Multi-timeframe confluence analysis
