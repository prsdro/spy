# Pre-registered FORWARD consistency check: ribbon-riding long on SPY, 2026-01-26 → present

**Written 2026-07-10, before fetching or examining any SPY data after
2026-01-23.** The ES/NQ files end 2026-01-23; every one of the 164 configs and
the NQ holdout used only data through that date. SPY bars after it are
temporally out-of-sample with respect to the entire study.

## What this can and cannot show (stated before running)

Power analysis from the ES in-sample estimate: per-signal-day mean/sd ≈ 0.06,
~66 signals/yr → over ~5.5 months (~28 expected trades) the expected
day-clustered t of a FULLY REAL ES-sized edge is ≈ 0.4–0.5. Therefore this
window **cannot confirm** the strategy at any conventional threshold, and no
PASS will be declared from it. It is a consistency check:

- reported: n, avg net, day-clustered t, win rate, equity path;
- avg net > 0 → "consistent with the ES estimate, still unconfirmed";
- avg net < 0 with t ≤ −1 → active evidence against;
- anything else → uninformative, as expected from power.

The honest confirmation gate remains a standing forward test as data accrues
(≥ ~2 years at this signal rate for 80% power at t ≥ 1.5).

## Frozen spec

Identical pipeline and signal to analyst/es_ema_po_ribbon_holdout_prereg.md
(dual-TF bull EMA stack, 3m PO compression → rising expansion arm, market
entry next 1-min open in windows 09:30–12:00 / 15:00–15:45 ET, exit after two
consecutive 3m closes below the 10m EMA21, 2.5×ATR14(3m) intrabar stop,
EOD flat 15:59 ET).

Instrument constants (set by rule, not by the new data):
- SPY ATR filter: price-scale mapping ES→SPY (≈÷10): **3m ATR14 ≥ 0.20 SPY
  pts** (cost-multiple rule 6.45 × 0.03 = 0.19 agrees).
- SPY cost: **0.03 SPY pts round trip** (1c spread + 1c slippage + fees).
- Data: Massive 1-min SPY aggregates, adjusted, fetched 2025-10-01 → present
  (single source, warmup ≥ 200 3m bars before the scoring window).
- Scoring window: entries from **2026-01-26** (first trading day after the
  ES data end) onward only.

Runner: analyst/es_ema_po_ribbon_forward_spy.py
