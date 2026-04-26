# Codex 5.5 review

## Claim 1 — bug verdict
- Verdict: CONFIRMED
- Evidence (line numbers, code excerpts):
  - `backtest_gg_with_po.py:62-70` loads `ind_1h` PO and computes `po_prev`.
  - `backtest_gg_with_po.py:79-91` does `pd.merge_asof(..., on="timestamp", direction="backward")` with unshifted 1h timestamps, then stamps `po_60m` / `po_prev_60m` onto each 10m bar.
  - `aggregate.py:57-66` and `aggregate.py:89-97` build `candles_1h` via pandas `resample("1h")` with default left-labeling. In this DB, the `2000-01-03 10:00:00` 1h candle equals the OHLC of `10:00-10:59`, not a bar that closed at `10:00`.
  - `backtest_gg_with_po.py:116-127` and `backtest_gg_with_po.py:149-160` find the first 10m bar that touches `38.2`, then immediately read the joined 1h PO from that same 10m timestamp. So a `09:30` trigger reads the `09:00` 1h row, which already contains `09:30-09:59`; a `10:xx` trigger reads the `10:00` row, which contains `10:00-10:59`. That is future-aware leakage.
  - The user's "10:00 close of the 09:00-10:00 bar" phrasing is slightly off. The real bug is worse: the code is seeing the current in-progress hour bar, not the last fully closed hour bar.
  - `backtest_gg_with_po.py:140-142` and `backtest_gg_with_po.py:172-174` also allow same 10m trigger-bar completion at `61.8`, which is a separate same-bar ordering ambiguity.
- Impact on stats:
  - This is a real look-ahead/data-leak in the PO-conditioned study. It does not materially change raw GG baseline completion, but it does materially distort which trades land in the "best" and "worst" PO buckets.
  - On the published `2000-2025` window with the current ATR-fixed DB, leaky join vs point-in-time-safe join under the same inclusive completion convention:
  - Bull `PO High+Rising`: `289/381 = 75.9%` -> `137/193 = 71.0%`
  - Bear `PO Low+Falling`: `240/268 = 89.6%` -> `120/141 = 85.1%`
  - Bull `PO Mid+Falling`: `342/672 = 50.9%` -> `515/817 = 63.0%`
  - Bear `PO Mid+Rising`: `341/626 = 54.5%` -> `538/773 = 69.6%`
  - The standout Bilbo edge weakens, and some "worst" buckets partly invert once the join is made point-in-time safe.
- Fix:
  - Shift 1h timestamps forward by one full hour before `merge_asof(..., direction="backward")`, or equivalently shift the joined PO values by one 1h bar, so each 10m trigger sees only the last fully closed 1h bar.
  - `backtest_bilbo_box_htf_po_exits.py:126-145` already shows the correct pattern: add one full HTF bar duration, then `merge_asof`.
  - After this fix, expect the published `77.7% / 90.2%` style Bilbo headlines to compress toward roughly low-70s for bull `High+Rising` and mid-80s for bear `Low+Falling` on the current DB, with bucket membership reshuffled materially.

## Claim 2 — stat verdict
- Verdict: PARTIAL
- Evidence (numbers, math):
  - Published surfaces are mixing two different chains. `analyst/studies_reference.md:12-13` and `site/cheatsheet.html:166-170` say `Trigger -> 38.2 = 80%`, while `MASTER_TRADING_KNOWLEDGE.md:399-408` and `site/cheatsheet-timing.html:269-272` summarize the GG subway/open-trigger study as `38.2 -> 61.8`, with open triggers around `86-88%`.
  - `KNOWLEDGE.md:172-205` is older image-sourced Tesrak public subway data for `trigger -> 38.2`, so it is not the same endpoint as the GG completion study.
  - Direct `2000-2025` sanity check on the current DB for GG `38.2 -> 61.8`:
  - Bull Cat A `open >= 61.8`: `368/368 = 100.0%`
  - Bull Cat B `38.2 <= open < 61.8`: `547/698 = 78.4%`
  - Bull residual `open < 38.2`, later crosses `38.2`: `1224/2355 = 52.0%`
  - Bear Cat A `open <= -61.8`: `375/375 = 100.0%`
  - Bear Cat B `-61.8 < open <= -38.2`: `390/482 = 80.9%`
  - Bear residual `open > -38.2`, later crosses `-38.2`: `1325/2339 = 56.6%`
  - Excluding later same-trigger-bar ambiguity only nudges the residual to `51.1%` bull / `56.1%` bear, so the user's `52.1% / 56.5%` residual is basically reproduced.
  - Cat A + B are about `31.2%` of bull GG samples and `26.8%` of bear GG samples. Including them lifts overall GG completion from residual `52.0% / 56.6%` to headline `62.5% / 65.4%`.
  - The open-gap cohort alone is `915/1066 = 85.8%` bull and `765/857 = 89.3%` bear, which is exactly why the Subway/open row lands near the published `86-88%`.
- Implication for the published 80%:
  - If someone uses the published `80%` as if it described a fresh intraday `38.2 -> 61.8` trigger, that is wrong. The true residual cohort is only about `52-56%`.
  - But the exact `80%` figure belongs to a different study, `23.6 trigger -> 38.2`, so the user's `52-56%` residual does not directly refute that chain. It does show that GG subway/open headlines are materially boosted by gap-through samples and should not be sold as the probability of a clean intraday cross continuing to `61.8`.

## Bottom line
`backtest_gg_with_po.py` has a real higher-timeframe look-ahead bug: the 1h PO join is not point-in-time safe because the hourly bars are start-labeled and merged without a one-bar shift. The user's residual `52-56%` GG numbers are real for the `38.2 -> 61.8` intraday-cross cohort, but they are being compared against a different published `80%` `trigger -> 38.2` chain unless the docs explicitly keep those two studies separate.
