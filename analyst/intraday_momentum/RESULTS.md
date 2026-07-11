# Intraday Momentum (SSRN 4824172) on ES — Prop-Eval Sizing Study

**Question.** Can the Zarattini/Aziz/Barbon "Beat the Market" intraday momentum
strategy (noise-area breakout, VWAP+band trailing stop) be tuned with variable
position size to (a) pass a futures prop eval — $4,500 profit target within ~5
trading days, blowup tolerance ~50% — and (b) sustain $4,500 per 2 weeks on a
funded account at ~20% blowup risk?

**Data.** ES 1-min continuous ratio-adjusted (2008-01 → 2026-01-23, ET),
SPY 1-min Massive (validation). RTH 09:30–15:59 ET only.

**Engine.** Faithful replication of the paper's rules: per-minute-of-day noise
bands sigma_m = mean over prior L sessions of |C_m/O − 1| anchored at
max/min(open, prev close); decisions at semi-hourly checkpoints 10:00–15:30
(signal on prior-minute close, fill at checkpoint-bar open); long above upper
band / short below lower; trailing stop = max(UB, VWAP) for longs, min(LB,
VWAP) for shorts; opposite-band cross flips; flat at session close.

**Costs.** ES: 1 tick/side slippage + $4.30 RT commission = 0.586 pt ≈ $29.3/RT
per contract. SPY validation: paper's $0.0035 + $0.001 per share/side.

## 1. Engine validation (SPY, paper window 2007-05 → 2024-04)

| metric | paper (Table 2, 100% size) | this replication |
|---|---|---|
| net Sharpe | 1.24 | 1.11 |
| ann. return (simple) | 9.7% (IRR) | 8.6% |
| hit rate, traded days | 43% | 42.8% |
| round trips / day | ~0.9 | 0.94 |

Engine reproduces the paper. Differences (VWAP def., exact fill mechanics) are
small.

## 2. The edge has decayed to ~zero post-publication

SPY, near-zero (paper) costs, net avg bps/day by year:
2022: **+6.35** · 2023: **+3.85** · 2024: **+1.76** · 2025: **+1.19** ·
2026 YTD (n=83): **−1.96**.
Post-publication window (2024-05 → 2026-04): **+0.56 bps/day, t = 0.34** —
statistically zero. The authors' own tracking table agrees (2025: +1.0% through
Aug at ~4× vol-target leverage).

ES net of realistic futures costs (1 ES contract, $/day):

| spec | full 2008-26 | 2022+ | post-pub (2024-05+) |
|---|---|---|---|
| VM 1.0 / LB 14 (paper base) | +$15.8/day (t=1.8) | +$32.6 (t=1.2) | **−$28.9 (t=−0.45)**, gross ≈ 0 |
| VM 1.0 / LB 90 | +$17.3 (t=2.5) | +$35.3 (t=1.1) | +$18.2 (t=0.4) |
| VM 1.5 / LB 90 (paper's pre-registered optima) | +$15.2 (t=2.4) | +$20.4 (t=0.7) | +$39.5 (t=0.8) |
| VM 2.0 (any LB) | ≈ 0 | negative | ≈ 0 |

The paper-base spec is gross-flat on ES post-publication — decay, not just
costs. VM 1.5 / LB 90 (both values published in the paper before the OOS
window, so not our mining) is the only spec with positive post-pub net PnL,
driven by fewer trades (0.38 RT/day) and extreme positive skew: median day $0,
skew ≈ 10, best day 2025-04-09 (tariff-pause melt-up) +$21,045 on one
contract. Worst single days (2022 vol regime): −$5.5K to −$6.7K on ONE
contract — each alone breaches any common eval trailing drawdown.

## 3. Prop-account Monte Carlo (bootstrap of intraday equity paths)

Whole trading days sampled iid from the historical window; minute-level marks;
trailing max-drawdown tracked intraday (Apex-style, worst case) or EOD
(Topstep-style). Trailing floor never freezes (real firms freeze it near the
start balance once profit ≈ DD — our blowup estimates are slightly
conservative). Target $4,500.

### Phase 1 — eval ($4,500 target, resolve within 5 trading days)

P(pass) / P(blow) for the base spec (VM 1.0/LB 14). 2022+ window; the
post-pub-only window (2024-05→2026-01, n=447 days) shown in parens where it
differs materially — it is generally *slightly better*, so the result is not
riding on 2022 vol.

**EOD-trailing drawdown (Topstep-style):**

| contracts | DD $2,500 | DD $3,000 | DD $4,000 |
|---|---|---|---|
| 5 | 57% / 36% | 59% / 32% | 61% / 28% |
| 12 | 69% / 29% (71%/26%) | 69% / 28% | 71% / 27% |
| 15 | 71% / 27% (73%/24%) | 72% / 26% | 73% / 25% |
| 20 | **75% / 23% (77%/20%)** | 76% / 23% | 76% / 22% |
| cushion/$250 | 67% / 30% (68%/28%) | 69% / 29% | 73% / 24% |

Remainder = unresolved at day 5 (can keep trading). Median resolution ~1-2
days at 12-20 contracts. Bigger is strictly better under EOD trailing: the
target is touched intraday before the EOD drawdown check ever marks the
excursion. Fast resolution also beats patient grinding — fixed 8 with 60-day
patience is strictly worse (65% / 35% at $2.5K) because time under a trailing
drawdown is itself risk.

**Intraday-trailing drawdown (Apex-style):** best cells only ~40-48% pass /
~50-57% blow (fixed 20, DD $4-5K). At Pedro's 50% blowup tolerance this is
marginal; EOD-trailing firms are structurally the right venue for this play.

VM 1.5/LB 90 spec: lower pass (63% at 20 lots, $2.5K EOD), lower blow (20%),
more unresolved — it trades only ~30% of days. Base spec resolves faster and
passes more; positive post-pub drift is irrelevant at this horizon (drift
$30-40/day vs $19-22K daily sd at 20 lots).

### Phase 2 — funded ($4,500 per 2 weeks, ≤20% blowup): INFEASIBLE

- Required expectancy ≈ $450/trading day. Best spec post-pub ≈ **$40/day per
  contract (t = 0.8)** → ~11 ES needed, where one 5th-percentile day is
  −$13K. No common drawdown survives.
- MC, funded 60 trading days, no profit target: P(blow) = 72-100% across ALL
  cells (1-5 contracts × $2.5-5K DD × both modes). Expected PnL $59-$240 per
  10 days. A ~zero-edge engine under a ratcheting trailing drawdown always
  dies; only the date varies.
- Verdict: this engine cannot meet the funded spec alone. It can contribute
  ~1 contract of positive-skew exposure to a multi-engine book, or serve
  purely as the eval-passing vehicle.

### Practical constraints to check per firm

- Contract caps: many $50-150K evals cap at 5-17 contracts — the 12-15 lot
  cells matter more than the 20-lot one.
- Consistency rules (best day ≤ X% of total) break one-day passes; firms
  without eval consistency rules are required for the fast-resolution play.
- Minimum trading days: wait them out flat or with 1 MES after hitting target.
- Intraday vs EOD trailing is THE deciding variable — verify before buying.

## 4. Tuning grid + hourly compression/expansion filters (2026-07-10)

96 configs (interval 15/30/60 min × VM 0.75-1.5 × LB 14/90 × stop mode
band+vwap / band / vwap / opp-band), selection on train (2008-07→2024-04,
ranked by 2022→2024-04 t), holdout = post-pub (2024-05→2026-01). Files:
tune_grid.py, day_flags.py, analyze_tune.py, tune_grid_summary.csv.

**Knobs do not rescue the holdout.** All top-train configs are ≤ 0 on holdout
(best cells −$26 to −$64/day, t −0.5 to −1.1). Train marginals: vwap-only stop
best on train-recent (+$51 vs $35-37/day), interval 15/30 ≈ tied > 60, LB 14 >
90 recently, VM 1.0-1.25 > 0.75/1.5 — none of it transfers.

**Day filters (pre-open, ETH 1h bars):**
- `rr6_60` = mean true range of last 6 completed 1h bars / last 60.
  Compression (`<0.79`, ~19% of days) on the base spec: train +$51.5/day
  t=2.2 Sharpe 1.24; holdout +$40.9/day t=0.62 Sharpe 0.83 (n=142) vs
  unfiltered holdout −$28.9/day. Threshold not knife-edge (monotone t 1.5-3.4
  across 0.6-1.1; rr<1.0 best train t=3.39). BUT: yearly PnL lumpy (2010-15
  negative, 2020 −$8.1K, 2024 −$4.4K; holdout carried by 2025 +$9.1K/84d) and
  the filter does NOT transfer to the VM1.5/LB90 spec (holdout subset
  −$2.2/day). Status: suggestive, unconfirmed — needs more OOS.
- Expansion anti-filter (`rr6_60>1.21`, ~15% of days): consistently negative
  in BOTH windows and across specs (train −$25 to −$55/day, t to −2.15;
  holdout −$49 to −$105/day). Robust hygiene rule: do not run this engine
  after hourly range expansion.
- Saty PO 1h compression flag: does NOT work here (comp=1 worse than comp=0
  on train: +$12.5 vs +$28.8/day) — the useful signal is "recent hours quiet
  vs their own trailing baseline", not the BB-vs-ATR structure state.
- NR4/NR7 prior day (paper's own filter): positive on train (+$24-28/day),
  ~0 to negative on holdout. Not confirmed.

Portfolio read: the engine's alpha is vol-regime-gated (2008/2018/2021-22/
Apr-2025 print; low-vol chop bleeds). A defensible sleeve today = base-family
spec, skip expansion days, small size (1-2 ES), expectation honestly $0-40/day
per contract with wide error bars; it earns its keep as crisis-convex
positive-skew exposure, not as a steady payer.

## 5. Tuning campaign round 2: variants, vol gates, stacks (goal: recover edge)

160 configs (entry windows incl. skip-lunch/AM/PM, 1-2 check confirmation,
round-trip caps × vm/interval/stop). Train marginals: skip-lunch mildly
positive, confirmation strictly hurts, RT caps neutral, vwap-only stop best.
Stacked with vol gates (VIX≥20, rvol14≥1.4%) and rr6_60≤1.0: train numbers
looked excellent (best stack +$88/day t=2.85 Sharpe 1.67; train-recent +$274/day
Sharpe 3.47). **Holdout (single pre-declared read, 3 stacks): all fail** —
−$49/day, +$5/day, −$33/day. Classic regime-memory collapse. Files:
tune_round2.py, analyze_r2.py, tune_r2_summary.csv.

## 6. NQ: the edge is alive on Nasdaq futures (the material finding)

Paper's EXACT base spec (VM 1.0, LB 14, 30-min checks, band+VWAP stop),
zero tuning, run on NQ 1-min (2008→2026-01), costs 1 tick/side + $4.30 RT
($14.30/RT ≈ 0.715 NQ pts). Clean OOS in instrument AND (post-pub) time:

| window | avg $/day/contract | t | Sharpe |
|---|---|---|---|
| train 2008-07→2024-04 | +$54.2 | 3.67 | 0.91 |
| train-recent 2022→2024-04 | +$150.7 | 2.11 | 1.37 |
| **holdout 2024-05→2026-01** | **+$105.8** | 0.94 | 0.70 |
| holdout 2024 | +$109.2 | 0.87 | 1.04 |
| holdout 2025 | +$164.0 | 0.94 | 0.93 |
| holdout 2026 YTD (n=16) | −$866.7 | −2.63 | — |

Per notional: NQ holdout ≈ +2.1 bps/day net vs ES −0.6. Same engine, same
period — the decay is instrument-specific, not universal.

Pre-declared confirmation reads (holdout touched twice more, then closed):
1. Train-selected variant (vm1.25/i30/vwap): holdout +$76/day — positive but
   below untuned base. Tuning adds nothing on NQ either.
2. Base + skip-expansion-days (rr6_60 ≤ 1.21 on NQ ETH 1h bars):
   **holdout +$142.3/day, t=1.18, Sharpe 0.95 (n=388)**; excluded expansion
   days −$134.3/day (n=59). Train: +$68.8/day t=4.38 vs −$33.9 on expansion
   days. The anti-filter is now confirmed in 4/4 instrument×window combos
   (ES/NQ × train/holdout).

**Final candidate: NQ, paper base spec, skip expansion days.**
Train +$68.8/day/contract (t=4.38, Sharpe 1.18, n=3501, ~86% of days
tradable); holdout +$142.3/day (t=1.18, Sharpe 0.95). Daily sd ≈
$2,300-2,400/contract.

Funded-phase update: $450/day still needs ~3-4 NQ → daily sd $8-10K → still
infeasible at 20% blowup with $2.5-5K trailing DD. But 1 NQ ≈ $1,400-2,800/mo
expectation at Sharpe ~1 — a real sleeve, and the eval variance play works on
NQ the same way (1 NQ ≈ 2.2 ES of daily vol).

## 7. Execution mechanics (intrabar stops): negative, and diagnostic

ES, train only (no holdout read — nothing beat baseline): intrabar stop-entry
at the band −$32.7/day (t=−2.75) vs checkpoint entries +$31.0/day; intrabar
trailing exits $16.5 vs $31.0; full intrabar stop-and-reverse −$462.8/day at
7.9 RT/day. The semi-hourly checkpoint discipline is the edge-preserving
mechanism — band touches are mostly noise; the 30-min confirmation filters
them. Do not "improve" the execution. File: intrabar_es.py.

## Campaign verdict (goal: materially improve the edge)

Achieved via instrument + one robust filter, not knobs:
- Deployable edge at goal-set time: ES base spec, post-pub **−$28.9/day**.
- Final: **NQ base spec + skip expansion days: train +$68.8/day (t=4.38,
  Sharpe 1.18); holdout +$142.3/day (t=1.18, Sharpe 0.95)**.
- Every pure parameter dimension (bands, lookback, check frequency, stops,
  entry windows, confirmation, vol gates, execution style) either failed the
  holdout or underperformed the paper's untuned spec. The recovered alpha came
  from (a) NQ hosting the anomaly better than ES, (b) not trading after hourly
  range expansion (4/4 instrument×window confirmations).

## Caveats

- iid day bootstrap ignores vol clustering; 2022-style clusters of −$5K days
  are more likely back-to-back in reality than in the MC.
- Continuous contract stitches rolls; roll-day overnight anchors slightly off.
- Fill model: market orders at checkpoint-bar open with 1 tick slippage;
  April-2025-style days likely slip worse.
- VM 1.5/LB 90 chosen among 6 specs partly on post-pub performance —
  quasi-OOS (values pre-registered by the paper), but treat +$40/day as an
  optimistic point estimate of a t=0.8 quantity.
