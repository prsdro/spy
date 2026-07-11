"""
Round 5b: push the ribbon-riding gradient (longs only) + matched baselines.

Round 5 gradient: slower exit > faster, wider stop > tighter, ATR>=2 filter
always helps, longs only. Extensions along that gradient (mechanism-driven):
  entry : arm (PO compression->expansion, as before)
          stack (enter when the bull EMA stack first aligns; no PO required —
                 the purer "ribbon riding" definition, more trades)
  exit  : r21, r10m21, r10m21x2 (TWO consecutive 3m closes below the 10m EMA21)
  stop  : 2.5 / 3.5 x ATR14(3m)
  window: both | all      filter: 3m ATR14 >= 2.0 pts (fixed)
Matched baseline for every cell: unconditional long entries every 10th eligible
minute (same window, same ATR filter, same exit/stop), reported alongside.

Output: analyst/es_ema_po_pullback_round5b.csv
"""

import numpy as np
import pandas as pd
import os

from backtest_es_ema_po_pullback_round5 import prep5, win_arr, stats5, WINDOWS5

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_ema_po_pullback_round5b.csv")
COST = 0.31
ATR_MIN = 2.0

IDLE, WATCH, ARMED = 0, 1, 2


def simulate5b(A, in_win, entry_mode, exit_ref, need_closes, stop_mult,
               signal_only=False):
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, idx3 = A["ts"], A["last_of_day"], A["idx3"]
    comp, cond, trig = A["comp"], A["cond_bull"], A["osc_rising"]
    c3, atr3, e21_3 = A["c3"], A["atr3"], A["e21_3"]
    eref = {"r21": A["e21_3"], "r10m21": A["e21_10"]}[exit_ref]
    n = A["n"]

    state, seen3, in_pos = IDLE, -1, False
    prev_cond = False
    entry_px = stop_px = 0.0
    below_ct = 0
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
            elif l1[i] <= stop_px:
                exit_px, reason = min(o1[i], stop_px), "stop"
            if exit_px is not None:
                trades.append((entry_ts, ts1[i],
                               exit_px - entry_px - COST, reason))
                in_pos = False
                ribbon_exit = False

        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if in_pos:
                    below_ct = below_ct + 1 if c3[k] < eref[k] else 0
                    if below_ct >= need_closes:
                        ribbon_exit = True
                if entry_mode == "arm":
                    if comp[k] == 1:
                        state = WATCH
                    elif state == WATCH:
                        state = ARMED if (trig[k] and cond[k]) else IDLE
                    elif state == ARMED:
                        if (not cond[k]) or (c3[k] < e21_3[k]):
                            state = IDLE
                else:  # stack onset
                    if cond[k] and not prev_cond:
                        state = ARMED
                    elif state == ARMED and ((not cond[k]) or (c3[k] < e21_3[k])):
                        state = IDLE
                    prev_cond = cond[k]
            seen3 = j

        if (not in_pos) and state == ARMED and in_win[i] and j >= 1:
            if not (atr3[j] >= ATR_MIN):
                continue
            entry_px = o1[i]
            stop_px = entry_px - stop_mult * atr3[j]
            entry_ts = ts1[i]
            in_pos = True
            below_ct = 0
            ribbon_exit = False
            state = IDLE

    return pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "pnl_pts", "reason"])


def baseline5b(A, in_win, exit_ref, need_closes, stop_mult, stride=10):
    """Unconditional long every stride-th eligible minute, same exit machinery."""
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, idx3 = A["ts"], A["last_of_day"], A["idx3"]
    c3, atr3 = A["c3"], A["atr3"]
    eref = {"r21": A["e21_3"], "r10m21": A["e21_10"]}[exit_ref]
    n = A["n"]
    pnls = []
    ts_out = []
    i = 0
    while i < n:
        j = idx3[i]
        if in_win[i] and not last_of_day[i] and j >= 1 and atr3[j] >= ATR_MIN:
            fill = o1[i]
            stop_px = fill - stop_mult * atr3[j]
            below_ct = 0
            seen = j
            k = i
            done = False
            while k < n and not done:
                jk = idx3[k]
                if jk > seen:
                    for kk in range(seen + 1, jk + 1):
                        below_ct = below_ct + 1 if c3[kk] < eref[kk] else 0
                    seen = jk
                    if below_ct >= need_closes:
                        pnls.append(o1[k] - fill - COST); done = True; break
                if last_of_day[k]:
                    pnls.append(o1[k] - fill - COST); done = True
                elif l1[k] <= stop_px:
                    pnls.append(min(o1[k], stop_px) - fill - COST); done = True
                k += 1
            ts_out.append(ts1[i])
            i += stride
        else:
            i += 1
    b = pd.DataFrame({"entry_ts": ts_out[:len(pnls)], "pnl_pts": pnls})
    return b


def main():
    A = prep5("/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt")
    masks = {w: win_arr(A, w) for w in WINDOWS5}
    rows = []
    base_cache = {}
    for entry_mode in ["arm", "stack"]:
        for wname, m in masks.items():
            for exit_ref, need in [("r21", 1), ("r10m21", 1), ("r10m21", 2)]:
                for stop_mult in [2.5, 3.5]:
                    t = simulate5b(A, m, entry_mode, exit_ref, need, stop_mult)
                    ename = exit_ref + ("x2" if need == 2 else "")
                    label = f"{entry_mode}|{wname}|{ename}|s{stop_mult}atr|atr2"
                    r = stats5(t, label)
                    bkey = (wname, exit_ref, need, stop_mult)
                    if bkey not in base_cache:
                        base_cache[bkey] = baseline5b(A, m, exit_ref, need, stop_mult)
                    b = base_cache[bkey]
                    bt = b.copy(); bt["entry_ts"] = pd.to_datetime(bt["entry_ts"])
                    r["base_avg"] = round(b["pnl_pts"].mean(), 3)
                    r["edge_vs_base"] = round(r.get("avg_pts", np.nan) - r["base_avg"], 3) if r.get("n", 0) else np.nan
                    r.update(entry=entry_mode, window=wname, exit=ename, stop=stop_mult)
                    rows.append(r)
                    print(f"  {label}: n={r.get('n',0)} avg={r.get('avg_pts')} "
                          f"pf={r.get('pf')} t={r.get('t_day')} tr={r.get('avg_0819')} "
                          f"te={r.get('avg_2026')} posyr={r.get('pos_years_pct')} "
                          f"base={r['base_avg']}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)
    cand = out[(out["avg_pts"] > 0) & (out["avg_0819"] > 0) &
               (out["avg_2026"] > 0) & (out["t_day"] >= 2) &
               (out["edge_vs_base"] > 0)]
    print(f"\ncandidates (net>0, halves>0, t>=2, beats baseline): {len(cand)}")
    if len(cand):
        print(cand[["config", "n", "avg_pts", "pf", "t_day", "avg_0819",
                    "avg_2026", "pos_years_pct", "base_avg"]].to_string(index=False))
    print(f"\nwritten to {OUT_CSV}")


if __name__ == "__main__":
    main()
