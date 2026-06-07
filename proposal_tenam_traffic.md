# Proposal: TenAM Traffic PO Divergence Backtest (3-min SPY)

## Indicator (the thing we're testing)

Pine indicator `Traffic Signal PO Divergence` by TenAMTrader. It reads an oscillator
source (intended use: Saty Phase Oscillator) and detects four types of pivot-to-pivot
divergences between price and the oscillator:

1. **Regular Bullish (🟢)**: price LL + osc HL → predicted reversal up
2. **Hidden Bullish (🟡)**: price HL + osc LL → predicted continuation up
3. **Regular Bearish (🔴)**: price HH + osc LH → predicted reversal down
4. **Hidden Bearish (🟡)**: price LH + osc HH → predicted continuation down

Default Pine inputs (we will mirror these):
- `lbL = 1`, `lbR = 3` — pivot detection: 1 bar left, 3 bars right
- `rangeLower = 0`, `rangeUpper = 60` — previous pivot must be within 0–60 bars
- Zone filters A and B default OFF (we test with them off; revisit later as a filter)
- `delay_plot_til_closed = false` — Pine fires on intrabar; for the backtest we treat
  every signal as confirmed (bar-close), since intraday repaint isn't relevant to
  historical hit-rate tests

## Hypothesis
On 3-minute SPY bars, divergence signals between price and the Saty Phase Oscillator
produce a tradable forward edge:
- Regular divergences should produce a reversal beyond the current pivot extreme
- Hidden divergences should produce continuation in the prevailing trend

We measure each signal against the bar-by-bar baseline of "what happens after a random
3-min bar at this time of day," and look for filters (time of day, PO zone at signal,
pivot ribbon trend, ATR-level location) that meaningfully improve hit rate.

## Data
- Table: `ind_3m`
- RTH only: 09:30–15:59 ET
- Range: 2000-01-03 → 2025-10-21 (~6,500 sessions)
- Oscillator source: `phase_oscillator` (matches Saty PO on 3m bars; documented to be
  accurate on 10m bars, no specific TV validation on 3m — flag this caveat in writeup)
- Per-session reset: pivot tracking restarts each session. We do NOT carry pivots
  overnight because (a) the indicator's range filter (60 bars) effectively makes them
  irrelevant anyway, and (b) overnight ATR data is unreliable

## Signal-detection implementation
1. Group bars by `date`.
2. Per session: compute pivot lows / pivot highs of `phase_oscillator` using a
   centered window of size `lbL + 1 + lbR = 5`. A pivot low at index `i` requires
   `osc[i] < osc[i-1]` and `osc[i] < osc[i+1..i+3]` — strict inequality both sides.
   Confirmation bar is `i + lbR = i + 3` (i.e., signal becomes actionable 3 bars
   after the pivot itself).
3. Track previous pivot per session: previous pivot value, previous pivot price
   (low for pivot lows / high for pivot highs), and bars-since-previous.
4. Apply range filter: drop signals where bars-since-previous > 60 or < 0.
5. Classify divergences using indicator's exact comparisons:
   - bull: `price_low_now < prev_low` AND `osc_now > prev_osc`
   - hidden bull: `price_low_now > prev_low` AND `osc_now < prev_osc`
   - bear: `price_high_now > prev_high` AND `osc_now < prev_osc`
   - hidden bear: `price_high_now < prev_high` AND `osc_now > prev_osc`

## Outcome metrics (per signal)
Measured from the close of the **confirmation bar** (bar `t`, where pivot was at `t−3`).
A trader sees the signal at close of bar `t`; the entry assumption is open of bar `t+1`
or close of bar `t` (we'll use close of bar `t` to align with the indicator's plot).

Forward windows: 5, 15, 30, 60 bars, plus EOD-RTH-close.

Per signal we compute:
- **MFE / MAE** in dollars and as % of ATR(14)
- **Hit rate to fixed % targets** in the predicted direction:
  - Bull: +0.1%, +0.25%, +0.5%, +1.0%
  - Bear: −0.1%, −0.25%, −0.5%, −1.0%
- **Hit rate to ATR levels**: did price reach the next ATR level in the predicted
  direction (e.g., bull signal below upper trigger → did upper trigger hit; bull
  signal above upper trigger → did 38.2% hit)
- **Stop-out**: did price exceed the local pivot extreme against the signal before the
  signal worked (e.g., bull signal made a fresh lower low)
- **EOD bias**: did price close higher than signal price (bull) / lower (bear)
- **Bars to target** (for the +0.25% target as a representative move): median, 25/75
  pct, % done within 30 bars

## Cross-cuts
For each signal type, slice by:
- **Time-of-day** half-hour buckets (09:30, 10:00, 10:30, …, 15:30) — the indicator's
  author handle suggests post-10am bias; we'll see if the data supports it
- **PO zone at signal** (extended_down, accumulation, neutral_down, neutral, neutral_up,
  distribution, extended_up)
- **Pivot Ribbon trend state** at signal: fast cloud bullish/bearish × slow cloud
  bullish/bearish (4 buckets)
- **ATR-level location of signal price**: above/below trigger, in golden gate, etc.
- **Optional zone filter A** (osc in 23.6–61.8) and **filter B** (osc in −61.8 to −23.6):
  do these "don't-take-signals-in-this-band" filters actually improve outcomes?

## Baseline comparison
For each time-of-day bucket, compute the "random bar" baseline forward MFE/MAE/hit-rate
using all RTH 3m bars (or a stratified sample). Edge = signal hit-rate minus baseline.
This guards against "signals just happen at trendy times of day."

## Sample-size guardrails
- Flag any cell with n < 50
- Refuse to draw conclusions from cells with n < 20

## Outputs
1. `backtest_tenam_traffic.py` — analysis script
2. JSON cache of per-signal records for downstream visualization
3. Console-printable summary tables (headline hit rates, time-of-day, PO-zone, ribbon)
4. Findings appended to `analyst/studies_reference.md` as new section
5. KNOWLEDGE.md updated with key results
6. Optional follow-up (ask user): HTML visualization page like `/ema21-reversion.html`

## Open questions for codex review
1. **Pine pivot semantics**: Pine's `ta.pivotlow(source, lbL, lbR)` — is the comparison
   strict `<` on both sides, or `<=` on the right side? My read of the docs is strict
   on both sides, but if codex knows otherwise we should match exactly. (Effect on our
   sample size will be small either way.)
2. **Bar alignment for `valuewhen`**: Pine's `ta.valuewhen(plFound, osc[lbR], 1)` returns
   the previous occurrence's value at its confirmation bar. My implementation tracks the
   previous pivot's value and price at confirmation — should be equivalent.
3. **RTH cleanliness**: 3m bars at 09:30 are the first RTH bar; should the first
   30 minutes get a warmup gate so we don't fire on incomplete oscillator state? My
   current plan keeps them in but flags a "first-30-min" subset in cross-cuts.
4. **Forward measurement window for last-half-hour signals**: signals at 15:30+ have
   a truncated window. We'll cap at RTH close and report sample-size caveats.
5. **Oscillator accuracy on 3m**: documented to be good on 10m. Worth a quick
   validation pass against the 10m PO and decide if 3m PO is reliable enough.

## Plan summary
1. Write `backtest_tenam_traffic.py` per spec above
2. Run + sanity-check signal counts & basic outcome stats
3. Investigate cross-cuts; identify any high-edge filter combinations
4. Compose study writeup; append to `studies_reference.md`
5. Update `KNOWLEDGE.md`
6. Offer HTML viz to user
