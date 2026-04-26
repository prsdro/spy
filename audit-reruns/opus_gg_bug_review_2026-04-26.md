# Opus 4.7 review

## Claim 1 — bug verdict
- **Verdict: CONFIRMED**
- Evidence (line numbers, code excerpts):
  - `backtest_gg_with_po.py:82-88` uses `pd.merge_asof(..., direction="backward")` to attach the 1h PO snapshot to each 10m timestamp.
  - `aggregate.py:57-66` resamples 1m → 1h with `df.resample("1h")`. Pandas default is **left-labeled, left-closed**, so the row labeled `09:00:00` represents the bar covering 09:00–09:59 (verified empirically: `df.resample('1h').last()` at the `09:00` label returns the value from minute 09:59).
  - The PO on `ind_1h` is computed on the 1h close (09:59 data). Therefore the 09:00 PO value is only knowable at/after 09:59:59.
  - In the backtest, when a Subway/GG trigger fires at, say, 09:40 (`trigger_idx` row in `df10`), `merge_asof(direction="backward")` matches it to the **09:00 1h row** — i.e., the PO computed on minutes 09:00–09:59. That is **19 minutes of look-ahead**. A 10:00 trigger gets the 10:00 1h row, which embeds the entire 10:00–10:59 hour — **up to ~60 minutes** of look-ahead.
  - The user's intuition is exactly right: when price rips through 38.2% in the first 10 minutes, the 1h candle then closes much higher than its open, dragging PO higher. Classifying the trigger by that future-tainted PO snapshot manufactures a "predictive" relationship that is really just trade outcome leaking back into the feature.
  - This is the **same defect already flagged** in `audit-reruns/milkman_audit_2026-04-22.md` for `bilbo-golden-gate`/`bilbo-10m`: *"1h PO is attached by current 1h bar start; a 10m event can see an unfinished 1h candle. Use completed-hour timestamps instead. (severity: critical)"*.
- **Impact on stats:** Every conditioned cell (zone × slope × state) is biased upward when the current hour's price action is the same direction as the trigger. Most damaging for early-morning triggers (09:40, 09:50, 10:00 entries get 20–60 min of forward leakage). Best/worst snapshot rankings, slope splits ("rising" vs "falling"), and state splits ("bull_exp" vs "bear_exp") are all contaminated, because slope and zone classification are precisely the things that flip when the hour finishes in the trigger's direction.
- **Fix:** Shift the 1h frame so each 10m bar sees only the *most recently completed* 1h bar. Concretely:
  ```python
  df60_reset["timestamp"] = df60_reset["timestamp"] + pd.Timedelta("1h")  # bar-end
  # then merge_asof backward, with allow_exact_matches handled to avoid the just-closed bar
  ```
  Or, equivalently: `merge_asof(..., direction="backward", tolerance=..., allow_exact_matches=False)` after relabeling 1h timestamps as bar-close (09:00 row → 10:00 stamp). Same fix applies to `po_prev_60m`.

## Claim 2 — stat verdict
- **Verdict: CONFIRMED (in principle); minor labeling caveat**
- Evidence (numbers, math): the user's decomposition (treating each cohort as an independent sample of "did the headline level get reached?"):
  | Cohort | Bull N | Bull rate | Bear N | Bear rate |
  |---|---:|---:|---:|---:|
  | Gap already past 61.8 | 362 | 100% | 373 | 100% |
  | Gap past 38.2 (sub-61.8) | 695 | 78.6% | 477 | 80.9% |
  | Open inside trigger band, crosses intraday | 2339 | **52.1%** | 2328 | **56.5%** |
  - Pooled rate ≈ (362·1.0 + 695·0.786 + 2339·0.521) / (362+695+2339) ≈ 2127 / 3396 ≈ **62.6% bull**, and analogously ≈ 67% bear. If you further restrict to "had to actually cross the level intraday" the rate collapses to 52/56%.
  - Mechanism: gap-over cohorts are tautologically successes for any "did price reach level L" question conditional on opening past L. Pooling them with intraday-cross cohorts inflates the headline conditional probability and, worse, smuggles in a predictor (the gap itself) that is not available when the level is being touched mid-session.
- **Implication for the published 80%:** The level-to-level table in `studies_reference.md:12` ("Trigger → ±38.2%: 80%") and the `bilbo-golden-gate` page numbers conflate these regimes. The honest framing is two separate statistics:
  1. *Open already past the level* → trivially 100% (or near-100%) and not actionable as a "next-step" stat.
  2. *Open inside, must cross intraday* → ~52% bull / ~56% bear, i.e. only modestly above coin-flip.
  - Note: the user's three-bucket numbers describe the **38.2% → 61.8% GG-completion** question (cohorts defined by where the open sits relative to 38.2 and 61.8, success = reaching 61.8), not strictly the 23.6 → 38.2 leg. The same selection-bias critique applies to either leg, and the published 80% headline is best read as an aggregated, gap-cohort-inflated number rather than a tradable conditional. Verdict still confirmed; the claim's structure is correct even if the specific level pair in the headline study is the 38.2→61.8 leg rather than 23.6→38.2.

## Bottom line
Claim 1 is a real, already-known look-ahead bug: `merge_asof` backward against left-labeled 1h bars hands the backtest the not-yet-closed hour's PO, and it materially biases the snapshot-conditional results — fix by lagging the 1h frame to bar-close before the join. Claim 2 is also correct: the marquee ~80% Subway/GG conditional pools gap-over cohorts (trivially 100%) with intraday-cross cohorts (~52% bull / ~56% bear), so the headline overstates what a trader actually faces when watching price approach the level live. Both findings argue for pulling/relabeling the bilbo-golden-gate publication and reissuing splits with completed-bar PO joins and explicit gap-cohort separation.
