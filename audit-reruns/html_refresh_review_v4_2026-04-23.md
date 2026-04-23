# HTML Refresh Review v4 - 2026-04-23

Source checked:

- `/root/milkman/premarket-ath.html`
- `/root/milkman/4h-po-opex.html`
- `/root/milkman/gg-invalidation.html`
- `/root/spy/premarket_ath_results.json`
- `/root/spy/audit-reruns/backtest_premarket_ath.log`
- `/root/spy/audit-reruns/backtest_4h_po_opex_extended.log`
- `/root/spy/audit-reruns/backtest_gg_entries.log`

Result: clean for the four v3 residuals. No stale numbers remain in the checked items.

## Checks

- `premarket-ath.html`: `runLow` now matches `/root/spy/premarket_ath_results.json` `running_low_profile` numerically for `pm`, `non`, and `pmUp`. The HTML uses a few trailing zeroes such as `-0.2410`, `-0.3060`, `-0.5330`, and `-0.6070`; those are value-equivalent to the JSON values.
- `premarket-ath.html`: `rrData` now matches the current RISK/REWARD table in `/root/spy/audit-reruns/backtest_premarket_ath.log`: First 30m `0.140/0.104/RR 1.26`, First hour `0.188/0.133/RR 1.37`, Morning `0.249/0.181/RR 1.41`, Full day `0.362/0.266/RR 1.34`; non-ATH rows `0.253/0.241/RR 1.00`, `0.350/0.330/RR 1.01`, `0.480/0.441/RR 1.06`, `0.699/0.635/RR 1.05`.
- `4h-po-opex.html`: the "hit years" sentence now includes `2000`, matching the current extended event list and the `2000-03-20` hit.
- `gg-invalidation.html`: the entries paragraph now uses `~32-37%`, `62-64%`, `96%`, and `~59%`, matching the current trigger-pullback and EMA 8 rows in `/root/spy/audit-reruns/backtest_gg_entries.log`.

No further stale values were found in this v3 residual pass.
