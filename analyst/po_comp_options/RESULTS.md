# Results: Hourly PO Compression → Options (AMZN/NVDA/MSFT, 2025-07-07 → 2026-07-06)

**Bottom line: NO exploitable options edge found.** Buying options out of hourly
phase-oscillator compression on these three mega-caps loses money on average in
every cell of the grid; selling premium also loses; even straddles are
flat-to-negative. Implied vol prices the compression breakout fairly. Every
directional rule tested pointed the WRONG way (short-term slope mean-reverts),
and the mirrored fade signal is not statistically significant.

All stats are event-clustered (legs within an episode aggregated first;
n=178-186 episodes). P&L = fraction of premium. Fills = actual trade prints
(no bid/ask spread modeled → real-world results would be WORSE).

## Q1 — Direction rule: none works; all point the wrong way

Mean P&L per trade with the sc50/80 exit (sell half +50%, rest +80%):

| rule (go WITH sign of) | with rule | against rule |
|---|---|---|
| daily 21EMA slope (3d) | −9.9% (t=−2.25) | +1.9% (t=0.46, ns) |
| daily 21EMA slope (1d) | −10.9% (t=−2.48) | +2.9% (t=0.71, ns) |
| hourly PO slope (3 bars) | −9.3% (t=−2.17) | +1.3% (t=0.29, ns) |
| hourly PO slope (1 bar) | −4.7% (t=−1.13) | −3.3% (ns) |
| expansion direction (confirm entries) | −15.3% (t=−3.13) | +2.6% (t=0.56, ns) |

Following momentum out of compression is reliably bad; fading it is ~breakeven
noise. The daily 21 EMA slope is not better than the hourly PO slope — both are
contrarian indicators here, neither significantly so when inverted.

## Q2 — Entry spot: near-ribbon less bad; confirm ≈ start

- comp_start vs expansion_confirm: statistically indistinguishable (both ~−10% sc50/80).
- Entries with |spot − hourly EMA21| < 0.35 ATR: −4.1% (ns) vs ≥0.35 ATR: −16.9%
  (t=−3.07). "Close to the ribbon" loses meaningfully less, but does not win.

## Q3 — Expiry: 2 weeks least bad; 1 month worst

sc50/80 exit: W1 −13.5%, **W2 −5.4% (t=−1.06, ns)**, M1 −14.7%.
Hold-to-expiry: W1 −27.7%, W2 −33.9%, M1 −49.9%.
Caveat: ~45% of M1 legs had no fill print near entry (thin far-dated weeklies) —
M1 numbers are the liquid subset.

## Q4 — Strike: ATM to +0.5 ATR; 1.0 ATR OTM worst

sc50/80: ATM −8.6%, +0.5 ATR −8.2%, +1.0 ATR −11.4%. Hold amplifies the
gradient (−29% → −36%). No strike distance flips the sign.

## Q5 — Exit: take profits early, but nothing goes positive

Ranked (rule-selected longs): TP100+stop50 −5.1% (ns) best; TP100+ribbon-invalidation
−6.2%; single TP50 −8.5%; sc50/80 −9.8%; TP200 −19.2%; premium −50% stop alone
−21.5% (win rate 10% — stops get run, then the option recovers); hold-to-expiry
−32.5% worst. Underlying-target exits (+0.5/+1 ATR tags): −9 to −11%.
Pattern: the LONGER you hold long premium after compression, the more you bleed.
Pedro's TP1 50% / TP2 80% scale-out: −9.8% per trade (t=−2.14).

## Credit side (selling the opposite-side option)

Also negative, though closer to zero and never significant: hold −14.2% of
premium received (t=−1.07, win 66%), decay-TPs −12/−13%, stop-at-2x −3.8% (ns).
Classic short-premium skew: frequent small wins, occasional large losses.

## Straddles (long ATM call+put — tested because both sides losing suggests it)

Flat-to-negative in all 6 entry×expiry cells; best cells are noise (M1 sc100/200
+0.9%, ns). W2 hold −15.9% (t=−2.91). The compression "big move coming" intuition
is real but ALREADY PRICED into IV on these names.

## Per-ticker consistency (W2 ATM long, sc50/80)

AMZN −20.6%, NVDA +0.7%, MSFT +10.5% (t=1.15, ns). No consistent cell across
tickers → the one mildly positive cell (MSFT) is indistinguishable from mining.

## Caveats

- Trade-print fills, no spread/commissions → all results are OPTIMISTIC bounds.
- One 12-month window (mostly 2025-26 regime), 3 correlated mega-caps.
- Mined grid (~10.7k legs, 16 exits) — treat any isolated positive cell as noise.
- 604 censored legs (late events, M1 expiries past 2026-07-06) marked and
  excluded from hold-exit comparisons.

## Bilbo Box variant (added 2026-07-07 evening CT)

Box = high/low of the FIRST 5 hourly bars of each compression episode.
Funnel: 186 episodes → 89 boxes (≥5-bar episodes) → 87 broke out ≤10 days →
83 retested the broken edge ≤7 days (95% retest rate — retests are near-universal).
Same leg grid (W1/W2/M1 × 0/0.5/1 ATR × long/short premium), box-specific exits
added (box_stop = hourly close through midpoint against trade, box-height
measured-move target). Built by `backtest_po_comp_bilbo.py` →
`bilbo_trades.parquet` (3,737 legs), `bilbo_summary.json`.

- **Retest beats immediate** for option entries — REVERSED from the SPX
  equity-level Bilbo study. Retest longs: TP100+stop50 +10.4% (t=1.50, ns),
  TP50 +7.1%, sc50/80 +7.9% — positive across most exits but nothing
  significant. Immediate: best cell +4.1% (ns), hold −15%. Buying the pullback
  pays because premium is cheaper and the strike closer — but it's still noise
  at n=81.
- **Up-breaks are the poison** (immediate entries, TP100+boxstop):
  down-breaks +13.5% (t=1.27, ns) vs up-breaks **−25.3% (t=−3.19, significant)**.
  Buying calls on upside compression breakouts reliably lost all year.
- **Thirds variant**: third_long ≈ flat-negative (ns). third_short (fading the
  top third) was the worst thing tested: hold −38.2% (t=−3.10),
  TP100+stop50 −22.5% (t=−3.23). Do not short strength inside these boxes.
- **Credit side**: all four variants mildly positive means with high win rates
  (decay50 win 83-91%) but t ≤ 1.04 — statistically nothing.
- Per-ticker (immediate long): AMZN −8%, MSFT +4%, NVDA −14% — no consistency.

Net: the box framework doesn't rescue long premium either. The only significant
results are NEGATIVE cells (up-break calls, top-third puts). The retest-entry
improvement and short-premium positives are suggestive but underpowered at
~85 boxes/12 months — a longer window or more tickers would be needed to
confirm.

### Variable-length boxes (box = first min(5, episode_len) bars; rerun same day)

Boxes 89 → 184 (median added box is 1-4 bars: expansion arrived early).
The added short boxes are UNIFORMLY BAD and dilute the retest edge to zero:

| retest longs | 1-4 bar boxes (n=87) | 5-bar boxes (n=81) |
|---|---|---|
| TP100+stop50 | −9.1% (t=−1.50) | **+10.4% (t=1.50)** |
| sc50/80 | −17.8% (t=−2.53) | +7.9% (t=1.08) |

Box maturity (a full 5 hours of compression) looks like a genuine precondition —
**REVERSED from the equity-level Bilbo study** where 1-4 bar boxes carried the
edge. Tiny boxes = tiny levels; their "breakouts" and "retests" are noise, and
the premium spent swamps the move.
Sharpest (and most mined — 3-way slice, treat as hypothesis only) cell:
5-bar box + retest + DOWN-break puts: +21.4% (t=2.09, n=41).
Robust negative unchanged: immediate up-break calls −17.2% (t=−3.04) across all
box sizes. third_long improves to +9.5% (t=1.39, ns) with short boxes included;
shorts (credit) all ≈ 0. Note: for <5-bar boxes the freeze is only confirmed at
the next bar close; since price leaving the box is what creates expansion,
entries approximate live behavior but carry that half-bar ambiguity.

## Random-entry control (added 2026-07-07 late; REFRAMES the study)

186 random hourly bars, matched per-ticker counts, same contracts/engine
(`scratch_po_comp_random_baseline.py` → `random_baseline_trades.parquet`):

- Random long ATM W1/W2 premium: **−15.5% (t=−3.25)** → the baseline for this
  regime is strongly negative; zero was the wrong null for every table above.
- Compression longs (−10.3%) BEAT random longs by ~5pp (two-sample t≈0.7, ns).
- Mirror: **short ATM premium at RANDOM times = +15.5%/trade (t=3.25)** — a fat
  variance-risk premium, the strongest t in the study, unreported until the
  control ran because shorts were only tested AT compression (+10.3%, weaker).
  Compression is the WORST time to sell premium → the signal does anticipate
  movement; it just can't beat theta from the long side at these strikes/DTEs.

Reframed live leads (edge vs baseline, not vs zero):
1. Short-premium carry away from compression (needs spread/tail haircuts).
2. Mature-box retest longs: +10.4% vs ~−10% baseline → ~+20pp relative.
3. 5-bar box + retest + down-break puts +21.4% (mined, needs v2 data).

## v2 expansion pull (launched 2026-07-07 ~18:52 CT)

8 tickers (AMZN NVDA MSFT AAPL META GOOGL TSLA AMD) × 24 months
(2024-07-14 →), W1/W2 only (M1 dropped: noise + 45% missing fills). Env-driven
rerun of fetch script (PO_* vars), shared DB/chains dedupe. Files:
events_v2.csv, contracts_todo_v2.json. Goal: power up leads 2 & 3 and test
the carry regime-switch idea (sell premium except when compression is on).

## v3 results (2026-07-07 late night CT; 8 tickers × 24mo, RTH + ETH, entry-anchored expiries)

Tables: v3_rth_trades.parquet (32.5k legs, 956 boxes), v3_eth_trades.parquet
(74k legs, 2,449 boxes, 1,359 overnight breaks). Event-clustered, contract-deduped.

1. **v2 retest lead faded at scale**: RTH mature-box retest tp100_stop50
   +3.6% (t=1.11); OOS +3.3%; down-break W1 cell +6.2% (t=1.24), OOS +2.3%.
   ETH retest ≈ 0. Box-maturity split FLIPPED between sessions (RTH favors
   5-bar, ETH favors 1-4) → that split was noise. v2's +10-21% was mostly mining.
2. **NEW STRONGEST FINDING — intraday breaks of ETH-defined boxes, immediate
   entry, long premium, TP+100%/stop−50%: +8.3%/trade (t=3.78, n=972 boxes).**
   Robust: up +7.2% (t=2.4) / down +9.5% (t=3.0); both box sizes; with/against
   PO slope; 7 of 8 tickers positive (AAPL −8.5% the exception; NVDA +14.6%
   t=2.4, TSLA +18.3% t=2.9). Overnight/gap breaks ≈ 0 (that's the chaff the
   ETH definition separates out — an ETH box level survived the overnight
   session, so an intraday break of it is a stronger signal; RTH immediate
   comparison +3.5% t=1.58). Exit shape matters: sc50/80 kills it (−1%);
   hold +7.9% ns; tp100_stop50 is the shape. Session A/B verdict: **ETH wins**
   (also matches Pedro's charting).
3. **PO direction/position/slope conditioning: NOT predictive** on top of box
   mechanics. Alignment with PO slope: no help (against-slope mildly better,
   ns). Slope terciles: falling +4.2% (t=1.92) vs rising +0.9% — mild
   counter-trend tilt only. Zone bins: neutral bands fine, extremes thin.
   The PO's tradeable content here is the compression FLAG, not its shape.
4. **Confirmed stay-out**: third_short (fading top-third strength inside the
   box) −6.2% (t=−3.87, n=1,421) — robust "don't" across the full sample.
   third_long +2.1% ns.
5. comp_start shorts hold +1.5% ns at scale (v1's +10.3% was small-sample);
   proper carry-timer test vs non-compression baseline still pending.

One-line caveat: no spread/commissions modeled; the +8.3% headline survives a
~2-4pp round-trip haircut on liquid ATM weeklies but thin names/strikes won't.

### TP×SL sensitivity (headline cell, per ticker; scratch_po_comp_tp_sl_grid.py)

Pooled grid (avg %/trade): SL sweet band = **−40 to −50%** at every TP level
(no-stop costs ~7-8pp; SL75 costs ~4pp; SL25 slightly worse than 40).
TP is a **plateau from +75% to +300%** (7.8-10.1% at SL40-50); pooled argmax
TP300|SL50 = +10.1% but t drops to 2.79 (vs 3.78 at TP100|SL50 = +8.3%) —
wider TP = fatter mean, fatter variance. TP150|SL40 = +9.2% is the balanced
point. Per-ticker argmaxes scatter across the plateau (GOOGL 75, MSFT/NVDA 100,
TSLA 200, AMD/META/AMZN 200-300) = jitter at n≈110-140/ticker; do NOT
per-ticker tune. AAPL's "best" (+11.6% at TP300/no-stop) is a lottery-ticket
artifact on a negative-baseline name — still excluded. Grid legs saved:
tp_sl_grid_legs.parquet.

### Trailing-stop variants (scratch_po_comp_trailing.py, trailing_variants_legs.parquet)

**Winner: arm-then-trail — fixed −50% stop until premium +100%, then trail 30%
below the option's high-water mark, no cap: +14.7%/trade, t=4.84** (vs +8.3,
t=3.78 fixed bracket) — beats baseline on BOTH mean and confidence. Trail-40
after arm: +14.5 (t=4.25). Pure trail-from-entry 40%: +12.0 (t=4.33);
trail30-from-entry has the tightest distribution (t=5.07) at +9.1. Ratchet
ladder +11.8 (t=3.50). Pedro's 2/3-base + 1/3-runner combos UNDERPERFORM:
base@75 +8.0%, base@50 +4.9% (win rates rise to 44-51% but expectancy falls) —
same lesson as scale-outs: banking early trims the tail that pays for the 62%
losers. Everything coherent with one principle: protect downside, never cap
upside. Caveat: trailing exits assume fill at the trail level (no gap-through);
second optimization pass on same data — validate arm-then-trail out-of-sample
before promoting over the simple bracket.

## Files

`trades.parquet` (10,680 legs × all exit P&Ls), `straddles.parquet`,
`summary.json`, built by `backtest_po_comp_options.py` + `analyze_po_comp_options.py`.
