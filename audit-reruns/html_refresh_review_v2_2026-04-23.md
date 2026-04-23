# HTML Refresh Review v2 - 2026-04-23

Source checked: `/root/spy/audit-reruns/refresh-outputs/*.log`,
`/root/spy/gap_fill_cumulative.json`, and
`/root/spy/premarket_ath_results.json`.

Result: not fully clean. Most priority fixes landed, but several stale
secondary widgets/prose blocks remain.

## Residual Findings

- `premarket-ath.html`: PARTIAL.
  - `/root/milkman/premarket-ath.html:300` still says `2007-2026` and `46%`
    smaller; current source range is `2013-04-11 -> 2026-01-28` and key
    insight is `48%` smaller.
  - `/root/milkman/premarket-ath.html:349` still shows `46%`; current
    rounded reduction from `-0.2493` vs `-0.4796` is about `48%`.
  - `/root/milkman/premarket-ath.html:488` and
    `/root/milkman/premarket-ath.html:494` still use stale run-low/R:R data.
    Example: HTML full-day PM `-0.395/+0.276/RR 1.35`; current log/JSON is
    `-0.362/+0.266/RR 1.34`.
  - `/root/milkman/premarket-ath.html:543` omits current years `2013`,
    `2014`, and `2015` from `yearData`.

- `sustained-po.html`: PARTIAL.
  - `/root/milkman/sustained-po.html:301` still has PO collapse values
    `91.4 / 7.9 / 0.3%`; current log is `91.3 / 8.5 / 0.4%`.
  - `/root/milkman/sustained-po.html:363` and
    `/root/milkman/sustained-po.html:370` still use old day-high bracket/time
    counts from the prior `n=289` sample. Current reversal log is `n=274`,
    bracket counts `26/34/36/73/85/20`, and 15:30 high count `84`, not `86`.
  - The fast-cloud section is now explicitly marked as prior `n=289`; that
    caveat is acceptable.

- `4h-po-opex.html`: PARTIAL.
  - `/root/milkman/4h-po-opex.html:148` still says the 5-day extended window
    hits `1%` only `43%`; current table/log is `46%`.
  - `/root/milkman/4h-po-opex.html:244` says deep extension hits `1%` at 5d
    `33%` vs moderate `43%`; current deep-extension row is `50%`, and the
    OpEx-window extended row is `46%`.
  - `/root/milkman/4h-po-opex.html:248` still references `2012` and `2018`
    as hit years, but neither appears in the current 13-row event list.

- `call-trigger.html`: PARTIAL.
  - `/root/milkman/call-trigger.html:748` correctly shows trigger-bar hits
    as `0`, but `/root/milkman/call-trigger.html:837` still renders
    `Same bar` speed as `6.1%`. Current log says `Hit on trigger bar itself:
    0 times`.
  - Spot-checked `timeData` and `invalData` rows now match the printed tables.

- `gg-invalidation.html`: MINOR.
  - `bullData`/`bearData` pct and `n` spot checks match current log-derived
    values.
  - `/root/milkman/gg-invalidation.html:187` still labels bearish held entries
    as `Held above 38.2%`; bearish direction should be mirrored, e.g.
    `Held below -38.2%`.

- `trigger-box-spreads.html`: MINOR.
  - Main tables match current log values.
  - `/root/milkman/trigger-box-spreads.html:103` still says bear held-1h
    `+61.8%` rate is `93.6%`; current table/log is `93.8%`.

- `gg-entries.html`: MINOR/new internal inconsistency.
  - Headers, EMA8 bigstat, and 1h EMA21 prose now match current log.
  - `/root/milkman/gg-entries.html:155` says trigger-level pullback
    completion drops to `43-48%`, but the refreshed rows/log show call/put
    trigger pullback completion of `32.4%` and `36.8%`.

## Clean Spot Checks

- `trigger-box.html`: reversal cards, `70-75%` prose, and meta description
  match current log.
- `multiday-gg.html`: `81.5%` bigstat and related table/prose match.
- `swing-gg.html`: `26%/45%` takeaway matches current log.
- `bilbo-golden-gate.html`: speed card counts `299/2,192/242/2,121` match.
- `gap-fills.html`: embedded `DATA` exactly matches
  `/root/spy/gap_fill_cumulative.json`; `33%`, `n=3` callout is correct.
- `bilbo-continuation.html` and `bilbo-10m.html`: caveat banners now clearly
  warn that embedded old 60m values are stale and point readers to
  `bilbo-golden-gate.html`.
