"""
SPX Multi-Day Golden Gate -- Day-of-Week Conditioning
=====================================================

Saty "Multiday mode": ATR levels are built from the WEEKLY 14-period Wilder ATR
and the PRIOR WEEK's close (PWC). The Golden Gate is the zone

    open  (38.2%)  ->  complete (61.8%)

of one weekly ATR away from PWC, in either direction. Continuation levels are
the 78.6% and 100% (full weekly ATR) marks beyond the gate.

Questions answered
------------------
1. For each week, on WHICH DAY OF THE WEEK does the weekly GG first OPEN
   (price reaches +/-38.2% of weekly ATR), and how does the chance the gate
   later COMPLETES (reaches +/-61.8% in the SAME week) evolve with that
   open-day?
2. Is the picture SYMMETRIC for the upside gate vs the downside gate?
3. CONTINUATION: once a gate completes, how often does it push on to 78.6%
   and a full weekly ATR (100%) within the same week?

Method
------
- Resample SPX daily bars into weekly (W-FRI) OHLC.
- Weekly Wilder ATR(14), lagged one week; PWC = prior weekly close.  These
  define the levels that apply to every daily bar of the *current* week.
- For each (week, direction):
    * open_dow      = weekday of the first daily bar whose high/low reaches
                      the +/-38.2% level (Mon..Fri).
    * completes     = a later-or-same daily bar reaches the +/-61.8% level
                      within that same week.
    * cont_786/100  = after completion, price reaches +/-78.6% / +/-100%.
  Each direction is evaluated independently, so a single week can contribute
  one upside event and/or one downside event.

Data: FirstRateData SPX index daily (2000-11 -> 2026-05).
Levels use prior-week close + one-week-lagged weekly Wilder ATR(14), matching
the day-mode lag convention used elsewhere in this repo.
Timezone note: SPX daily bars are date-stamped; no intraday clock involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one, atr_series

BASE_DIR = Path(__file__).resolve().parent
OUT_CSV = BASE_DIR / "analyst" / "spx_multiday_gg_dow_events.csv"
OUT_JSON = BASE_DIR / "analyst" / "spx_multiday_gg_dow_summary.json"
OUT_SITE = BASE_DIR / "site" / "data" / "spx-multiday-gg-dow.json"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]
FIBS = {"0382": 0.382, "0618": 0.618, "0786": 0.786, "100": 1.000, "trig": 0.236}


def build_weeks(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLC -> weekly (W-FRI) bars with lagged Wilder ATR(14) + PWC."""
    d = daily.set_index("timestamp").sort_index()
    wk = d.resample("W-FRI").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna(subset=["close"])
    wk["atr_14"] = atr_series(wk, 14).shift(1)   # prior-week-ending ATR
    wk["pwc"] = wk["close"].shift(1)             # prior week's close
    return wk


def analyze(daily: pd.DataFrame):
    d = daily.copy()
    d["week"] = d["timestamp"].dt.to_period("W-FRI")
    weeks = build_weeks(daily)
    # map weekly period -> (pwc, atr)
    wk_by_period = weeks.copy()
    wk_by_period.index = wk_by_period.index.to_period("W-FRI")

    records = []
    for period, g in d.groupby("week", sort=True):
        if period not in wk_by_period.index:
            continue
        w = wk_by_period.loc[period]
        pwc, atr = w["pwc"], w["atr_14"]
        if pd.isna(pwc) or pd.isna(atr) or atr <= 0:
            continue
        g = g.sort_values("timestamp")
        days = g["timestamp"].dt.weekday.tolist()  # 0=Mon
        highs = g["high"].to_numpy()
        lows = g["low"].to_numpy()
        n = len(g)

        for direction in ("up", "down"):
            if direction == "up":
                lvl = {k: pwc + f * atr for k, f in FIBS.items()}
                open_hits = highs >= lvl["0382"]
            else:
                lvl = {k: pwc - f * atr for k, f in FIBS.items()}
                open_hits = lows <= lvl["0382"]

            if not open_hits.any():
                continue
            oi = int(np.argmax(open_hits))  # first day index that opens
            open_dow = days[oi]
            if open_dow > 4:   # ignore weekend-stamped anomalies
                continue
            remaining = n - oi  # sessions from open day to week end (inclusive)

            if direction == "up":
                comp_hits = highs[oi:] >= lvl["0618"]
            else:
                comp_hits = lows[oi:] <= lvl["0618"]
            completes = bool(comp_hits.any())
            comp_dow = days[oi + int(np.argmax(comp_hits))] if completes else None
            same_day_complete = bool(completes and comp_dow == open_dow and int(np.argmax(comp_hits)) == 0)
            days_to_complete = int(np.argmax(comp_hits)) if completes else None

            # Continuation, measured from the completion day forward.
            cont_786 = cont_100 = False
            if completes:
                ci = oi + int(np.argmax(comp_hits))
                if direction == "up":
                    cont_786 = bool((highs[ci:] >= lvl["0786"]).any())
                    cont_100 = bool((highs[ci:] >= lvl["100"]).any())
                else:
                    cont_786 = bool((lows[ci:] <= lvl["0786"]).any())
                    cont_100 = bool((lows[ci:] <= lvl["100"]).any())

            records.append({
                "week_end": str(period.end_time.date()),
                "direction": direction,
                "open_dow": open_dow,
                "open_dow_name": DOW_NAMES[open_dow],
                "remaining_sessions": remaining,
                "completes": completes,
                "same_day_complete": same_day_complete,
                "comp_dow": comp_dow,
                "comp_dow_name": DOW_NAMES[comp_dow] if comp_dow is not None else None,
                "days_to_complete": days_to_complete,
                "cont_786": cont_786,
                "cont_100": cont_100,
                "atr_14": round(float(atr), 2),
                "pwc": round(float(pwc), 2),
            })

    return pd.DataFrame(records), len(weeks.dropna(subset=["pwc", "atr_14"]))


def rate(sub, col):
    return round(float(sub[col].mean()) * 100, 1) if len(sub) else None


def dow_table(ev):
    rows = []
    for dow in range(5):
        sub = ev[ev["open_dow"] == dow]
        if len(sub) == 0:
            continue
        comp = sub[sub["completes"]]
        rows.append({
            "dow": dow,
            "dow_name": DOW_NAMES[dow],
            "n": int(len(sub)),
            "median_remaining": int(sub["remaining_sessions"].median()),
            "completes": rate(sub, "completes"),
            "same_day_complete": rate(sub, "same_day_complete"),
            # continuation is conditional on completion
            "cont_786_given_complete": round(float(comp["cont_786"].mean()) * 100, 1) if len(comp) else None,
            "cont_100_given_complete": round(float(comp["cont_100"].mean()) * 100, 1) if len(comp) else None,
            "median_days_to_complete": (int(comp["days_to_complete"].median()) if len(comp) else None),
        })
    return rows


def overall(ev):
    comp = ev[ev["completes"]]
    return {
        "n": int(len(ev)),
        "completes": rate(ev, "completes"),
        "same_day_complete": rate(ev, "same_day_complete"),
        "cont_786_given_complete": round(float(comp["cont_786"].mean()) * 100, 1) if len(comp) else None,
        "cont_100_given_complete": round(float(comp["cont_100"].mean()) * 100, 1) if len(comp) else None,
    }


def main():
    print("Loading FirstRateData SPX daily ...", flush=True)
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)
    ev, n_weeks = analyze(daily)
    ev.to_csv(OUT_CSV, index=False)

    up = ev[ev["direction"] == "up"].copy()
    dn = ev[ev["direction"] == "down"].copy()

    # how often does each gate open in a week, and both / neither
    weeks_with_up = up["week_end"].nunique()
    weeks_with_dn = dn["week_end"].nunique()
    weeks_both = len(set(up["week_end"]) & set(dn["week_end"]))

    payload = {
        "meta": {
            "ticker": "SPX",
            "mode": "Multiday (weekly ATR)",
            "source": "FirstRateData SPX index daily",
            "date_start": str(daily["timestamp"].min().date()),
            "date_end": str(daily["timestamp"].max().date()),
            "n_weeks": int(n_weeks),
            "weeks_up_gate_opens": int(weeks_with_up),
            "weeks_dn_gate_opens": int(weeks_with_dn),
            "weeks_both_open": int(weeks_both),
        },
        "up": {"overall": overall(up), "by_dow": dow_table(up)},
        "down": {"overall": overall(dn), "by_dow": dow_table(dn)},
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    OUT_SITE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SITE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    m = payload["meta"]
    print(f"\nWeeks analyzed: {m['n_weeks']:,}  ({m['date_start']} -> {m['date_end']})")
    print(f"Upside gate opens in {m['weeks_up_gate_opens']:,} weeks "
          f"({m['weeks_up_gate_opens']/m['n_weeks']*100:.1f}%); "
          f"downside in {m['weeks_dn_gate_opens']:,} ({m['weeks_dn_gate_opens']/m['n_weeks']*100:.1f}%); "
          f"both in {m['weeks_both_open']:,} ({m['weeks_both_open']/m['n_weeks']*100:.1f}%).")

    for key, lbl in [("up", "UPSIDE gate (+38.2% -> +61.8%)"),
                     ("down", "DOWNSIDE gate (-38.2% -> -61.8%)")]:
        o = payload[key]["overall"]
        print(f"\n{'='*78}\n  {lbl}\n{'='*78}")
        print(f"  Events (gate opens): {o['n']:,}")
        print(f"  Overall completes 61.8% same week: {o['completes']}%   "
              f"(opens & completes same day: {o['same_day_complete']}%)")
        print(f"  Given completion -> continues to 78.6%: {o['cont_786_given_complete']}%   "
              f"to full ATR (100%): {o['cont_100_given_complete']}%")
        print(f"\n  By day-of-week the gate OPENS:")
        print(f"    {'DOW':<5}{'N':>6}{'medRem':>8}{'Complete':>10}{'SameDay':>9}"
              f"{'Cont786|c':>11}{'Cont100|c':>11}{'medD2C':>8}")
        for r in payload[key]["by_dow"]:
            flag = "*" if r["n"] < 50 else " "
            print(f"   {flag}{r['dow_name']:<4}{r['n']:>6}{r['median_remaining']:>8}"
                  f"{str(r['completes'])+'%':>10}{str(r['same_day_complete'])+'%':>9}"
                  f"{str(r['cont_786_given_complete'])+'%':>11}"
                  f"{str(r['cont_100_given_complete'])+'%':>11}"
                  f"{str(r['median_days_to_complete']):>8}")
        print("   * n < 50;  medRem = median sessions left in week incl. open day;  "
              "Cont*|c = continuation given completion;  medD2C = median sessions open->complete")

    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
