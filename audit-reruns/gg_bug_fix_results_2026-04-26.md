# GG Bug Fix Results — 2026-04-26

Window used for all saved reruns: published `2000-2025` RTH sample only, implemented as `timestamp < 2026-01-01 00:00:00`. This explicit cutoff matters because `/root/spy/spy.db` now extends through `2026-04-09`.

Artifacts saved under `/root/spy/audit-reruns/postfix-stats_2026-04-26/`:

- `gg_leg_breakdowns_2026-04-26.csv`
- `gg_leg_breakdowns_2026-04-26.json`
- `gg_po_bucket_comparison_2026-04-26.csv`
- `gg_po_bucket_comparison_2026-04-26.json`

## Fix

Consumer-side fix only. `aggregate.py` remains unchanged and still produces left-labeled 1h bars. `backtest_gg_with_po.py` now shifts 1h timestamps to bar-end before the backward `merge_asof`, matching the already-safe pattern in `backtest_bilbo_box_htf_po_exits.py:126-145`.

```diff
diff --git a/backtest_gg_with_po.py b/backtest_gg_with_po.py
index 14efe1e..8de2ef6 100644
--- a/backtest_gg_with_po.py
+++ b/backtest_gg_with_po.py
@@ -64,21 +64,19 @@ def main():
         "FROM ind_1h ORDER BY timestamp",
         conn, parse_dates=["timestamp"]
     )
+    df60 = df60.dropna(subset=["phase_oscillator"]).copy()
     df60 = df60.set_index("timestamp").sort_index()

-    # Pre-compute PO slope (current vs previous bar)
+    # Pre-compute PO slope (current vs previous completed bar).
     df60["po_prev"] = df60["phase_oscillator"].shift(1)

-    # For fast lookup: for a given 10m timestamp, find the most recent 60m bar
-    # Build a mapping: each 10m bar -> nearest prior 60m PO reading
+    # aggregate.py writes left-labeled 1h bars, so a row stamped 09:00 contains
+    # the hour that closes at 10:00. Shift to bar-end timestamps before the
+    # backward merge so 10m triggers only see fully closed 1h PO values.
     print("Mapping 10m bars to 60m PO snapshots...", flush=True)
-    po_vals = df60["phase_oscillator"]
-    po_prevs = df60["po_prev"]
-    po_comp = df60["compression"]
-
-    # Use merge_asof for efficient time-based join
     df10_reset = df10.reset_index()
     df60_reset = df60.reset_index()
+    df60_reset["timestamp"] = df60_reset["timestamp"] + pd.Timedelta(hours=1)
     merged = pd.merge_asof(
         df10_reset[["timestamp"]],
         df60_reset[["timestamp", "phase_oscillator", "po_prev", "compression"]],
```

## Verification

- `aggregate.py:57-66` still uses left-labeled `resample("1h")`. That is the producer behavior that made the original join unsafe.
- The fix is intentionally at the consumer side, so studies that already shift completed higher-timeframe bars remain untouched.
- `backtest_bilbo_box_htf_po_exits.py:126-145` is already correct.
- `backtest_call_to_put_reversal.py:142-158` is already correct.
- The unconditioned leg tables below are identical before and after the join fix. That is expected: the bug changes PO bucket assignment, not whether price touched `23.6`, `38.2`, or `61.8`.

Cat definitions used below:

- `Cat A`: open already beyond the target level
- `Cat B`: open between the source level and the target level
- `Residual`: open before the source level, then cross it intraday

## Trigger Leg — 23.6 -> 38.2

| Direction | Category | Buggy N | Buggy Done | Buggy % | Fixed N | Fixed Done | Fixed % |
|---|---|---:|---:|---:|---:|---:|---:|
| BULL | Overall | 4355 | 3421 | 78.6% | 4355 | 3421 | 78.6% |
| BULL | Cat A | 1066 | 1066 | 100.0% | 1066 | 1066 | 100.0% |
| BULL | Cat B | 767 | 666 | 86.8% | 767 | 666 | 86.8% |
| BULL | Residual | 2522 | 1689 | 67.0% | 2522 | 1689 | 67.0% |
| BEAR | Overall | 4044 | 3196 | 79.0% | 4044 | 3196 | 79.0% |
| BEAR | Cat A | 857 | 857 | 100.0% | 857 | 857 | 100.0% |
| BEAR | Cat B | 582 | 520 | 89.3% | 582 | 520 | 89.3% |
| BEAR | Residual | 2605 | 1819 | 69.8% | 2605 | 1819 | 69.8% |

## GG Completion Leg — 38.2 -> 61.8

| Direction | Category | Buggy N | Buggy Done | Buggy % | Fixed N | Fixed Done | Fixed % |
|---|---|---:|---:|---:|---:|---:|---:|
| BULL | Overall | 3421 | 2139 | 62.5% | 3421 | 2139 | 62.5% |
| BULL | Cat A | 368 | 368 | 100.0% | 368 | 368 | 100.0% |
| BULL | Cat B | 698 | 547 | 78.4% | 698 | 547 | 78.4% |
| BULL | Residual | 2355 | 1224 | 52.0% | 2355 | 1224 | 52.0% |
| BEAR | Overall | 3196 | 2090 | 65.4% | 3196 | 2090 | 65.4% |
| BEAR | Cat A | 375 | 375 | 100.0% | 375 | 375 | 100.0% |
| BEAR | Cat B | 482 | 390 | 80.9% | 482 | 390 | 80.9% |
| BEAR | Residual | 2339 | 1325 | 56.6% | 2339 | 1325 | 56.6% |

## PO Bucket Comparison

The base GG completion rates are unchanged by the fix:

- Bull: `2139/3421 = 62.5%`
- Bear: `2090/3196 = 65.4%`

The distortion is in bucket membership and bucket win rates. The headline zone+slope shifts reproduced from the prior review are:

- Bull `High+Rising`: `289/381 = 75.9%` -> `137/193 = 71.0%`
- Bear `Low+Falling`: `240/268 = 89.6%` -> `120/141 = 85.1%`
- Bull `Mid+Falling`: `342/672 = 50.9%` -> `515/817 = 63.0%`
- Bear `Mid+Rising`: `341/626 = 54.5%` -> `538/773 = 69.6%`

### Bullish

| Zone | Slope | State | Buggy N | Buggy Done | Buggy % | Fixed N | Fixed Done | Fixed % | Δ pct |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| mid | rising | compression | 1266 | 747 | 59.0% | 1207 | 693 | 57.4% | -1.6% |
| mid | rising | bull_exp | 684 | 471 | 68.9% | 540 | 343 | 63.5% | -5.4% |
| mid | rising | bear_exp | 295 | 194 | 65.8% | 448 | 293 | 65.4% | -0.4% |
| mid | falling | compression | 334 | 156 | 46.7% | 374 | 227 | 60.7% | +14.0% |
| mid | falling | bull_exp | 268 | 148 | 55.2% | 363 | 234 | 64.5% | +9.3% |
| high | rising | bull_exp | 361 | 272 | 75.3% | 183 | 132 | 72.1% | -3.2% |
| high | falling | bull_exp | 107 | 87 | 81.3% | 167 | 123 | 73.7% | -7.6% |
| mid | falling | bear_exp | 70 | 38 | 54.3% | 80 | 54 | 67.5% | +13.2% |
| low | rising | bear_exp | 11 | 7 | 63.6% | 33 | 21 | 63.6% | +0.0% |
| low | falling | bear_exp | 2 | 1 | 50.0% | 15 | 13 | 86.7% | +36.7% |
| high | rising | compression | 20 | 17 | 85.0% | 10 | 5 | 50.0% | -35.0% |
| high | falling | compression | 3 | 1 | 33.3% | 1 | 1 | 100.0% | +66.7% |

### Bearish

| Zone | Slope | State | Buggy N | Buggy Done | Buggy % | Fixed N | Fixed Done | Fixed % | Δ pct |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| mid | falling | compression | 1325 | 844 | 63.7% | 1228 | 753 | 61.3% | -2.4% |
| mid | falling | bear_exp | 651 | 455 | 69.9% | 487 | 322 | 66.1% | -3.8% |
| mid | falling | bull_exp | 214 | 112 | 52.3% | 388 | 213 | 54.9% | +2.6% |
| mid | rising | compression | 318 | 143 | 45.0% | 352 | 238 | 67.6% | +22.6% |
| mid | rising | bear_exp | 274 | 185 | 67.5% | 346 | 251 | 72.5% | +5.0% |
| low | rising | bear_exp | 103 | 93 | 90.3% | 148 | 128 | 86.5% | -3.8% |
| low | falling | bear_exp | 263 | 235 | 89.4% | 139 | 118 | 84.9% | -4.5% |
| mid | rising | bull_exp | 34 | 13 | 38.2% | 75 | 49 | 65.3% | +27.1% |
| high | falling | bull_exp | 9 | 5 | 55.6% | 20 | 9 | 45.0% | -10.6% |
| high | rising | bull_exp | 0 | 0 |  | 10 | 6 | 60.0% |  |
| low | falling | compression | 5 | 5 | 100.0% | 2 | 2 | 100.0% | +0.0% |
| low | rising | compression | 0 | 0 |  | 1 | 1 | 100.0% |  |

## Follow-Up — Do Not Fix In This Pass

Exact same GG + 60m PO consumer bug still exists here:

- `server.py:792-807` — same unshifted `ind_1h` PO `merge_asof` onto 10m bars
- `export_study_dates.py:137-145` — same unshifted `df60` PO join in the bilbo GG export path

Same start-labeled 1h `merge_asof` pattern, but on other 1h features rather than PO:

- `backtest_gg_entries.py:44-52` — unshifted 1h EMA join onto 10m bars
- `backtest_gg_invalidation.py:59-67` — unshifted 1h EMA join onto 10m bars

These were cataloged only. No changes were made outside the Agent A scope.
