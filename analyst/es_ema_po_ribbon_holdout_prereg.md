# Pre-registered holdout: EMA/PO ribbon-riding long → NQ

**Written 2026-07-10, BEFORE running anything on NQ data for this study.**
NQ 1-min (FirstRateData continuous ratio-adjusted, 2008-01 → 2026-01) has not
been touched by any round of the EMA/PO pullback study (rounds 1–5b). All
discovery was done on ES only.

## Mining pressure (disclosed)

163 configurations were examined on ES across five rounds before this
candidate emerged (1 base + 34 + 42 + 14 + 48 + 24). The candidate is the only
cell meeting the in-sample bar (net>0, both era halves>0, day-clustered t≥2,
beats matched baseline). Mitigation: the cell tops a monotone, mechanism-
coherent gradient (slower exit > faster, wider stop > tighter, ATR filter
helps everywhere, longs only) rather than being an isolated spike, and this
cross-instrument test is fully out-of-sample w.r.t. every parameter choice.
NQ is correlated with ES over the same period, so a regime artifact could
still pass — a temporal forward test remains the final gate.

## Frozen spec (no changes permitted after this file is written)

Pipeline: 1-min RTH 09:30–15:59 ET, bars with range > 3% of close dropped,
resampled to 3m and 10m (label=left, closed=left). EMA9/EMA21 on both TFs,
ATR14 (Wilder, ewm alpha=1/14) and Saty Phase Oscillator + compression flag
(indicators.py definition) on the 3m series. 200-bar warmup. All signals on
completed bars; 10m state = last fully closed 10m bar.

Signal (long only):
1. 10m EMA21 rising, 10m EMA9 rising and above 10m EMA21;
   3m EMA21 rising and above 10m EMA21; 3m EMA9 rising and above 3m EMA21.
2. 3m PO compression flag on → WATCH.
3. Compression ends with oscillator rising while (1) holds → ARMED.
   Disarm if (1) fails or a 3m close < 3m EMA21; new compression → WATCH.
4. Entry: market at the open of the next 1-min bar while ARMED, inside
   entry windows 09:30–12:00 or 15:00–15:45 ET, provided 3m ATR14 ≥ threshold
   at the last completed 3m bar. Arm consumed on entry; one position at a time.

Exit:
- Ribbon: after TWO consecutive completed 3m closes below the 10m EMA21,
  exit at the next 1-min bar open.
- Disaster stop: entry − 2.5 × ATR14(3m at entry), checked intrabar on 1-min
  lows, stop-first, gap-through fills at open.
- Force flat at the open of the last RTH minute (15:59 ET).

## Instrument constants (set from cost math, not from NQ results)

- NQ cost: 1 tick (0.25 pt) slippage + $3.10 commission at $20/pt
  = **0.405 NQ pts round trip**.
- ATR filter, same cost-multiple as ES (2.0 / 0.31 = 6.45×cost):
  **3m ATR14 ≥ 2.6 NQ pts**.

## Pass criteria (same as the compression-drift holdout)

PASS = average net P&L per trade > 0 AND day-clustered t ≥ 1.5 on NQ,
full sample 2008 → 2026-01. No rescue analysis if it fails: the config is
demoted to unconfirmed and the study result stands as "no confirmed edge."

Runner: analyst/es_ema_po_ribbon_holdout_nq.py (imports the frozen round-5b
simulator; only COST/ATR_MIN/data-path differ from the ES run).
