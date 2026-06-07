"""
SPX Swing Golden Gate -- Week-of-Month + Trigger/Pivot Retracement Study
=======================================================================

Saty "Swing mode": ATR levels are built from the MONTHLY 14-period Wilder ATR
and the PRIOR MONTH's close (PMC). The Golden Gate is the zone

    open  (38.2%)  ->  complete (61.8%)

of one monthly ATR away from PMC, in either direction. Continuation levels are
the 78.6% and 100% (full monthly ATR) marks beyond the gate. The "trigger" is
+/-23.6% (call trigger above, put trigger below) and the "monthly pivot" is the
0-ATR line == the prior month's close itself.

Two questions
-------------
A. WEEK-OF-MONTH OPEN. For each calendar month, on which WEEK of the month does
   the swing GG first OPEN (price reaches +/-38.2% of the monthly ATR)? Buckets
   are week 1 (days 1-7), 2 (8-14), 3 (15-21), 4 (22-28), 5 (29-31). How does
   the chance the gate later COMPLETES (reaches +/-61.8% in the SAME month)
   evolve with the open-week? Is the upside gate symmetric to the downside gate?
   Once completed, how often does it continue to 78.6% and a full ATR (100%)?

B. TRIGGER / PIVOT RETRACEMENT ("invalidation or entry?"). Once a gate OPENS,
   price often bounces back toward the pivot before (maybe) completing. For each
   opened gate we find how FAR back it retraced before completion (or month end):
     - none      : never bounced back to the same-side trigger
     - trigger   : bounced to the same-side trigger (+/-23.6%) but not the pivot
     - pivot     : bounced all the way to the monthly pivot (0 line == PMC)
     - opposite  : crossed the pivot and reached the OPPOSITE trigger (+/-23.6%)
   For each retrace depth we report the completion rate of the gate. If deep
   retraces still complete at a high rate, the pullback is a "good entry"; if
   completion collapses, the retrace "invalidates" the gate.
   (Downside gate -> the relevant trigger is the PUT trigger; upside gate -> the
   CALL trigger, per the request.)

Method
------
- FirstRateData SPX index daily bars (2000-11 -> 2026-05).
- Resample to calendar-month OHLC; monthly Wilder ATR(14) lagged one month;
  PMC = prior month's close. These levels apply to every daily bar of the
  *current* month.
- Each direction (up/down) is evaluated independently, so one month can
  contribute an upside event and/or a downside event.
- Daily bars only: within a single day the order of a high vs a low is unknown.
  This is rare at monthly scale; we resolve completion at day granularity and
  flag same-day open+complete events (no retrace window).

Outputs
-------
- analyst/swing_gg_wom_events.csv     (one row per opened gate)
- analyst/swing_gg_wom_summary.json   (full tables)
- site/data/swing-gg-wom.json         (compact, for a viz page)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one, atr_series

BASE_DIR = Path(__file__).resolve().parent
OUT_CSV = BASE_DIR / "analyst" / "swing_gg_wom_events.csv"
OUT_JSON = BASE_DIR / "analyst" / "swing_gg_wom_summary.json"
OUT_SITE = BASE_DIR / "site" / "data" / "swing-gg-wom.json"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

WOM_NAMES = {1: "Week 1", 2: "Week 2", 3: "Week 3", 4: "Week 4", 5: "Week 5"}
FIBS = {"trig": 0.236, "0382": 0.382, "0618": 0.618, "0786": 0.786, "100": 1.000}

# Completion horizon, and the minimum in-month window a gate must have to be
# counted in the findings. A gate that opens with fewer than this many trading
# sessions left in its month cannot fairly reach 61.8% before the monthly level
# resets, so its non-completion is a calendar artifact, not a failed setup —
# such "clock-truncated" gates are excluded from all reported rates.
HORIZON_DAYS = 5


def week_of_month(day: int) -> int:
    """Calendar week-of-month from day number: 1-7 -> 1, ... 29-31 -> 5."""
    return (day - 1) // 7 + 1


def build_months(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLC -> calendar-month bars with lagged Wilder ATR(14) + PMC."""
    d = daily.set_index("timestamp").sort_index()
    mo = d.resample("ME").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna(subset=["close"])
    mo["atr_14"] = atr_series(mo, 14).shift(1)   # prior-month-ending ATR
    mo["pmc"] = mo["close"].shift(1)             # prior month's close
    return mo


def analyze(daily: pd.DataFrame):
    d = daily.copy().sort_values("timestamp").reset_index(drop=True)
    d["month"] = d["timestamp"].dt.to_period("M")
    months = build_months(daily)
    mo_by_period = months.copy()
    mo_by_period.index = mo_by_period.index.to_period("M")

    # Global trading-session arrays, so a fixed N-session forward window can run
    # past month-end (the price level stays fixed at the opening month's level).
    g_high = d["high"].to_numpy()
    g_low = d["low"].to_numpy()
    N_GLOBAL = len(d)
    HORIZON = HORIZON_DAYS  # "within 5 trading days": the open session + the next four.

    records = []
    for period, g in d.groupby("month", sort=True):
        if period not in mo_by_period.index:
            continue
        m = mo_by_period.loc[period]
        pmc, atr = m["pmc"], m["atr_14"]
        if pd.isna(pmc) or pd.isna(atr) or atr <= 0:
            continue
        g = g.sort_values("timestamp")
        gpos = g.index.to_numpy()            # global session positions of this month's bars
        dom = g["timestamp"].dt.day.to_numpy()
        highs = g["high"].to_numpy()
        lows = g["low"].to_numpy()
        n = len(g)

        for direction in ("up", "down"):
            if direction == "up":
                lvl = {k: pmc + f * atr for k, f in FIBS.items()}
                opp_trig = pmc - FIBS["trig"] * atr
                open_hits = highs >= lvl["0382"]
            else:
                lvl = {k: pmc - f * atr for k, f in FIBS.items()}
                opp_trig = pmc + FIBS["trig"] * atr
                open_hits = lows <= lvl["0382"]

            if not open_hits.any():
                continue
            oi = int(np.argmax(open_hits))      # first day the gate opens
            open_wom = week_of_month(int(dom[oi]))
            remaining = n - oi                  # sessions from open day to month end (incl.)

            # Completion: same-side 61.8% reached on open day or later.
            if direction == "up":
                comp_hits = highs[oi:] >= lvl["0618"]
            else:
                comp_hits = lows[oi:] <= lvl["0618"]
            completes = bool(comp_hits.any())
            comp_rel = int(np.argmax(comp_hits)) if completes else None
            days_to_complete = comp_rel

            # Completes within 5 trading sessions of the open (global window,
            # may cross month-end; the +/-61.8% price level is fixed at this
            # month's level). Open session counts as day 1.
            gi = int(gpos[oi])
            end5 = min(gi + HORIZON, N_GLOBAL)
            if direction == "up":
                complete_5d = bool((g_high[gi:end5] >= lvl["0618"]).any())
            else:
                complete_5d = bool((g_low[gi:end5] <= lvl["0618"]).any())

            # Continuation, from completion day forward.
            cont_786 = cont_100 = False
            if completes:
                ci = oi + comp_rel
                if direction == "up":
                    cont_786 = bool((highs[ci:] >= lvl["0786"]).any())
                    cont_100 = bool((highs[ci:] >= lvl["100"]).any())
                else:
                    cont_786 = bool((lows[ci:] <= lvl["0786"]).any())
                    cont_100 = bool((lows[ci:] <= lvl["100"]).any())

            # --- Retracement depth before completion (or month end) ---
            # Window: open day .. (day before completion). If completion is on
            # the open day there is no retrace window.
            if completes and comp_rel == 0:
                retrace = "same_day_complete"
            else:
                end_rel = (oi + comp_rel) if completes else n   # exclusive of comp day
                if direction == "up":
                    # bounce DOWN toward pivot: lowest low in window
                    extreme = lows[oi:end_rel].min()
                    reach_trig = extreme <= lvl["trig"]      # back to +23.6%
                    reach_pivot = extreme <= pmc             # back to 0 line
                    reach_opp = extreme <= opp_trig          # to -23.6%
                else:
                    # bounce UP toward pivot: highest high in window
                    extreme = highs[oi:end_rel].max()
                    reach_trig = extreme >= lvl["trig"]      # back to -23.6%
                    reach_pivot = extreme >= pmc             # back to 0 line
                    reach_opp = extreme >= opp_trig          # to +23.6%
                if reach_opp:
                    retrace = "opposite"
                elif reach_pivot:
                    retrace = "pivot"
                elif reach_trig:
                    retrace = "trigger"
                else:
                    retrace = "none"

            records.append({
                "month_end": str(period.end_time.date()),
                "direction": direction,
                "open_dom": int(dom[oi]),
                "open_wom": open_wom,
                "open_wom_name": WOM_NAMES[open_wom],
                "remaining_sessions": int(remaining),
                "clock_truncated": bool(remaining < HORIZON),
                "completes": completes,
                "complete_5d": complete_5d,
                "days_to_complete": days_to_complete,
                "cont_786": cont_786,
                "cont_100": cont_100,
                "retrace": retrace,
                "atr_14": round(float(atr), 2),
                "pmc": round(float(pmc), 2),
            })

    return pd.DataFrame(records), int(len(months.dropna(subset=["pmc", "atr_14"])))


def rate(sub, col):
    return round(float(sub[col].mean()) * 100, 1) if len(sub) else None


def wom_table(ev):
    rows = []
    for wom in range(1, 6):
        sub = ev[ev["open_wom"] == wom]
        if len(sub) == 0:
            continue
        comp = sub[sub["completes"]]
        rows.append({
            "wom": wom,
            "wom_name": WOM_NAMES[wom],
            "n": int(len(sub)),
            "median_remaining": int(sub["remaining_sessions"].median()),
            "completes": rate(sub, "completes"),
            "complete_5d": rate(sub, "complete_5d"),
            "cont_786_given_complete": round(float(comp["cont_786"].mean()) * 100, 1) if len(comp) else None,
            "cont_100_given_complete": round(float(comp["cont_100"].mean()) * 100, 1) if len(comp) else None,
            "median_days_to_complete": (int(comp["days_to_complete"].median()) if len(comp) else None),
        })
    return rows


def retrace_table(ev):
    order = ["none", "trigger", "pivot", "opposite", "same_day_complete"]
    labels = {
        "none": "No bounce to trigger",
        "trigger": "Bounced to trigger (23.6%)",
        "pivot": "Bounced to pivot (0 line)",
        "opposite": "Crossed to opposite trigger",
        "same_day_complete": "Completed same day (no window)",
    }
    rows = []
    for key in order:
        sub = ev[ev["retrace"] == key]
        if len(sub) == 0:
            continue
        rows.append({
            "retrace": key,
            "label": labels[key],
            "n": int(len(sub)),
            "share": round(len(sub) / len(ev) * 100, 1),
            "completes": rate(sub, "completes"),
        })
    return rows


def overall(ev):
    comp = ev[ev["completes"]]
    return {
        "n": int(len(ev)),
        "completes": rate(ev, "completes"),
        "complete_5d": rate(ev, "complete_5d"),
        "cont_786_given_complete": round(float(comp["cont_786"].mean()) * 100, 1) if len(comp) else None,
        "cont_100_given_complete": round(float(comp["cont_100"].mean()) * 100, 1) if len(comp) else None,
    }


def main():
    print("Loading FirstRateData SPX daily ...", flush=True)
    daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)
    ev_all, n_months = analyze(daily)
    ev_all.to_csv(OUT_CSV, index=False)   # full set (incl. clock_truncated flag)

    # Exclude clock-truncated gates (opened with < HORIZON_DAYS sessions left in
    # the month) from all reported rates — their month ran out before a fair
    # completion window, so their non-completion is a calendar artifact.
    excl = ev_all[ev_all["clock_truncated"]]
    ev = ev_all[~ev_all["clock_truncated"]].copy()

    up = ev[ev["direction"] == "up"].copy()
    dn = ev[ev["direction"] == "down"].copy()
    excl_up = excl[excl["direction"] == "up"]
    excl_dn = excl[excl["direction"] == "down"]

    months_with_up = up["month_end"].nunique()
    months_with_dn = dn["month_end"].nunique()
    months_both = len(set(up["month_end"]) & set(dn["month_end"]))

    payload = {
        "meta": {
            "ticker": "SPX",
            "mode": "Swing (monthly ATR)",
            "source": "FirstRateData SPX index daily",
            "date_start": str(daily["timestamp"].min().date()),
            "date_end": str(daily["timestamp"].max().date()),
            "n_months": n_months,
            "horizon_days": HORIZON_DAYS,
            "months_up_gate_opens": int(months_with_up),
            "months_dn_gate_opens": int(months_with_dn),
            "months_both_open": int(months_both),
            "excluded_clock_truncated_up": int(len(excl_up)),
            "excluded_clock_truncated_dn": int(len(excl_dn)),
        },
        "up": {
            "overall": overall(up),
            "by_wom": wom_table(up),
            "retrace": retrace_table(up),
        },
        "down": {
            "overall": overall(dn),
            "by_wom": wom_table(dn),
            "retrace": retrace_table(dn),
        },
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    OUT_SITE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SITE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    m = payload["meta"]
    print(f"\nMonths analyzed: {m['n_months']:,}  ({m['date_start']} -> {m['date_end']})")
    print(f"Upside gate opens in {m['months_up_gate_opens']:,} months "
          f"({m['months_up_gate_opens']/m['n_months']*100:.1f}%); "
          f"downside in {m['months_dn_gate_opens']:,} "
          f"({m['months_dn_gate_opens']/m['n_months']*100:.1f}%); "
          f"both in {m['months_both_open']:,} ({m['months_both_open']/m['n_months']*100:.1f}%).")

    for key, lbl, trig_name in [
        ("up", "UPSIDE gate (+38.2% -> +61.8%)", "call trigger"),
        ("down", "DOWNSIDE gate (-38.2% -> -61.8%)", "put trigger"),
    ]:
        o = payload[key]["overall"]
        print(f"\n{'='*80}\n  {lbl}\n{'='*80}")
        print(f"  Events (gate opens): {o['n']:,}")
        print(f"  Overall completes 61.8% same month: {o['completes']}%   "
              f"(completes within 5 trading days: {o['complete_5d']}%)")
        print(f"  Given completion -> continues to 78.6%: {o['cont_786_given_complete']}%   "
              f"to full ATR (100%): {o['cont_100_given_complete']}%")

        print(f"\n  By WEEK-OF-MONTH the gate OPENS:")
        print(f"    {'Week':<8}{'N':>6}{'medRem':>8}{'Complete':>10}{'<=5day':>9}"
              f"{'Cont786|c':>11}{'Cont100|c':>11}{'medD2C':>8}")
        for r in payload[key]["by_wom"]:
            flag = "*" if r["n"] < 50 else " "
            print(f"   {flag}{r['wom_name']:<7}{r['n']:>6}{r['median_remaining']:>8}"
                  f"{str(r['completes'])+'%':>10}{str(r['complete_5d'])+'%':>9}"
                  f"{str(r['cont_786_given_complete'])+'%':>11}"
                  f"{str(r['cont_100_given_complete'])+'%':>11}"
                  f"{str(r['median_days_to_complete']):>8}")

        print(f"\n  RETRACEMENT after open ({trig_name} / pivot) -> still completes?")
        print(f"    {'Depth':<32}{'N':>6}{'Share':>8}{'Completes':>11}")
        for r in payload[key]["retrace"]:
            flag = "*" if r["n"] < 50 else " "
            print(f"   {flag}{r['label']:<31}{r['n']:>6}{str(r['share'])+'%':>8}"
                  f"{str(r['completes'])+'%':>11}")
        print("   * n < 50;  'Completes' = gate still reaches 61.8% after retracing that far.")

    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}\nWrote {OUT_SITE}")


if __name__ == "__main__":
    main()
