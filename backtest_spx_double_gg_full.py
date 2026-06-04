"""
SPX Double Golden Gate -- full study (both orderings, all day, time-segmented).

Generalizes backtest_spx_double_gg_revert.py:

  A "double-gate" session is one where BOTH the downside gate (-38.2% ATR) and
  the upside gate (+38.2% ATR) open during RTH. The ordering defines the case:

    down_first : downside gate opens, then later the upside gate opens
                 (a down-then-up whipsaw; the 2nd gate is the UPSIDE one)
    up_first   : upside gate opens, then later the downside gate opens
                 (an up-then-down whipsaw; the 2nd gate is the DOWNSIDE one)

  No noon cutoff -- the second open can happen any time in RTH. Occurrences and
  outcomes are segmented by the time of day the SECOND gate opens (when the
  setup becomes actionable).

For each case, measured from the SECOND gate's open through the RTH close:
  - does the 2nd gate COMPLETE (reach its +/-61.8% level)?
  - does price REVERT to PDC?
  - does neither gate ever complete (no +/-61.8% all day)?
  - and after a 2nd-gate completion: continuation / sideways / mean reversion.

Output:
  analyst/spx_double_gg_full_events.csv
  site/data/spx-double-gg.json   (embedded in the published page)

Data: FirstRateData SPX index, 1-minute RTH bars (2008-01 -> 2026-05).
Levels from prior daily close + one-session-lagged Wilder ATR(14).
Timezone note: timestamps are ET; 12pm Central = 1:00pm ET.
"""

from __future__ import annotations

import json
import pandas as pd

from backtest_spx_double_gg_revert import load_spx, first_time

OUT_CSV = "analyst/spx_double_gg_full_events.csv"
OUT_JSON = "site/data/spx-double-gg.json"

HALF_HOURS = ["09:30", "10:00", "10:30", "11:00", "11:30", "12:00",
              "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"]


def hhmm(ts):
    return f"{ts.hour:02d}:{0 if ts.minute < 30 else 30:02d}"


def analyze_day(g):
    """Return an event dict if the day is a double-gate day, else None."""
    first = g.iloc[0]
    pdc, atr = first["prev_close"], first["atr_14"]
    up_o, dn_o = first["up_0382"], first["dn_0382"]
    up_c, dn_c = first["up_0618"], first["dn_0618"]
    up_e, dn_e = first["up_0786"], first["dn_0786"]
    up_f, dn_f = first["up_100"], first["dn_100"]
    up_t, dn_t = first["up_trig"], first["dn_trig"]

    t_dn_open = first_time(g, g["low"] <= dn_o)
    t_up_open = first_time(g, g["high"] >= up_o)
    if t_dn_open is None or t_up_open is None:
        return None

    if t_dn_open < t_up_open:
        case = "down_first"          # 2nd gate is the UPSIDE gate
        t_first, t_second = t_dn_open, t_up_open
        # second-gate (up) levels
        s_open, s_complete, s_ext, s_full = up_o, up_c, up_e, up_f
        s_trig = up_t
        # first-gate (down) re-levels
        f_open, f_complete = dn_o, dn_c
        revert_dir = "down"          # revert to PDC means pulling DOWN to pdc
    else:
        case = "up_first"            # 2nd gate is the DOWNSIDE gate
        t_first, t_second = t_up_open, t_dn_open
        s_open, s_complete, s_ext, s_full = dn_o, dn_c, dn_e, dn_f
        s_trig = dn_t
        f_open, f_complete = up_o, up_c
        revert_dir = "up"

    from_second = g[g.index >= t_second]
    after_second = g[g.index > t_second]

    # Whole-day completions (either gate).
    dn_complete_ever = bool((g["low"] <= dn_c).any())
    up_complete_ever = bool((g["high"] >= up_c).any())
    neither_close_ever = (not dn_complete_ever) and (not up_complete_ever)

    # Sign-aware helpers operating on the second gate's direction.
    if case == "down_first":      # second gate up
        s_complete_after_t = first_time(after_second, after_second["high"] >= s_complete)
        s_ext_after = bool((from_second["high"] >= s_ext).any())
        s_full_after = bool((from_second["high"] >= s_full).any())
        f_complete_after_t = first_time(after_second, after_second["low"] <= f_complete)
        pdc_revert_t = first_time(after_second, after_second["low"] <= pdc)
        trig_revert_t = first_time(after_second, after_second["low"] <= s_trig)
    else:                          # second gate down
        s_complete_after_t = first_time(after_second, after_second["low"] <= s_complete)
        s_ext_after = bool((from_second["low"] <= s_ext).any())
        s_full_after = bool((from_second["low"] <= s_full).any())
        f_complete_after_t = first_time(after_second, after_second["high"] >= f_complete)
        pdc_revert_t = first_time(after_second, after_second["high"] >= pdc)
        trig_revert_t = first_time(after_second, after_second["high"] >= s_trig)

    # First resolution after the 2nd gate opens.
    cands = {}
    if s_complete_after_t is not None:
        cands["second_completes"] = s_complete_after_t
    if f_complete_after_t is not None:
        cands["first_completes"] = f_complete_after_t
    first_res = min(cands, key=lambda k: cands[k]) if cands else "neither"

    # After-completion behavior (only meaningful if the 2nd gate completes).
    after_complete_label = None
    ext_after_t = None     # time the 78.6% extension is hit after completion
    if s_complete_after_t is not None:
        ac = g[g.index > s_complete_after_t]
        if len(ac):
            if case == "down_first":
                ext_after_t = first_time(ac, ac["high"] >= s_ext)
                cont = (ext_after_t is not None) or (g.iloc[-1]["close"] >= s_ext)
                gave_back = bool((ac["low"] <= s_open).any())
            else:
                ext_after_t = first_time(ac, ac["low"] <= s_ext)
                cont = (ext_after_t is not None) or (g.iloc[-1]["close"] <= s_ext)
                gave_back = bool((ac["high"] >= s_open).any())
            if cont:
                after_complete_label = "continuation"
            elif gave_back:
                after_complete_label = "mean_reversion"
            else:
                after_complete_label = "sideways"

    close_price = g.iloc[-1]["close"]
    close_atr = (close_price - pdc) / atr

    # Timing: minutes from the 2nd gate opening to completion, and from
    # completion to the 78.6% continuation; plus the clock time each lands.
    complete_min = ((s_complete_after_t - t_second).total_seconds() / 60.0
                    if s_complete_after_t is not None else None)
    complete_hhmm = hhmm(s_complete_after_t) if s_complete_after_t is not None else None
    cont_min = ((ext_after_t - s_complete_after_t).total_seconds() / 60.0
                if ext_after_t is not None else None)
    cont_hhmm = hhmm(ext_after_t) if ext_after_t is not None else None

    return {
        "date": str(g.index[0].date()),
        "case": case,
        "t_first": hhmm(t_first),
        "t_second": hhmm(t_second),
        "second_dir": "up" if case == "down_first" else "down",
        "revert_dir": revert_dir,
        "before_noon_ct": t_second.time() < pd.Timestamp("13:00").time(),
        "both_before_noon_ct": (t_first.time() < pd.Timestamp("13:00").time()
                                and t_second.time() < pd.Timestamp("13:00").time()),
        "neither_close_ever": neither_close_ever,
        "second_completes": s_complete_after_t is not None,
        "second_ext": s_ext_after,
        "second_full": s_full_after,
        "first_recompletes": f_complete_after_t is not None,
        "pdc_revert": pdc_revert_t is not None,
        "trig_revert": trig_revert_t is not None,
        "first_resolution": first_res,
        "after_complete": after_complete_label,
        "close_atr": close_atr,
        "reversal_min": (t_second - t_first).total_seconds() / 60.0,
        "complete_min": complete_min,
        "complete_hhmm": complete_hhmm,
        "cont_min": cont_min,
        "cont_hhmm": cont_hhmm,
    }


def rate(sub, col):
    return round(float(sub[col].mean()) * 100, 1) if len(sub) else None


def summarize(ev):
    n = len(ev)
    out = {
        "n": n,
        "neither_close_ever": rate(ev, "neither_close_ever"),
        "second_completes": rate(ev, "second_completes"),
        "pdc_revert": rate(ev, "pdc_revert"),
        "trig_revert": rate(ev, "trig_revert"),
        "first_recompletes": rate(ev, "first_recompletes"),
        "second_ext": rate(ev, "second_ext"),
        "second_full": rate(ev, "second_full"),
        "first_res_second": round(float((ev["first_resolution"] == "second_completes").mean()) * 100, 1) if n else None,
        "first_res_first": round(float((ev["first_resolution"] == "first_completes").mean()) * 100, 1) if n else None,
        "first_res_neither": round(float((ev["first_resolution"] == "neither").mean()) * 100, 1) if n else None,
        "close_atr_median": round(float(ev["close_atr"].median()), 3) if n else None,
        "reversal_min_median": round(float(ev["reversal_min"].median()), 0) if n else None,
    }
    # After-completion split (subset where the 2nd gate completed).
    comp = ev[ev["after_complete"].notna()]
    nc = len(comp)
    out["after_complete"] = {
        "n": nc,
        "continuation": round(float((comp["after_complete"] == "continuation").mean()) * 100, 1) if nc else None,
        "sideways": round(float((comp["after_complete"] == "sideways").mean()) * 100, 1) if nc else None,
        "mean_reversion": round(float((comp["after_complete"] == "mean_reversion").mean()) * 100, 1) if nc else None,
    }
    # Timing: how long the second gate takes to complete, and (when it
    # continues) how long the 78.6% extension takes after completion.
    cm = ev.loc[ev["second_completes"], "complete_min"].dropna()
    xm = ev["cont_min"].dropna()
    def q(s, p):
        return round(float(s.quantile(p)), 0) if len(s) else None
    out["timing"] = {
        "n_completed": int(len(cm)),
        "complete_min_p25": q(cm, 0.25),
        "complete_min_median": q(cm, 0.50),
        "complete_min_p75": q(cm, 0.75),
        "n_continued": int(len(xm)),
        "cont_min_p25": q(xm, 0.25),
        "cont_min_median": q(xm, 0.50),
        "cont_min_p75": q(xm, 0.75),
    }
    return out


def time_hist(ev, col):
    """Distribution of a clock-time column (hh:mm) over the half-hour grid."""
    vc = ev[col].dropna().value_counts()
    return [{"bucket": b, "n": int(vc.get(b, 0))} for b in HALF_HOURS]


def by_time(ev):
    rows = []
    for b in HALF_HOURS:
        sub = ev[ev["t_second"] == b]
        if len(sub) == 0:
            continue
        cm = sub.loc[sub["second_completes"], "complete_min"].dropna()
        rows.append({
            "bucket": b,
            "n": int(len(sub)),
            "second_completes": rate(sub, "second_completes"),
            "pdc_revert": rate(sub, "pdc_revert"),
            "neither_close_ever": rate(sub, "neither_close_ever"),
            "first_recompletes": rate(sub, "first_recompletes"),
            "complete_min_median": round(float(cm.median()), 0) if len(cm) else None,
        })
    return rows


def main():
    print("Loading SPX ...", flush=True)
    df = load_spx()
    n_sessions = df["date"].nunique()
    recs = [r for _, g in df.groupby("date", sort=True) if (r := analyze_day(g)) is not None]
    ev = pd.DataFrame(recs)
    ev.to_csv(OUT_CSV, index=False)

    down = ev[ev["case"] == "down_first"].copy()
    up = ev[ev["case"] == "up_first"].copy()

    payload = {
        "meta": {
            "ticker": "SPX",
            "source": "FirstRateData SPX index, 1-minute RTH",
            "date_start": str(df.index.min().date()),
            "date_end": str(df.index.max().date()),
            "n_sessions": int(n_sessions),
            "n_double_gate": int(len(ev)),
            "n_down_first": int(len(down)),
            "n_up_first": int(len(up)),
            "tz_note": "Timestamps ET; 12pm Central = 1:00pm ET",
        },
        "down_first": {
            "overall": summarize(down),
            "by_time": by_time(down),
            "morning_subset": summarize(down[down["both_before_noon_ct"]]),
        },
        "up_first": {
            "overall": summarize(up),
            "by_time": by_time(up),
            "morning_subset": summarize(up[up["both_before_noon_ct"]]),
        },
        # The headline edge: up->down setup that becomes valid in the morning.
        "edge": {
            "label": "Up→Down, 2nd gate opens before noon CT",
            "summary": summarize(up[up["both_before_noon_ct"]]),
            "complete_clock": time_hist(up[up["both_before_noon_ct"]], "complete_hhmm"),
            "cont_clock": time_hist(up[up["both_before_noon_ct"]], "cont_hhmm"),
        },
        # Occurrence distribution by second-gate-open half hour (both cases).
        "occurrence_by_time": [
            {
                "bucket": b,
                "down_first": int(((ev["case"] == "down_first") & (ev["t_second"] == b)).sum()),
                "up_first": int(((ev["case"] == "up_first") & (ev["t_second"] == b)).sum()),
            }
            for b in HALF_HOURS
        ],
    }

    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    # ---- console summary ----
    m = payload["meta"]
    print(f"\nSessions: {m['n_sessions']:,}  ({m['date_start']} -> {m['date_end']})")
    print(f"Double-gate days: {m['n_double_gate']}  "
          f"(down-first {m['n_down_first']}, up-first {m['n_up_first']})")

    for case, lbl in [("down_first", "DOWN-first (then upside gate)"),
                      ("up_first", "UP-first (then downside gate)")]:
        s = payload[case]["overall"]
        print(f"\n=== {lbl}  n={s['n']} ===")
        print(f"  2nd gate completes (+/-61.8%):  {s['second_completes']}%")
        print(f"  Reverts to PDC:                 {s['pdc_revert']}%")
        print(f"  Neither gate ever completes:    {s['neither_close_ever']}%")
        print(f"  First resolution = 2nd completes:{s['first_res_second']}%  "
              f"first re-completes:{s['first_res_first']}%  neither:{s['first_res_neither']}%")
        print(f"  Close vs PDC (median ATR):      {s['close_atr_median']:+}")
        ac = s["after_complete"]
        print(f"  After 2nd completes (n={ac['n']}): "
              f"cont {ac['continuation']}% / sideways {ac['sideways']}% / revert {ac['mean_reversion']}%")
        print(f"  Morning subset (both pre-noon CT) n={payload[case]['morning_subset']['n']}: "
              f"2nd completes {payload[case]['morning_subset']['second_completes']}%, "
              f"PDC revert {payload[case]['morning_subset']['pdc_revert']}%")
        print(f"  By 2nd-open time:")
        print(f"    {'time':<7} {'n':>4} {'2ndComp':>8} {'PDCrev':>7} {'Neither':>8}")
        for r in payload[case]["by_time"]:
            flag = "*" if r["n"] < 20 else " "
            print(f"    {r['bucket']:<7}{flag}{r['n']:>3} {str(r['second_completes']):>8} "
                  f"{str(r['pdc_revert']):>7} {str(r['neither_close_ever']):>8}")

    print(f"\nWrote {OUT_JSON} and {OUT_CSV}")


if __name__ == "__main__":
    main()
