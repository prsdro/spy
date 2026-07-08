# Hourly PO Compression → Options Study (AMZN, NVDA, MSFT)

Started 2026-07-07 (evening CT). Data pull runs detached via
`setsid nohup python3 /root/spy/fetch_po_comp_options.py` (log: `pull.log`,
progress: `state.json`, launcher stdout: `../po_comp_options_nohup.out`).
**Resumable**: just rerun the script — every phase checkpoints and skips done work.

## Question (Pedro's framing)

Using the most recent 12 months (2025-07-07 → 2026-07-06) of AMZN/NVDA/MSFT,
find hourly-candle Saty Phase Oscillator compression episodes, then use real
historical option prices to answer:

1. **Direction rule**: daily 21 EMA slope vs hourly PO slope — which picks long/short better?
2. **Entry spot**: near the hourly 9-21 ribbon during compression vs after expansion is confirmed?
3. **Expiry**: 1 week / 2 weeks / 1 month out?
4. **Strike**: ATM vs 0.5×dATR vs 1.0×dATR OTM?
5. **Exit**: TP1/TP2 on premium (e.g. +50%/+80%), hold-to-expiry, stops?

## Decisions confirmed by Pedro (AskUserQuestion, 2026-07-07)

- **Vehicle**: long premium AND credit side (sell the opposite-side option).
  Credit side needs no extra data — same contracts, mirrored P&L from trade prints.
- **TP semantics**: test ALL interpretations — (a) % premium gain with scale-out
  (half at TP1, rest at TP2), (b) % premium gain all-out single exit,
  (c) underlying-based targets (ATR levels / fib extensions).
- **Stops**: small grid — none (defined risk), premium −50%, underlying
  invalidation (hourly close back through opposite side of 9-21 ribbon).
- **Pull size**: full grid — 3 expiries (W1/W2/M1 ≈ 7/14/28d, Friday-snapped)
  × 5 strike offsets ({0, ±0.5, ±1.0}×daily ATR14, snapped to real strikes)
  × calls & puts.

## Defaults I set (flag if wrong)

- TV-style RTH-only hourly bars, anchored 09:30 ET (7 bars/day, last is 30 min).
- Compression = Pine-spec `po_compression` from `/root/spy/indicators.py`
  (BB(21,2) width inside 2×ATR14 envelope with expansion-release logic).
- Event = compression episode START bar (first bar where po_compression flips 1).
  Episode end = first later bar with po_compression 0 (expansion-confirm entry variant).
- Daily ATR14 = Wilder RMA on RTH daily bars derived from 5m (NOT vendor daily,
  per known split-anomaly issue), as of prior completed day.
- Option fills from minute trade prints (free tier has NO bid/ask, NO greeks/IV/OI).
  Illiquid strike-days may be empty — report drop counts in analysis.
- Expiry = Friday; holiday Fridays fall back to Thursday (e.g. Good Friday 2026-04-03).
- Splits checked: only NVDA 10:1 on 2024-06-10, before window. Strikes clean.

## Sample size (measured)

Hourly compression is COMMON: 22-30% of all hourly bars. Episodes in window:
AMZN 57, NVDA 50, MSFT 54 through 2026-05-07 local data (~190 expected with
the 2-month API top-up). Contract grid ≈ 190 × 3 expiries × ~5 strikes × 2 types,
deduped ≈ 3,000-4,500 unique contracts ≈ 10-15 h at free-tier 5 req/min.
Pull is priority-ordered (W1/W2 ATM-ish first, M1 far-OTM last) so partial
data is analyzable early.

## Files

- `underlying_5m_topup.parquet` — 5m bars 2026-05-06 → 2026-07-06 (API top-up)
- `events.csv` — one row per compression episode w/ all entry-time features
  (spot, dATR, hourly ema9/21, PO + slopes, phase zone, daily ema21 + slopes)
- `chains/{TKR}_{EXPIRY}.json` — cached strike lists
- `contracts_todo.json` — unique contract pull list w/ priority
- `option_bars.sqlite` — `contracts` (meta+status: ok/empty/not_authorized) and
  `bars` (minute aggs: t ms-UTC, o/h/l/c/v/vw/n)
- `state.json` — machine-readable progress; `pull.log` — full log

## Plan upgrade mid-pull (2026-07-07 ~17:50 CT)

Pedro upgraded the Massive key to paid mid-pull. REQ_SPACING dropped 12.4s → 0.15s
and the pull relaunched (resumed at contract ~140). Snapshots (greeks/IV/OI,
current chains only) now authorized; quotes/trades still not; 2yr history cap remains.

## Sanity check (2026-07-07 ~17:40 CT, first 13 contracts)

PASS: every tested event had an option print at the entry minute (lag 0-1 min,
150-300 prints/day); ATM weekly premiums 0.7-1.6% of spot = plausible; 13/13 ok.

**CRITICAL for analysis**: `events.csv` `start_ts_et`/`end_ts_et` are hourly
bar-OPEN labels (resample left edge). The signal is known at bar CLOSE →
entry time = label + 60 min (+30 min for the 15:30 bar). Same for the
expansion-confirm bar. Do NOT price entries at the label timestamp (lookahead).

## Session definition: RTH vs ETH (2026-07-07 ~19:45 CT)

Pedro charts ETH ("open to changing my mind for hourly swings if the data
speaks") → A/B both definitions in the v3 rerun. Measured divergence (v1
tickers, 12mo): ETH yields ~2.6× more episodes (157-169/ticker vs 60-63),
53-59% START overnight; ~85% of RTH episode days are matched by an ETH episode.
ETH = TV extended-hours stock chart: on-the-hour bars 04:00-19:55
(`hourly_and_daily(session='ETH')` / PO_SESSION env). Daily ATR stays RTH.
events_v2_eth.csv pulled via lean grid (W1/W2, offsets 0/±0.5).
**Analysis-layer TODO for ETH events**: overnight signals fill at next 09:30
open (extend entry_fill with carry-to-open); ETH bar close = label+60min flat
(no 15:30 special case); expiry anchoring per Codex fix = entry date not
episode start for delayed entries.

## v3 rerun queue (all data in DB after ETH pull)

1. Codex fixes: entry-anchored expiries (supplemental todo from bilbo retest
   timestamps), contract-dedup in pooled stats, fill-lag sensitivity,
   3-way baselines (non-compression / compression-bar / all-random).
2. Bilbo pipeline on events_v2 (RTH) and events_v2_eth (ETH), 8 tickers ×
   24mo: confirm mature-box retest cell + down-break puts out-of-sample.
3. Carry timer: short ATM W1 premium, all times vs ex-compression (both
   session definitions), plus credit-spread variant (sell ATM buy 1-ATR wing).
4. Overnight-coil class (new, ETH-only): episodes starting 16:00-09:30 →
   gap-open breakout behavior at 09:30 — untested territory, may be its own
   study section.

## Next steps (after pull completes)

1. Analysis script: per event × direction-rule × entry-rule × expiry × strike ×
   exit-rule grid; long premium + short-opposite-side. Entry price = last trade
   print at/before entry ts (fallback window forward ~30 min; drop if none).
2. Careful about: multiplicity (this is a mined grid — report t-stats and
   holdout by ticker), overlapping episodes (same-week events share contracts,
   returns correlated), truncated outcomes for June-2026 events with M1 expiries.
3. Report times in **Central Time** for Pedro. Save results to this dir +
   site/data if published.

## How to check progress (future session)

```bash
cat /root/spy/analyst/po_comp_options/state.json
tail -20 /root/spy/analyst/po_comp_options/pull.log
pgrep -af fetch_po_comp_options.py   # is it still running?
sqlite3 /root/spy/analyst/po_comp_options/option_bars.sqlite \
  "SELECT status, count(*), sum(nbars) FROM contracts GROUP BY status"
# if dead before COMPLETE: setsid nohup python3 /root/spy/fetch_po_comp_options.py \
#   >> /root/spy/analyst/po_comp_options_nohup.out 2>&1 < /dev/null &
```
