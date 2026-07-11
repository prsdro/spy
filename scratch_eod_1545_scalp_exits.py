"""
EOD scalp exits: same 15:45 entries, but exit at a profit target instead of
holding to the close.

Mechanics: short at the 15:45 ET bar open. A resting buy limit sits at
(entry - target). On each 1-min bar 15:45-15:59, if bar low <= limit price,
we assume a fill AT the limit. If never touched, cover at the 15:59 close.
Longs mirror with bar highs. No stop (the close is the hard stop, 14 min away).

Targets tested: fixed points (2/3/5/7/10) and ATR-scaled (5/7.5/10/15% of the
lagged daily ATR). Fixed-point targets are regime-dependent: 5 pts was ~0.4%
of SPX in 2008 but ~0.08% in 2026, so era splits matter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import load_spx

s = pd.read_csv("analyst/spx_eod_1545_sessions.csv", parse_dates=["date"])
s["new_ll"] = (s["lo2"] < s["lo1"]).fillna(False)

df = load_spx()
df["time"] = df.index.strftime("%H:%M")
win = df[(df["time"] >= "15:45") & (df["time"] <= "15:59")].copy()

# per-session window arrays
paths = {pd.Timestamp(d): g for d, g in win.groupby("date")}

RULES = {
    "S1 last_hr<=-0.10 (short)": (s["last_hr"] <= -0.10, -1),
    "S7 S1+new low+red (short)": ((s["last_hr"] <= -0.10) & s["new_ll"] & (s["day_ret"] < 0), -1),
    "L2 last_hr>=0.25 & green (long)": ((s["last_hr"] >= 0.25) & (s["day_ret"] > 0), +1),
}

FIXED = [2, 3, 5, 7, 10]
ATRF = [0.05, 0.075, 0.10, 0.15]
ERAS = [("2008-2015", 2008, 2015), ("2016-2019", 2016, 2019),
        ("2020-2022", 2020, 2022), ("2023-2026", 2023, 2026)]


def run(trades: pd.DataFrame, side: int, tgt_pts: pd.Series) -> pd.DataFrame:
    """Return per-trade pnl (pts) and hit flag/time for a target expressed in points."""
    out = []
    for _, r in trades.iterrows():
        g = paths.get(r["date"])
        if g is None or not len(g):
            continue
        entry = g["open"].iloc[0]
        tgt = tgt_pts.loc[r.name]
        lim = entry + side * tgt  # short (side=-1): entry - tgt below; long (side=+1): entry + tgt above
        touch = g["low"] <= lim if side < 0 else g["high"] >= lim
        if touch.any():
            i = int(np.argmax(touch.values))
            pnl = tgt
            out.append(dict(date=r["date"], year=r["year"], hit=1, pnl=pnl, mins=i))
        else:
            close = g["close"].iloc[-1]
            pnl = side * (close - entry)
            out.append(dict(date=r["date"], year=r["year"], hit=0, pnl=pnl, mins=len(g) - 1))
    return pd.DataFrame(out)


pd.set_option("display.width", 250)
for name, (mask, side) in RULES.items():
    t = s[mask]
    print(f"\n================ {name}  (n={len(t)}) ================")
    rows = []
    # hold to close baseline
    base = side * t["fwd_pts"]
    rows.append(dict(target="hold to close", hit_pct=np.nan,
                     mean_pts=round(base.mean(), 2), med_pts=round(base.median(), 2),
                     win=round(100 * (base > 0).mean(), 1),
                     loser_mean=round(base[base <= 0].mean(), 2), med_mins=np.nan,
                     **{}))
    for tp in FIXED:
        res = run(t, side, pd.Series(tp, index=t.index, dtype=float))
        losers = res[res["hit"] == 0]["pnl"]
        rows.append(dict(target=f"{tp} pts", hit_pct=round(100 * res["hit"].mean(), 1),
                         mean_pts=round(res["pnl"].mean(), 2), med_pts=round(res["pnl"].median(), 2),
                         win=round(100 * (res["pnl"] > 0).mean(), 1),
                         loser_mean=round(losers.mean(), 2),
                         med_mins=res.loc[res["hit"] == 1, "mins"].median()))
    for f in ATRF:
        res = run(t, side, (f * t["atr"]).astype(float))
        losers = res[res["hit"] == 0]["pnl"]
        rows.append(dict(target=f"{f:.1%} ATR", hit_pct=round(100 * res["hit"].mean(), 1),
                         mean_pts=round(res["pnl"].mean(), 2), med_pts=round(res["pnl"].median(), 2),
                         win=round(100 * (res["pnl"] > 0).mean(), 1),
                         loser_mean=round(losers.mean(), 2),
                         med_mins=res.loc[res["hit"] == 1, "mins"].median()))
    print(pd.DataFrame(rows).to_string(index=False))

    # era detail for the 5-pt scalp
    res5 = run(t, side, pd.Series(5.0, index=t.index))
    print("\n  5-pt scalp by era:")
    era_rows = []
    for era, y0, y1 in ERAS:
        e = res5[(res5["year"] >= y0) & (res5["year"] <= y1)]
        if not len(e):
            continue
        era_rows.append(dict(era=era, n=len(e), hit_pct=round(100 * e["hit"].mean(), 1),
                             mean_pts=round(e["pnl"].mean(), 2),
                             win=round(100 * (e["pnl"] > 0).mean(), 1),
                             loser_mean=round(e.loc[e["hit"] == 0, "pnl"].mean(), 2)))
    print(pd.DataFrame(era_rows).to_string(index=False))
