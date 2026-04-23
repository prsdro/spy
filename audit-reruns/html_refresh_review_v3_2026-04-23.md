# HTML Refresh Review v3 - 2026-04-23

Result: not fully clean.

- `premarket-ath.html`: `/root/milkman/premarket-ath.html:488-490` `runLow`
  is close but not exact to `/root/spy/premarket_ath_results.json`
  `running_low_profile`. Replace with current arrays:
  `pm [-0.12,-0.1396,-0.1581,-0.1774,-0.1879,-0.1986,-0.2224,-0.241,-0.2558,-0.2649,-0.2793,-0.2934,-0.306,-0.3228,-0.3326,-0.3484,-0.3619]`;
  `non [-0.2096,-0.2531,-0.2993,-0.3283,-0.3501,-0.3725,-0.4246,-0.4594,-0.4895,-0.5123,-0.533,-0.5545,-0.5806,-0.607,-0.6369,-0.6724,-0.6993]`;
  `pmUp [0.0895,0.1037,0.1151,0.1248,0.1333,0.1432,0.1597,0.1737,0.1845,0.1964,0.2078,0.2181,0.2252,0.2333,0.2406,0.2504,0.2656]`.

- `premarket-ath.html`: `/root/milkman/premarket-ath.html:493-497`
  `rrData` still does not match current `backtest_premarket_ath.log`
  RISK/REWARD table. Current rows are First 30m
  `0.140/0.104/RR 1.26`, First hour `0.188/0.133/RR 1.37`,
  Morning `0.249/0.181/RR 1.41`, Full day `0.362/0.266/RR 1.34`;
  Non-ATH rows are `0.253/0.241/RR 1.00`, `0.350/0.330/RR 1.01`,
  `0.480/0.441/RR 1.06`, `0.699/0.635/RR 1.05`.

- `4h-po-opex.html`: `/root/milkman/4h-po-opex.html:248` says
  `2001, 2007, 2011, 2017, 2019` are "the hit years"; current extended event
  list also has a hit on `2000-03-20`. Add `2000` or remove the exhaustive
  wording.

- `gg-invalidation.html`: `/root/milkman/gg-invalidation.html:157` still says
  trigger pullback completion is `~43-48%`; current `backtest_gg_entries.log`
  trigger-pullback rows are `32.4%` and `36.8%`, so this should be `32-37%`.
