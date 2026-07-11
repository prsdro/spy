# Codex Review 2: Bias audit of the arm-then-trail headlines (2026-07-08)

## Round 1 — independent adversarial review

# Adversarial Review: PO Compression Options Arm-Trail Headlines

I did not modify repo files or data. Main conclusion: the raw +13.5% single-leg and +12.0% straddle arm-trail results are directionally plausible as a convexity-harvesting signal, but the headline magnitude and t-stats are materially inflated by option execution assumptions. A read-only resimulation already in the repo reproduced the published trail exactly, then conservative mechanics cut the straddle from +12.0% to roughly +3.8% to +5.2%, with date-clustered t around +1.2.

## Findings

| # | Mechanism | File:line | Direction | Rough magnitude | Concrete test |
|---|---|---:|---|---:|---|
| 1 | Trail exits fill at the synthetic stop level whenever minute low crosses it. Fast option moves can trade through the level; the code does not require an actual print at the level. | [scratch_po_comp_trailing.py](/root/spy/scratch_po_comp_trailing.py:61), [scratch_po_comp_trailing.py](/root/spy/scratch_po_comp_trailing.py:69), [scratch_po_comp_flip_armtrail.py](/root/spy/scratch_po_comp_flip_armtrail.py:43) | Inflates | Biggest measured issue. Single: +13.1% to +6.3%; straddle: +12.0% to +5.5% using trigger-bar close as next-print proxy. | Recompute exits as first actual print after trigger, or `min(level, trigger_bar_close)` for sells; also report trigger-bar-low worst bound. |
| 2 | Initial -50% stop is also filled exactly at -50%, ignoring gap-through. This affects 64% of published single-leg exits. | [scratch_po_comp_flip_armtrail.py](/root/spy/scratch_po_comp_flip_armtrail.py:40), [scratch_po_comp_flip_armtrail.py](/root/spy/scratch_po_comp_flip_armtrail.py:45), [backtest_po_comp_bilbo.py](/root/spy/backtest_po_comp_bilbo.py:200) | Inflates | Stop exits lose another mean ~4.6-5.3pp versus trigger-bar close; p90 gap-through cost ~14-19pp. | For stop exits, fill at next available print/close after stop trigger; separately report stop-only slippage distribution. |
| 3 | High-water mark is based on minute-bar highs from trade prints. Single outlier prints can arm or raise the trail without executable size. | [scratch_po_comp_trailing.py](/root/spy/scratch_po_comp_trailing.py:44), [scratch_po_comp_trailing.py](/root/spy/scratch_po_comp_trailing.py:47), [fetch_po_comp_options.py](/root/spy/fetch_po_comp_options.py:339) | Inflates | DB-wide, 39.7% of option minute bars are single-print bars. Close-confirmed trail cuts straddle from +12.0% to +6.0% before spread. | Recompute HWM from closes only, or only from bars with `n >= 2` and volume threshold; compare to current high-based HWM. |
| 4 | Entry fill can use stale pre-signal prints: last close <= signal within 20 minutes, then 60-minute fallback. Because signal is a break, stale pre-move prints can underprice the winning option. | [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:78), [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:83), [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:87) | Inflates individual winners; aggregate mixed | 33% of long-side fills and 38% of opposite-leg fills are stale; >5 min stale is 4.6% and 7.8%. Direct strict-after entry alone did not hurt aggregate much, but strict-live entry definitions on orig8 dropped single from +15.3% to +4.9%. | Force first print strictly after signal, cap wait at 5 minutes, drop otherwise; stratify by stale-fill age and by winner/loser. |
| 5 | No bid/ask spread. Trade prints bounce between bid/ask; live buy is closer to ask and exit sell closer to bid. Straddle pays this twice. | [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:11), [fetch_po_comp_options.py](/root/spy/fetch_po_comp_options.py:317) | Inflates | Estimated spread haircut: single +6.6% to +4.2%; straddle +5.7% to +3.8% after strict entry + next-print exits. Median half-spread ~0.7-0.8% of premium per side; p90 ~1.8-2.0%. | Apply per-leg spread haircut from local high-low/Roll estimator, plus fixed floors by premium bucket; require minimum print counts. |
| 6 | Fixed bracket tie-breaking is inconsistent. Bilbo puts TP before stop in the candidate list; older options path puts stop before TP. Same-minute TP/SL bars can flip outcomes. | [backtest_po_comp_bilbo.py](/root/spy/backtest_po_comp_bilbo.py:192), [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:215) | Usually inflates if TP wins ties | Current headline fixed-bracket check found 0 same-bar TP/SL ties, so low for this sample; still a latent correctness issue. | Always apply conservative ordering: stop first if high and low both cross in same minute; report tie count. |
| 7 | No-fill and no-contract selection may remove the worst liquidity cases. Rows with no fill or entry <= $0.01 disappear from the denominator. | [backtest_po_comp_bilbo.py](/root/spy/backtest_po_comp_bilbo.py:151), [backtest_po_comp_bilbo.py](/root/spy/backtest_po_comp_bilbo.py:152), [backtest_po_comp_v3.py](/root/spy/backtest_po_comp_v3.py:100) | Likely inflates, unknown size | New12 run logged 22,463 no-fill leg drops. For headline legs, 27% of long legs and 36% of opposite legs have <100 entry-day prints. | Build an attempt-level table with reason codes; count boxes with missing one/both straddle legs; rerun with liquidity filters known before entry. |
| 8 | Rolled-to-open exclusion is a major sample definition. Strategy says intraday RTH break, so exclusion is defensible, but it removes 56% of immediate W1 ATM long legs. | [backtest_po_comp_v3.py](/root/spy/backtest_po_comp_v3.py:45), [backtest_po_comp_v3.py](/root/spy/backtest_po_comp_v3.py:160), [scratch_po_comp_flip_armtrail.py](/root/spy/scratch_po_comp_flip_armtrail.py:71) | Inflates if marketed as all breaks; neutral if strictly intraday-only | 3,043 / 5,422 long W1 ATM immediate legs are rolled-to-open. Excluded fixed bracket is -1.3%, so including them kills fixed bracket. | Publish intraday and overnight as separate strategies; do not pool or silently exclude. |
| 9 | Date/ticker clustering inflates t-stats. The 20 names are correlated and many boxes occur on the same market days. | [RESULTS.md](/root/spy/analyst/po_comp_options/RESULTS.md:320), [RESULTS.md](/root/spy/analyst/po_comp_options/RESULTS.md:341) | Inflates significance, not mean | Published all-name date clustering: single t 5.85 -> 4.31; straddle t 8.42 -> 5.61. Under realistic fills, straddle tclust falls to ~1.16-1.25. | Report date-clustered, ticker-clustered, and two-way cluster/bootstrap t for every headline. |
| 10 | Exit/data mining: arm-then-trail was chosen after a first fixed-bracket pass; new12 uses the same selected exit, so it is unseen tickers but not unseen exit logic. | [RESULTS.md](/root/spy/analyst/po_comp_options/RESULTS.md:209), [RESULTS.md](/root/spy/analyst/po_comp_options/RESULTS.md:220), [RESULTS.md](/root/spy/analyst/po_comp_options/RESULTS.md:295) | Inflates expected out-of-sample confidence | Unknown exact haircut. The later W1/W2 and stop grid confirms parameter shopping; the plateau helps, but t-stats should be deflated. | Nested validation: choose exit on orig8 year1, freeze, test orig8 year2 and new12; then reverse. |
| 11 | Strike snapping means “ATM” is sometimes not very ATM. | [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:70), [fetch_po_comp_options.py](/root/spy/fetch_po_comp_options.py:265) | Mixed | Median snap is 0.28% of spot, p90 0.65%, p99 2.01%; 24 headline legs >2% of spot. Small but nonzero. | Report moneyness bins; require `abs(strike-spot)/spot <= 1%` for ATM headline. |
| 12 | Settlement/hold uses intrinsic from underlying daily close, not an executable option bid near close. This mostly affects hold tails and the 4.9% of trail legs that hold to expiry. | [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:185), [backtest_po_comp_options.py](/root/spy/backtest_po_comp_options.py:190), [backtest_po_comp_bilbo.py](/root/spy/backtest_po_comp_bilbo.py:159) | Mixed; can inflate hold/straddle hold | Passive straddle hold is +9.4%, but executable close marks are unknown. | For held legs, exit at last print before 15:55/16:00 with bid/ask haircut proxy; compare to intrinsic settlement. |

## Quantified Robustness Snapshot

Published all-name W1 ATM intraday:

| Variant | Single | Straddle |
|---|---:|---:|
| Published level-fill trail | +13.5%, t=5.85 | +12.0%, t=8.42 |
| Date-clustered published | t=4.31 | t=5.61 |
| Strict entry + next-print/close exit | +6.6%, t=2.86 | +5.7%, t=4.06 |
| Strict entry + next-print/close + spread | +4.2%, t=1.83 | +3.8%, t=2.69 |
| Both legs <=5 min wait + spread | +6.4%, t=2.60 | +4.9%, t=3.14 |
| Same, date-clustered | t=1.62 | t=1.16 |

So the edge may survive in mean, but the current headline should not be presented as +12-13% executable expectancy.

## Bias-Robust Recovery Variants

1. **Strict next-print entry + next-print exit**
   Use first option print strictly after `sig_ms`, max wait 5 minutes. On trail/stop trigger, exit at first print after trigger or trigger-bar close proxy. This is already mostly codable from `scratch_bias_1_resim.py`.

2. **Close-confirmed arm-trail**
   Arm from prior closes, trail from prior close HWM, trigger and fill on close. Current recovery result: single +7.3%, straddle +5.2% after strict entry and spread, though date-clustered t is still weak.

3. **Liquidity-gated straddle**
   Require both legs: entry wait <=5 minutes, entry-day prints >=100, premium >= $0.25, estimated half-spread <=2% of premium. Current realistic straddle with >=100 prints/day is ~+6.2% to +7.0% depending exit proxy.

4. **Spread-aware fixed bracket baseline**
   Re-run TP100/SL50 with stop-first ties and stop fill at next print. Current fixed bracket drops from +2.8% to -0.6%, so it becomes a useful sanity benchmark: any trail variant must clear this under identical execution.

5. **Date-clustered portfolio variant**
   One trade per ticker per day max, or one straddle per calendar day selected by best pre-entry liquidity/cost. Report day-level mean and bootstrap CI. This directly addresses the current t-stat inflation without needing new data.

## Round 2 — response to quantified findings + recovery pick

I agree with the core read: after freeze ambiguity plus realistic fills, the current headline should be retired, not caveated.

One process note: I accidentally ran `scratch_bias_4_freeze.py`, which rewrites `scratch_bias_freeze_class.parquet`. It regenerated the same derived classification and printed the numbers you quoted, but that did violate your read-only preference for round 2.

**1. Ambiguous classification**

Your classification is fair for invalidating the published headline. The published entry uses the final frozen box before the bar that proves the box is final has closed. That is a real survivorship channel: failed pokes that would have expanded/redefined the box are absent.

Two refinements:

- `entry <= confirm_close` may slightly overcount boundary cases exactly at `confirm_close`. In practice, if the hourly close and option entry timestamp are identical, a live trader would only know the final compression state after the close, then still need a post-close option print. I would keep it ambiguous or make a third `boundary` bucket; do not move it into clean tradeable without proving the option fill occurs after final bar observability.
- Variant A does not mathematically “settle” every ambiguous case because it is orig8 only and it may not reproduce the exact final-box population. But it is the right falsification test. If a live intrabar-flag trader must also take reabsorbed pokes, and A realistic is ~0, then the ambiguous subset’s +16.5% single / +8.8% straddle is not deployable evidence.

So: not overstated. I would phrase it as “the residual realistic edge is concentrated in a non-final-box subset; the closest live analogue does not reproduce it.”

**2. Exit proxy**

`min(level, trigger-bar close)` is not too harsh. If anything, it is still generous for stop-market behavior in fast option tape.

The single-print issue argues against level fills, not against close fills. On a single-print minute, `high == low == close`; if low crosses the stop, the only observed trade is already at or through the stop. Filling at the stop level is synthetic.

Better prints-only proxies, in order:

- Best/optimistic: current level fill.
- Practical midpoint: trigger-bar close or VWAP if `vw` is populated.
- More causal: next minute open after the trigger bar.
- Conservative: trigger-bar low for stop exits.
- Sensitivity band: report close/VWAP and next-minute-open; if the edge only survives level fills, it is not executable.

I would not build a Brownian bridge or infer trade ordering inside the minute. That adds model comfort without real observability.

**3. Spread band**

Yes, fair: report the realistic mean as roughly +2% to +6%, with sign uncertain after quoted spreads and clustering.

Your effective-spread estimator is not a quote spread. It can overstate spread when high-low is real movement, but it can also understate live cost because buys lift ask and sells hit bid, especially on weeklies around breaks. The right language is:

“Using trade-print effective-spread proxies, realistic straddle means are low-single-digit positive. At plausible quoted half-spreads of 1-2% per side, the expectancy ranges from marginally positive to indistinguishable from zero; at ~3.4%/side it is gone.”

Also emphasize date clustering: the realistic straddle tclust around 1 is the bigger statistical killer than the exact spread point estimate.

**4. Pick one recovery experiment**

Pick **F locked 5-bar box straddle with underlying-price-based exits**, on existing `flip8_fullbox_trades.parquet`.

Reason: F is the cleanest live-knowable entry left, and underlying-based exits directly remove the remaining option-print HWM/outlier problem. Day aggregation is a reporting fix, not a recovery. New12 F is the real validation, but it is an expensive rerun; do it only if this survives orig8 under clean exits.

Precise test:

- Population: `flip8_fullbox_trades.parquet`, `bucket == W1`, `offset == 0`, `~rolled_to_open`, `~censored`, both straddle legs present.
- Entry: first option print strictly after `entry_ts`, max wait 5 min, both legs required.
- Underlying exit clock: 5m underlying bars after entry.
- For each leg independently:
  - Call favorable path = underlying high/close above entry spot.
  - Put favorable path = underlying low/close below entry spot.
  - Arm when favorable 5m close excursion reaches `0.75 * box_h` from entry spot.
  - Trail on underlying closes at 50% retracement of the best favorable close excursion after arming.
  - Initial invalidation before arming: 5m close back through the opposite side of the locked box.
  - Time exit: Friday 15:55 ET or last available pre-expiry print.
- Option execution: sell at first option print after the underlying exit bar close, max wait 15 min; apply the same spread haircut.
- Report: mean, plain t, date-clustered t, win rate, and compare to current F option-HWM straddle +5.8%.

Pass bar: F straddle remains >+4% mean and date-clustered t >1.5 on orig8. If it fails, stop. If it passes, spend on new12 F rerun.

**5. What I’d push back on**

Your bias table is mostly right. The only places I’d soften:

- “Entire edge is non-live” is true for the realistic residual in the published population, but not literally for the ideal-fill published straddle: tradeable V0 straddle is still +11.2%, t=6.2. The correct conclusion is that tradeable V0 depends on non-executable exits, while realistic residual depends on ambiguous entries.
- A does not fully settle new12 because it is orig8 only. It is strong evidence, not final proof.
- The spread estimator should not be called “the” effective spread. It is a proxy from trade aggregates. Keep the band framing.
- F straddle +5.8%, t=1.7 is not dead; it is underpowered and unvalidated. It is the only remaining candidate I would spend another hour on.
