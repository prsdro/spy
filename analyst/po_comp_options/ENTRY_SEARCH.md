# Entry/Exit Combination Search + Pre-Registered Fresh-Cohort Confirmation

2026-07-09. Follow-up to `BIAS_REVIEW.md` (which retired the +12–13.5% headlines)
and the "Post-audit" section of `RESULTS.md` (current baselines). Goal: a
disciplined search over live-knowable entries × the underlying-keyed straddle
exit, then a one-shot pre-registered confirmation on ~10 tickers never used in
this study.

**Fixed mechanics for every cell** (from `scratch_entry_search_undexit.py`,
a parameterized generalization of `scratch_bias_6_undexit.py` — it reproduces
all four published baselines print-for-print):
straddle = both W1 ATM legs, filled at the first actual option print strictly
after the signal (≤5 min or the leg is skipped); each leg managed off
underlying 5m closes — arm at 0.75× box-height favorable excursion, exit at
50% retrace of best excursion, pre-arm invalidation at the opposite box edge,
expiry fallback; option exits at the first print within 15 min after the
trigger bar close (else last prior print). Intraday signals only
(`rolled_to_open` excluded), uncensored, offset 0.

**Cost stance (Pedro, fixed)**: central case = no bid/ask spread haircut
(limit orders + good broker). The measured-effective-spread version
(`strad_sp`, ~0.7%/side median proxy) is reported once per headline cell as a
sensitivity lower bound.

**Stats format**: mean % of combined premium per box + n boxes + plain t +
date-clustered t (cluster = entry date) + win% (+ d = distinct entry dates).

**Cohorts** — both are burned (used in the audit and baseline selection);
everything in Phase 1 is treated as in-sample:
- orig8 (o8): AAPL AMD AMZN GOOGL META MSFT NVDA TSLA, 2024-07→2026-07
- new12 (n12): AVGO BAC COIN DIS HOOD INTC JPM MU NFLX PLTR SMCI UBER, same window

## Phase 1 — mining ledger

Every cell run is listed, including the losers. Cells = one (entry × gate ×
cohort × exit-param) stat on the straddle column. Spread-sensitivity re-reads
of the same cell are not counted as separate cells.

### 1a. Entry variants (no gate, arm 0.75 / retrace 0.50)

| # | entry | cohort | straddle result |
|---|---|---|---|
| 1 | locked 5-bar box, first 5m poke (baseline) | o8 | +9.4% (n=397, t +3.69, tc +3.14, win 53%, d=256) |
| 2 | locked 5-bar box, first 5m poke (baseline) | n12 | +5.8% (n=410, t +2.15, tc +1.31, win 47%, d=256) |
| 3 | hourly close-confirmed break (baseline) | o8 | +8.0% (n=645, t +4.43, tc +3.86, win 58%, d=336) |
| 4 | hourly close-confirmed break (baseline) | n12 | +4.0% (n=624, t +2.15, tc +1.99, win 53%, d=325) |
| 5 | first 5m CLOSE beyond box edge | o8 | +7.0% (n=425, t +3.00, tc +2.68, win 54%, d=270) |
| 6 | first 5m CLOSE beyond box edge | n12 | +5.3% (n=453, t +2.06, tc +1.49, win 48%, d=275) |
| 7 | first 10m CLOSE beyond box edge | o8 | +7.0% (n=406, t +3.10, tc +2.60, win 54%, d=261) |
| 8 | first 10m CLOSE beyond box edge | n12 | +4.0% (n=425, t +1.60, tc +1.58, win 49%, d=273) |
| 9 | first 30m CLOSE beyond box edge | o8 | +5.2% (n=385, t +2.35, tc +2.20, win 54%, d=250) |
| 10 | first 30m CLOSE beyond box edge | n12 | +4.0% (n=390, t +1.76, tc +1.65, win 52%, d=252) |
| 11 | 10m close + LTF PO gate | o8 | +5.7% (n=425, t +2.61, tc +2.37, win 54%, d=266) |
| 12 | 10m close + LTF PO gate | n12 | +4.5% (n=416, t +1.90, tc +1.50, win 50%, d=260) |
| 13 | 30m close + LTF PO gate | o8 | +4.6% (n=412, t +2.39, tc +2.13, win 57%, d=254) |
| 14 | 30m close + LTF PO gate | n12 | +5.4% (n=389, t +2.20, tc +2.36, win 55%, d=243) |
| 15 | 5m close + LTF PO gate | o8 | +6.6% (n=423, t +2.96, tc +2.47, win 53%, d=269) |
| 16 | 5m close + LTF PO gate | n12 | +5.1% (n=451, t +2.27, tc +1.72, win 51%, d=271) |
| 17 | re-poke, same edge (1st poke fails on 5m close) | o8 | +5.0% (n=182, t +1.67, tc +1.57, win 51%, d=152) |
| 18 | re-poke, same edge | n12 | +2.6% (n=175, t +0.75, tc +0.74, win 49%, d=151) |
| 19 | re-poke, either edge | o8 | +5.1% (n=194, t +1.75, tc +1.59, win 52%, d=156) |
| 20 | re-poke, either edge | n12 | +3.0% (n=199, t +0.98, tc +0.85, win 49%, d=166) |

Read (1a): no alternative entry beats the two baselines on both cohorts. The
5m/10m/30m close entries land between the poke and hourly-confirm baselines
(earlier entry than the hourly confirm buys nothing net); the LTF PO gates
shuffle a point either way with no consistent sign. Re-poke entries are the
weakest family tested — conditioning on a failed first poke removes more edge
than it adds (and cuts n by ~55%). New walks: `scratch_entry_search_pipeline.py`
(copy of `scratch_po_comp_flip_rerun.py` + `REPOKE` env) and
`scratch_po_comp_ltf_entry.py` with `LTF=5`; artifacts `es_*_trades.parquet`.

### 1b. Box-quality gates (on the two baseline entries, arm 0.75 / retr 0.50)

Box height in daily-ATR buckets (`box_h_atr` = box height / prior-day ATR14):

| # | entry | gate | o8 | n12 |
|---|---|---|---|---|
| 21–22 | fullbox poke | boxh <0.3 | −1.7% (n=18, t −0.69, tc −0.69, win 33%) | −0.0% (n=19, t −0.01, tc −0.01, win 42%) |
| 23–24 | fullbox poke | boxh 0.3–0.6 | +11.7% (n=153, t +3.05, tc +2.93, win 58%) | +10.8% (n=182, t +2.32, tc +2.19, win 52%) |
| 25–26 | fullbox poke | boxh ≥0.6 | +8.7% (n=226, t +2.40, tc +2.01, win 51%) | +1.9% (n=209, t +0.57, tc −0.22, win 44%) |
| 27–28 | fullbox poke | boxh <0.6 | +10.3% (n=171, t +2.97, tc +2.84, win 56%) | +9.7% (n=201, t +2.32, tc +2.10, win 51%) |
| 29–30 | fullbox poke | boxh ≥0.3 | +9.9% (n=379, t +3.73, tc +3.18, win 54%) | +6.0% (n=391, t +2.15, tc +1.44, win 48%) |
| 31–32 | close-confirm | boxh <0.3 | +12.6% (n=116, t +2.48, tc +2.33, win 59%) | +6.2% (n=142, t +1.80, tc +1.42, win 53%) |
| 33–34 | close-confirm | boxh 0.3–0.6 | +6.5% (n=273, t +2.68, tc +1.77, win 56%) | +5.7% (n=256, t +1.98, tc +1.82, win 56%) |
| 35–36 | close-confirm | boxh ≥0.6 | +7.4% (n=256, t +2.54, tc +2.47, win 59%) | +0.8% (n=226, t +0.23, tc +0.43, win 48%) |
| 37–38 | close-confirm | boxh <0.6 | +8.3% (n=389, t +3.65, tc +3.00, win 57%) | +5.9% (n=398, t +2.65, tc +2.31, win 55%) |
| 39–40 | close-confirm | boxh ≥0.3 | +6.9% (n=529, t +3.67, tc +3.55, win 57%) | +3.4% (n=482, t +1.54, tc +1.85, win 52%) |

Box-bars at entry (`grey_bars_at_entry`, close-confirm only — fullbox is 5 by construction):

| # | entry | gate | o8 | n12 |
|---|---|---|---|---|
| 41–42 | close-confirm | grey 1–2 | +7.0% (n=190, t +2.22, tc +2.41, win 58%) | +6.1% (n=230, t +1.88, tc +2.00, win 51%) |
| 43–44 | close-confirm | grey 3–4 | +14.1% (n=79, t +2.61, tc +2.52, win 62%) | −2.6% (n=75, t −0.44, tc −0.18, win 35%) |
| 45–46 | close-confirm | grey ≥5 | +7.2% (n=376, t +3.00, tc +2.69, win 56%) | +4.1% (n=319, t +1.67, tc +1.62, win 58%) |

Box formed in RTH vs overnight (fraction of the box's hourly ETH bars with
bar-start hour 9–15 ET):

| # | entry | gate | o8 | n12 |
|---|---|---|---|---|
| 47–48 | fullbox poke | mostly RTH (≥0.6) | +10.3% (n=280, t +3.11, tc +2.71, win 54%) | +3.2% (n=292, t +1.11, tc +0.82, win 46%) |
| 49–50 | fullbox poke | mixed (0.2–0.6) | +12.8% (n=33, t +1.38, tc +1.44, win 58%) | +14.9% (n=45, t +1.81, tc +1.64, win 49%) |
| 51–52 | fullbox poke | mostly overnight (≤0.2) | +4.8% (n=84, t +1.68, tc +1.53, win 50%) | +10.5% (n=73, t +1.25, tc +1.25, win 52%) |
| 53–54 | close-confirm | mostly RTH (≥0.6) | +6.7% (n=423, t +3.16, tc +2.54, win 57%) | +2.6% (n=402, t +1.17, tc +1.23, win 51%) |
| 55–56 | close-confirm | mixed (0.2–0.6) | +13.8% (n=81, t +1.94, tc +2.18, win 60%) | +6.3% (n=85, t +1.06, tc +0.72, win 55%) |
| 57–58 | close-confirm | mostly overnight (≤0.2) | +8.4% (n=141, t +2.57, tc +2.12, win 60%) | +6.8% (n=137, t +1.67, tc +1.05, win 55%) |

Read (1b): **box height is the one gate with a consistent shape in both
cohorts** — boxes ≥0.6 dATR decay hard out-of-cohort (+8.7→+1.9 poke,
+7.4→+0.8 confirm) and <0.3 dATR is the worst poke bucket in both; the
simple `boxh <0.6` cut improves mean AND clustering-adjusted t on both
entries in both cohorts. Economic sense: a box already ≥0.6 of a day's range
has spent much of the day's expected move before entry, so the post-break
excursion available to the 0.75×box arm is smaller relative to the (larger)
straddle premium. Grey-bars and RTH/overnight buckets flip sign between
cohorts — treated as null. On the confirm entry the boxh<0.3 bucket is FINE
(+12.6/+6.2) — the tiny-box problem is specific to the poke entry (intrabar
poke of a tiny box is mostly noise; a full hourly close beyond a tiny box is
still information), so the gate is a pure upper cut.

### 1c. VIX gate (vix_1h.parquet, merge_asof backward at entry)

| # | entry | gate | o8 | n12 |
|---|---|---|---|---|
| 59–60 | fullbox poke | VIX <18 | +12.1% (n=215, t +3.37, tc +2.80, win 54%) | +6.9% (n=237, t +2.06, tc +1.80, win 48%) |
| 61–62 | fullbox poke | VIX 18–20 | +1.7% (n=84, t +0.38, tc +0.01, win 49%) | +6.8% (n=74, t +0.81, tc +0.86, win 46%) |
| 63–64 | fullbox poke | VIX ≥20 | +10.0% (n=98, t +1.83, tc +1.75, win 55%) | +2.1% (n=99, t +0.48, tc +0.25, win 46%) |
| 65–66 | close-confirm | VIX <18 | +8.9% (n=367, t +3.79, tc +3.40, win 59%) | +6.3% (n=361, t +2.36, tc +2.11, win 53%) |
| 67–68 | close-confirm | VIX 18–20 | +11.3% (n=110, t +1.94, tc +1.65, win 58%) | +0.7% (n=105, t +0.21, tc +0.23, win 51%) |
| 69–70 | close-confirm | VIX ≥20 | +3.7% (n=168, t +1.42, tc +1.21, win 55%) | +1.1% (n=158, t +0.30, tc +0.24, win 53%) |

Read (1c): VIX <18 is the best bucket on both entries in both cohorts
(cheap-premium regime; plausible for a long-convexity trade), but the middle
bucket flips sign between cohorts and the gate is calendar-shared — a fresh
ticker cohort over the SAME 24 months cannot independently confirm a VIX
gate. Kept out of the primary config for that reason.

### 1d. Combinations

| # | entry + gates | o8 | n12 |
|---|---|---|---|
| 71–72 | fullbox poke + boxh 0.3–0.6 + VIX<18 | +12.3% (n=85, t +2.11, tc +2.10, win 54%) | +8.4% (n=113, t +1.70, tc +1.76, win 51%) |
| 73–74 | fullbox poke + boxh<0.6 + VIX<18 | +11.1% (n=94, t +2.10, tc +2.10, win 53%) | +7.4% (n=129, t +1.70, tc +1.64, win 50%) |
| 75–76 | fullbox poke + boxh≥0.3 + VIX<18 | +12.6% (n=206, t +3.38, tc +2.81, win 54%) | +7.4% (n=221, t +2.07, tc +1.95, win 48%) |
| 77–78 | close-confirm + boxh 0.3–0.6 + VIX<18 | +6.6% (n=161, t +2.21, tc +1.44, win 58%) | +7.7% (n=140, t +1.95, tc +1.80, win 60%) |
| 79–80 | close-confirm + boxh<0.6 + VIX<18 | +9.2% (n=228, t +3.02, tc +2.44, win 58%) | +8.1% (n=232, t +2.62, tc +2.15, win 56%) |
| 81–82 | close-confirm + boxh≥0.3 + VIX<18 | +7.5% (n=300, t +3.18, tc +3.06, win 59%) | +5.5% (n=269, t +1.75, tc +1.95, win 54%) |

Pooled 20-ticker views (o8+n12, in-sample; date-clustered t over shared dates):

| # | cell | pooled |
|---|---|---|
| 83 | fullbox poke, all | +7.5% (n=807, t +4.08, tc +2.85, win 50%, d=356) |
| 84 | fullbox poke + boxh<0.6 | +10.0% (n=372, t +3.61, tc +3.47, win 53%, d=231) — spread-haircut +8.1% (tc +2.86) |
| 85 | fullbox poke + boxh 0.3–0.6 | +11.2% (n=335, t +3.65, tc +3.55, win 55%, d=217) |
| 86 | fullbox poke + VIX<18 | +9.4% (n=452, t +3.83, tc +2.84, win 51%, d=212) |
| 87 | fullbox poke + boxh<0.6 + VIX<18 | +8.9% (n=223, t +2.67, tc +2.53, win 52%, d=139) |
| 88 | close-confirm, all | +6.0% (n=1269, t +4.64, tc +3.53, win 55%, d=421) |
| 89 | close-confirm + boxh<0.6 | +7.1% (n=787, t +4.45, tc +3.48, win 56%, d=354) — spread-haircut +5.4% (tc +2.32) |
| 90 | close-confirm + boxh 0.3–0.6 | +6.1% (n=529, t +3.26, tc +2.48, win 56%, d=293) |
| 91 | close-confirm + VIX<18 | +7.6% (n=728, t +4.29, tc +3.42, win 56%, d=258) |
| 92 | close-confirm + boxh<0.6 + VIX<18 | +8.6% (n=460, t +3.99, tc +2.96, win 57%, d=217) — spread-haircut +6.9% (tc +2.06) |

Per-ticker breadth of the finalists (share of tickers with positive mean):

| cell | o8 | n12 |
|---|---|---|
| fullbox poke + boxh<0.6 | 6/8 (AAPL −0, NVDA −1) | 7/12 (MU +51 carries; BAC/DIS/HOOD/JPM/UBER negative) |
| close-confirm + boxh<0.6 | **8/8** | **10/12** (INTC −0, NFLX −10) |
| close-confirm + boxh<0.6 + VIX<18 | **8/8** | **11/12** (NFLX −12) |
| close-confirm + VIX<18 | **8/8** | **11/12** (NFLX −9) |

### 1e. Exit-neighborhood plateau (arm 0.5/0.75/1.0 × retrace 0.4/0.5/0.6)

Cells 93–164 (9 exit configs × {fullbox, confirm} × {o8, n12} × {ungated,
boxh<0.6}; full grid in `es_plateau.parquet`). Straddle mean (tc), gated
boxh<0.6 shown:

close-confirm + boxh<0.6:

| arm \ retr | 0.4 | 0.5 | 0.6 |
|---|---|---|---|
| 0.50 | o8 +6.6 (2.32) / n12 +4.8 (2.20) | +4.4 (1.79) / +4.1 (1.79) | +3.4 (1.46) / +0.8 (0.88) |
| 0.75 | +10.3 (3.17) / +7.4 (2.74) | **+8.3 (3.00) / +5.9 (2.31)** | +5.9 (2.42) / +1.8 (1.47) |
| 1.00 | +9.5 (2.77) / +9.6 (2.81) | +7.8 (2.76) / +7.7 (2.51) | +5.4 (2.18) / +2.3 (1.33) |

fullbox poke + boxh<0.6:

| arm \ retr | 0.4 | 0.5 | 0.6 |
|---|---|---|---|
| 0.50 | +8.4 (2.23) / +11.0 (2.40) | +7.3 (2.11) / +9.8 (2.18) | +6.3 (2.09) / +8.2 (2.22) |
| 0.75 | +11.6 (2.90) / +9.9 (2.07) | **+10.3 (2.84) / +9.7 (2.10)** | +9.8 (3.03) / +8.1 (2.08) |
| 1.00 | +12.6 (3.09) / +7.7 (1.49) | +11.0 (3.04) / +8.2 (1.59) | +11.0 (3.40) / +7.2 (1.59) |

Read (1e): all 18 gated cells positive in both cohorts. For the confirm
entry the canonical 0.75/0.50 sits on a plateau (its 0.4-retrace and 1.0-arm
neighbors are somewhat better, 0.6-retrace worse); no knife-edge. The
canonical exit parameters are kept — they were the one-shot pre-registered
choice from the bias review, and re-optimizing them here would be a second
mining pass. Fullbox poke is mean-stable everywhere but its n12 tc collapses
at arm 1.0 (0.77–1.05 ungated) — mildly less robust.

**Running cell count, Phase 1: 164 cells** (20 entry-variant, 38 single-gate,
22 combo/pooled, 72 plateau, plus the 12 per-ticker breadth reads not counted
as cells). With this many reads, one or two tc≈2.5 cells are expected by
chance; the selection below leans on both-cohort consistency + breadth +
economic sense, not the single best number.

## Phase 2 — pre-registration (written 2026-07-09, BEFORE any fresh-cohort data was pulled)

Codex was consulted on the finalist choice (one `codex exec` pass); it
concurred with the primary, flagged the runner-up as needing quarantine from
the success claim, and asked that the pass bar be made mechanical. Adopted
below.

**Fresh cohort**: ORCL, QCOM, MRVL, CRM, WMT, XOM, GS, LLY, CAT, SHOP —
10 liquid optionable US names never used in any phase of this study. Checked
before registration (reference data only): all 10 have weekly options on
non-monthly Fridays (2024-08-02 and 2025-03-07 chains exist) and zero splits
2024-07-01→2026-07-08. Window: PO_WINDOW_START=2024-07-14, ETH sessions,
same 24 months as the burned cohorts — so this test validates TICKER
generalization within the same regime, not time-regime robustness.

**PRIMARY (the only cell that can declare a pass)** — "close-confirm + small
box":
- Episode: hourly (ETH grid, 4:00–19:55 ET, on-the-hour bars) PO-compression
  episode per `fetch_po_comp_options.phase2_events` with default freeze5 box
  (box = range of completed grey bars, frozen after 5).
- Entry signal: the first hourly bar that BOTH closes out of compression AND
  broke the box range (high>box_hi or low<box_lo), i.e.
  `scratch_po_comp_flip_rerun.py` with `CONFIRM_CLOSE=1`, exactly as
  `flip8_confirm`. Signal at that bar's close; direction = break side (close
  vs box mid if both sides). Intraday signals only (`rolled_to_open`
  excluded); censored boxes excluded.
- Gate: box height < 0.6 × prior-day daily ATR14 (`box_h_atr < 0.6`).
  Applied to the primary only; no VIX gate, no other gate.
- Position: W1 ATM straddle (nearest strike to entry spot, next Friday ≥4
  DTE), both legs long, offset 0. Each leg filled at the FIRST actual option
  print strictly after the signal, ≤5 min or the leg is skipped; box counts
  only if BOTH legs fill (same as every Phase-1 cell).
- Exit (per leg, on underlying 5m closes after entry): arm at 0.75×box-height
  favorable excursion from entry spot; after arming exit when excursion
  retraces to 50% of best; pre-arm invalidation at a 5m close through the
  opposite box edge; expiry fallback. Option sold at the first print within
  15 min after the exit-trigger bar close, else last prior print.
- Cost: no spread haircut (central case). The effective-spread version is
  reported as sensitivity only and does not gate the verdict.
- Metric: per-box straddle return = premium-weighted mean of the two leg
  returns; equal weight per box.

**PASS BAR (all three, simultaneously, on the primary cell, pooled over all
fresh-cohort boxes)**:
1. date-clustered t ≥ 2.0 (cluster = entry date, t on daily means, the exact
   `stats()` in `scratch_entry_search_undexit.py`);
2. mean ≥ +4.0% of combined premium per box;
3. ≥6 of the 10 fresh tickers have a positive per-ticker mean straddle
   return (a ticker with zero qualifying boxes counts as NOT positive).

**RUNNER-UP (descriptive only — CANNOT rescue a failed primary, reported
verbatim either way)**: locked 5-bar box, first 5m poke entry (`NO_FLAG=1
WAIT_FULL_BOX=1`, as `flip8_fullbox`) + the same boxh<0.6 gate, same
position/exit/cost. Same three statistics reported against the same bar, but
labeled secondary; if it passes and the primary fails, the study result is
still "primary failed".

Anything else computed on the fresh cohort (ungated versions, VIX splits,
other entries) is exploratory and will be labeled as such.

## Phase 3 — fresh-cohort confirmation (the only part that counts)

Data: `fetch_po_comp_options.py` with PO_TICKERS=ORCL,QCOM,MRVL,CRM,WMT,XOM,GS,LLY,CAT,SHOP,
PO_WINDOW_START=2024-07-14, ETH, W1 ATM both types only (`events_fresh10.csv`,
2,966 episodes; `contracts_todo_fresh10.json`, 4,524 contracts pulled into the
shared `option_bars.sqlite`; log `fresh10_pull.log`). Walks:
`scratch_entry_search_pipeline.py` CONFIRM_CLOSE=1 → `fresh10_confirm_trades.parquet`
(1,897 entries) and NO_FLAG=1 WAIT_FULL_BOX=1 → `fresh10_fullbox_trades.parquet`
(1,264 entries); incremental-flag validation 100% on all 10 tickers.

### Pre-registered verdict (verbatim from the harness)

**PRIMARY — close-confirm + boxh<0.6, W1 ATM straddle, underlying-keyed exit
(arm 0.75, retrace 0.50), no spread haircut:**
- straddle **+3.7% of combined premium (n=119 boxes, t +0.96, date-clustered
  t +1.58, win 55%, 104 entry dates)**
- effective-spread sensitivity: +1.7% (t +0.44, tc +1.10, win 50%)
- per-ticker mean: ORCL +28.0, CAT +21.2, CRM +10.8, LLY +6.1, MRVL +5.6,
  QCOM −2.0, WMT −2.7, XOM −4.0, SHOP −4.1, GS −9.8 → **5/10 positive**
- pass bar: tc ≥2.0 **FAIL** (+1.58) · mean ≥+4% **FAIL** (+3.7%) · ≥6/10
  tickers positive **FAIL** (5/10)
- **VERDICT: FAIL** (all three criteria, each narrowly)

**RUNNER-UP (descriptive only) — locked-box first-poke + boxh<0.6, same
position/exit/cost:**
- straddle **−2.2% (n=53, t −0.74, tc −1.02, win 43%, 48 dates)**; spread
  sensitivity −4.9%; per-ticker 3/10 positive
- **VERDICT: FAIL** (all three criteria, decisively)

### Exploratory reads on the fresh cohort (NOT pre-registered, labeled as such)

- close-confirm UNGATED: +5.3% (n=183, t +1.52, tc +1.74, win 55%) — 5/10
  tickers positive.
- fullbox poke UNGATED: +13.2% (n=121, t +2.43, tc +2.47, win 53%, 7/10
  positive) — and its boxh≥0.6 COMPLEMENT is the strong part: +25.2% (n=68,
  t +2.76, tc +2.79, win 60%). The pre-registered gate cut in exactly the
  wrong direction on fresh tickers. After a 164-cell mining phase these
  post-hoc reads carry no confirmatory weight; they are listed to document
  that the gate, not the underlying breakout effect, is what failed.
- close-confirm + boxh<0.6 + VIX<18: +1.3% (n=76, t +0.32, tc +0.97).
- Liquidity attrition is the fresh cohort's dominant feature: 1,897
  close-confirm entries collapsed to 183 boxes with both W1 ATM legs printing
  within 5 min (~10% fill-through vs ~40% on the burned mega-cap cohorts;
  boxes per ticker range 5 (CAT) to 43 (WMT)). The strategy as specified
  needs mega-cap-tech-grade weekly-option tape to even fill.

## Honest bottom line

- **No config passed the pre-registered bar.** The primary missed all three
  criteria — narrowly (mean +3.7% vs +4%, tc 1.58 vs 2.0, 5/10 vs 6/10
  tickers) — and the runner-up failed outright with a negative mean.
- The box-height gate that looked consistent across both burned cohorts
  (10 of 10 gated comparisons better in-sample) inverted on fresh tickers
  (gated −2.2% vs complement +25.2% on the poke entry). That is the signature
  of a mined conditioning variable, and it means the in-sample "consistency
  across cohorts" standard was still not strict enough — both cohorts had
  been read many times before this search.
- What remains defensible after this exercise: the underlying-keyed straddle
  exit on live-knowable breakout entries has shown a positive mean on every
  cohort tried (burned: +4.0% to +9.4%; fresh ungated: +3.7% to +13.2%), but
  its clustering-adjusted significance on genuinely fresh data is ≤1.7 ungated
  and the per-ticker breadth (5/10) is coin-flip-like. Measured, not proven.
- **Recommended live config: none.** Do not trade this sizing signal as an
  edge claim. If Pedro wants to keep a research position open, the only cell
  with a pre-registerable future is close-confirm UNGATED (drop the box-height
  gate), and the honest next test is a forward paper-trade or a new calendar
  window (e.g. data before 2024-07 via quote-based history), not another
  ticker cohort from the same 24 months.
- Publication guidance: the existing page/cheatsheet headline (+8.3%/trade
  family) still reflects pre-audit mechanics; this search does not rescue it.
  Pull or caveat per the BIAS_REVIEW recommendation.

**Final cell count: 164 mined cells (Phase 1) + 2 pre-registered + 8 labeled
exploratory fresh-cohort reads.**
