# Codex Review: PO-Compression Options Study

## 1. Correctness

### High: delayed entries use expiries anchored to compression start, not actual entry

Files: `backtest_po_comp_options.py:121-123`, `backtest_po_comp_options.py:125-132`, `backtest_po_comp_bilbo.py:111-116`, `backtest_po_comp_bilbo.py:205-211`, `fetch_po_comp_options.py:261-267`.

Issue: W1/W2/M1 contracts are selected from `start_ts_et` for all entry variants. That is reasonable for `comp_start`, but `expansion_confirm`, `immediate`, and especially `retest` can occur hours or days later. Those delayed entries are therefore not always "1 week / 2 weeks / 1 month out" at entry time.

Why it matters: this can materially change the option being traded. In saved results, `expansion_confirm` W1 has DTE 0-10 and 22.9% of legs are under 4 DTE; Bilbo retest W1 has DTE 0-10. The 5-bar retest lead is concentrated in W1: raw 5-bar retest long `pnl_tp100_stop50` is +10.4% over 81 episodes, while W1 alone is +12.2% and W2 is only +2.0%. The sharp down-break put cell is +31.3% in W1 but +10.0% in W2. Short DTE may be the edge, but then the label is wrong; if the desired test is true entry-date W1/W2, the current number is biased by stale expiry selection.

Direction of bias: ambiguous for the broad result, but it likely inflates convex retest-breakout leads if the winning path depends on cheap near-expiry gamma. It can also over-penalize delayed entries when theta is already mostly gone or the contract is effectively same-week.

Fix: for any entry variant with its own `sig_ts`, compute `w1 = next_friday(sig_ts.date())` and buckets from that entry date. Pull missing contracts for the delayed-entry contract universe, then rerun side-by-side: `expiry_anchor=start` vs `expiry_anchor=entry`. Keep the start-anchored version only if deliberately testing "contracts selected at compression start and entered later."

### Medium: random baseline is not an away-from-compression carry baseline

Files: `scratch_po_comp_random_baseline.py:44-47`, `scratch_po_comp_random_baseline.py:150-161`.

Issue: the baseline samples random hourly bars from the whole eligible window. It does not exclude `po_compression == 1` bars or periods near active compression episodes. A read-only check found 55 of 186 pseudo events, 29.6%, are themselves compression bars.

Why it matters: the live lead says "short premium carry away from compression" and "compression is the worst time to sell premium." The current random sample is a mixed baseline, not an away-from-compression baseline. If compression hurts short-premium carry, including compression bars understates the true carry-away edge and blurs the overlay result.

Direction of bias: likely understates short-premium carry away from compression, and likely understates compression long-premium edge versus a pure non-compression baseline.

Fix: create three controls with the same ticker counts and date caps: `all_random`, `non_compression_random`, and `compression_bar_random`. Also test exclusion windows around episodes, e.g. no active compression and no compression start/end in the prior/next 1, 3, and 7 hourly bars.

### Medium: baseline script mutates the shared SQLite database

Files: `scratch_po_comp_random_baseline.py:72-113`, `scratch_po_comp_random_baseline.py:137`.

Issue: the baseline script writes missing contracts and bars directly into `option_bars.sqlite`. That is operationally unsafe while another process is appending and makes the baseline dependent on live API/data state.

Why it matters: not necessarily a directional bias in the saved artifact, but it can change future reruns, collide with the v2 writer, and makes reproducing the baseline harder.

Fix: run baseline pulls into a separate SQLite file, or make the script fail fast if contracts are missing and require the fetch phase to populate them. For this review I only read parquet/csv artifacts and did not touch SQLite.

### Low: duplicate snapped contracts are counted multiple times in pooled cells

Files: `backtest_po_comp_options.py:70-75`, `backtest_po_comp_options.py:137-150`, `backtest_po_comp_bilbo.py:116-127`.

Issue: multiple requested offsets can snap to the same listed option contract. Offset-specific tables are still interpretable, but pooled means can overweight duplicate rows.

Why it matters: this did not materially move the current leads: 5-bar retest long `pnl_tp100_stop50` changes from +10.4% to +9.6% after contract-level dedupe; down-break puts change from +21.5% to +20.4%. Still, deduping is cleaner for pooled headline stats.

Fix: when aggregating across offsets, drop duplicates on event, entry/variant, direction, bucket, vehicle, contract, exit rule before event clustering; keep offset-specific tables unchanged.

### Low: `fill_lag_min` sign is inverted from the field name

Files: `backtest_po_comp_options.py:78-92`, `backtest_po_comp_options.py:225-232`.

Issue: `fill_lag_min = (sig_ms - fill_ms) / 60000`, so positive means a stale print before signal and negative means a forward fill after signal.

Why it matters: the numbers are not wrong, but sensitivity reports can be misread. Saved fills include stale prints as old as 53 minutes and forward waits as high as 59 minutes.

Fix: rename to `fill_staleness_min`, add `fill_wait_min`, or store both signed and absolute fields. Rerun the lead cells with `abs_lag <= 5`, `<= 15`, and no stale-before-entry fills.

## 2. Amplification

Ranked by expected impact times testability with current artifacts or sub-hour Massive pulls.

1. Re-anchor delayed-entry expiries and explicitly test DTE buckets at entry. This resolves the biggest correctness issue and may reveal that the real edge is "5-bar retest plus 0-3 DTE gamma" rather than generic W1. Test W0/same-week, 4-7 DTE, 8-14 DTE, and 15-30 DTE for mature-box retests and down-break puts.

2. Turn the random short-premium lead into a compression risk-timer. Build `sell ATM W1/W2 except during active compression or N bars after compression start/end`, then compare to always-sell random entries. Metrics should include mean premium return, left-tail loss, stop2x rate, and avoided-loss contribution by ticker.

3. Convert naked short premium into defined-risk credit spreads using already pulled multi-strike prints. For random/non-compression carry, sell ATM or 0.5 ATR option and buy 1.0 ATR wing on the same side; for compression avoidance, suppress entries when PO compression is active. Test width in ATR, decay50, stop at spread value 2x credit, and max-loss hold.

4. Convert mature-box down-break puts into put debit spreads. Buy ATM/0.5 ATR put at retest and sell 1.0 ATR or box-measured-move put. This should reduce theta and spread/slippage exposure while preserving the lead's directional convexity. Test W0/W1/W2 after expiry re-anchor.

5. Add IV-proxy filters from `straddles.parquet`: trade retest longs only when ATM straddle cost as pct of spot is below the ticker's rolling median/tercile for that DTE. Hypothesis: compression predicts movement, but long premium wins only when the move is not fully priced.

6. Add box-quality filters: require 5 compression bars, box height between 0.25 and 0.75 daily ATR, retest within 1-3 sessions, and retest close not deeply back inside the box. The current notes already say tiny boxes dilute the edge; quantify the mature-box geometry that keeps enough move for premium.

7. Exit retest longs on first favorable impulse instead of static option TP only. Test 5m close through breakout extreme, box measured-move touch, trailing stop after +50% premium, and time stop after 2 or 4 RTH hours without progress. This targets the observed "longer hold bleeds" pattern.

8. Size by premium risk and realized fill quality. For long retests, skip contracts with entry premium above a percentile of spot or with stale/forward fill over 5 minutes. For short carry, scale down when ATM straddle cost is in the top tercile or when the underlying is in active compression.

## 3. Fresh Structures

1. Compression state overlay for a systematic weekly short straddle/strangle proxy. Sell ATM call plus put, or sell 0.5 ATR strangle, only outside compression. Use bought 1.0 ATR wings for defined risk. This directly exploits the strongest current result: random short ATM premium +15.5% while compression shorts are weaker.

2. Cross-ticker conditioning from v2. Use all 8 tickers to test whether mature-box retest longs work only when the broader mega-cap complex is aligned, e.g. at least 5 of 8 above hourly EMA21, or no more than 2 tickers simultaneously in compression. This is testable from `events_v2.csv` plus existing 5m data.

3. IV-proxy term structure without quotes. Compare W1 ATM straddle cost / spot to W2 ATM straddle cost / spot at entry. Long retests should prefer low W1/W2 cost or compressed term premium; short carry should prefer high W1 cost but avoid active compression.

4. Opening-hour and late-day split. Separate entries in first 60 minutes, mid-day, and after 14:30 ET. Option prints and gamma behavior differ materially by time of day, and Bilbo entries are 5m-timed enough to test this now.

5. Earnings proximity filter. Pull or load earnings dates for the 8 tickers and classify entries as pre-earnings, post-earnings drift, or normal. With only trade prints, earnings proximity is the cheapest way to approximate event-vol contamination.

6. Retest microstructure filter. For retest entries, measure whether the retest is a wick-only touch versus a 5m close back through the broken edge. Buy only failed retests that close back outside the box in breakout direction; fade or skip deep closes inside the box.

7. Paired long/short overlay: hold short premium by default, but buy a cheap put/call debit spread only on mature-box retest/down-break events. This tests whether the retest signal is best used as a hedge/tail overlay on the carry book rather than standalone long premium.

8. Ticker-personality split. Current 5-bar retest episodes are balanced across AMZN/MSFT/NVDA, but payoff likely is not. In v2, rank tickers by random carry Sharpe, compression penalty, and retest payoff; deploy the carry overlay only where compression meaningfully raises short-premium loss risk.

## 4. Minimal Rerun Plan

1. Patch expiry bucket construction to support `anchor=start|entry`, rerun main and Bilbo with `anchor=entry`.

2. Build pure `non_compression_random` and `compression_random` baselines; report carry overlay lift versus both.

3. Add deduped pooled summaries and fill-lag sensitivity cuts.

4. Use existing multi-strike prints to simulate defined-risk credit spreads and put debit spreads for the top cells.

5. Run v2 on the same corrected definitions before promoting any single mined cell.

One-line caveat: treat current lead cells as hypotheses until v2 confirms them out of sample, but prioritize fixing expiry anchoring and baseline state first because those can make the edge definition sharper rather than merely more conservative.
