# Milkman Trades — Analyst Study Reference
# All statistics from 25 years of SPY data (2000-2025), 6,466+ trading days

## TERMINOLOGY (GET THIS RIGHT)
- Trigger = ±23.6% ATR from previous close. Call trigger = upper, Put trigger = lower.
- Golden Gate ENTRY = ±38.2% ATR. Golden Gate COMPLETION = ±61.8% ATR.
- The GG OPENS when 38.2% is hit. It COMPLETES when 61.8% is reached.
- Hitting the trigger does NOT mean the GG opened. GG opens at 38.2%, not 23.6%.

## 1. LEVEL-TO-LEVEL PROBABILITIES (Day Mode, within same day)
- Close → ±Trigger (23.6%): reached on 99.2% of days in either direction
- Trigger → ±38.2%: 80% conditional probability
- 38.2% → 61.8%: 69%
- 61.8% → 78.6%: 60%
- 78.6% → 100%: 55%
- Close → full ATR (cumulative): only 14% of days
- Bull GG baseline completion: 63.0% (n=3,411)
- Bear GG baseline completion: 65.0% (n=3,200)

## 2. BILBO GOLDEN GATE (conditioned on 1-hour Phase Oscillator)
Bull GG completion by 1h PO state:
- PO High + Rising: 77.7% (n=372) ← best bull signal
- PO High + Falling: 77.6% (n=107)
- PO Mid + Rising: 63.3% (n=2,256)
- PO Mid + Falling: 51.5% (n=664) ← worst, below baseline
- Baseline: 63.0%

Bear GG completion by 1h PO state:
- PO Low + Falling: 90.2% (n=265) ← best bear signal
- PO Low + Rising: 88.5% (n=96)
- PO Mid + Falling: 64.0% (n=2,203)
- PO Mid + Rising: 54.2% (n=626) ← worst
- Baseline: 65.0%

## 3. BILBO CONTINUATION (how far does price go beyond 61.8%?)
Bullish (PO High+Rising): 61.8%=77.7%, 78.6%=58.9%, 100%=39.2%, 123.6%=23.7%
Bullish baseline: 61.8%=63%, 78.6%=42.7%, 100%=25.5%, 123.6%=12.7%
Bearish (PO Low+Falling): 61.8%=90.2%, 78.6%=80%, 100%=66%, 123.6%=43.8%
Bearish baseline: 61.8%=65%, 78.6%=48.1%, 100%=31.4%, 123.6%=18.3%
KEY: Bearish Bilbo has 66% chance of full ATR — higher than baseline GG completion rate.

## 4. 10m vs 60m PHASE OSCILLATOR
60m PO is 5-12x more predictive than 10m PO for GG completion.
Bull edge: 60m gives +14.7% over baseline, 10m gives only +3.1%.
Bear edge: 60m gives +25.2%, 10m gives only +2.1%.
USE 60-MINUTE PO, not 10-minute, for Bilbo setups.

## 5. GG ENTRY OPTIMIZATION
Entry at 38.2% (immediate): 63-65% completion, +10% ATR EV, appears 100%
EMA 8 pullback (10m): 62-63%, +10-12% EV, appears 97%
EMA 21 pullback (10m): 58%, +8% EV, appears 88%
1h EMA 21 pullback: 42%, +7-9% EV, appears 57-62%, best R:R (2.3-3.2x)
50% midpoint: 60%, NEGATIVE EV (-3%). Reward too small vs risk.
Call/put trigger pullback: 43-48% completion but 38.2% ATR reward.

## 6. GG PULLBACK / INVALIDATION (when to cut)
Trigger (23.6%) is the key stop level:
- Holds: 84-89% GG completion
- Breaks (10m close): 45-51% completion
- Delta: -39 percentage points — strongest signal of any level

Other invalidation levels (10m close):
- 1h EMA 21 break: -20 to -28% delta (early warning)
- 10m EMA 48 break: -18 to -20% delta
- 10m EMA 21 break: -6% delta (weak)
- 10m EMA 8 break: noise (happens 93% of the time)

## 7. SUBWAY TIMING (GG completion by trigger hour)
Bullish GG: Open=86%, 09:30=63%, 10:00=57%, 11:00=55%, 12:00=48%, 13:00=39%, 14:00=41%, 15:00=16%
Bearish GG: Open=88%, 09:30=64%, 10:00=60%, 11:00=56%, 12:00=56%, 13:00=56%, 14:00=48%, 15:00=30%
KEY: Open triggers are highest conviction. Bearish holds up later than bullish. 15:00 bull is nearly worthless.

## 8. TRIGGER BOX
Bearish box: open below PDC but above put trigger. Occurs 22.6% of days (n=1,462).
Bullish box: open above PDC but below call trigger. Occurs 26.3% of days (n=1,698).

GG open rates (full-day outcome, most GGs trigger during the hold period):
- Baseline: bull 57.3%, bear 59.0%
- Held 30min: bull 72.6%, bear 71.6%
- Held 1hr: bull 82.2%, bear 80.2%

If GG hasn't triggered after hold:
- After 30min hold: 59-62% still triggers later
- After 1hr hold: 55-60%
- After 2hr hold: ~50% (coin flip)
- After 2.5hr hold: below 50% for bullish
- After 5hr (2:30 PM): effectively over (~25-31%)

When PDC is reclaimed in first hour:
- 73% reach the opposite trigger
- 49% reach the opposite GG entry (38.2%)

## 9. TRIGGER BOX CREDIT SPREADS (win rate = price does NOT reach level)
Sell CALL spreads from bearish box:
           +38.2%  +61.8%  +100%
All days:  66.6%   84.6%   96.1%
Held 30m:  79.7%   90.6%   97.8%
Held 1hr:  85.8%   93.6%   98.7%

Sell PUT spreads from bullish box:
           -38.2%  -61.8%  -100%
All days:  64.8%   79.9%   92.6%
Held 30m:  76.0%   87.7%   96.0%
Held 1hr:  82.6%   92.0%   97.5%

Two approaches: ±100% (97-99% win, less premium) or ±61.8% (88-93% win, more premium but worse loss ratio).
Use ±38.2% as stop. Setup fires ~10% of trading days.

## 10. GAP FILL (midpoint fill = price reaches halfway back through gap)
Gap Up midpoint fill rates (all / EMA21 bearish / EMA21 bullish):
<0.25%: 94% / 99% / 93% day 1
0.25-0.5%: 83% / 96% / 77%
0.5-1%: 73% / 85% / 66%
1-2%: 57% / 67% / 49%
2%+: 62% / 68% / 57%

Gap Down midpoint fill rates:
<0.25%: 95% / 92% / 96% day 1
0.25-0.5%: 88% / 84% / 91%
0.5-1%: 77% / 71% / 86%
1-2%: 70% / 66% / 80%

KEY: Counter-trend gaps fill much faster. Small gaps (<0.25%) are near-certain fills.
Large gap-ups in compression + bull trend resist filling (only 50% at 7 days).

## 11. MULTI-DAY GG (Weekly ATR, conditioned on PREVIOUS day's daily PO)
Bull GG (weekly): 65% complete day 1, 84% by day 5
- Bilbo (prev day PO high+rising): 74% day 1, 84% by day 5 (n=115)
- Counter (prev day PO mid+falling): 53% day 1, 78% by day 5

Bear GG (weekly): 72% complete day 1, 83% by day 5
- Bilbo (prev day PO low+falling): 94% day 1 (n=54) ← strongest signal in all studies
- Counter (prev day PO mid+rising): 60% day 1

## 12. SWING GG (Monthly ATR, conditioned on PREVIOUS week's weekly PO)
Bull Swing GG (monthly): 10.7% day 1, 35.1% day 5, 54.8% day 10, 73.2% day 20 (n=299)
Bear Swing GG (monthly): 33.8% day 1, 58.1% day 5, 67.9% day 10, 76.5% day 20 (n=234)
Weekly PO adds minimal edge at monthly timeframe — not enough extreme readings.
KEY: Bearish is 3x faster than bullish on day 1. Monthly moves take weeks. Full ATR only 24% bull / 42% bear by day 20.

## 13. 10-MINUTE COMPRESSION → EXPANSION
When the 10m Phase Oscillator enters compression (Bollinger Band squeeze ≥30 min),
price consolidates. The squeeze eventually releases — "expansion" — and price moves
directionally. Measurements: 120 min after expansion, from compression range midpoint.
Total events: 6,116 (n=3,311 bullish, n=2,805 bearish). 25 years of data.

### Baseline
- 54.1% of expansions are bullish, 45.9% bearish
- Expansion direction is correct 91% of the time (max profit > max drawdown)
- Bullish: mean profit 0.58%, mean drawdown near zero, mean net +0.31%
- Bearish: mean profit 0.69%, mean drawdown near zero, mean net +0.35%

### EMA 21/48 TREND PREDICTS DIRECTION (key finding)
The 10m 21 EMA vs 48 EMA trend at expansion time predicts direction, and the
edge SCALES with compression duration:
| Duration       | 21>48 → Bull% | 21<48 → Bull% | Edge  |
| Short (30-50m) | 63.5% (n=948) | 42.5% (n=847) | +21pp |
| Med (60-110m)  | 68.2% (n=1200)| 34.8% (n=1056)| +33pp |
| Long (120-170m)| 78.6% (n=602) | 30.2% (n=517) | +48pp |
| XLong (180m+)  | 83.7% (n=522) | 22.9% (n=424) | +61pp |
← Longer compression amplifies the EMA trend signal.
180+ min compression with bullish EMA trend → 84% bullish expansion.

### COMPRESSION LENGTH → MAGNITUDE & RELIABILITY
Longer squeezes produce bigger, cleaner moves:
| Duration       |   N  | Mean Profit | Net>0% |
| Short (30-50m) | 1795 | 0.607%      | 76.1%  |
| Med (60-110m)  | 2256 | 0.625%      | 81.4%  |
| Long (120-170m)| 1119 | 0.640%      | 83.6%  |
| XLong (180m+)  |  946 | 0.680%      | 86.2%  |
← Drawdown shrinks toward zero (or negative) at longer durations.

### ATR POSITION AT EXPANSION
Expansion direction correlates strongly with ATR grid position:
- Above 61.8%: 91% bullish expansion
- Trigger–38.2%: 81% bullish
- Bull trigger box: 67% bullish
- Bear trigger box: 38% bullish (62% bearish)
- Below -61.8%: 89% bearish expansion

### TIME OF DAY
Minimal effect. Bull/bear split is ~54/46 across all time buckets.
Bearish expansions have slightly higher profit at open and close.

## TIMEFRAME COMPARISON
| Timeframe | ATR Ref | Bull baseline 1d | Bear baseline 1d | Bull Bilbo 1d | Bear Bilbo 1d |
| Day | Daily | 63% | 65% | 78% (1h PO) | 90% (1h PO) |
| Multi-Day | Weekly | 65% | 72% | 74% (daily PO) | 94% (daily PO) |
| Swing | Monthly | 11% | 34% | — (weak signal) | — (weak signal) |
Bearish moves are faster at EVERY timeframe. Higher TF PO = less edge.

## 14. 4H PO ROLLOVER + OpEx WINDOW (EXTENDED CONDITIONS)
Signal: 4H PO peak ≥ 80, crosses below 80 (classic "leaving distribution").
Baseline sample: 118 signals over 25 years. Baseline ≥1% 5d hit rate = 50.8%.

### OpEx timing suppresses then releases drop probability
Signals clustered by trading days relative to monthly OpEx (3rd Friday).
Within the OpEx Fri + Post-OpEx 1-5d window (n=26 unfiltered):
| Horizon |  N  | ≥0.5% | ≥1.0% | ≥1.5% | ≥2.0% | Median |  25th |
| 1d      |  26 |  42%  |  19%  |  15%  |   4%  | -0.40% | -0.83%|
| 3d      |  26 |  62%  |  46%  |  23%  |  15%  | -0.95% | -1.40%|
| 5d      |  26 |  73%  |  50%  |  27%  |  23%  | -0.99% | -1.57%|
| 10d     |  26 |  77%  |  69%  |  46%  |  38%  | -1.37% | -2.68%|
KEY: Hit rates climb sharply from 1d to 10d as pin-release plays out.

### Extended filter: weekly OR monthly ATR position ≥ 0.618 (n=21)
| Horizon |  N  | ≥0.5% | ≥1.0% | ≥1.5% | ≥2.0% | Median |  25th | Worst |
| 1d      |  21 |  43%  |  14%  |  14%  |   5%  | -0.47% | -0.77%| -2.11%|
| 3d      |  21 |  57%  |  38%  |  19%  |  14%  | -0.77% | -1.12%| -5.11%|
| 5d      |  21 |  71%  |  43%  |  24%  |  24%  | -0.92% | -1.48%| -5.11%|
| 10d     |  21 |  71%  |  62%  |  43%  |  38%  | -1.25% | -2.44%| -8.65%|
← 10d window is the money zone: 62% hit 1%, 43% hit 1.5%, 38% hit 2%.

### Deep extended: weekly OR monthly ATR position ≥ 1.0 (n=12)
| Horizon |  N  | ≥0.5% | ≥1.0% | ≥1.5% | ≥2.0% | Median | Worst |
| 1d      |  12 |  42%  |   8%  |   8%  |   0%  | -0.41% | -1.56%|
| 3d      |  12 |  50%  |  33%  |  17%  |   8%  | -0.63% | -2.54%|
| 5d      |  12 |  67%  |  33%  |  17%  |  17%  | -0.83% | -4.83%|
| 10d     |  12 |  67%  |  50%  |  33%  |  33%  | -1.05% | -8.65%|
Deep extension underperforms moderate extension in 5d but tail risk skews larger
(Feb 2018 -8.65%, May 2001 -4.83%).

### OpEx offset breakdown (unfiltered, 5d horizon)
| Bucket                    |  N  | ≥0.5% | ≥1.0% | ≥1.5% | Med5d |
| OpEx Friday (day 0)       |  5  |  80%  |  80%  |  40%  | -1.48%|
| Post-OpEx day 1 (Mon)     |  6  | 100%  |  67%  |  33%  | -1.08%|
| Post-OpEx day 2 (Tue)     |  5  |  60%  |  20%  |  20%  | -0.70%|
| Post-OpEx day 3 (Wed)     |  2  | (too small)                  |
| Post-OpEx day 4 (Thu)     |  4  |  50%  |  25%  |   0%  | -0.65%|
| Post-OpEx day 5 (Fri)     |  4  |  75%  |  75%  |  50%  | -1.57%|
| Non-OpEx window           | 92  |  75%  |  51%  |  34%  | -1.07%|
KEY: OpEx Fri + Post-Mon is the strongest pair. Post-Tue/Wed/Thu weaken as
the suppression fades and dealers unwind delta.

### TAKEAWAYS
1. A 4H PO rollover that fires within the OpEx Fri + Post-OpEx 1-5d window under
   extended conditions (wk or mo ATR ≥ 0.618) produces a meaningful edge over the
   10d horizon: 62% hit 1%, 43% hit 1.5%, 38% hit 2%, median drawdown -1.25%.
2. Short-horizon (1d, 3d) hit rates are modest — don't expect an immediate dump.
   The drop plays out over days as dealer gamma unwinds.
3. 25th-percentile 10d drawdown is -2.44% under extended, -2.74% under deep extended
   — the tail is where the trade pays. Long-dated puts preferred over weeklies.
4. Deep extension (wk or mo ATR ≥ 1.0) underperforms moderate extension at 5d but
   has fatter left tails at 10d (worst case -8.65%, Feb 2018).
5. The non-OpEx-window baseline (n=92) at 5d = 51% hit 1% — same as the full baseline.
   The OpEx-proximate edge isn't hit rate at 5d, it's tail expansion at 10d.
