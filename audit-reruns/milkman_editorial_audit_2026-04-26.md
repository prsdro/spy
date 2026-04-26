# Milkman Trades — Editorial Audit
**Date:** 2026-04-26
**Scope:** 23 published study pages on milkmantrades.com (cheatsheets, analyst, data vault excluded)
**Lens:** Quality (statistical rigor, sample size, edge magnitude, caveats acknowledged) and Actionability (entry/exit clarity, real-time identifiability, frequency, fit for 0DTE/short-dated SPX/SPY)
**Stat sources used:** `/root/spy/MASTER_TRADING_KNOWLEDGE.md`, `/root/spy/analyst/studies_reference.md`, `/root/spy/audit-reruns/milkman_audit_2026-04-22.md`, `/root/spy/audit-reruns/change_magnitude_report_2026-04-23.md`. Stats not re-run.

---

## 1. Ranked scoring table

Scores 1–10 (10 = best). Combined = Q + A. Sorted by Combined.

| # | Study | Q | A | Σ | Recommendation |
|---|---|---:|---:|---:|---|
| 1 | call-trigger (3-Minute Close) | 9 | 10 | 19 | **KEEP** — flagship |
| 2 | bilbo-golden-gate | 9 | 9 | 18 | **KEEP** — flagship |
| 3 | gg-invalidation | 9 | 9 | 18 | **KEEP** — core risk rule |
| 4 | multiday-gg | 9 | 8 | 17 | **KEEP** |
| 5 | gg-entries | 8 | 8 | 16 | **KEEP** |
| 6 | trigger-box (directional) | 7 | 8 | 15 | **KEEP** |
| 7 | call-to-put-reversal | 7 | 8 | 15 | **KEEP** |
| 8 | golden-gate (Subway / level-to-level) | 8 | 7 | 15 | **KEEP** — foundational |
| 9 | gg-chop-zone | 7 | 7 | 14 | **KEEP** |
| 10 | sustained-po | 7 | 7 | 14 | **KEEP** |
| 11 | gap-fills (cumulative midpoint) | 8 | 6 | 14 | **KEEP** |
| 12 | bilbo-htf-po (bracket exits) | 7 | 6 | 13 | **KEEP** |
| 13 | swing-gg | 7 | 6 | 13 | **KEEP** (not 0DTE) |
| 14 | trigger-box-spreads | 6 | 7 | 13 | **REVISE** |
| 15 | multiday-put-trigger-reversion | 6 | 6 | 12 | **REVISE** |
| 16 | premarket-ath | 6 | 5 | 11 | **REVISE** |
| 17 | bilbo-box-breakout (raw) | 7 | 4 | 11 | **REVISE** |
| 18 | ema21-reversion | 5 | 6 | 11 | **REVISE** |
| 19 | 4h-po-opex | 4 | 5 | 9 | **REVISE** (toward KILL) |
| 20 | 4h-po-reversal | 4 | 5 | 9 | **REVISE** |
| 21 | bilbo-continuation | 4 | 5 | 9 | **REVISE** |
| 22 | bilbo-10m (10m vs 60m PO) | 4 | 4 | 8 | **KILL** (or fold into bilbo-golden-gate) |
| 23 | tenam-traffic | 5 | 3 | 8 | **KILL** |

---

## 2. Per-study one-line reasoning

1. **call-trigger** — 97% clean-run hit on 38.2% target, n=2,027, median 18m; trivial to identify in real time. Best 0DTE play in the catalog.
2. **bilbo-golden-gate** — Bear Low+Falling 90.3% GG completion (n=268); Bull High+Rising 77.1% (n=388). Largest validated directional edge in the system; 1h PO bar must be **completed**.
3. **gg-invalidation** — 10m close back through trigger = −39pp completion delta. Single most important risk rule; survives rerun.
4. **multiday-gg** — Bear Bilbo day-1 GG 96.3% / Full ATR day-1 81.5%; weekly setup, swing-friendly, identifiable Monday/Tuesday.
5. **gg-entries** — Immediate-at-38.2 ranks top EV (+9.4% ATR); 1h EMA21 pullback = best R:R (2.3–3.2x). Clear ranked menu of entries.
6. **trigger-box** — 1hr hold → 71.6%/75.3% GG opens. Edge softer post-rerun but still actionable; mislabel (38.2 vs 23.6) was fixed.
7. **call-to-put-reversal** — n=653, 73.7% PDC recovery / 75.3% put-trigger GG open; clear morning-fade trigger.
8. **golden-gate** — The level-to-level table (80% / 69% / 60% / 55%) is the spine of every other GG study; foundational reference, large n.
9. **gg-chop-zone** — Useful PO-state filter to avoid low-quality GG entries; numbers stable across rerun.
10. **sustained-po** — n=274, 83.6% close-green when PO sustained pre-11:00; clean morning regime tag.
11. **gap-fills** — n=6,536; 99/96/84/65 fill rates by gap size; high-volume, identifiable at the bell.
12. **bilbo-htf-po** — Target-before-stop bracket framework gives realistic exits where raw box-breakout cannot; treat as the "executable" sibling of bilbo-box-breakout.
13. **swing-gg** — Monthly ATR, day-20 bear 77.3%; legitimate swing edge but not a 0DTE play — keep for the Multi-Day cheatsheet audience.
14. **trigger-box-spreads** — REVISE: 93.6% short-strike no-touch is **not** a realized spread P&L (no fills, debits, gamma, settlement). Reframe as "no-touch probability," not "win rate."
15. **multiday-put-trigger-reversion** — REVISE: new, narrower companion to call-to-put-reversal; needs clearer sample-size/baseline comparison and explicit weekly-trigger definition.
16. **premarket-ath** — REVISE: post-rerun n=243, frequency only 3.7%. Real edge per event but too rare to anchor; consolidate into a "morning fade" cluster.
17. **bilbo-box-breakout** — REVISE: raw 51% / +0.03R is a near-zero edge across 50,889 events. Either kill or repackage as the *negative finding* that sets up bilbo-htf-po.
18. **ema21-reversion** — REVISE: 50 episodes is underpowered; useful as context, not a standalone tradable. Add explicit "next-session executable" framing.
19. **4h-po-opex** — REVISE/near-KILL: extended-filter n=13, baseline n=81; tiny sample, OpEx-conditional, hard to deploy live. Either deepen sample or retire.
20. **4h-po-reversal** — REVISE: still under re-verification banner; HTML event log/velocity buckets came from a script no longer in the repo. Rebuild before promoting.
21. **bilbo-continuation** — REVISE: 78.6→200% extension reach rates not reproducible from current `backtest_gg_with_po.py`. Either rebuild or fold the surviving 60m PO buckets into bilbo-golden-gate.
22. **bilbo-10m (10m vs 60m PO)** — KILL or absorb: 10m column is not reproducible; conclusion ("60m more predictive") is already covered in bilbo-golden-gate. Standalone page is redundant.
23. **tenam-traffic** — KILL: n=36,829 PO divergences with **regular signals underperforming baseline** and hidden divergences carrying only a marginal, time-window-conditional edge. Honest negative finding, but not a tradable playbook page.

---

## 3. Executive summary

### Core actionable playbook (the 7 keepers Mr. Pedro should foreground)

These cover entry, continuation, risk-off, and regime in roughly the order a 0DTE/short-dated trader actually uses them in a session:

1. **call-trigger (3-Minute Close)** — primary 0DTE entry signal; cleanest hit-rate and median-time stats in the catalog.
2. **bilbo-golden-gate** — the 1h-PO conditioned GG, especially the bear Low+Falling cohort. The single largest validated directional edge.
3. **gg-invalidation** — the −39pp "10m close back through trigger" rule. Without this rule, the GG edge is half what it looks like.
4. **gg-entries** — the ranked menu (immediate / EMA8 / EMA21 / 1h EMA21) so users pick by EV vs. R:R rather than feel.
5. **trigger-box (directional)** — 1-hour hold → GG opens at 71–75%; the "did the morning commit?" filter.
6. **call-to-put-reversal** — the only well-powered morning-reversal study (n=653, 73.7% PDC recovery); pairs naturally with #1 as its inverse.
7. **multiday-gg** — bear Bilbo 96.3% day-1 GG / 81.5% day-1 Full ATR; the swing/1DTE bridge from intraday into weekly ATR.

`golden-gate` (level-to-level) sits underneath all seven as the foundational reference and stays in the catalog as canon.

### Kill list (low edge, low frequency, redundant, or stat-questionable)

- **tenam-traffic** — negative-finding study; honest but not playbook material.
- **bilbo-10m** — under re-verification; conclusion already lives in bilbo-golden-gate. Redundant page.
- **4h-po-opex** — n=13 in the headline cohort. Either deepen sample or retire; current page is over-claiming.

### Revise list (real signal, weak frame)

- **trigger-box-spreads** — relabel "win rate" → "short-strike no-touch probability"; add caveat that real spreads carry credit, gamma, and settlement risk not modeled.
- **bilbo-box-breakout** — raw 51% / +0.03R is essentially no edge; either retire or reposition as the setup that motivates bilbo-htf-po.
- **bilbo-continuation** and **4h-po-reversal** — drop "Under Re-Verification" banners by rebuilding from current code, or merge surviving sections into adjacent pages.
- **ema21-reversion** — explicitly frame as "close-confirmed / next-session executable"; n=50 episodes is too thin to stand alone.
- **premarket-ath** — frequency 3.7% is too low for a standalone page; consolidate with call-to-put-reversal under a "morning fade" cluster.
- **multiday-put-trigger-reversion** — add baseline comparison and a crisp weekly-trigger definition; otherwise it reads like a thinner cousin of call-to-put-reversal.
- **swing-gg** — keep but clearly mark non-0DTE; tighten the day-1 horizon definition.

### Bottom line

The catalog is healthy at the top. The seven core keepers form a coherent intraday system: identify regime (sustained-po, gg-chop-zone, gap-fills), pick the entry (call-trigger, bilbo-golden-gate, gg-entries), manage risk (gg-invalidation), and extend horizon when needed (multiday-gg, swing-gg). The middle tier is fine as supporting material. The bottom tier is mostly **publication overhead** — under-powered, under-frequency, or stat-questionable pages that dilute the brand without adding tradable edge. Trim three (kill list), rebuild three (4h-po-reversal, bilbo-continuation, bilbo-10m or absorb), and relabel two (trigger-box-spreads, bilbo-box-breakout). After that pass, the published catalog goes from "34 pages of mixed quality" to "≈18 pages, every one of which has a clear edge, a clear entry, and a clear risk rule."

---

## Addendum 2026-04-26 evening — bilbo-golden-gate demoted to DRAFT

After the original audit went out, both Codex 5.5 and Opus 4.7 independently re-reviewed `backtest_gg_with_po.py` and confirmed two material findings (full diagnoses in `audit-reruns/codex_gg_bug_review_2026-04-26.md` and `audit-reruns/opus_gg_bug_review_2026-04-26.md`):

1. **Look-ahead bias in the PO join.** `merge_asof(direction="backward")` against left-labeled 1h bars produced by `aggregate.py:57-66` lets the 10-minute trigger (e.g. 09:40) read the not-yet-closed 09:00–09:59 hour bar. Up to **60 minutes of forward leakage** depending on where in the hour the trigger fires. The reference pattern in `backtest_bilbo_box_htf_po_exits.py:126-145` already shifts HTF timestamps forward by one bar duration before the join — `backtest_gg_with_po.py` does not.
2. **Inflated Subway "trigger → 38.2 = 80%" headline.** That figure conflates Cat A (opens beyond trigger), Cat B (gap-opens inside and crosses), and the actually tradable residual. Codex's reproduction of the residual cohort (open inside, cross intraday) is **52.0% bull (1224/2355)** and **56.6% bear (1325/2339)** — a different number than the published headline. The Subway page is salvageable with proper framing; the GG-with-PO study is not, in its current form.

**Codex's quantified impact when the join is made point-in-time safe:**
- Bear PO Low+Falling: **89.6% → 85.1%**
- Bull PO High+Rising: 75.9% → 71.0%
- Bull PO Mid+Falling: 50.9% → 63.0% (worst bucket partly inverts)
- Bear PO Mid+Rising: 54.5% → 69.6%

**Action taken on the site (this addendum):**
- `bilbo-golden-gate` removed from the Day Trading core (homepage now shows 5 core + 4 supporting cards instead of 6 + 4).
- New 9th draft entry on `/drafts.html#bilbo-golden-gate` documenting the bug + corrected stats.
- Amber draft banner added to `bilbo-golden-gate.html` linking back to the drafts entry.
- Honest-residual callout (52% bull / 56% bear) added to `golden-gate.html` above the Subway tables.
- `cheatsheet-bilbo.html` archived to `_archive_cheatsheet-bilbo.html`; link removed from the master cheat sheet.

The original review's "core 7-study playbook" framing is now a **6-study core** (call-trigger, gg-invalidation, gg-entries, trigger-box, call-to-put-reversal on the day side, plus multiday-gg on the swing side). Bilbo Golden Gate stays demoted until a rebuilt version with bar-end PO joins lands and the residual stats hold up under the corrected math.
