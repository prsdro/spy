# Bias Review: Bilbo Box Breakout → Options (arm-then-trail headlines)

2026-07-08, joint audit: Claude (this doc, `scratch_bias_1..6_*.py` in this
dir) + Codex CLI (two adversarial passes, full text in `CODEX_REVIEW_2.md`;
round 1 was independent and later cross-checked against the scripts here).
Note: single-leg V0 means below read +13.1% instead of the published +13.5%
only because the resim population is 2,360 boxes vs the straddle file's 2,345;
on the matched 2,345 the reproduction is exact.

**Scope**: the published headline — single-leg break-direction W1 ATM
arm-then-trail **+13.5%/trade (t=5.85)** and straddle arm-then-trail
**+12.0% (t=8.42)** on 2,345 intraday boxes / 20 tickers / 24 months
(`straddle_armtrail.parquet`) — plus the fixed-bracket +2.8% pooled cell.
The re-simulation (`scratch_bias_resim_legs.parquet`, 2,360 boxes: the 15
extras are boxes whose put leg never filled, absent from the straddle file)
reproduces both published columns print-for-print (corr 1.0000, max abs diff
0.0000) before any variant is applied, so every delta below is attributable to
the mechanic being changed, not to population drift.

## Bias table

Population for all quantifications: the 2,360-box headline set (immediate
entry, W1, ATM, intraday, uncensored), single-leg long unless stated.
"pp" = percentage points of premium per trade.

| # | Bias | Mechanism | Direction | Quantified impact |
|---|---|---|---|---|
| 1 | **Exit fills at the level, not at a print** | Trail/stop exit assumed AT `level` on the first minute bar whose low ≤ level. With trade-print-only data (~49% of minute bars on these contracts are single prints; 39.7% DB-wide) the "bar" that triggers is often itself the first print far below the level. | Inflates | Largest single item. Exit at min(level, trigger-bar close) instead: single **+13.1% → +6.3%** (t 5.7→2.8), straddle **+12.0% → +5.5%** (t 8.4→3.9), n=2,360/2,345. Worst bound (fill at trigger-bar low) only ~1pp lower again → the estimate is tight. |
| 2 | **Initial −50% stop gap-through** | Stop assumed filled at exactly −50%. 64% of single legs exit via this stop. | Inflates | Realistic stop fills average **−55.3%** of premium (slip p50 1.1pp, p90 18.5pp, p99 46.6pp of premium). Included in #1's total. Trail-phase exits slip more (p50 4.7pp, p90 27.2pp): the trail binds after fast moves, exactly when the tape gaps. |
| 3 | **No bid/ask spread** | Trade prints bounce bid↔ask; live entry ≈ ask, exit ≈ bid; straddle pays twice. | Inflates | Measured *effective* half-spread (multi-print bar ranges, Roll fallback): median **0.7%/side of premium** (p90 2.0%; median $0.025 on $3.75 premium). Applied round-trip: single −2.0pp, straddle −1.9pp. Sensitivity: at a quoted-spread-like 2%/side the straddle falls to +2.8% (t=1.8); **breakeven ≈ 3.4%/side**. Sign of the net edge depends on an unobservable (no quotes in the data). |
| 4 | **Stale entry prints (fill_lag)** | `entry_fill` takes the last print ≤ signal (20-min window, 60-min fallback): 33% of headline entries priced off a pre-signal print; 4.6% >5 min stale (max 50 min). | **Neutral to deflating** on average | Re-priced at the first print strictly AFTER the signal: single +13.1% → **+13.4%** — the headline does not live on stale fills (median lag = 0 min; the >5-min-stale trades average −5.7%, i.e. staleness correlates with dead contracts, not with lookahead profit). Verified suspicion, acquitted. |
| 5 | **Box-freeze ambiguity (half-bar lookahead / poke survivorship)** | For <5-bar boxes the box is only knowable at the CLOSE of the first non-compression hourly bar, but entries are admitted from one bar earlier. Mid-hour pokes that got re-absorbed (compression continued, box grew) are silently excluded from the entry sample; live you'd have bought them. | **Inflates — the decisive item** | 842/2,360 headline entries (36%) occur inside the confirmation hour of a <5-bar box. Under realistic fills (#1+#3+#4) they carry **+16.5%** single (t=3.8) while the fully live-knowable 1,518 carry **+0.8%** (t=0.3); straddle +8.8% vs +2.8% (t=1.4). Of the published +13.1% single mean, 7.8pp comes from the ambiguous 36%. Strict-live entry reruns (flip8, orig8 cohort) with realistic fills: pure-price pokes −4.2% single / +1.0% straddle (ns); intrabar-flag entries −1.1% / +1.1% (ns) — the ambiguous subset's profit is not recoverable by computing the flag live intrabar. |
| 6 | **Clustering (20 correlated names, shared days)** | Box-level t treats same-day breaks across tickers as independent; the headline sample spans only 470 distinct entry dates. | Inflates significance | Published straddle t 8.42 → **5.61** date-clustered; single 5.85 → 4.31 (published fills). Under realistic fills the date-clustered t's are 1.0–2.3 across variants. |
| 7 | **Exit rule mined on the same data** | Arm-then-trail was a second optimization pass; the new12 "OOS" test reused the in-sample-chosen exit (and W1/−35% vs W2/−25% shopping continued after). | Inflates expected live performance | Not separable from #1–#5 with this data; directionally confirmed by cohort decay under realistic fills (orig8 +5.7% vs new12 +4.2% straddle). Treat any surviving mean as an upper bound. |
| 8 | **Same-bar TP/SL tie-break** (fixed bracket) | `bilbo.leg()` resolves a same-timestamp TP+stop to TP (optimistic); `options.py long_exit` resolves to stop. | Latent only | **0 occurrences** in 2,359 headline fixed-bracket legs. No impact on published numbers; worth fixing for hygiene. |
| 9 | **Fixed bracket fill optimism** | Same level-fill assumptions applied to TP100/SL50. | Inflates | Pooled fixed bracket **+2.8% (t=1.9) → −0.6% (t=−0.4)** with stop fills at min(level, close); new12 −4.1% (t=−2.1). The "conservative baseline bracket" was also flattered. |
| 10 | **No-fill / penny-premium attrition** | Legs dropped when no print near entry or entry ≤ $0.01 (22,463 leg-drops logged in the new12 run); requiring a print ≤5 min after signal keeps boxes that average +14.9% (V0) vs −2.0% for the dropped 243. | Mixed — live-replicable | This selection is implementable (you observe at entry time whether the contract is trading), so it is a liquidity filter, not lookahead — but published pooled numbers inherit it silently. |
| 11 | **Strike snapping** | "ATM" = nearest pulled strike to entry spot. | Negligible | Median snap 0.28% of spot, p90 0.65%, p99 2.0%; 24/5,422 legs >2%. |
| 12 | **Censoring / overnight exclusion** | 19 intraday boxes censored at data end (excluded); 3,043/5,422 (56%) of immediate W1 legs are overnight breaks, excluded by strategy definition. | Neutral if labeled | Excluded overnight set: fixed bracket −1.3% (t=−1.0) — the exclusion is a real conditioning, not result-shopping. Keep "intraday breaks of ETH boxes" in the strategy label. |
| 13 | **Settlement marks for held legs** | Hold exits (4.9% single / 5.8% short legs) marked at intrinsic from the RTH daily close, not an executable option bid near Friday close. | Mildly inflates | Not separately quantified (small population share); covered qualitatively by the spread haircut. |

## What survives: realistic-mechanics ladder

Single-leg / straddle W1 ATM arm-trail, mean per trade (n, plain t, date-clustered t):

| mechanics | single leg | straddle |
|---|---|---|
| Published (level fills, stale entries OK) | +13.1% (2,360, t 5.7, tc 4.1) | +12.0% (2,345, t 8.4, tc 5.6) |
| + exits at next print (min(level, close)) | +6.3% (t 2.8, tc 1.8) | +5.5% (t 3.9, tc 2.1) |
| + strict-after entry, ≤5 min wait | +8.3% (2,117, t 3.4, tc 2.3) | +6.8% (1,892, t 4.3, tc 2.1) |
| + measured effective spread (0.7%/side median) | **+6.4% (t 2.6, tc 1.6)** | **+4.9% (t 3.1, tc 1.2)** |
| … same, only live-knowable entries (bias #5 out) | **+0.8% (1,368, t 0.3, tc −0.3)** | **+2.8% (1,226, t 1.4, tc 0.6)** |

Strict-live entry reruns (flip8, orig8 cohort, realistic fills + spread):
pure-price first poke **−4.2% single / +1.0% straddle** (n=1,109/1,055, ns);
close-confirmed hourly entry +4.1% / +2.1% (ns); wait-for-locked-5-bar-box
then first poke +4.8% (t 0.9) / **+5.8% (t 1.7, tc 1.2, n=397)** — the best
surviving live-knowable cell, and it is not significant.

Recovery variants tested and their best results (all realistic fills + spread):

- **Liquidity gate** (≥100 prints/day both legs): straddle +6.2% (1,333, t 3.4,
  tc 1.3); close-confirmed-trail flavor +7.0% (1,284, t 3.6, tc 1.7). Plain t
  clears 3, date-clustered does not; and the gate does not remove bias #5 —
  restricted to live-knowable entries these cells fall with everything else.
- **Close-confirmed trail** (hwm and trigger on closes): straddle +5.2%
  (1,892, t 3.3, tc 1.25) — marginally better than the low-triggered trail,
  same clustering problem.
- **Cohort check**: realistic straddle orig8 +5.7% (t 2.6) vs new12 +4.2%
  (t 1.9) — mild in→out decay on top of everything above.

## Honest bottom line

- The published +13.5%/+12.0% depend on two non-executable ingredients that
  largely partition the sample: under ideal level fills the live-knowable
  subset still shows +11.2% straddle (t 6.2) — i.e. the *tradeable* V0 number
  leans on non-executable exits — while under realistic fills the residual
  mean concentrates in the 36% of entries that condition on the
  box-confirmation bar (bias 5). Applied together, the live-knowable,
  realistically-filled version of the published headline is **+0.8% single
  (t 0.3) / +2.8% straddle (t 1.4)** on 1,368/1,226 boxes over 470 trade
  dates.
- Spread language (per Codex): the haircut used here is a trade-print
  effective-spread *proxy* (median 0.7%/side), not a quoted spread. At
  plausible quoted half-spreads of 1–2%/side the realistic straddle
  expectancy ranges from marginally positive to indistinguishable from zero;
  at ~3.4%/side it is gone.
- The 20-year underlying result (large symmetric post-box excursions) is
  untouched by this review — the convexity *hypothesis* stands; what fails is
  the claim that W1 ATM premium managed off the option's own print tape
  monetizes it at +12-13% per trade.
- One recovery candidate survived (next section): locked-box straddle with
  exits keyed to the UNDERLYING and executed at actual option prints —
  **+7.7% of combined premium (n=397 boxes, t 3.0, date-clustered t 2.6,
  win 48%)**, orig8 cohort only, pending out-of-sample validation.

## Recommendations

1. Do not publish or trade the +13.5%/+12.0% numbers. If the study page goes
   up, headline the realistic band (straddle +2 to +6% per box depending on
   spread regime, date-clustered t ≤ 1.7) with n and the fill caveats.
2. Any future options backtest on this print-only dataset should adopt, as
   defaults: entries at first print strictly after signal (≤5 min or skip),
   exits at min(level, trigger-bar close), a measured effective-spread
   haircut, and date-clustered t alongside plain t. (The resim harness in
   `scratch_bias_1_resim.py` implements all four.)
3. Entry-signal code must not reference the hourly bar that ends compression:
   either require the locked 5-bar box (flip8 F) or a close-confirmed break
   (flip8 D). The flip8 pipeline already builds both populations.
4. Next steps for the surviving candidate, in order: (a) rerun the flip
   pipeline (WAIT_FULL_BOX) on the new12 events and apply
   `scratch_bias_6_undexit.py` to it — true out-of-sample for both entry and
   this exit; (b) quote-based data (e.g. ThetaData) to replace the
   effective-spread proxy with NBBO and extend pre-2024.

## Codex round-2 addendum + final recovery experiment

Codex reviewed the quantifications above and concurred ("the current headline
should be retired, not caveated"), with these refinements adopted here:
treat entries timestamped exactly at the confirm close as ambiguous; call the
spread number a proxy, not "the" effective spread; the flip8-A falsification
is orig8-only evidence, strong but not final for new12; and the min(level,
close) exit proxy "is not too harsh — if anything still generous" (on a
single-print minute the only observed trade is already at or through the
stop). Process note: Codex re-ran `scratch_bias_4_freeze.py` during its pass,
which regenerated `scratch_bias_freeze_class.parquet` with identical content
(derived file; no source data touched).

Codex's pre-registered recovery pick (pass bar set before running: straddle
mean > +4% AND date-clustered t > 1.5): **locked 5-bar box straddle with
underlying-based exits** — entries from `flip8_fullbox_trades.parquet` (the
cleanest live-knowable population), first option print strictly after signal
(≤5 min), each leg managed off underlying 5m closes (arm at 0.75×box-height
favorable excursion, exit at 50% retracement of best excursion; pre-arm
invalidation at a close through the opposite box edge), option sold at the
first ACTUAL print within 15 min of the trigger, effective-spread haircut
applied (`scratch_bias_6_undexit.py`).

Result: **straddle +7.69% of combined premium (n=397 boxes, t 3.03,
date-clustered t 2.60 over 256 dates, win 48%)**; break-direction single leg
+13.24% (t 2.94, tclust 2.29). Parameter neighborhood (arm 0.5–1.0 ×
box-height, retrace 40–60%): all 9 cells +3.6% to +9.7%, tclust 1.7–3.3 — a
plateau, not a knife-edge. Because exits key off the underlying and fill at
real prints, biases 1–3 do not apply; the entry is live-knowable, so bias 5
does not apply. Remaining caveats: orig8 cohort only (8 tickers, 24 months),
exit shape inherits the mined arm-then-trail idea (parameters were one-shot,
not grid-searched), and the spread proxy stands in for quotes. This is the
one cell worth the new12 validation run before anything is published.
