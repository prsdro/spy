# Pre-registered holdout: 3m compression-drift strategy → NQ

**Written 2026-07-10, BEFORE running anything on NQ data.** NQ 1-min
(FirstRateData continuous ratio-adjusted, 2008-01 → 2026-01) has not been
touched by any part of this study. All discovery was done on ES only.

## What this is and isn't

NQ over the same period is a **cross-instrument robustness test**, not a
temporal holdout — NQ and ES are correlated, so a regime-driven artifact could
pass. It is, however, fully out-of-sample with respect to every parameter
choice (thresholds, exits, ATR filter), which is where the mining risk lives.
A true forward test would follow if this passes.

## Frozen specs (no changes permitted after this file is written)

Common pipeline: 1-min RTH 09:30–15:59 ET, bars with range > 3% of close
dropped, resampled to 3m. EMA21/ATR14(Wilder)/PO/Saty compression tracker
computed on the RTH-only 3m series, 200-bar warmup. Episodes: contiguous
compression=1 runs, 1-bar gap tolerance, ≥8 bars, expansion bar in-session.
Classification: first-5-bar range; flat = both-side breach < 0.25 ATR;
drift = one side ≥ 0.50 ATR, other < 0.25 ATR (ATR at expansion bar).
Expansion direction: expansion-bar close vs midpoint of last-5 compression
bars' range (PO-sign tiebreak). Entry: next 3m bar open, same session.

**Config A — flat_break/fix10**: flat episodes, enter expansion direction,
exit at close of the 10th bar after entry, or session close, whichever first.

**Config B — aligned_cont/brk10**: drift episodes with expansion aligned to
drift, enter expansion direction, stop 1.0×ATR14 adverse (conservative:
stop checked before anything else intrabar, gap-through fills at open),
else exit at session close.

## Instrument constants (set from cost math, not from NQ results)

- NQ cost: 1 tick (0.25 pt) slippage + $3.10 commission at $20/pt
  = **0.405 NQ pts round trip**.
- ATR filter, same cost-multiple as ES (2.0 / 0.31 = 6.45×cost):
  **3m ATR14 ≥ 2.6 NQ pts**. (Expected to bind rarely on NQ — its point
  scale is larger; that is the honest consequence of the cost-ratio rule.)

## Pass criteria (per config, decided now)

1. Average net P&L per trade > 0.
2. Day-clustered t-stat of net P&L ≥ 1.5.

Both configs judged independently. A config failing either line is a FAIL —
no post-hoc filters, exit tweaks, or subperiod selection may rescue it.
Reported-but-non-gating diagnostics: long/short split, first/second half,
gross edge in ATR units (comparison vs ES: flat fix10 gross ≈ +0.35 ATR,
aligned brk10 gross ≈ +0.29 ATR at ATR≥2), trades/yr, max drawdown.

## ES in-sample reference (what NQ is being compared against)

- A: ES n=218, +2.41 pts net avg, day-clustered t=2.36.
- B: ES n=2,558, +0.91 pts net avg, day-clustered t=2.93.
