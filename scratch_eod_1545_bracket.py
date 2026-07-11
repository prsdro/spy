"""
EOD bracket matrix: 15:45 short entries with target x stop brackets (points).

Short at the 15:45 ET bar open; buy limit at entry-target, stop at entry+stop.
Walked bar-by-bar on 1-min data; if both sides touch in the same bar the STOP
fills first (conservative). No stop -> losers exit at the 15:59 close.
Reports mean pts/trade overall and for 2023-2026 (current regime).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import load_spx

s = pd.read_csv("analyst/spx_eod_1545_sessions.csv", parse_dates=["date"])
s["new_ll"] = (s["lo2"] < s["lo1"]).fillna(False)
df = load_spx()
df["time"] = df.index.strftime("%H:%M")
win = df[(df["time"] >= "15:45") & (df["time"] <= "15:59")]
paths = {pd.Timestamp(d): g for d, g in win.groupby("date")}


def bracket(trades: pd.DataFrame, side: int, tgt: float, stp: float | None) -> pd.Series:
    pnl = []
    for _, r in trades.iterrows():
        g = paths.get(r["date"])
        if g is None or not len(g):
            continue
        e = g["open"].iloc[0]
        lim = e + side * tgt
        stop = e - side * stp if stp else None
        done = None
        for _, b in g.iterrows():
            hit_s = stop is not None and (b["high"] >= stop if side < 0 else b["low"] <= stop)
            hit_t = b["low"] <= lim if side < 0 else b["high"] >= lim
            if hit_s:
                done = -stp
                break
            if hit_t:
                done = tgt
                break
        pnl.append(done if done is not None else side * (g["close"].iloc[-1] - e))
    return pd.Series(pnl, index=trades.index[: len(pnl)])


RULES = {
    "S1 (short)": (s[s["last_hr"] <= -0.10], -1),
    "S7 (short)": (s[(s["last_hr"] <= -0.10) & s["new_ll"] & (s["day_ret"] < 0)], -1),
}
pd.set_option("display.width", 250)
for name, (t, side) in RULES.items():
    print(f"\n== {name} n={len(t)} :: bracket matrix, mean pts/trade (all | 2023-2026) ==")
    recent = t["year"] >= 2023
    rows = []
    for tgt in [3, 5, 7, 10]:
        row = {"target": f"{tgt}pt"}
        for stp in [3, 5, 7, 10, None]:
            p = bracket(t, side, tgt, stp)
            row[f"stop {stp or 'none'}"] = f"{p.mean():+.2f} | {p[recent.values].mean():+.2f}"
        rows.append(row)
    base = -t["fwd_pts"] if side < 0 else t["fwd_pts"]
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"hold-to-close ref: {base.mean():+.2f} | {base[recent].mean():+.2f}   (win {100 * (base > 0).mean():.0f}%)")
