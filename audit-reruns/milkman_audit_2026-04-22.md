# Milkman Published Study Audit - 2026-04-22

Scope: published pages in `/root/milkman/*.html` mapped to `/root/spy/backtest_*.py`.

Global blocker checked across studies:

- Canonical Saty levels use prior-period close and prior-period ATR (`saty_atr_levels.pine:74-85`, `period_index = 1`).
- Shared generated level tables do not match that spec: `indicators.py:156-210` shifts `prev_close` but uses the current-row ATR. Any study that consumes `atr_lower_trigger`, `atr_upper_0382`, `atr_upper_1000`, etc. directly from `ind_1m`, `ind_3m`, `ind_10m`, `ind_1d`, or `ind_1w` needs a rerun unless it explicitly recomputes shifted ATR.
- Clean exceptions found: `backtest_4h_po_opex_extended.py` uses `study_utils.compute_resampled_atr_ref`, and `backtest_swing_gg.py` recomputes monthly shifted ATR. `ema21-reversion` does not depend on ATR levels for its core signal.

### 4h-po-opex
Status: MINOR
Files checked: `backtest_4h_po_opex.py`, `backtest_4h_po_opex_extended.py`, `milkman/4h-po-opex.html`
Issues found:
  - Forward window starts on the next daily row after the 4h signal, while the page says "from signal close"; same-day post-signal action is excluded when the signal occurs before the RTH close. (severity: minor)
  - Small-sample claims need stronger caveats, especially the extension subset. (severity: minor)
Recommended action: edit-only

### 4h-po-reversal
Status: BROKEN
Files checked: `backtest_4h_po_daily_mean_reversion.py`, `backtest_4h_po_mean_reversion.py`, `backtest_4h_po_drop_softened.py`, `backtest_4h_po_drop_by_atr_position.py`, `backtest_4h_po_confluence.py` searched, `milkman/4h-po-reversal.html`
Issues found:
  - Published headline claims such as the 118-episode sample and the 14/14 cloud-flip filter are hardcoded in HTML and are not reproduced by the mapped backtest files. (severity: critical)
  - Sequence filters such as cloud flip or conviction bear are not tradable from the original PO event unless the measured outcome is reset to the time those later conditions become observable. (severity: critical)
  - `backtest_4h_po_drop_by_atr_position.py` shifts weekly/monthly references but uses simple rolling ATR instead of Wilder/RMA ATR, so it is inconsistent with Saty. (severity: major)
Recommended action: pull-down-until-fixed

### bilbo-10m
Status: BROKEN
Files checked: `backtest_po_sustained_morning.py`, `backtest_gg_with_po.py` searched, `server.py` searched, `milkman/bilbo-10m.html`
Issues found:
  - The published 10m-vs-60m Golden Gate comparison is not reproduced by `backtest_po_sustained_morning.py`; the mapped file is a sustained-morning-PO study, not this page's study. (severity: critical)
  - The 60m/Bilbo path uses 10m daily ATR levels from `ind_10m`, inheriting the shared current-ATR bug. (severity: critical)
  - 1h PO state is merged by the 1h bar start, so a 10m event can see an unfinished 1h candle. Use completed-hour timestamps instead. (severity: critical)
  - Same-10m-bar completion is counted; this is only descriptive, not an executable entry after observing the touch. (severity: major)
Recommended action: pull-down-until-fixed

### bilbo-continuation
Status: BROKEN
Files checked: `backtest_po_sustained_reversal.py`, `backtest_po_sustained_cloud_mtf.py`, `backtest_gg_with_po.py` searched, `milkman/bilbo-continuation.html`
Issues found:
  - The continuation-to-78.6/full-ATR/123.6 claims are not reproduced by the mapped sustained-PO scripts. (severity: critical)
  - If sourced from the Bilbo/GG pipeline, it inherits both the `ind_10m` ATR-level bug and the incomplete-1h-PO lookahead. (severity: critical)
  - Published control/baseline is not auditable from the mapped files. (severity: major)
Recommended action: pull-down-until-fixed

### bilbo-golden-gate
Status: MAJOR_FLAW
Files checked: `backtest_gg_with_po.py`, `server.py` searched, `milkman/bilbo-golden-gate.html`
Issues found:
  - Uses `ind_10m` daily ATR levels directly, so GG/trigger/full-ATR levels inherit the shared current-ATR bug. (severity: critical)
  - 1h PO is attached by current 1h bar start; a 10m GG touch inside the hour can use an unfinished 1h candle. (severity: critical)
  - Same-10m-bar completion is included. The page discloses same-bar behavior, but it is not executable after the touch is observed. (severity: major)
Recommended action: pull-down-until-fixed

### call-to-put-reversal
Status: MAJOR_FLAW
Files checked: `backtest_call_to_put_reversal.py`, `milkman/call-to-put-reversal.html`
Issues found:
  - Uses `ind_1m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - Downside target checks include the put-trigger 1m bar, creating first-touch/same-bar ambiguity for GG and full-ATR races. (severity: major)
Recommended action: rerun-required

### call-trigger
Status: MAJOR_FLAW
Files checked: `backtest_call_trigger_confirmation.py`, `milkman/call-trigger.html`
Issues found:
  - Uses `ind_3m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - Target checks exclude the trigger bar, which is good, but "clean run" rates are path-conditioned by later invalidation. Page wording should treat this as a stop/exit rule, not a filter known at entry. (severity: major)
Recommended action: rerun-required

### ema21-reversion
Status: MINOR
Files checked: `backtest_ema21_reversion.py`, `backtest_ema21_reversion_4h_po.py`, `milkman/ema21-reversion.html`
Issues found:
  - Daily close > EMA21 stretch is only known after the close; any intraday 4h-PO overlay must be framed as next-session or close-confirmed, not same-day executable from the earlier 4h event. (severity: minor)
  - RTH daily vs ETH 4h PO mixing is disclosed on the page; keep that caveat visible. (severity: minor)
Recommended action: edit-only

### gap-fills
Status: MAJOR_FLAW
Files checked: `backtest_gap_fill_cumulative.py`, `backtest_gap_up_dump.py`, `backtest_gap_up_pre_noon.py`, `milkman/gap-fills.html`
Issues found:
  - `backtest_gap_fill_cumulative.py` uses today's daily EMA21 slope at the gap open; current daily EMA is only known after the close. (severity: critical)
  - Weekly EMA mapping is not clearly restricted to the prior completed weekly bar. Treat as weekly lookahead until rerun. (severity: major)
  - HTML says the 9:00 1h compression bar includes the market open, while the code uses the completed 8:00 bar. This is publication drift. (severity: major)
  - `backtest_gap_up_pre_noon.py` uses `ind_10m` ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - `backtest_gap_up_dump.py` defines dumps using the day's later high and drawdown; that is post-hoc unless clearly labeled as descriptive only. (severity: major)
Recommended action: pull-down-until-fixed

### gg-chop-zone
Status: MAJOR_FLAW
Files checked: `backtest_gg_chop_zone.py`, `milkman/gg-chop-zone.html`
Issues found:
  - Uses `ind_10m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - "Instant continuation" counts targets hit in the same 10m bar as GG completion; intrabar order is unknown. (severity: major)
  - PO at completion is a 10m close value, but the level touch may have happened before that close. (severity: major)
Recommended action: rerun-required

### gg-entries
Status: MAJOR_FLAW
Files checked: `backtest_gg_entries.py`, `milkman/gg-entries.html`
Issues found:
  - Uses `ind_10m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - 1h EMA is merged by current 1h bar start, so 10m entries can use unfinished 1h information. (severity: critical)
  - Code comments say next-bar entry after touch/bounce, but implementation enters on the touch bar. Execution convention and published wording need reconciliation before rerun. (severity: major)
Recommended action: pull-down-until-fixed

### gg-invalidation
Status: MAJOR_FLAW
Files checked: `backtest_gg_invalidation.py`, `milkman/gg-invalidation.html`
Issues found:
  - Uses `ind_10m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - Higher-timeframe invalidation context is merged by current bar timestamps; 1h/3m context needs completed-bar checks. (severity: major)
  - Entry, completion, and invalidation checks include the same 10m bar, so first-touch ordering is ambiguous. (severity: major)
Recommended action: rerun-required

### golden-gate
Status: MAJOR_FLAW
Files checked: `backtest_atr_probabilities.py`, `milkman/golden-gate.html`
Issues found:
  - Uses `ind_10m` daily ATR levels through the shared loader, inheriting the current-ATR bug. (severity: critical)
  - Level-to-level probabilities use daily high/low containment and do not always model first touch order, especially for either-direction summaries. (severity: major)
  - Subway/open-session handling mixes same-bar open logic with later trigger-bar exclusion; rerun should use one explicit execution convention. (severity: major)
Recommended action: rerun-required

### multiday-gg
Status: MAJOR_FLAW
Files checked: `backtest_multiday_gg.py`, `backtest_multiday_atr_wednesday.py`, `milkman/multiday-gg.html`
Issues found:
  - `backtest_multiday_gg.py` reads weekly ATR levels directly from `ind_1w`, inheriting the weekly current-ATR bug. (severity: critical)
  - `backtest_multiday_atr_wednesday.py` also reads `ind_1w` ATR levels directly. (severity: critical)
  - Wednesday ATR script uses current-week PO/zone/trend from the weekly row, which is not known midweek. (severity: critical)
  - Horizon labeling is ambiguous: `h=1` includes the entry day plus the next trading day. Page should define whether day 1 includes the entry day. (severity: minor)
Recommended action: pull-down-until-fixed

### premarket-ath
Status: MAJOR_FLAW
Files checked: `backtest_premarket_ath.py`, `milkman/premarket-ath.html`
Issues found:
  - Prior ATH is computed from all-hours 10m data; if page readers interpret ATH as RTH ATH, this mixes ETH and RTH regimes. (severity: major)
  - "10m PO at the open" uses the 09:30 10m bar's close-derived indicator, which is only known after that bar closes. (severity: critical)
  - ATR framework uses `ind_10m` ATR values/levels, inheriting the shared current-ATR bug. (severity: critical)
Recommended action: rerun-required

### sustained-po
Status: MAJOR_FLAW
Files checked: `backtest_po_sustained_morning.py`, `backtest_po_sustained_reversal.py`, `backtest_po_sustained_cloud_mtf.py`, `milkman/sustained-po.html`
Issues found:
  - Sustained-morning core PO screen is mostly clean if treated as an after-11:00 entry, but ATR-hit and high-as-percent-ATR claims use `ind_10m` ATR levels/values and inherit the shared current-ATR bug. (severity: critical)
  - 11:00 timestamp likely refers to the 11:00-11:10 10m bar close; page should not imply observability exactly at 11:00 if timestamps are bar starts. (severity: minor)
  - Reversal/day-high analysis is post-hoc when it conditions on the day's high and PO at that high. Label as descriptive or rerun from an observable trigger. (severity: major)
  - 1h cloud-flip follow-up should use completed-hour timestamps. (severity: major)
Recommended action: rerun-required

### swing-gg
Status: MINOR
Files checked: `backtest_swing_gg.py`, `milkman/swing-gg.html`
Issues found:
  - Horizon labeling is ambiguous: the `h=1` window includes entry day plus the next trading day. If the page reads as "one trading day after entry", numbers need relabeling or rerun. (severity: minor)
  - Weekly PO references are shifted before merge, which is conservative, but page should document that weekly filter is prior completed week. (severity: minor)
Recommended action: edit-only

### trigger-box
Status: MAJOR_FLAW
Files checked: `backtest_trigger_box.py`, `backtest_trigger_box_spreads.py` searched, `milkman/trigger-box.html`
Issues found:
  - Uses `ind_10m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - Page labels call/put triggers as 38.2% ATR in multiple places; Saty trigger is 23.6%, while GG is 38.2%. (severity: critical)
  - Page says hold-time numbers are full-day outcomes filtered by hold time, but code measures after-hold windows. This is publication drift. (severity: major)
Recommended action: pull-down-until-fixed

### trigger-box-spreads
Status: MAJOR_FLAW
Files checked: `backtest_trigger_box_spreads.py`, `milkman/trigger-box-spreads.html`
Issues found:
  - Uses `ind_10m` daily ATR levels directly, inheriting the shared current-ATR bug. (severity: critical)
  - Study reports short-strike touch/no-touch after hold, not actual option-spread P&L, fills, credit, stop, assignment, or expiry settlement. Page should not imply realized spread win rate. (severity: major)
  - Same trigger-box hold convention must be documented explicitly after the ATR rerun. (severity: minor)
Recommended action: rerun-required

## Severity Groups

Critical / pull-down candidates:

- `4h-po-reversal`: published claims not reproducible from mapped backtests; later sequence filters appear non-executable from the original event.
- `bilbo-10m`: wrong mapped study plus inherited ATR bug and incomplete 1h PO lookahead.
- `bilbo-continuation`: published claims not reproducible from mapped files; likely inherits Bilbo/GG flaws.
- `bilbo-golden-gate`: inherited ATR bug plus current-hour 1h PO lookahead.
- `gap-fills`: current-day EMA slope at open, ATR bug in pre-noon variant, and publication drift.
- `gg-entries`: inherited ATR bug plus current-hour 1h EMA lookahead.
- `multiday-gg`: weekly ATR levels from `ind_1w` plus current-week PO/zone/trend in Wednesday script.
- `trigger-box`: inherited ATR bug plus trigger mislabeled as 38.2% instead of 23.6%.

Rerun-required from shared ATR-level bug:

- `bilbo-golden-gate`
- `call-to-put-reversal`
- `call-trigger`
- `gap-fills`
- `gg-chop-zone`
- `gg-entries`
- `gg-invalidation`
- `golden-gate`
- `multiday-gg`
- `premarket-ath`
- `sustained-po`
- `trigger-box`
- `trigger-box-spreads`

Major human-review items:

- Same-bar or first-touch ambiguity: `bilbo-10m`, `bilbo-golden-gate`, `call-to-put-reversal`, `gg-chop-zone`, `gg-invalidation`, `golden-gate`.
- RTH/ETH mixing or timestamp observability: `ema21-reversion`, `premarket-ath`, `sustained-po`, `gap-fills`.
- Control/baseline or selected-universe weakness: `bilbo-continuation`, `gap-fills`, `trigger-box-spreads`.

Minor/edit-only items:

- `4h-po-opex`: clarify forward window starts next daily row, not literally signal close.
- `ema21-reversion`: frame the 4h PO overlay as close-confirmed or next-session executable.
- `swing-gg`: define the day-1 horizon and prior-week PO convention.
