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

## 15. ATR LEVEL CASCADE (DRAFT)
Source: backtest_atr_cascade.py, 3-min RTH bars, 25y SPY (6,582 days, 33,153 first-hit events)

For each first-touch of an ATR level, classify the next adjacent move: continuation (one
level further from PDC), retrace (one level closer to PDC), or last (no further adjacent
level reached before close). Filterable by hour-of-day of the first hit. Ladder: full
Saty fib set from -2 ATR through PDC to +2 ATR (25 rungs incl. ±0.236, ±0.382, ±0.50,
±0.618, ±0.786, ±1.00, ±1.236, ±1.382, ±1.50, ±1.618, ±1.786, ±2.00).

### Headline (all hours)
- Continue to next level: 52.0%
- Retrace to prior level: 41.4%
- No further adjacent move: 5.0%
- Median time to next adjacent level: 21 min

### Inner triggers (call & put)
- +0.236 (call trigger), n=4,400: 68% beyond, 27% behind, 4% last
- -0.236 (put trigger),  n=4,090: 67% beyond, 30% behind, 2% last

### Time-of-day shape (call trigger example)
- 09:30-10:00 (n=2,939): 78% beyond, 22% behind, 0% last
- 10:00-11:00 (n=  592): 52% beyond, 45% behind, 1% last
- 14:00-15:00 (n=  195): 43% beyond, 36% behind, 17% last
- 15:00-16:00 (n=  158): 26% beyond, 13% behind, 61% last

### Sticky vs magnet rungs
- ±0.382 GG-entry: retrace > continuation overall (call: 37% behind vs 59% beyond when
  next rung is +0.50; put: 42% behind vs 55% beyond)
- ±0.618 GG-completion: retrace > continuation on both sides (call: 52% behind vs 41%;
  put: 59% behind vs 37%)

### Extension behavior
- ±1.50 to ±1.786: median time to retrace 2-5 minutes — extension tags rarely hold
- ±2.00: 0% beyond (capped), 66-79% behind, 21-34% last (n=38 / 123)

### Path-dependent (chronological prefix conditioning)
The page also exposes a path explorer. For each day, the chronological sequence of
first-hit level indices (incl. PDC) is captured. Conditioning on a user-built prefix:
- "PDC → +0.236" (n=868):       64% next-up (+0.382), 20% next-down (-0.236), 17% end
- "PDC → +0.236 → +0.382" (n=553): 67% next-up,         10% next-down,           23% end
- "PDC → ... → +1.00" 7-step monotonic (n=74): 45% next-up (+1.236), 1% next-down, 54% end
- "PDC → ... → -1.00" 7-step monotonic (n=71): 52% next-down (-1.236), 0% next-up, 48% end
KEY: A retrace in path-language means a NEW first-hit on the opposite frontier (one
level beyond the path's outermost-toward-PDC rung), not a re-touch of an already-
visited level. Re-touches don't register as new events.

### Output files
- analyst/atr_cascade_table.csv  — per (level, hour_bucket) summary
- site/data/atr-cascade.json     — page payload incl. time-to-next histograms + per-day paths
- site/atr-cascade.html          — interactive explorer (heatmap + path builder)
- site/cheatsheet-atr-cascade.html

### TODO before promoting
1. Stratify by ATR-environment (low/normal/high daily ATR vs 21d-avg)
2. Stratify by gap-size (gap up/down/flat) — gap days behave differently at the open
3. FOMC/CPI day exclusion
4. Cross-check first-hit detection at gap-over levels (touch vs directional rule)
5. Add a "given prior path" version (e.g., conditional on having hit -trigger first)

## 16. MULTI-DAY GG BY WEEKDAY (SPX, weekly ATR — published 2026-06-06)
Question: when the weekly-ATR GG first OPENS (±38.2%) on a given weekday, how does the
chance it COMPLETES (±61.8%) by Friday evolve? Symmetric up vs down? Continuation?
Data: FirstRateData SPX cash daily, 2000-11→2026-05, 1,313 weeks. Levels = prior weekly
close + 1-week-lagged weekly Wilder ATR(14). Each direction scored independently per week.
Upside gate opens in 54% of weeks, downside 50%, both 14%.

Completion (±61.8% same week) decays with later open — mostly the clock confound
(Mon≈5 sessions left, Fri=1). Completion is fast: median ~1 session open→complete.
| Open day | Up completes | Down completes | Up same-day | Down same-day |
|----------|-------------|----------------|-------------|---------------|
| Mon | 78.2% | 73.7% | 24.3% | 38.0% |
| Tue | 64.9% | 66.7% | 20.9% | 28.6% |
| Wed | 62.7% | 66.7% | 24.6% | 36.7% |
| Thu | 41.2% | 55.1% | 17.5% | 37.1% |
| Fri | 15.5% | 38.8% | 15.5% | 38.8% |
Overall: up 60.2% / down 65.2% complete.

NOT symmetric — downside is faster & harder:
- Same-day completion (time-independent): down ~35-38% EVERY weekday vs up ~15-25%.
- Late-week survival: Thu/Fri down completes 55%/39% vs up 41%/16%.
- Continuation given completion: down 70.6%→78.6% & 41.4%→full ATR vs up 64.0% & 32.7%.
  Continuation strongest for early-week opens (Mon up→full ATR 46%, down 54%; Thu+ ~none).
"Stairs up, elevator down" holds on the weekly frame.

### Output files
- backtest_spx_multiday_gg_dow.py
- analyst/spx_multiday_gg_dow_events.csv  — one row per (week, direction) opened event
- analyst/spx_multiday_gg_dow_summary.json
- site/data/spx-multiday-gg-dow.json + site/spx-multiday-gg-dow.html (interactive, direction toggle)

## 17. SWING GG BY WEEK-OF-MONTH + TRIGGER/PIVOT RETRACEMENT (SPX, monthly ATR — built 2026-06-07)
Question A (week-of-month): when the monthly-ATR (Swing) GG first OPENS (±38.2%) in week
1/2/3/4 of the calendar month, how does the chance it COMPLETES (±61.8%) by month end evolve?
Question B (retracement = the headline): once a gate opens, price often bounces back toward
the pivot. Does retracing to the same-side trigger (±23.6%) or the monthly pivot (0-ATR line
= prior month close, PMC) INVALIDATE the gate, or is it merely a good re-entry? (Downside
gate → put trigger; upside gate → call trigger, per request.)
Data: FirstRateData SPX cash daily; 293 months analyzed (2002-01→2026-04). Levels = prior-month
close + 1-month-lagged monthly Wilder ATR(14). Each direction scored independently per month.
Daily bars (no intraday tie-break; same-day open+complete events broken out separately).
CLOCK-TRUNCATED EXCLUSION (added 2026-06-07): a gate opening with < 5 trading sessions left in
the month can't fairly reach 61.8% before the level resets, so those opens are dropped from ALL
reported rates — 11 upside, 13 downside (every week-4/5 open). Counted gates: up 166, down 126.

A) WEEK-OF-MONTH — fair-window gates only (clock-truncated dropped). The late-month collapse is
gone; what remains is a mild early-month edge plus a real upside week-3 dip:
| Open week | Up completes (medRem) | Down completes (medRem) |
|-----------|-----------------------|-------------------------|
| Week 1 | 41 of 55 (74.5%, 19) | 51 of 68 (75.0%, 19) |
| Week 2 | 44 of 60 (73.3%, 15) | 20 of 37 (54.1%, 15)* |
| Week 3 | 13 of 42 (31.0%, 9)* | 10 of 16 (62.5%, 9)* |
| Week 4 | 3 of 9 (33.3%, 7)*  | 2 of 5 (40.0%, 6)* |
Overall completion by month end: up 101 of 166 (60.8%) / down 83 of 126 (65.9%). Continuation
given completion: down 65 of 83 (78.3%) to 78.6% & 41 of 83 (49.4%) to full ATR vs up 58 of 101
(57.4%) & 26 of 101 (25.7%) — same "stairs up, elevator down" downside dominance. (* n<50)

Fixed-horizon control — completes within 5 trading sessions of the open (open session + next 4):
up 56 of 166 (33.7%) / down 60 of 126 (47.6%). Among the kept (fair-window) gates this sits at or
below the by-month-end bar by construction. The clock-truncated opens we removed are exactly the
ones whose 5-day rate exceeded their by-month-end rate (e.g. removed downside week-4 opens
completed 9% by month end but ~36–62% within 5 sessions) — confirming their non-completion was
the calendar, not the setup. (Replaced the earlier same-day-completion metric per request.)

B) RETRACEMENT — read as LIFT vs each side's baseline (up 60.8% / down 65.9%), NOT raw rate:
| Retrace depth before completion | Up: completes (lift) | Down: completes (lift) |
|---------------------------------|----------------------|------------------------|
| No bounce to trigger | 50 of 56 (89.3%, +29) | 10 of 10 (100.0%, +34) |
| Bounced to trigger (±23.6%) | 32 of 60 (53.3%, −8) | 39 of 45 (86.7%, +21) |
| Bounced to pivot (0 line / PMC) | 6 of 22 (27.3%, −34)* | 15 of 23 (65.2%, −1)* |
| Crossed to OPPOSITE trigger | 3 of 18 (16.7%, −44)* | 3 of 32 (9.4%, −57)* |
- The ROBUST findings (hold under sensitivity, see caveat): (1) the same-side **trigger** is
  ASYMMETRIC — a shallow pullback to the put trigger is *tolerated* on the downside (+21 lift,
  87%) but *damaging* on the upside (−8 lift, and worse under the stricter window); (2) crossing
  past the pivot to the OPPOSITE trigger ≈ death both ways (9–17%).
- The downside-pivot "good entry" reading is NOT supported: 65.2% is ~baseline (−1 lift) and goes
  NEGATIVE when the open day is excluded from the retrace window. By the time price is back at the
  pivot the edge is gone in BOTH directions — the pivot is the invalidation boundary, not a
  re-entry. Only the same-side *trigger* differs by direction.
- ⚠ Daily-bar caveat: the retrace window includes the OPEN day, whose intraday high/low may
  predate the open — contaminating the bucketing. Excluding the open day (oi+1) reclassifies
  54/292 fair-window events and moves the thin buckets (up-trigger 53→35%, up-pivot 27→11%,
  down-trigger 87→76%, down-pivot 65→56%); the trigger asymmetry and opposite-trigger-death
  survive. pivot/opposite buckets are n<50. **Question B's exact rates are not robust on daily
  bars — the definitive test needs intraday (1-min SPX, 2008+) ordering.**

SPEED PREDICTOR (downside, fair-window set; backtest_swing_gg_wom_predictors.py): how fast price
traverses put-trigger(−23.6%)→gate(−38.2%) modestly predicts completion. Base 83 of 126 (65.9%).
Fast (≤1 session) 55 of 79 (69.6%, +4) vs slow (≥2) 28 of 47 (59.6%, −6). Survives holding
days-left fixed (>10 left: fast 54 of 77 = 70% vs slow 20 of 32 = 63%) and mirrors on the upside
(fast 40 of 55 = 73% vs slow 61 of 111 = 55%). Smaller edge than the trigger-retrace asymmetry;
EMA slope / price-vs-EMA were within a few points of base.

### Output files
- backtest_swing_gg_wom.py
- analyst/swing_gg_wom_events.csv  — one row per (month, direction) opened gate
- analyst/swing_gg_wom_summary.json
- site/data/swing-gg-wom.json + site/spx-swing-gg-wom.html (published, linked from home)
- Reviewed by Codex 2026-06-07: Question A sound (clock + travel-speed confound); Question B
  headline downgraded — see lift framing + daily-bar caveat above.
