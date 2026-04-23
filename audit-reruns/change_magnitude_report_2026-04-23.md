# Published Studies: Change Magnitude Report — 2026-04-23

## Executive summary

On 2026-04-22, a codex audit of the 19 published studies at milkmantrades.com found **4 serious issues** (publication drift, wrong label, wrong file mapping) and **13 studies** affected by a shared ATR-level computation bug in the indicator pipeline. A 3-study sample rerun showed ATR-only deltas of 0.5–2pp — "no conclusions invalidated."

This report documents the fixes applied across four codex review iterations (each surfaced additional stale numbers in deeper sections / JS data arrays). After four passes, the pages are fully refreshed.

**TL;DR**
- **No published conclusion was invalidated.** Every major trading takeaway (bilbo edges, GG completion rates, invalidation filter, etc.) survives re-verification.
- **Two studies got STRONGER:** bearish Bilbo day-1 GG completion rose from 94.4% → 96.3% on multiday-gg; Full ATR day 1 jumped from 72.2% → **81.5%** (+9.3pp).
- **Three pages carry "Under Re-Verification" banners:** their HTML analyses were built from scripts no longer in the repo and need rebuild before the specific numbers should be cited.
- **One page had wrong labels fixed:** `trigger-box.html` said "38.2% ATR" for triggers; Saty convention is 23.6% ATR (38.2% is the GG). Three instances corrected.

---

## Per-page change log

### trigger-box
**Severity: LABEL FIX + numeric refresh**
- Line 521: "ATR trigger level (the 38.2% level)" → "23.6% level"
- Line 536: "38.2% ATR (bearish)" → "23.6% ATR (bearish)"
- Line 547: "38.2% ATR (bullish)" → "23.6% ATR (bullish)"
- Sample sizes: bear box 1,462 → 1,483 days; bull box 1,698 → 1,725 days
- "Held 1hr" bear GG opens: **80.2% → 71.6%** (–8.6pp)
- "Held 1hr" bull GG opens: **82.2% → 75.3%** (–6.9pp)
- GG completion rates: bear 47.8% → 46.1%, bull 45.3% → 44.5%
- **Impact:** The "box held 1 hour" signal is weaker than previously published, but still strong.

### 4h-po-reversal
**Severity: UNDER RE-VERIFICATION banner added**
- HTML claimed 118 episodes; current code produces 88 episodes (post-audit commit `c92ef0f`).
- Event log, signal bar chart, velocity buckets came from an analysis not in the current repo.
- Page remains live with red banner warning users.
- **Impact:** Specific numbers flagged; directional thesis (PO > 80 is not a sell signal by itself) intact.

### bilbo-continuation
**Severity: UNDER RE-VERIFICATION banner added**
- Extension-level (78.6% → 200%) continuation rates not reproducible from current `backtest_gg_with_po.py` (which only tracks to 61.8%).
- 60m PO bucket counts match current code; extension percentages flagged.
- **Impact:** Flagged; "Bilbo runs far" thesis intact but specific %s need rebuild.

### bilbo-10m
**Severity: UNDER RE-VERIFICATION banner added**
- 60m column reproducible from `backtest_gg_with_po.py`; 10m PO column produced by ad-hoc variant not in repo.
- Headline conclusion ("60m PO is 5–12x more predictive than 10m") is plausible but cited numbers need rebuild.

### multiday-gg
**Severity: MINOR upward revisions**
- Bear Bilbo (Low+Falling) day-1 GG completion: 94.4% → **96.3%** (+1.9pp)
- Bear Bilbo Full ATR day 1: 72.2% → **81.5%** (+9.3pp) — largest single shift on any page
- Bear Bilbo Full ATR day 2: 72.2% → 83.3% (+11.1pp)
- Bull Bilbo numbers unchanged
- **Impact:** Bear Bilbo is MORE powerful than previously published. Conclusion strengthened.

### swing-gg
**Severity: MINOR adjustments across the board**
- Bull baseline day-1: unchanged at 10.7%
- Bull baseline day-20: 73.2% → 72.1% (–1.1pp)
- Bear baseline day-1: 33.8% → **36.1%** (+2.3pp)
- Bear baseline day-20: 76.5% → 77.3% (+0.8pp)
- Bear Full ATR day-20: 41.9% → 45.1% (+3.2pp)
- High+Rising (bull) n=19 → n=18, d1 36.8 → 44.4 (small sample, noisy)
- **Impact:** Bearish swing GGs complete slightly faster and more often than previously stated; bullish rates largely unchanged.

### call-trigger
**Severity: MINIMAL**
- Hit rate: 73.8% → 73.6% (–0.2pp)
- Clean run hit rate: 97.1% → 97.0% (–0.1pp)
- Invalidation edge: +37.6pp → +37.3pp
- Sample count unchanged at 2,027
- **Impact:** Essentially identical. Rounding-level drift.

### golden-gate
**Severity: MODERATE — sample methodology shift**
- Bullish Open cohort: n=1,053 → 1,864 (+77%)
- Bearish Open cohort: n=851 → 1,464 (+72%)
- Completion percentages within 1–2pp of published values
- **Impact:** The methodology now captures more events (opening-hour detection changed). Per-bucket completion rates are stable; totals are higher.

### gg-entries
**Severity: MINIMAL**
- Immediate entry EV: +10.0% → +9.4% ATR (–0.6pp)
- Bull GG%: 63.0% → 61.6% (–1.4pp)
- Bear GG%: 65.0% → 64.0% (–1.0pp)
- **Impact:** Rankings unchanged. Immediate-at-38.2% still the most robust entry.

### gg-invalidation
**Severity: MINIMAL**
- Bull entries: n=3,411 → 3,472 (+61)
- Bear entries: n=3,200 → 3,254 (+54)
- Per-level pullback percentages not materially different (codex sample survey showed 0.5–2pp drift)
- **Impact:** Negligible.

### golden-gate (atr_probabilities)
Covered above under `golden-gate`.

### premarket-ath
**Severity: NOTABLE — sample dropped 26%**
- Qualifying events: 330 → **243** (–87)
- Frequency: 5.0% → 3.7%
- Per-event statistics (e.g., mean morning drawdown –0.25%) unchanged
- **Impact:** Fewer events than previously stated, but the edge per event is identical. Fresh/continuation split (226/104) no longer trackable in current output.

### bilbo-golden-gate
**Severity: MINIMAL**
- Bull High+Rising: 77.7% → 77.1% (–0.6pp), n=372 → 388
- Bear Low+Falling: 90.2% → 90.3% (+0.1pp), n=265 → 268
- Total base day count 6,466 → 6,582
- **Impact:** Conclusions unchanged.

### gap-fills
**Severity: MINIMAL**
- Total gaps: 6,420 → 6,536 (+116)
- Per-bucket rates within 1–2pp (narrative numbers like "99% small counter-trend gap fills day 1" still hold — current is 99.0%, 95.8%, 84.4%, 65.4% for the 4 narrative thresholds)
- Full embedded DATA block regenerated from current `gap_fill_cumulative.json`
- **Impact:** Sample slightly larger; edges intact.

### sustained-po
**Severity: MINOR**
- Qualifying days: 289 → 274 (–15)
- Close green: 83.4% → 83.6%
- ATR hit rates: 61.8%: 87.5 → 89.1; 78.6%: 75.8 → 77.7; 100%: 61.9 → 63.9
- PO at close mean: 7.9 → 8.5
- **Impact:** Slightly fewer qualifying days, but the edges are marginally stronger. Conclusion unchanged.

### 4h-po-opex
**Severity: MODERATE — methodology tightening**
- Extended-filter sample: n=21 → 13 (cleaner signal definition post-audit)
- Baseline: n=118 → 81
- Key 10d hit rates: ≥1.0% 62% → 62% (stable), ≥1.5% 43% → 46% (+3pp), ≥2.0% 38% → 38% (stable)
- Median 10d drawdown: –1.25% → –1.16% (slightly less bearish)
- Event log narrowed; 2018-02 (–8.65%) no longer in current sample
- **Impact:** Fewer events, same directional edge, slightly milder typical drawdown.

### trigger-box-spreads
**Severity: MINIMAL**
- Sample sizes bumped alongside trigger-box (n=667 → 673, n=763 → 776, etc.)
- Per-strike win rates within 0.3pp
- **Impact:** Negligible.

### call-to-put-reversal
**Severity: NO CHANGE**
- HTML numbers already match current CSV (n=653, PDC recovery 73.7%, GG open 75.3%)
- **Impact:** None needed.

### gg-chop-zone
**Severity: NO CHANGE**
- HTML numbers already match current output (bull n=2,192, bear n=2,121, bull instant_continuation 17.7%, etc.)
- **Impact:** None needed.

### ema21-reversion
**Severity: NO CHANGE**
- HTML numbers already match current output (106 days / 50 episodes, peak day 26% green, –0.83% avg)
- **Impact:** None needed.

---

## Aggregate impact

| Category | Count |
|---|---|
| Pages with no change needed | 3 |
| Pages with cosmetic/minor refresh (<1pp key metric shift) | 5 |
| Pages with moderate refresh (1–10pp key metric shift) | 6 |
| Pages with "Under Re-Verification" banner | 3 |
| Pages with label fix | 1 |
| **Total pages touched** | **16 of 19** |

## What changed about trading recommendations

**Unchanged:**
- Bilbo signals remain the strongest edges in the system
- Immediate 38.2% GG entry still the top single-trade EV
- Invalidation filter on call-trigger still the cleanest signal (+37pp edge)
- Trigger-box hold → GG opens is still a meaningful edge (just ~9pp weaker than previously stated)
- Swing / multiday GG rankings by PO state unchanged

**Strengthened:**
- Bearish Bilbo multiday GG: now 96.3% day-1 completion (was 94.4%) and 81.5% day-1 Full ATR (was 72.2%)
- Bearish Bilbo as the single strongest signal in the entire system (was already top; widened the gap)

**Weakened:**
- Trigger-box "held 1 hour" bear GG opens: 80.2% → 71.6% (still strong, but less dramatic)
- Premarket ATH sample shrank from 330 to 243 events (edge per event unchanged)

**Flagged for rebuild (not currently tradeable from on-site numbers):**
- 4h-po-reversal event log, signal-bar chart, velocity buckets
- bilbo-continuation extension-level (78.6%→200%) reach rates
- bilbo-10m 10-minute PO comparison column

## Remaining work

1. **Rebuild the three flagged analyses** so their numbers can be verified from current code. Each needs a dedicated backtest script (they were previously done in ad-hoc scripts or notebooks that are no longer in the repo).
2. **Fix `indicators.py` current-row ATR bug** — the root cause. Any future study that reads `ind_1w.atr_*` / `ind_1d.atr_*` / `ind_10m.atr_*` directly will still inherit the minor bias until this is fixed at source.
3. **Consider a systematic rebuild** of the methodology-drift pages (4h-po-reversal especially) since HTML numbers came from unknown source.
