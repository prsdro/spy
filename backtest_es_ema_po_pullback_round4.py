"""
Round 4: pullback + reclaim-confirmation entry.

Same arm signal (dual-TF bullish EMA stack + 3m PO compression -> bullish
expansion). New entry sequence:
  ARMED  -> a 3m bar's low touches the 9/21 zone (low <= 3m EMA9)   [PULLED]
  PULLED -> a 3m bar CLOSES back above the 3m EMA9                  [GO]
  GO     -> buy at the open of the next 1-min bar inside a window
Disarm anywhere in the sequence if the EMA stack breaks or a 3m close < EMA21;
a fresh compression resets to WATCH. The dip-and-reclaim can be one bar
(low <= EMA9 and close > EMA9 on the same bar).

Exits & windows as round 3. Train 2008-2019 / test 2020-2026 split,
matched random-entry baselines for candidates.

Output: analyst/es_ema_po_pullback_round4.csv
"""

import os
import numpy as np
import pandas as pd

from backtest_es_ema_po_pullback_round2 import prep, COST_ES, PT_VALUE
from backtest_es_ema_po_pullback_round3 import (WINDOWS, EXITS, win_mask,
                                                baseline, stats)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_ema_po_pullback_round4.csv")

IDLE, WATCH, ARMED, PULLED, GO = 0, 1, 2, 3, 4


def simulate(A, in_win, stop=5, tgt=None, mgmt="fixed",
             be_arm=None, trail_arm=None, trail_dist=None):
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, idx3 = A["ts"], A["last_of_day"], A["idx3"]
    comp, cond, rising = A["comp"], A["cond"], A["rising"]
    e9_3, e21_3, c3, l3 = A["e9_3"], A["e21_3"], A["c3"], A["l3"]
    n = A["n"]

    state, seen3, in_pos = IDLE, -1, False
    entry_px = stp = hi = 0.0
    tgt_px = None
    entry_ts = None
    trades = []

    for i in range(n):
        j = idx3[i]

        if in_pos:
            exit_px = None; reason = None
            if last_of_day[i]:
                exit_px, reason = o1[i], "eod"
            elif l1[i] <= stp:
                exit_px, reason = min(o1[i], stp), "stop"
            elif tgt_px is not None and h1[i] >= tgt_px:
                exit_px, reason = max(o1[i], tgt_px), "target"
            if exit_px is None and mgmt in ("be", "trail"):
                hi = max(hi, h1[i])
                if mgmt == "be" and hi >= entry_px + be_arm:
                    stp = max(stp, entry_px)
                elif mgmt == "trail" and hi >= entry_px + trail_arm:
                    stp = max(stp, entry_px, hi - trail_dist)
            if exit_px is not None:
                trades.append((entry_ts, ts1[i], exit_px - entry_px - COST_ES, reason))
                in_pos = False
            if in_pos:
                continue

        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if comp[k] == 1:
                    state = WATCH
                    continue
                if state == WATCH:
                    state = ARMED if (rising[k] and cond[k]) else IDLE
                    continue
                if state in (ARMED, PULLED, GO):
                    if (not cond[k]) or (c3[k] < e21_3[k]):
                        state = IDLE
                        continue
                if state == ARMED and l3[k] <= e9_3[k]:
                    state = PULLED
                if state == PULLED and l3[k] <= e9_3[k] < c3[k]:
                    state = GO      # dip-and-reclaim same bar counts
                elif state == PULLED and c3[k] > e9_3[k]:
                    state = GO
            seen3 = j

        if (not in_pos) and state == GO and in_win[i] and j >= 1:
            fill = o1[i]
            in_pos = True
            entry_px = fill
            stp = fill - stop
            tgt_px = (fill + tgt) if tgt is not None else None
            hi = fill
            entry_ts = ts1[i]
            state = IDLE

    return pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "pnl_pts", "reason"])


def main():
    A = prep()
    masks = {w: win_mask(A, w) for w in ["both", "am"]}
    rows = []
    for wname, m in masks.items():
        for ename, kw in EXITS.items():
            t = simulate(A, m, **kw)
            label = f"reclaim|{wname}|{ename}"
            r = stats(t, label)
            r["window"], r["exit"] = wname, ename
            rows.append(r)
            print(f"  {label}: n={r.get('n',0)} avg={r.get('avg_pts')} "
                  f"pf={r.get('pf')} t_day={r.get('t_day')} "
                  f"train={r.get('avg_0819')} test={r.get('avg_2026')}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)

    cand = out[(out["avg_pts"] > 0) & (out["avg_0819"] > 0) & (out["avg_2026"] > 0)]
    print(f"\ncandidates positive full + both halves: {len(cand)}")
    for _, r in cand.iterrows():
        kw = EXITS[r["exit"]]
        b = baseline(A, masks[r["window"]],
                     stop=kw["stop"], tgt=kw["tgt"], mgmt=kw["mgmt"],
                     be_arm=kw.get("be_arm"), trail_arm=kw.get("trail_arm"),
                     trail_dist=kw.get("trail_dist"))
        print(f"  {r['config']}: avg {r['avg_pts']} pf {r['pf']} t_day {r['t_day']} "
              f"| baseline avg {b.mean():+.3f} (n={len(b)})")

    print(f"\nwritten to {OUT_CSV}")


if __name__ == "__main__":
    main()
