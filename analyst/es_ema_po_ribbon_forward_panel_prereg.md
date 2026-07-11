# Pre-registered forward REPLICATION panel: QQQ + IWM, 2026-01-26 → present

**Written 2026-07-10, before fetching or examining any QQQ or IWM intraday
data.** Neither instrument has been used anywhere in this study (rounds 1–5b
used ES; the holdout used NQ; the first forward check used SPY). The scoring
window post-dates the ES/NQ data end (2026-01-23), so this is temporal AND
cross-instrument out-of-sample.

## Why this exists

The SPY forward window (already run, t=1.56, +0.368 pts/trade over 66 trades)
was pre-registered as a consistency check with no pass declarable. This panel
is the replication test for that result. QQQ and IWM trade the same days as
SPY, so pooling adds breadth (imperfectly correlated indices), not fully
independent days — stated plainly: a common macro regime could still drive all
three. What this panel CAN rule out is an SPY-idiosyncratic fluke.

## Frozen spec

Identical signal/exit pipeline to analyst/es_ema_po_ribbon_holdout_prereg.md.
Data: Massive 1-min aggregates, adjusted, 2025-10-01 → present, single source.
Scoring window: entries 2026-01-26 onward.

Instrument constants (cost-multiple rule, threshold = 6.45 × round-trip cost,
set before fetching):
- QQQ: cost 0.03 pts RT (1c spread + 1c slip + fees) → 3m ATR14 ≥ 0.19
- IWM: cost 0.02 pts RT (lower price, 1c spread)     → 3m ATR14 ≥ 0.13

## Pass criteria (fixed now)

REPLICATION PASS requires ALL of:
1. QQQ forward-window mean net P&L per trade > 0
2. IWM forward-window mean net P&L per trade > 0
3. Pooled QQQ+IWM day-clustered t ≥ 1.0
   (power-calibrated: expected ≈ 1.2–1.5 if the SPY-sized effect is real;
   ~16% false-pass under null on this leg alone, acceptable because it is a
   replication of an existing positive, not a solo discovery)

If PASS: the strategy is labeled **"works, pending continued forward
monitoring"** — the strongest label this study will assign until the standing
forward test reaches full power. If FAIL: the SPY forward result is demoted to
likely-luck and the study's verdict reverts to "no confirmed edge"; no rescue.

Runner: analyst/es_ema_po_ribbon_forward_panel.py
