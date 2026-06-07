"""
SPX Swing Golden Gate -- Downside-Completion PREDICTORS
=======================================================

Extension of backtest_swing_gg_wom.py. Sibling: [[project_swing_gg_wom]].

QUESTION
--------
The base study showed the DOWNSIDE swing gate (PMC -38.2% -> -61.8% of one
monthly ATR) opens in 139 months and COMPLETES (-61.8% same month) 63.3% of
the time. Do any of these conditions -- measured AT THE MOMENT the gate opens,
using only information available then -- raise that completion rate?

  1. SPEED   days from the put-trigger (-23.6%) first touch to the gate open
             (-38.2%), within the month. 0 = same-day/gap, 1 = one-day
             traversal, etc. A fast traversal = momentum.
  2. dEMA21  slope of the DAILY 21-EMA (rising / falling), from the bar BEFORE
             the open day.
  3. dPX     close vs the DAILY 21-EMA (above / below), prior bar.
  4. dPO     DAILY phase-oscillator position (zone) and slope, prior bar.
  5. wEMA21  slope of the WEEKLY 21-EMA, last fully-completed week.
  6. wPO     WEEKLY phase-oscillator position and slope, last completed week.

LOOK-AHEAD DISCIPLINE
---------------------
The gate opens intraday on day `oi` (low <= -38.2%). A trader entering at the
gate knows only the *previous* completed daily bar and the *last completed*
weekly bar. So every daily indicator is read at `oi-1` (the prior daily close)
and every weekly indicator from the latest weekly bar ENDING STRICTLY BEFORE
the open date. SPEED is known at the open itself.

n = 139 downside events -> only coarse 2-4 bucket splits are meaningful.
Upside (177 events) is computed too, as a mirror, but downside is the headline.

Outputs
-------
- analyst/swing_gg_wom_predictors_events.csv   (events + predictor columns)
- analyst/swing_gg_wom_predictors_summary.json (conditioned completion tables)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one, atr_series
from backtest_swing_gg_wom import build_months, FIBS, week_of_month, WOM_NAMES, HORIZON_DAYS
from indicators import ema, compute_phase_oscillator

BASE_DIR = Path(__file__).resolve().parent
OUT_CSV = BASE_DIR / "analyst" / "swing_gg_wom_predictors_events.csv"
OUT_JSON = BASE_DIR / "analyst" / "swing_gg_wom_predictors_summary.json"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------
# Indicator series (computed once on the full history, then read at oi-1 / last
# completed week so there is no look-ahead).
# ----------------------------------------------------------------------------
def daily_indicators(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily 21-EMA (+ slope) and phase oscillator (+ slope), indexed by date."""
    d = daily.set_index("timestamp").sort_index().copy()
    d["ema21"] = ema(d["close"], 21)
    # slope over a 5-bar window, normalized to % of price per bar (robust sign)
    d["ema21_slope"] = (d["ema21"] - d["ema21"].shift(5)) / d["close"] / 5 * 100
    d = compute_phase_oscillator(d)  # adds phase_oscillator, phase_zone, ...
    d["po"] = d["phase_oscillator"]
    d["po_slope"] = d["po"] - d["po"].shift(1)
    return d[["close", "ema21", "ema21_slope", "po", "po_slope", "phase_zone"]]


def weekly_indicators(daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly (W-FRI) 21-EMA (+ slope) and phase oscillator (+ slope)."""
    d = daily.set_index("timestamp").sort_index()
    wk = d.resample("W-FRI").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    ).dropna(subset=["close"])
    wk["ema21"] = ema(wk["close"], 21)
    wk["ema21_slope"] = (wk["ema21"] - wk["ema21"].shift(1)) / wk["close"] * 100
    wk = compute_phase_oscillator(wk)
    wk["po"] = wk["phase_oscillator"]
    wk["po_slope"] = wk["po"] - wk["po"].shift(1)
    return wk[["close", "ema21", "ema21_slope", "po", "po_slope", "phase_zone"]]


def build_events(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per opened gate (both directions) + predictors read at the open."""
    d = daily.copy()
    d["month"] = d["timestamp"].dt.to_period("M")
    months = build_months(daily)
    mo_by_period = months.copy()
    mo_by_period.index = mo_by_period.index.to_period("M")

    di = daily_indicators(daily)
    wi = weekly_indicators(daily)
    di_dates = di.index.to_numpy()      # sorted daily dates
    wi_dates = wi.index.to_numpy()      # sorted weekly-end dates

    records = []
    for period, g in d.groupby("month", sort=True):
        if period not in mo_by_period.index:
            continue
        m = mo_by_period.loc[period]
        pmc, atr = m["pmc"], m["atr_14"]
        if pd.isna(pmc) or pd.isna(atr) or atr <= 0:
            continue
        g = g.sort_values("timestamp")
        ts = g["timestamp"].to_numpy()
        dom = g["timestamp"].dt.day.to_numpy()
        highs = g["high"].to_numpy()
        lows = g["low"].to_numpy()
        n = len(g)

        for direction in ("up", "down"):
            if direction == "up":
                lvl = {k: pmc + f * atr for k, f in FIBS.items()}
                open_hits = highs >= lvl["0382"]
                trig_hits = highs >= lvl["trig"]
                comp_side = lambda a: a >= lvl["0618"]
            else:
                lvl = {k: pmc - f * atr for k, f in FIBS.items()}
                open_hits = lows <= lvl["0382"]
                trig_hits = lows <= lvl["trig"]
                comp_side = lambda a: a <= lvl["0618"]

            if not open_hits.any():
                continue
            oi = int(np.argmax(open_hits))
            open_ts = ts[oi]
            open_wom = week_of_month(int(dom[oi]))
            remaining = n - oi   # sessions from open day to month end (incl.)

            # Completion (same-side 61.8% on open day or later)
            arr = highs[oi:] if direction == "up" else lows[oi:]
            comp_hits = comp_side(arr)
            completes = bool(comp_hits.any())
            comp_rel = int(np.argmax(comp_hits)) if completes else None

            # SPEED: sessions from first trigger touch to gate open (this month)
            if trig_hits[:oi + 1].any():
                ti = int(np.argmax(trig_hits[:oi + 1]))
                days_trig_to_open = oi - ti
            else:  # gate opened on a gap without touching trigger first
                days_trig_to_open = None

            # ---- Daily indicators at the PRIOR completed daily bar (oi-1) ----
            prior_pos = int(np.searchsorted(di_dates, open_ts, side="left")) - 1
            if prior_pos >= 0:
                dr = di.iloc[prior_pos]
                d_ema_slope = float(dr["ema21_slope"])
                d_px_vs_ema = float(dr["close"] - dr["ema21"])
                d_po = float(dr["po"])
                d_po_slope = float(dr["po_slope"])
                d_zone = str(dr["phase_zone"])
            else:
                d_ema_slope = d_px_vs_ema = d_po = d_po_slope = np.nan
                d_zone = None

            # ---- Weekly indicators at the last week ENDING before open ----
            wpos = int(np.searchsorted(wi_dates, open_ts, side="left")) - 1
            if wpos >= 0:
                wr = wi.iloc[wpos]
                w_ema_slope = float(wr["ema21_slope"])
                w_po = float(wr["po"])
                w_po_slope = float(wr["po_slope"])
                w_zone = str(wr["phase_zone"])
            else:
                w_ema_slope = w_po = w_po_slope = np.nan
                w_zone = None

            records.append({
                "month_end": str(period.end_time.date()),
                "direction": direction,
                "open_dom": int(dom[oi]),
                "open_wom": open_wom,
                "remaining_sessions": int(remaining),
                "clock_truncated": bool(remaining < HORIZON_DAYS),
                "completes": completes,
                "days_to_complete": comp_rel,
                "days_trig_to_open": days_trig_to_open,
                "d_ema21_slope": round(d_ema_slope, 4) if pd.notna(d_ema_slope) else None,
                "d_px_minus_ema21": round(d_px_vs_ema, 2) if pd.notna(d_px_vs_ema) else None,
                "d_po": round(d_po, 1) if pd.notna(d_po) else None,
                "d_po_slope": round(d_po_slope, 2) if pd.notna(d_po_slope) else None,
                "d_zone": d_zone,
                "w_ema21_slope": round(w_ema_slope, 4) if pd.notna(w_ema_slope) else None,
                "w_po": round(w_po, 1) if pd.notna(w_po) else None,
                "w_po_slope": round(w_po_slope, 2) if pd.notna(w_po_slope) else None,
                "w_zone": w_zone,
                "atr_14": round(float(atr), 2),
                "pmc": round(float(pmc), 2),
            })

    return pd.DataFrame(records)


# ----------------------------------------------------------------------------
# Conditioning / reporting
# ----------------------------------------------------------------------------
def cond_rate(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "completes": None}
    return {"n": int(n), "completes": round(float(sub["completes"].mean()) * 100, 1)}


def bucket_table(ev: pd.DataFrame, baseline: float, buckets: list) -> list:
    """buckets = [(label, mask_series), ...]; appends lift vs baseline."""
    rows = []
    for label, mask in buckets:
        sub = ev[mask]
        r = cond_rate(sub)
        r["label"] = label
        r["lift"] = (round(r["completes"] - baseline, 1)
                     if r["completes"] is not None else None)
        rows.append(r)
    return rows


def analyze_direction(ev: pd.DataFrame, direction: str) -> dict:
    e = ev[ev["direction"] == direction].copy()
    base = round(float(e["completes"].mean()) * 100, 1)
    n_all = len(e)

    tables = {}

    # 1. SPEED: trigger -> open
    sp = e[e["days_trig_to_open"].notna()]
    tables["speed_trig_to_open"] = bucket_table(sp, base, [
        ("0 (same-day / gap)", sp["days_trig_to_open"] == 0),
        ("1 day (one-day traversal)", sp["days_trig_to_open"] == 1),
        ("2-3 days", sp["days_trig_to_open"].between(2, 3)),
        ("4+ days (slow grind)", sp["days_trig_to_open"] >= 4),
    ])
    tables["speed_fast_vs_slow"] = bucket_table(sp, base, [
        ("<=1 day (fast)", sp["days_trig_to_open"] <= 1),
        (">=2 days (slow)", sp["days_trig_to_open"] >= 2),
    ])

    # 2. Daily 21-EMA slope (rising vs falling)
    de = e[e["d_ema21_slope"].notna()]
    tables["daily_ema21_slope"] = bucket_table(de, base, [
        ("falling (<0)", de["d_ema21_slope"] < 0),
        ("rising (>=0)", de["d_ema21_slope"] >= 0),
    ])

    # 3. Price vs daily 21-EMA
    dp = e[e["d_px_minus_ema21"].notna()]
    tables["daily_px_vs_ema21"] = bucket_table(dp, base, [
        ("below EMA", dp["d_px_minus_ema21"] < 0),
        ("above EMA", dp["d_px_minus_ema21"] >= 0),
    ])

    # 4. Daily phase oscillator position (sign) + slope (sign)
    dpo = e[e["d_po"].notna()]
    tables["daily_po_position"] = bucket_table(dpo, base, [
        ("PO < -61.8 (accum/extended-dn)", dpo["d_po"] < -61.8),
        ("PO -61.8..0 (neutral-dn)", dpo["d_po"].between(-61.8, 0, inclusive="left")),
        ("PO 0..61.8 (neutral-up)", dpo["d_po"].between(0, 61.8, inclusive="left")),
        ("PO >= 61.8 (distrib/extended-up)", dpo["d_po"] >= 61.8),
    ])
    dps = e[e["d_po_slope"].notna()]
    tables["daily_po_slope"] = bucket_table(dps, base, [
        ("PO falling (<0)", dps["d_po_slope"] < 0),
        ("PO rising (>=0)", dps["d_po_slope"] >= 0),
    ])

    # 5. Weekly 21-EMA slope
    we = e[e["w_ema21_slope"].notna()]
    tables["weekly_ema21_slope"] = bucket_table(we, base, [
        ("falling (<0)", we["w_ema21_slope"] < 0),
        ("rising (>=0)", we["w_ema21_slope"] >= 0),
    ])

    # 6. Weekly phase oscillator position + slope
    wpo = e[e["w_po"].notna()]
    tables["weekly_po_position"] = bucket_table(wpo, base, [
        ("PO < -61.8 (accum/extended-dn)", wpo["w_po"] < -61.8),
        ("PO -61.8..0 (neutral-dn)", wpo["w_po"].between(-61.8, 0, inclusive="left")),
        ("PO 0..61.8 (neutral-up)", wpo["w_po"].between(0, 61.8, inclusive="left")),
        ("PO >= 61.8 (distrib/extended-up)", wpo["w_po"] >= 61.8),
    ])
    wps = e[e["w_po_slope"].notna()]
    tables["weekly_po_slope"] = bucket_table(wps, base, [
        ("PO falling (<0)", wps["w_po_slope"] < 0),
        ("PO rising (>=0)", wps["w_po_slope"] >= 0),
    ])

    return {"n": n_all, "baseline_completes": base, "tables": tables}


def print_dir(title: str, res: dict):
    print(f"\n{'='*82}\n  {title}   (n={res['n']}, baseline completes = {res['baseline_completes']}%)\n{'='*82}")
    for key, rows in res["tables"].items():
        print(f"\n  {key}")
        print(f"    {'bucket':<36}{'N':>5}{'Complete':>10}{'Lift':>8}")
        for r in rows:
            flag = "*" if r["n"] < 25 else " "
            comp = f"{r['completes']}%" if r["completes"] is not None else "--"
            lift = f"{r['lift']:+}" if r["lift"] is not None else "--"
            print(f"   {flag}{r['label']:<35}{r['n']:>5}{comp:>10}{lift:>8}")
    print("\n   * n < 25 -- treat as anecdotal.")


def main():
    print("Loading FirstRateData SPX daily ...", flush=True)
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)
    ev_all = build_events(daily)
    ev_all.to_csv(OUT_CSV, index=False)   # full set (incl. clock_truncated flag)

    # Match the parent study: exclude clock-truncated gates (opened with fewer
    # than HORIZON_DAYS sessions left in the month) so their calendar-forced
    # non-completion does not bias the conditioned rates.
    ev = ev_all[~ev_all["clock_truncated"]].copy()
    excl_dn = int((ev_all["clock_truncated"] & (ev_all["direction"] == "down")).sum())
    excl_up = int((ev_all["clock_truncated"] & (ev_all["direction"] == "up")).sum())

    down = analyze_direction(ev, "down")
    up = analyze_direction(ev, "up")

    payload = {
        "meta": {
            "ticker": "SPX",
            "mode": "Swing (monthly ATR)",
            "source": "FirstRateData SPX index daily",
            "date_start": str(daily["timestamp"].min().date()),
            "date_end": str(daily["timestamp"].max().date()),
            "horizon_days": HORIZON_DAYS,
            "excluded_clock_truncated_up": excl_up,
            "excluded_clock_truncated_dn": excl_dn,
            "lookahead_note": ("daily indicators read at oi-1 (prior daily close); "
                               "weekly indicators from last weekly bar ending before open; "
                               "speed known at open. Clock-truncated opens "
                               "(< horizon_days sessions left in month) excluded."),
        },
        "down": down,
        "up": up,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print_dir("DOWNSIDE gate completion predictors", down)
    print_dir("UPSIDE gate completion predictors (mirror)", up)
    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
