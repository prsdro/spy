# Cheatsheet Audit & Realignment — 2026-04-26

Scope: align /root/milkman/cheatsheet-*.html to the post-2026-04-26 study catalog
(KEEPER / DRAFT / FAILED buckets per `milkman_editorial_audit_2026-04-26.md`).

## Summary verdicts

| Cheatsheet | Underlying study/studies | Status | Verdict | Action |
|---|---|---|---|---|
| `cheatsheet.html` (master) | index/overview | — | EDIT | Resources link list rewritten: dropped Credit Spreads, added Call→Put, Chop Zone, Sustained PO, Gap Fills, Multi-Day & Swing |
| `cheatsheet-basics.html` | Saty vocab + chain + gap-fills + abs hit rates | KEEPER content | KEEP | Spot-checked: 63/65% GG baseline, 14% full-ATR, 80→69→60→55 chain, gap-fill table all match `MASTER_TRADING_KNOWLEDGE.md` and live `gap-fills.html` aggregates. No changes. |
| `cheatsheet-bilbo.html` | bilbo-golden-gate (KEEPER) only | already focused | KEEP | 77.7% / 90.2% / 66% / baselines 63/65 all match `bilbo-golden-gate.html`. No bilbo-10m / bilbo-continuation / bilbo-htf-po / bilbo-box-breakout content present — already clean. |
| `cheatsheet-entries.html` | gg-entries (KEEPER) | KEEPER content | KEEP | Entry table (immediate / EMA8 / EMA21 / 1h-EMA21 / 50% midpoint / trigger-retrace / PDC-retrace) matches `gg-entries.html`. |
| `cheatsheet-pullbacks.html` | gg-invalidation (KEEPER) | KEEPER content | KEEP | 84/89 hold vs 45/51 break, full pullback hierarchy matches `gg-invalidation.html`. No ema21-reversion content present. |
| `cheatsheet-trigger-box.html` | trigger-box (KEEPER, directional) | KEEPER content | KEEP | 22.6% / 26.3% box frequencies, 80%/82% 1h-hold GG-open rates, reversal & patience numbers all match `trigger-box.html`. No spreads content here. |
| `cheatsheet-timing.html` | call-trigger + golden-gate Subway (both KEEPERS) | KEEPER content | KEEP | Hourly bar chart and bull/bear subway tables match `golden-gate.html` Subway section and `call-trigger.html`. No tenam-traffic / 4h-po-opex content. |
| `cheatsheet-multiday-swing.html` | multiday-gg + swing-gg (both KEEPERS) | EDIT | EDIT | Swing-bear stats updated to current `swing-gg.html` (n=233, 36.1% day 1, 77.3% day 20). Cross-timeframe comparison table & bottom-line bullets updated 34% → 36%. |
| `cheatsheet-spreads.html` | trigger-box-spreads (DRAFT) | DRAFT | DELETE (archived) | Renamed to `_archive_cheatsheet-spreads.html`. The 93.6% framing is short-strike no-touch probability, not realized P&L — flagged in editorial audit as mis-labeled. Underlying study sits at `/drafts.html`. |

## New cheatsheets created (4)

Created to fill KEEPER coverage gaps:

1. **`cheatsheet-call-to-put.html`** — Call→Put Morning Reversal. Sourced from `call-to-put-reversal.html`. Headline stats: 73.7% PDC recovery, 75.3% downside GG, 43.3% call recovery, 41.2% close < put trigger (n=653). Includes hourly-PO filter table.
2. **`cheatsheet-chop-zone.html`** — GG Chop Zone after 61.8% completion. Sourced from `gg-chop-zone.html`. Headline: 78% reversal on first-bar fail, 64% continuation after 60+ min hold, 12&ndash;1pm reversal warning (81&ndash;82%), PO-at-completion table.
3. **`cheatsheet-sustained-po.html`** — Sustained Morning PO regime. Sourced from `sustained-po.html`. Headline: 89.1% / 77.7% / 63.9% ATR levels reached; 1/274 days hold PO all day; +0.82% fast-cloud edge from 11am.
4. **`cheatsheet-gap-fills.html`** — Cumulative midpoint fill probabilities. Sourced from `gap-fills.html` (n=6,536). Day-1/day-7 grid by gap size, counter-trend table, compression × trend interaction.

All four use the established design system: dark `#060709` background, `--acc:#fbbf24` yellow accent, `#1cd48a` bull / `#ef6c00` bear, DM Sans + JetBrains Mono, 1200px poster shell, mobile/PNG export buttons matching the rest of the suite.

## Master cheatsheet links updated

`/root/milkman/cheatsheet.html` Resources strip now reads:
01 Basics · 02 Bilbo · 03 Entries · 04 Pullbacks · 05 3m Close · 06 Timing · Trigger Box · **Call→Put Reversal** · **GG Chop Zone** · **Sustained PO** · **Gap Fills** · **Multi-Day & Swing**

Removed: `cheatsheet-spreads.html` link (study is DRAFT, sheet archived).

## Homepage (index.html)

No homepage-link changes required. `index.html` only referenced `cheatsheet.html` and `cheatsheet-multiday-swing.html` from Resources — both still exist and KEEP. No links to draft/failed cheat sheets to remove.

## KEEPER coverage matrix (post-edit)

| KEEPER study | Cheat sheet coverage |
|---|---|
| call-trigger.html | cheatsheet-timing.html (3-min close section) + cheatsheet.html master + direct link |
| bilbo-golden-gate.html | cheatsheet-bilbo.html |
| gg-invalidation.html | cheatsheet-pullbacks.html |
| gg-entries.html | cheatsheet-entries.html |
| trigger-box.html | cheatsheet-trigger-box.html |
| call-to-put-reversal.html | **cheatsheet-call-to-put.html (new)** |
| golden-gate.html (Subway) | cheatsheet-timing.html + cheatsheet-basics.html (chain) |
| gg-chop-zone.html | **cheatsheet-chop-zone.html (new)** |
| sustained-po.html | **cheatsheet-sustained-po.html (new)** |
| gap-fills.html | **cheatsheet-gap-fills.html (new)** + basics page has gap-size table |
| multiday-gg.html | cheatsheet-multiday-swing.html |
| swing-gg.html | cheatsheet-multiday-swing.html |

All 12 KEEPERS now have at least one cheat-sheet touchpoint.

## Files modified

- `/root/milkman/cheatsheet.html` (resources link list)
- `/root/milkman/cheatsheet-multiday-swing.html` (swing-bear stats refresh: n=233, 36.1%, 77.3%; bottom-line + comparison table 34% → 36%)
- `/root/milkman/cheatsheet-spreads.html` → renamed to `_archive_cheatsheet-spreads.html`

## Files created

- `/root/milkman/cheatsheet-call-to-put.html`
- `/root/milkman/cheatsheet-chop-zone.html`
- `/root/milkman/cheatsheet-sustained-po.html`
- `/root/milkman/cheatsheet-gap-fills.html`

## Remaining gaps / risks

- All cheatsheets still carry the "Draft — Not Verified" yellow badge in the header. That language is site-wide convention (`@tesrak`/`@todor` data, not independently verified) and not a draft-study marker — left in place to match aesthetic. If desired, the badge could be revisited globally as part of a separate styling pass.
- The new cheat sheets do **not** link to the master sheet from any prominent nav — they're reachable from `cheatsheet.html` Resources strip and direct URL. If we want them in the global `nav.js`, that's a separate change.
- `cheatsheet-basics.html` includes a 2x rough estimate ("~2/3 of days hit trigger", "~15% full ATR") — these match `MASTER_TRADING_KNOWLEDGE.md` headline numbers (67%/63% bull/bear trigger touch, 14%/16% full ATR). No action needed.
- Sustained-PO cheatsheet acknowledges the n=289 vs current n=274 sample drift on the fast-cloud table (matches study-page disclaimer).

## Verification — HTTP 200 gold set

Run on dev (live nginx serves `/root/milkman/`):

```
200 cheatsheet.html
200 cheatsheet-basics.html
200 cheatsheet-bilbo.html
200 cheatsheet-entries.html
200 cheatsheet-multiday-swing.html
200 cheatsheet-pullbacks.html
200 cheatsheet-timing.html
200 cheatsheet-trigger-box.html
200 cheatsheet-call-to-put.html        (new)
200 cheatsheet-chop-zone.html          (new)
200 cheatsheet-sustained-po.html       (new)
200 cheatsheet-gap-fills.html          (new)
404 cheatsheet-spreads.html            (intentionally archived)
```

All cheat sheets in the active catalog return 200; the archived spreads URL correctly 404s.

---

## Addendum 2026-04-26 evening — cheatsheet-bilbo archived

Following the bilbo-golden-gate demotion (see `milkman_editorial_audit_2026-04-26.md` addendum), `cheatsheet-bilbo.html` has been moved to `_archive_cheatsheet-bilbo.html` and removed from the master cheat sheet's link bar. The cheat sheet is dedicated entirely to the contaminated 1h PO × Golden Gate stats; rather than band-aid the numbers, it's pulled offline until the bug-fixed rerun produces a verified PO grid worth printing again. Master cheat sheet positions renumbered: Basics(01) → Entries(02) → Pullbacks(03) → 3m Close(04) → Timing(05).
