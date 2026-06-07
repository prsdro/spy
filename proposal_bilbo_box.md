# Bilbo Box Breakout Study — Final Design

Codex reviewed the first draft and flagged five blocking issues plus a few
nice-to-haves. This revised version addresses all of them.

## Hypothesis

When the Saty Phase Oscillator enters compression, price consolidates into
a range (the "Bilbo Box"). Once price breaks out of that range, it tends
to follow through in the direction of the break. This study measures
follow-through (max profit, max drawdown, net move) over the next 5, 10,
and 15 bars, across multiple timeframes, and compares three entry variants:

1. **Immediate** — enter as soon as price trades outside the box
2. **Close outside** — wait for one full candle to close outside the box
3. **Retest** — wait for price to come back and touch the box boundary
   after the break

## Timeframes

- `ind_3m`   — intraday, RTH-only (09:30–15:59). Forward window truncated
  at session end.
- `ind_10m`  — intraday, RTH-only. Forward window truncated at session end.
- `ind_1h`   — all-hours bars, multi-session forward windows allowed.
  **Caveat**: per KNOWLEDGE.md the hourly Phase Oscillator has a known
  20–45% accuracy gap vs TradingView due to extended-hours ATR inflation,
  so the compression signal on this timeframe is less reliable. Reader
  should discount 1h findings accordingly.
- `ind_4h`   — all-hours bars, multi-session forward windows allowed.
- `ind_1d`   — RTH-only (daily tables are already session-filtered).
  Multi-day forward windows.

`ind_1m` skipped (noise). `ind_1w` skipped (sample too small).

## Event Construction

### Box formation (5-bar cap, exclusive)

1. First bar with `compression=1` after a `compression=0` run → box opens.
2. The first **5 contiguous bars** (bars 1..5 of the box) define the
   range. `box_high = max(high[1..5])`, `box_low = min(low[1..5])`.
   Break-watch begins on bar 6.
3. Early-exit case: if `compression` turns `0` before bar 5 (say at
   bar `j < 5`), the box uses bars 1..j-1 (last compression bar). 
   **Break-watch then begins on bar j** (the expansion bar itself — we
   know at bar `j`'s close that compression has ended, so bar `j+1` is
   the first fully-observable break-watch bar). To be safe and avoid
   same-bar look-ahead, break-watch always starts at `lock_bar + 1`.

### Break detection (strictly forward from lock+1)

Step through bars `lock_bar + 1` onward up to `BREAK_LOOKBACK=20` bars:

- `bar.high > box_high` → bullish break (break price = `box_high`)
- `bar.low  < box_low`  → bearish break (break price = `box_low`)
- **Outside bar** (both boundaries pierced on the same bar): treat as
  stopped-out first (worst-case). Classify the break direction by which
  boundary `close` is on, but flag `ambiguous_outside_bar=True` and
  exclude these events from the main immediate-variant stats. They're
  counted separately.
- **Gap-through bar** (bar opens beyond the box boundary): entry for
  the immediate variant must use `bar.open`, not `box_high/low`. Flag
  `gap_through=True`.

If no break within 20 bars, discard the event (expired box).

### Stale-box rollover

If a new compression period starts while an old box is still live
(waiting for break), the new compression **replaces** the old box. The
old event is discarded as expired. This prevents overlapping episodes.

### Entry variants (each with its own eligibility)

For each break event, we evaluate three entries independently:

1. **Immediate**
   - Entry bar = break bar
   - Entry price = `box_high`/`box_low` normally, or `bar.open` on a
     gap-through
   - Eligible: every non-ambiguous break event
2. **Close outside**
   - Walk bars from the break bar onward up to `CLOSE_CONFIRM_LOOKBACK=5`
   - Entry bar = first bar whose `close` is beyond the broken boundary
     in the break direction
   - Entry price = that bar's close
   - Eligible: events where confirmation fires within 5 bars
3. **Retest**
   - Walk bars from the bar after the break bar onward up to
     `RETEST_LOOKBACK=10`
   - Entry bar = first bar that trades back to the broken boundary
     (`low <= box_high` for bull; `high >= box_low` for bear)
   - Entry price = `box_high`/`box_low`
   - Invalidation: if price reaches the **opposite** box boundary before
     the retest, the retest is abandoned
   - Eligible: events where retest fires before invalidation

Each variant reports both its **trigger rate** (share of all break events
that fire the variant) and its conditional MFE/MAE/net. This gives a
real apples-to-apples comparison.

### Outcome measurement

Forward windows: **5, 10, 15 bars after entry bar** (each variant starts
its own timer at its own entry). Windows are truncated per variant so
intraday events never spill past 15:59.

Metrics (from entry price, in SPY points **and** in R-multiples):

- `max_profit_pts` = max favourable excursion
- `max_drawdown_pts` = max adverse excursion
- `net_pts` = `close_at_end - entry_price`, signed by direction
- `R` = `box_high - box_low` (the stop distance if you use opposite
  boundary). Normalised metrics: `max_profit_R = max_profit_pts / R`,
  `max_drawdown_R = max_drawdown_pts / R`, `net_R = net_pts / R`.
- `stopped_out` = bool, whether opposite-box boundary touched before
  window end. Worst-case ordering: if a bar's range spans both targets,
  it stops out first.

R-multiples are the primary metric for cross-timeframe ranking since
point moves are apples-to-oranges across 3m and 1d.

## Segmentation (reported per timeframe)

- **Overall**: n, bull/bear split, mean & median metrics, % net > 0,
  stop-out rate
- **By entry variant**: trigger rate, conditional metrics
- **By direction**: bull vs bear
- **By box width / ATR** (normalised): narrow / medium / wide terciles
- **By EMA trend at break**: `ema_21 vs ema_48` (in-trend vs counter-trend)
- **By time-of-day of break** (intraday only): open / mid / close
- **By compression duration** when box locked (1, 2, 3, 4, 5 bars). Note:
  1-bar boxes are the degenerate case where compression was only active
  on the start bar and ended the next bar; these are kept because they
  turned out to carry material edge.

## Sample-size guardrails

- `n < 50`: flag cautiously
- `n < 20`: don't report

## Output

- Stdout: per-timeframe summary tables
- Event-level data: `analyst/bilbo_box_events.csv`
- JSON summary for the HTML page: `analyst/bilbo_box_summary.json`
- Run log: `analyst/bilbo_box_run.log`

## Decisions explicitly made

- The user's `690 → 680.5 → 691 = 0.5 drawdown` example is arithmetically
  inconsistent (680.5 drawdown would be 9.5). Assumed they meant 689.5.
  Flagged for user.
- "Compression exit = break" (per user's wording) is rejected. Break
  requires actual range exit; compression state flipping is only a volatility
  signal, not a directional decision.
- Break-watch always starts at `lock_bar + 1` — never using same-bar
  information to detect breaks.
- Worst-case same-bar resolution when both stop and break are touched on
  the same bar: stop wins.
- Stale-box rollover: new compression always kills prior pending box.
