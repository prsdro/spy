# Codex consult: PO-compression options study — review + fresh ideas

## Your role and posture (important)

You are a collaborating quant, not a referee. The mission is FIND AND AMPLIFY
edge. Bug-hunting is in scope ONLY where a bug would change a conclusion
(lookahead, fill logic, sign errors, clustering mistakes) — finding those makes
the edge real, so hunt hard. What is NOT wanted: generic caveat lists
(overfitting/multiple-comparisons/regime lectures) — we know; one line each at
the end, max. For every concern you raise, propose the experiment that
resolves it. For every promising number, propose how to make it bigger.

## Context

Saty Phase Oscillator hourly compression episodes on mega-caps → real historical
option prices (Massive/Polygon minute trade prints; no quotes/greeks).
User (Pedro) trades Saty-style: ribbon (EMA 9/21/34), PO compression, ATR levels.

Read in this order:
1. `analyst/po_comp_options/NOTES.md` — design decisions, lookahead trap
2. `analyst/po_comp_options/RESULTS.md` — all findings incl. random-entry control
3. Code: `backtest_po_comp_options.py` (leg engine), `backtest_po_comp_bilbo.py`
   (box variants), `analyze_po_comp_options.py`, `scratch_po_comp_random_baseline.py`,
   `fetch_po_comp_options.py` (data pull)

Data: `analyst/po_comp_options/option_bars.sqlite` (contracts + minute bars;
a v2 expansion pull is APPENDING to it right now — treat as read-only),
`trades.parquet` (10,680 legs × exit-rule P&L columns), `bilbo_trades.parquet`
(7,507 legs), `random_baseline_trades.parquet`, `events.csv` (186 episodes),
`straddles.parquet`. events_v2.csv (8 tickers × 24mo) landing within the hour.

## Current live leads (edge vs random baseline, not vs zero)

1. Mature-box (5-bar) retest longs: +10.4%/trade abs (t=1.5, n=81) vs −10%ish
   baseline → ~+20pp relative. Sharpest sub-cell: retest + down-break puts
   +21.4% (t=2.09, n=41).
2. Short ATM premium carry at random times: +15.5%/trade (t=3.25) — and
   compression is the WORST time to sell premium → compression may be best
   used as a risk-timer overlay on a carry strategy.
3. third_long (buy bottom third of box) +9.5% (t=1.39) with variable boxes.

## Deliverables (write to analyst/po_comp_options/CODEX_REVIEW.md)

1. CORRECTNESS: any bug in the leg engine / bilbo detection / baseline script
   that would materially change a number. Point to file:line, say which
   direction it biases, propose the fix.
2. AMPLIFICATION: ≥5 concrete, testable ideas to grow leads 1-3 (filters,
   exits, structures like debit/credit spreads from our multi-strike prints,
   regime overlays, sizing). Rank by (expected impact × testability with data
   we already have or can pull in <1h with unlimited-rate Massive key,
   2-yr history cap, minute aggs only, no quotes/greeks).
3. FRESH STRUCTURES: anything exploitable in this dataset we haven't tested
   (e.g. cross-ticker conditioning, IV-proxy via straddle cost, day-of-week,
   earnings proximity, opening-hour effects). Same testability ranking.

You may run read-only python/duckdb/sqlite against the data to check ideas —
sqlite may be mid-write, so tolerate busy retries; do not write to it.
