# HTML Refresh Review - 2026-04-23

Source checked: `/root/spy/audit-reruns/refresh-outputs/*.log`, plus
`/root/spy/gap_fill_cumulative.json`.

Note: the NumPy warning/traceback preambles in the logs were ignored. For
`backtest_call_trigger_confirmation.log`, the JSON-ready `BY_HOUR` and
`BY_HALFHOUR` export is corrupt/repeated, so the printed tables were treated as
source of truth.

## Priority Findings

- PRIORITY: `call-trigger.html` has updated headline/prose values but stale JS
  arrays.
  - Line 810, 09:30 row: HTML `hit=679`, `hitPct=81.4`, `cleanN=326`,
    `invN=508`; correct printed table is `hit=677`, `hitPct=81.2`,
    `cleanN=320`, `invN=514`.
  - Line 811, 10:00 row: HTML `hit=250`, `hitPct=76.2`, `cleanN=127`,
    `invN=201`, `invPct=61.2`; correct is `hit=249`, `hitPct=75.9`,
    `cleanN=122`, `invN=206`, `invPct=61.7`.
  - Line 819, 14:00 row: HTML `cleanN=40`, `invN=37`, `invPct=45.9`;
    correct is `cleanN=39`, `invN=38`, `invPct=47.4`.
  - Line 822, 15:30 row: HTML `hit=16`, `hitPct=29.1`, `cleanHit=13`,
    `cleanPct=43.3`; correct is `hit=15`, `hitPct=27.3`,
    `cleanHit=12`, `cleanPct=40.0`.
  - Lines 826-833, `invalData`: examples include 09:00 `326/508` but
    correct `320/514`; 10:00 `196/321` but correct `191/326`; 14:00
    `cleanPct=98.5`, `cleanN=65`, `invN=87`, `invPct=40.2`, `edge=58.2`
    but correct `98.4`, `64`, `88`, `40.9`, `57.5`; 15:00 `cleanPct=56.2`,
    `cleanHit=27`, `edge=32.6` but correct `54.2`, `26`, `30.5`.
  - Lines 837-845, `speedRows`: HTML says `Same bar` is `6.1%`; current log
    says "Hit 38.2 on trigger bar itself: 0 times". Replace or recompute this
    unsupported section.

- PRIORITY: `premarket-ath.html` mixes updated headline count with stale
  330-event chart/table data.
  - Line 300 lede: HTML says `2007-2026` and `46% smaller`; current log range
    is `2013-04-11` to `2026-01-28` and verdict is `48% smaller`.
  - Line 494, `runLow`: HTML uses old PM close low about `-0.3950`; correct
    current PM full-day low is `-0.362`, and PM max-up close is `+0.266`.
  - Lines 499-504, `rrData`: correct current rows are First 30m
    `0.140/0.104/RR 1.26`, First hour `0.188/0.133/RR 1.37`, Morning
    `0.249/0.181/RR 1.41`, Full day `0.362/0.266/RR 1.34`.
  - Lines 506-512, thresholds: HTML `>=0.25` PM/non `39.1/60.1` should be
    `37.9/59.8`; HTML `>=0.50` `13.3/35.0` should be `11.1/34.7`.
  - Lines 514-549, bucket arrays are old n=330 data. Correct current counts:
    extension `44/77/100/22`, gap `31/118/61/33`, PO
    `16/45/90/58/24/10`, ATR position `31/84/54/39/28/7`, fresh/continuation
    `68/175`.
  - Line 552, `yearData`: old counts remain. Current counts include 2013
    `23`, 2014 `28`, 2015 `2`, 2016 `15`, 2017 `37`, 2018 `11`, 2019 `22`,
    2020 `19`, 2021 `44`, 2022 `1`, 2024 `32`, 2025 `7`, 2026 `2`.

- PRIORITY: `sustained-po.html` updates the top setup count and hit rates, but
  much of the page is still old 289-day data.
  - Lines 319-333: HTML mean `+0.016`, median `+0.089`, positive `55.7%`,
    edge `+0.004`; correct current values are `+0.027`, `+0.095`, `56.9%`,
    edge `+0.015`.
  - Line 341: HTML says `n=289`; correct qualifying days are `274`.
  - Lines 343-350: old return distribution counts remain
    `23/22/24/58/79/41/26/16`; correct counts are
    `22/19/23/53/76/40/26/15`.
  - Lines 285 and 302-310: PO collapse values are slightly stale:
    `91.4/7.9/0.3` should be `91.3/8.5/0.4`.
  - Lines 423, 431, 457, 466, and 636 still use `/289` and `157/132` splits.
    Current log does not reproduce the fast-cloud table, so this section needs
    a rerun/refresh or an explicit caveat.

- PRIORITY: `4h-po-opex.html` has the updated n=13 headline and horizon table,
  but old offset/event-list sections remain.
  - Lines 185-197, "By OpEx Offset": HTML shows old `n=5/6/5/2/4/4` and
    Non-OpEx `n=92`. Correct unfiltered current counts are day0 `n=3`, day1
    `n=4`, day2 `n=3`, day3 `n=0`, day4 `n=2`, day5 `n=3`, Other `n=66`.
    Correct extended counts are day0 `n=2`, day1 `n=3`, day2 `n=3`, day3
    `n=0`, day4 `n=2`, day5 `n=3`, Other `n=59`.
  - Line 204: HTML says "Every Extended Event (n=21)"; correct current
    extended key-window event list is `n=13`.
  - Lines 210-230 include old events not in the current 13-event list, including
    `2003-03-24`, `2007-04-23`, `2007-04-26`, `2012-03-16`, `2017-02-22`,
    `2018-01-23`, `2018-01-24`, `2021-04-16`, and a duplicate `2021-10-21`.
  - Line 240: HTML says only `14%` hit 1% at 1 day; current extended n=13
    horizon table is `31%` for `>=1.0%` at 1 day.
  - Line 256: null-pattern commentary is still tied to the old 21-event list
    and should be re-evaluated.

- PRIORITY: `gg-entries.html` has current row values, but stale totals and
  prose remain.
  - Lines 115 and 123: HTML headers still say Bullish `n=3,411` and Bearish
    `n=3,200`; correct current totals are `n=3,472` and `n=3,254`.
  - Line 141: HTML bigstat says EMA8 pullback is `+11%`; current log is
    `+6.1%` bull and `+7.7%` bear.
  - Line 158: HTML says 1h EMA21 appears `57-62%`, completes `39-42%`, EV
    `+7-9%`; correct current values are about `54.6-60.1%`, `33.1-36.2%`,
    EV `+3.3-5.3%`.

- PRIORITY: `gg-invalidation.html` has updated page totals but stale waterfall
  arrays.
  - Lines 175-195 still reflect old row values. Examples: Bull EMA8 HTML
    `64.2` should be `64.4`; Bull EMA21 `61.8` should be `62.0`; Bull Upper
    Trigger `45.3` should be `45.5`; Bear EMA8 `66.1` should be `66.3`; Bear
    Lower Trigger `50.6` should be `50.8`.
  - The row `n` values are also stale relative to the new totals. Current log
    prints occurrence percentages rather than exact row counts, so recompute row
    counts before updating the JS.
  - Line 187 label says Bear "Held above 38.2%"; bearish direction should be
    mirrored, e.g. "Held below -38.2%" or equivalent.

## Per-Page Results

- `trigger-box.html`: PARTIAL.
  - Spot checks OK: progressive arrays for baseline, held 30m, and held 1h
    match the log: bear `58.7/32.4`, `67.5/40.2`, `71.6/46.1`; bull
    `57.2/29.4`, `69.7/39.1`, `75.3/44.5`.
  - Wrong-label fix OK: trigger-specific labels now say `23.6% ATR` at lines
    521, 536, and 547. GG `38.2%` references remain at lines 594 and 705.
  - Lines 7, 625, and 716 still say `80%+` GG rates/conviction/trigger rate.
    Current held-1h GG-open rates are `71.6%` bear and `75.3%` bull.
  - Lines 640-659, reversal section is stale: HTML `n=795`, `73.2%`,
    `n=935`, `72.7%`, and labels GG as `61.8%`. Correct values are bear-box
    failure `n=810`, call trigger `73.0%`, bullish GG `38.2%` hit `49.4%`;
    bull-box failure `n=949`, put trigger `72.9%`, bearish GG `38.2%` hit
    `50.2%`.
  - Optional: line 521 "about half" value `48.9%` is close but exact current
    box-day share is `3254/6582 = 49.4%` for box days in the call-trigger log,
    and `3208/6582 = 48.7%` for trigger-box days.

- `4h-po-reversal.html`: OK for caveat intent.
  - Banner is visible at line 267 and accurately says the analysis predates the
    audit and current code produces `88` episodes instead of the old `118`.
  - Old `118`-episode narrative/numbers remain unchanged as intended, including
    lines 286, 291, 359, 471, and 687.

- `bilbo-continuation.html`: CAVEAT NEEDS TIGHTENING.
  - Banner is visible at line 86.
  - Issue: banner says GG-to-61.8% completion numbers are independently
    reproducible, but the page still shows old `77.7% n=372` and `90.2% n=265`
    values. Current `backtest_gg_with_po.log` has `77.1% n=362` for Bull
    High+Rising/Bull Expansion and `90.3% n=268` for Bear Low+Falling/Bear
    Expansion.
  - Either update those displayed 60m/GG completion rows or revise the banner to
    say the extension analysis and displayed comparison table are pending
    refresh.

- `bilbo-10m.html`: CAVEAT NEEDS TIGHTENING.
  - Banner is visible at line 94 and correctly says the 10m PO variant is not
    in the current repo.
  - Issue: banner says the 60m PO column numbers are reproducible from current
    code, but displayed 60m rows still show old `77.7% n=372` and `90.2% n=265`
    values. Current comparable values are `77.1% n=362` and `90.3% n=268`.
  - Since the page was intentionally not rewritten, the banner should avoid
    implying the displayed 60m table is current.

- `multiday-gg.html`: PARTIAL.
  - Spot checks OK: bull baseline `n=901`, day1/day5 completion `65.0/84.1`;
    bear baseline `n=706`, day1/day5 `72.0/83.0`; Bear Low+Falling day1 GG
    completion `96.3` and day1 full ATR `81.5` in the detailed table match the
    log.
  - Issue: line 411 bigstat still says Bearish Bilbo full weekly ATR Day 1 is
    `72.2%`; correct current value is `81.5%`. Later table/JS values already
    use `81.5%`, so this is an internal inconsistency.

- `swing-gg.html`: OK.
  - Spot checks match current log: bull baseline `n=298`, day1/day20
    `10.7/72.1`; bear baseline `n=233`, day1/day20 `36.1/77.3`; bear full ATR
    day1/day20 `4.7/45.1`.
  - Narrative, bigstats, and JS arrays are internally consistent with these
    refreshed values.

- `call-trigger.html`: PRIORITY, see above.
  - Headline/prose spot checks OK: `2,027` trigger days, `1,492` hits,
    `73.6%` hit rate, `97.0%` clean hit rate, `734/757`, and `758/1270` match
    current log.
  - JS arrays and speed bucket section are stale/inconsistent.

- `golden-gate.html`: OK.
  - Spot checks match `backtest_atr_probabilities.log`: subway Bull Open
    `n=1864`, done `94.2`; Bull 09:30 `n=1102`, done `73.5`; Bear Open
    `n=1464`, done `95.5`; Bear 09:30 `n=1059`, done `73.7`.
  - Embedded data arrays are internally consistent with the refreshed subway
    totals.

- `gg-entries.html`: PRIORITY, see above.
  - Spot checks OK in the strategy rows: immediate EV `+8.9%` bull and `+9.8%`
    bear; 10m EMA8 EV `+6.1%` bull and `+7.7%` bear; 50% midpoint EV is
    negative for both sides.
  - Stale headers/prose need refresh.

- `gg-invalidation.html`: PRIORITY, see above.
  - Page totals `n=3,472` bull and `n=3,254` bear are updated.
  - Waterfall JS arrays remain stale.

- `premarket-ath.html`: PRIORITY, see above.
  - Top event count `243` is updated.
  - Most chart/table datasets remain old n=330 values.

- `bilbo-golden-gate.html`: OK.
  - Spot checks match current log: Bull High+Rising `77.1% n=362`; Bear
    Low+Falling `90.3% n=268`; baselines `63.1% n=3472` and `65.2% n=3254`.
  - Narrative, bigstats, and JS arrays are internally consistent.

- `gap-fills.html`: OK.
  - Embedded DATA block matches `/root/spy/gap_fill_cumulative.json`.
  - Spot checks OK: total gaps `6,536`; gap up `n=3,589`; gap down `n=2,947`;
    All gap up `<0.25` `n=1562`; All gap down `<0.25` `n=1306`.

- `sustained-po.html`: PRIORITY, see above.
  - Top setup count `274` and level-hit percentages `89.1/77.7/63.9` match the
    current log.
  - Return, distribution, fast-cloud, and some PO-collapse sections are stale.

- `4h-po-opex.html`: PRIORITY, see above.
  - Headline `n=13` and horizon table match current extended-window log values:
    1d `54/31/23/8`, 3d `69/46/31/23`, 5d `69/46/31/31`, 10d
    `69/62/46/38`.
  - Offset/event-list/commentary sections remain old.

- `trigger-box-spreads.html`: MINOR/PARTIAL.
  - Sample sizes were mostly refreshed, including held-1h `n=673` bear and
    `n=776` bull.
  - Several percentages are stale by 0.1-0.5 pp. Examples: Bear All +38.2
    HTML `66.6` should be `66.4`; Bear held-1h +38.2 `85.8` should be `85.7`;
    Bear held-1h top-half +38.2 `87.5` should be `86.8`; Bull All -38.2
    `64.8` should be `64.7`; Bull held-1h row `82.6/87.8/92.0/97.5` should be
    `82.9/88.0/92.1/97.6`.
  - Lines 138-139 held-1h bull top/bottom subset n are stale: HTML `477/286`;
    correct current n are `485/291`. Bottom-half values should be
    `86.6/91.1/94.5/98.6`.

## Anything Missed

The biggest missed pattern is partial refresh inside a page: updated headline
stats with old JS arrays, event lists, or explanatory copy. The affected pages
are `call-trigger.html`, `premarket-ath.html`, `sustained-po.html`,
`4h-po-opex.html`, `gg-entries.html`, `gg-invalidation.html`,
`trigger-box.html`, `trigger-box-spreads.html`, and `multiday-gg.html`.

Clean pages from this pass: `4h-po-reversal.html` for caveat intent,
`swing-gg.html`, `golden-gate.html`, `bilbo-golden-gate.html`, and
`gap-fills.html`.
