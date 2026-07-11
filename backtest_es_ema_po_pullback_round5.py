"""
Round 5: "ribbon riding" — market entry on arm, exit when the ribbon breaks.

Signal family unchanged (dual-TF EMA stack + 3m Saty PO compression -> expansion
arm), now with:
  sides  : long (bull stack, osc rising) AND short (mirrored bear stack, osc falling)
  entry  : market at next 1-min open while armed, inside the entry window
  exits  : ribbon exits at next 1m open after a 3m close breaks
             r9     — the 3m EMA9
             r21    — the 3m EMA21
             r10m21 — the 10m EMA21
           each with an ATR-scaled intrabar disaster stop {1.5, 2.5}×ATR14(3m),
           EOD flat at 15:59 ET
  filter : none vs live-knowable 3m ATR14 >= 2.0 pts at entry
           (drift-study mechanism: edge ~constant in ATR units, fixed cost
           eats low-ATR years; ES threshold = 6.45x cost)
  window : both (09:30-12:00 + 15:00-15:45 ET) | all (09:30-15:44)

Search instrument: ES only. Candidates (net>0, both halves>0, t_day>=2) go to a
frozen pre-registered NQ holdout. Cost 0.31 ES pts RT.

Output: analyst/es_ema_po_pullback_round5.csv
"""

import os
import sys
import numpy as np
import pandas as pd

from backtest_es_ema_po_pullback_round2 import compute_phase_oscillator, atr_df, ema, build_tf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_ema_po_pullback_round5.csv")

WARMUP_BARS = 200
WINDOWS5 = {
    "both": [(570, 720), (900, 945)],
    "all":  [(570, 944)],
}

IDLE, WATCH, ARMED = 0, 1, 2


def prep5(data_path):
    print(f"loading {data_path}...", flush=True)
    df = pd.read_csv(data_path, header=None,
                     names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index()
    df = df.between_time("09:30", "15:59")
    rng_pct = (df["h"] - df["l"]) / df["c"]
    df = df[rng_pct <= 0.03]

    tf3 = compute_phase_oscillator(build_tf(df, "3min"))
    tf3["atr3"] = atr_df(tf3, 14)
    tf10 = build_tf(df, "10min")

    tf3 = tf3.reset_index().rename(columns={"ts": "start"})
    tf3["end"] = tf3["start"] + pd.Timedelta(minutes=3)
    tf10 = tf10.reset_index().rename(columns={"ts": "start"})
    tf10["end"] = tf10["start"] + pd.Timedelta(minutes=10)
    tf10["s21_10"] = tf10["ema21"].diff()
    tf10["s9_10"] = tf10["ema9"].diff()
    ten = tf10[["end", "ema9", "ema21", "s9_10", "s21_10"]].rename(
        columns={"ema9": "ema9_10", "ema21": "ema21_10"})
    tf3["s21_3"] = tf3["ema21"].diff()
    tf3["s9_3"] = tf3["ema9"].diff()
    tf3 = pd.merge_asof(tf3.sort_values("end"), ten.sort_values("end"),
                        on="end", direction="backward")

    tf3["cond_bull"] = (
        (tf3["s21_10"] > 0) & (tf3["s9_10"] > 0) & (tf3["ema9_10"] > tf3["ema21_10"]) &
        (tf3["s21_3"] > 0) & (tf3["ema21"] > tf3["ema21_10"]) &
        (tf3["s9_3"] > 0) & (tf3["ema9"] > tf3["ema21"])
    )
    tf3["cond_bear"] = (
        (tf3["s21_10"] < 0) & (tf3["s9_10"] < 0) & (tf3["ema9_10"] < tf3["ema21_10"]) &
        (tf3["s21_3"] < 0) & (tf3["ema21"] < tf3["ema21_10"]) &
        (tf3["s9_3"] < 0) & (tf3["ema9"] < tf3["ema21"])
    )
    osc_d = tf3["phase_oscillator"].diff()
    tf3["osc_rising"] = osc_d > 0
    tf3["osc_falling"] = osc_d < 0
    tf3.loc[:WARMUP_BARS, ["cond_bull", "cond_bear"]] = False

    m1r = df.reset_index()
    m1r["mod"] = m1r["ts"].dt.hour * 60 + m1r["ts"].dt.minute
    m1r["day"] = pd.factorize(m1r["ts"].dt.date)[0]
    idx3 = np.searchsorted(tf3["end"].values, m1r["ts"].values, side="right") - 1

    return {
        "o": m1r["o"].values, "h": m1r["h"].values, "l": m1r["l"].values,
        "ts": m1r["ts"].values, "mod": m1r["mod"].values,
        "last_of_day": m1r["day"].ne(m1r["day"].shift(-1)).values,
        "idx3": idx3,
        "comp": tf3["po_compression"].values,
        "cond_bull": tf3["cond_bull"].values, "cond_bear": tf3["cond_bear"].values,
        "osc_rising": tf3["osc_rising"].values, "osc_falling": tf3["osc_falling"].values,
        "e9_3": tf3["ema9"].values, "e21_3": tf3["ema21"].values,
        "e21_10": tf3["ema21_10"].values,
        "c3": tf3["close"].values, "atr3": tf3["atr3"].values,
        "n": len(m1r),
    }


def win_arr(A, wname):
    m = np.zeros(A["n"], dtype=bool)
    for lo, hi in WINDOWS5[wname]:
        m |= (A["mod"] >= lo) & (A["mod"] < hi)
    return m


def simulate5(A, side, in_win, exit_ref, stop_mult, atr_min, cost):
    """side: +1 long / -1 short. exit_ref: 'r9'|'r21'|'r10m21'.
    Ribbon exit fires at next 1m open after a 3m close breaks the reference EMA.
    Intrabar disaster stop stop_mult*atr3 (set at entry). EOD flat."""
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, idx3 = A["ts"], A["last_of_day"], A["idx3"]
    comp = A["comp"]
    cond = A["cond_bull"] if side > 0 else A["cond_bear"]
    trig = A["osc_rising"] if side > 0 else A["osc_falling"]
    c3, atr3 = A["c3"], A["atr3"]
    eref = {"r9": A["e9_3"], "r21": A["e21_3"], "r10m21": A["e21_10"]}[exit_ref]
    n = A["n"]

    state, seen3, in_pos = IDLE, -1, False
    entry_px = stop_px = 0.0
    ribbon_exit = False
    entry_ts = None
    trades = []

    for i in range(n):
        j = idx3[i]

        if in_pos:
            exit_px = None; reason = None
            if last_of_day[i]:
                exit_px, reason = o1[i], "eod"
            elif ribbon_exit:
                exit_px, reason = o1[i], "ribbon"
            elif side > 0 and l1[i] <= stop_px:
                exit_px, reason = min(o1[i], stop_px), "stop"
            elif side < 0 and h1[i] >= stop_px:
                exit_px, reason = max(o1[i], stop_px), "stop"
            if exit_px is not None:
                trades.append((entry_ts, ts1[i],
                               side * (exit_px - entry_px) - cost, reason))
                in_pos = False
                ribbon_exit = False

        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if in_pos and side * (c3[k] - eref[k]) < 0:
                    ribbon_exit = True
                if comp[k] == 1:
                    state = WATCH
                elif state == WATCH:
                    state = ARMED if (trig[k] and cond[k]) else IDLE
                elif state == ARMED:
                    if (not cond[k]) or (side * (c3[k] - A["e21_3"][k]) < 0):
                        state = IDLE
            seen3 = j

        if (not in_pos) and state == ARMED and in_win[i] and j >= 1:
            if atr_min is not None and not (atr3[j] >= atr_min):
                continue
            entry_px = o1[i]
            stop_px = entry_px - side * stop_mult * atr3[j]
            entry_ts = ts1[i]
            in_pos = True
            ribbon_exit = False
            state = IDLE

    return pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "pnl_pts", "reason"])


def stats5(t, label):
    if len(t) == 0:
        return {"config": label, "n": 0}
    t = t.copy()
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t["year"] = t["entry_ts"].dt.year
    pnl = t["pnl_pts"]
    daily = t.groupby(t["entry_ts"].dt.date)["pnl_pts"].sum()
    tday = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl <= 0].sum()
    tr = t[t["year"] <= 2019]; te = t[t["year"] >= 2020]
    yr = t.groupby("year")["pnl_pts"].sum()
    return {
        "config": label, "n": len(t),
        "win_pct": round((pnl > 0).mean() * 100, 1),
        "avg_pts": round(pnl.mean(), 3),
        "tot_pts": round(pnl.sum(), 1),
        "pf": round(wins / losses, 3) if losses > 0 else np.inf,
        "t_day": round(tday, 2),
        "avg_0819": round(tr["pnl_pts"].mean(), 3) if len(tr) else np.nan,
        "avg_2026": round(te["pnl_pts"].mean(), 3) if len(te) else np.nan,
        "pos_years_pct": round((yr > 0).mean() * 100, 0),
    }


def main():
    A = prep5("/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt")
    COST = 0.31
    masks = {w: win_arr(A, w) for w in WINDOWS5}
    rows = []
    for side, sname in [(1, "long"), (-1, "short")]:
        for wname, m in masks.items():
            for exit_ref in ["r9", "r21", "r10m21"]:
                for stop_mult in [1.5, 2.5]:
                    for atr_min in [None, 2.0]:
                        t = simulate5(A, side, m, exit_ref, stop_mult, atr_min, COST)
                        fl = "atr2" if atr_min else "none"
                        label = f"{sname}|{wname}|{exit_ref}|s{stop_mult}atr|{fl}"
                        r = stats5(t, label)
                        r.update(side=sname, window=wname, exit=exit_ref,
                                 stop=stop_mult, filt=fl)
                        rows.append(r)
                        print(f"  {label}: n={r.get('n',0)} avg={r.get('avg_pts')} "
                              f"pf={r.get('pf')} t={r.get('t_day')} "
                              f"tr={r.get('avg_0819')} te={r.get('avg_2026')} "
                              f"posyr={r.get('pos_years_pct')}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)
    cand = out[(out["avg_pts"] > 0) & (out["avg_0819"] > 0) &
               (out["avg_2026"] > 0) & (out["t_day"] >= 2)]
    print(f"\ncandidates (net>0, both halves>0, t_day>=2): {len(cand)}")
    if len(cand):
        print(cand.to_string(index=False))
    print(f"\nwritten to {OUT_CSV}")


if __name__ == "__main__":
    main()
