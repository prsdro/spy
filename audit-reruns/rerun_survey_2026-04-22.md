# ATR Shift Rerun Survey - 2026-04-22

Scope: 3 representative published studies. Correction applied only to the shared ATR-level bug: levels use prior close and prior ATR (`period_index=1` equivalent). Live HTML and original backtest files were not modified.

Scratch runner: `audit-reruns/rerun_survey_2026-04-22.py`

### `backtest_multiday_gg.py` / `multiday-gg`

Published metric: bearish Bilbo weekly GG completion, day 1 = 94.4% (HTML, n=54)

Corrected metric: same metric with shifted weekly ATR = 96.3% (52/54)

Delta: +1.9 pp (+2.0% relative)

Verdict: SLIGHTLY ADJUSTED

Note: current uncorrected script on this DB already prints 96.3%, so the HTML appears stale versus current repo output; the ATR fix itself did not reduce this headline.

### `backtest_call_trigger_confirmation.py` / `call-trigger`

Published metric: open inside trigger box -> confirmed 3m close above call trigger -> hit 38.2% = 73.8%

Corrected metric: same metric with shifted daily ATR = 73.2% (1,480/2,021)

Delta: -0.6 pp (-0.8% relative)

Verdict: SLIGHTLY ADJUSTED

Note: corrected clean-run hit rate remains 97.1% (725/747), matching the page headline after rounding.

### `backtest_gg_entries.py` / `gg-entries`

Published metric: EV of entering immediately at 38.2%, both directions = +10% ATR

Corrected metric: same immediate-entry EV with shifted daily ATR = +9.4% ATR (4,197/6,689 completed; 62.7% GG completion)

Delta: -0.6 pp of ATR EV (-6.3% relative)

Verdict: SLIGHTLY ADJUSTED

Note: current uncorrected script on this DB prints +9.4% combined EV already, while the page rounds the older published value to +10%.

## Phase 2 Recommendation

Recommendation: A. Small deltas across the sampled timeframe range -> edit HTML to cite corrected numbers; no ATR-only full rerun campaign appears necessary.

Action items:

- Update affected pages with corrected ATR-anchor language and corrected headline numbers.
- Add a short audit note where current repo output already drifted from published HTML.
- Keep separate non-ATR methodology issues from `milkman_audit_2026-04-22.md` on their own rerun/pull-down track; this survey only isolates the shared ATR shift.
