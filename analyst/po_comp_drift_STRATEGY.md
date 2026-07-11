# Compression-Drift Continuation — ES/NQ 3m Day-Trading Strategy

**Status: validated candidate** (in-sample discovery → pre-registered NQ
holdout PASS → 5.5-month forward test in line). Finalized 2026-07-10.

## The signal (3-minute chart, RTH 09:30–15:59 ET)

1. **Compression episode**: Saty compression (BB-squeeze tracker) on for ≥8
   consecutive 3m bars (a single 1-bar flicker off doesn't break the run).
2. **Drift**: take the high/low set by the episode's first 5 candles. The
   episode is *drifting* when later compression candles breach that range by
   ≥0.50×ATR14 on one side while the other side holds within 0.25×ATR14.
   The breach side is the drift direction.
3. **Expansion**: the first bar where compression turns off. Direction =
   that bar's close vs the midpoint of the last 5 compression bars' range.
4. **Trade only if expansion direction == drift direction** ("aligned").
   Skip flat episodes (failed holdout as a system), mixed episodes, and
   anti-drift expansions.
5. **Volatility gate** (why the edge clears friction): 3m ATR14 ≥ 6.45× the
   round-trip cost — **ES: ATR ≥ 2.0 pts; NQ: ATR ≥ 2.6 pts**.

## Execution

- **Entry**: market at the next 3m bar's open after the expansion bar closes
  (everything is known at that close). Same session only.
- **Stop**: 1.0× the **3-minute ATR14** (value at the expansion bar) adverse,
  intrabar. NOT the daily ATR — every ATR in this document is the 3m-bar ATR.
  Typical stop distance on ES: median ~3.5 pts (~$173/contract), IQR 2.6–5.1,
  p90 ~7 pts; 2024+ median ~4 pts. Size = risk budget ÷ ATR.
- **Exit**: stop, or market-on-close of the session. No target, no trail —
  targets and trails were tested and destroy the edge (the P&L lives in the
  EOD runners).
- **Costs assumed**: ES 0.31 pts RT, NQ 0.405 pts RT (1 tick slip + comms).

## What to expect (be honest with yourself before trading it)

- **Win rate ≈ 20–25%.** Four of five trades stop out at −1 ATR. All the
  profit is in the minority of runners held to the close. Expect losing
  streaks and losing months at any size.
- ES 2008–2026: n=2,558 (~135/yr), +0.91 pts net/trade (~$45), day-clustered
  t=2.93, shorts stronger than longs (+1.28 vs +0.56 pts).
- NQ holdout (specs frozen first): n=4,450, +2.46 pts net (~$49), t=2.85,
  both sides positive. Max DD 1,522 NQ pts over 18 yrs — size accordingly
  (MNQ/MES first).
- Forward 2026-01-26→07-10 (data unseen by all fitting): 273 trades,
  +$83/trade combined 1 ES + 1 NQ, monthly swings −$13k…+$31k.

## Why 3m (timeframe sweep, ES)

Structure (flat continues > aligned continues > opposed weak) replicates on
1m, 3m, and 10m — the mechanic is not a timeframe artifact. Net of friction
the tradeable edge peaks at 3m: day-clustered t = 1.46 (1m) / **3.04 (3m)** /
1.07 (10m) for the same rules at ATR≥2.

## Things measured and rejected (don't re-add them)

- **Fading a drifting compression's breakout** (the original mean-reversion
  hypothesis): drift direction dominates; rejected, 10,648 episodes.
- **Flat-break system** (Config A): best per-event stats but FAILED the
  pre-registered NQ holdout (t=1.42 < 1.5, shorts ~0). Chart context only.
- **10m confluence filter** (same-dir = trade / opposite = skip / comp =
  half size): would have ~halved P&L; buckets not separable. Run unfiltered.
- **Fixed targets, trailing stops, fixed-bar exits** on Config B: all worse
  than stop-else-EOD.

## Evidence chain (scripts)

`backtest_es_po_comp_drift.py` (event study) →
`backtest_es_po_comp_drift_strategy.py` (execution grid) →
`analyst/es_po_comp_drift_atr_filter.py` (cost-multiple ATR gate) →
`analyst/es_po_comp_drift_10m_confluence.py` (confluence rejected) →
`analyst/es_po_comp_drift_holdout_prereg.md` + `_holdout_nq.py` (frozen
holdout) → `analyst/es_po_comp_drift_forward_2026.py` (forward test, data via
Massive `futures/v1`, rerunnable top-up: `analyst/fetch_futures_forward_2026.py`)
→ `backtest_po_comp_drift_tf_sweep.py` (1m/10m sweep).

## Next gates before real size

1. Live/paper tracking (bilbo-scanner-style cron alerting aligned expansions).
2. Re-run the forward script quarterly as new data accrues.
3. Portfolio sim with overlap dedupe + daily-loss cap at intended size.
