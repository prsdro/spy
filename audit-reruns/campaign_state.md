# Indicators.py Fix Campaign — Autonomous Continuation State

## Background
User ran a full campaign fixing the ATR-level bug in /root/spy/indicators.py (shift by 1 period to match Saty's period_index=1). HTML numbers on milkmantrades.com were first refreshed against the BUGGY backtest outputs; after the fix, they'll shift another 0.5-2pp and need a second refresh.

## Completed before autonomous mode
1. Fixed `compute_atr_levels` in indicators.py (line 165-190) — shifted both atr_14 and prev_close
2. Fixed 5 malformed daily timestamps in candles_1d
3. Kicked off rebuild #2 of all ind_* tables (running now or done)
4. Chained bulk_rerun.sh to execute after rebuild (server-side)
5. HTML pages are currently at "v4 codex-clean" state matching pre-fix outputs

## Current phase: wait for backtest completion
Completion signaled by presence of `/tmp/post_rerun_done`. Outputs will be in `/root/spy/audit-reruns/postfix-outputs/backtest_*.log`.

## Remaining phases

### Phase 3: HTML refresh pass 2
Compare each HTML in /root/milkman/ against corresponding postfix-outputs log. Expected deltas: 0.5-2pp on sample sizes and headline percentages. Pages to re-check (in priority order):
- `multiday-gg.html` (bull GG 901 entries may shift slightly; bear 706; Bilbo 94.4→96.3 should now be Saty-correct)
- `swing-gg.html` (bull 298, bear 233)
- `call-trigger.html` (2,027 entries)
- `gg-entries.html` (3,472 bull / 3,254 bear)
- `gg-invalidation.html`
- `bilbo-golden-gate.html`
- `trigger-box.html`
- `trigger-box-spreads.html`
- `premarket-ath.html` (243 events)
- `gap-fills.html` (6,536 total)
- `sustained-po.html` (274 qualifying)
- `4h-po-opex.html` (13 extended / 81 baseline)
- `golden-gate.html` (subway)
- `ema21-reversion.html`

For pages where the pre-fix numbers already reflected sample counts (e.g. multiday-gg 94.4→96.3 was already the post-fix value before because that study does its own level math), skip.

### Phase 4: Codex review
Run codex exec reviewing the HTML vs current /root/spy/audit-reruns/postfix-outputs logs. Write to `/root/spy/audit-reruns/html_post_indicators_fix_review.md`. Iterate until clean.

### Phase 5: Update change magnitude report
Append a section to `/root/spy/audit-reruns/change_magnitude_report_2026-04-23.md` documenting the post-indicators-fix deltas.

### Phase 6: Verify & close out
Confirm all 16 pages HTTP 200. Mark tasks complete. Update MEMORY.md pointing at the new state.

## Files
- Fix: `/root/spy/indicators.py` (compute_atr_levels shifts atr_14 by 1)
- Current backtest outputs: `/root/spy/audit-reruns/postfix-outputs/backtest_*.log` (populating)
- Chain log: `/tmp/chain.log`
- Rebuild log: `/tmp/indicators_rebuild2.log`
- Bulk rerun log: embedded in /tmp/chain.log
