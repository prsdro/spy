"""
EOD drilldown: momentum-continuation rules for the last 15 min (15:45-16:00 ET).

Builds on scratch_eod_1545_explore.py findings: late-day momentum CONTINUES
into the close (downside robustly across eras), and afternoon PO divergences
do NOT revert price. Here we test concrete rules with window MAE/MFE and
year-by-year stability, plus entry-time sensitivity.

Rules (signal at 15:44 close, enter 15:45 open, exit 15:59 close):
  Shorts: combinations of last-hour momentum down, red day, fresh afternoon
  low, position below the put trigger.
  Longs: symmetric upside variants.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import load_spx

s = pd.read_csv("analyst/spx_eod_1545_sessions.csv", parse_dates=["date"])

# window path for MAE/MFE (per session: 15:45-15:59 highs/lows vs entry)
df = load_spx()
df["time"] = df.index.strftime("%H:%M")
win = df[(df["time"] >= "15:45") & (df["time"] <= "15:59")]
g = win.groupby("date")
path = pd.DataFrame({
    "hi": g["high"].max(), "lo": g["low"].min(),
    "entry": g["open"].first(), "nbars": g["close"].size(),
})
path.index = pd.to_datetime(path.index)
s = s.merge(path, left_on="date", right_index=True, how="left")
s["mfe_short"] = (s["entry"] - s["lo"]) / s["atr"]   # best excursion for a short
s["mae_short"] = (s["hi"] - s["entry"]) / s["atr"]   # worst excursion for a short

s["new_ll"] = (s["lo2"] < s["lo1"]).fillna(False)
s["new_hh"] = (s["hi2"] > s["hi1"]).fillna(False)

RULES = {
    # ---- shorts (edge = negative fwd) ----
    "S1 last_hr<=-0.10": (s["last_hr"] <= -0.10, -1),
    "S2 S1 & red day": ((s["last_hr"] <= -0.10) & (s["day_ret"] < 0), -1),
    "S3 S1 & new aft low": ((s["last_hr"] <= -0.10) & s["new_ll"], -1),
    "S4 day<=-1 ATR": (s["day_ret"] <= -1, -1),
    "S5 S1 & below put trig": ((s["last_hr"] <= -0.10) & (s["atr_pos"] < -0.236), -1),
    "S6 new aft low only": (s["new_ll"], -1),
    "S7 S3 & red day": ((s["last_hr"] <= -0.10) & s["new_ll"] & (s["day_ret"] < 0), -1),
    "S8 fade bull div": ((s["lo2"] < s["lo1"]) & (s["po_lo2"] > s["po_lo1"]), -1),
    # ---- longs ----
    "L1 last_hr>=0.25": (s["last_hr"] >= 0.25, +1),
    "L2 L1 & green day": ((s["last_hr"] >= 0.25) & (s["day_ret"] > 0), +1),
    "L3 new aft high & lh>=0.1": (s["new_hh"] & (s["last_hr"] >= 0.10), +1),
    "L4 at high & day>=0.15": ((s["dist_hi"] <= 0.05) & (s["day_ret"] >= 0.15), +1),
    "L5 fade bear div": ((s["hi2"] > s["hi1"]) & (s["po_hi2"] < s["po_hi1"]), +1),
}

rows = []
for name, (mask, side) in RULES.items():
    t = s[mask].copy()
    if not len(t):
        continue
    pnl_atr = side * t["fwd_atr"]
    pnl_pts = side * t["fwd_pts"]
    n = len(t)
    sem = pnl_atr.std(ddof=1) / np.sqrt(n)
    yearly = pnl_atr.groupby(t["year"]).mean()
    rows.append(dict(
        rule=name, n=n, pct_of_days=round(100 * n / len(s), 1),
        win=round(100 * (pnl_pts > 0).mean(), 1),
        atr=round(pnl_atr.mean(), 4), pts=round(pnl_pts.mean(), 3),
        med_pts=round(pnl_pts.median(), 3),
        t=round(pnl_atr.mean() / sem, 2),
        yrs_pos=f"{(yearly > 0).sum()}/{len(yearly)}",
        mfe=round((t["mfe_short"] if side < 0 else t["mae_short"]).mean(), 4),
        mae=round((t["mae_short"] if side < 0 else t["mfe_short"]).mean(), 4),
        cum_pts=round(pnl_pts.sum(), 0),
    ))
pd.set_option("display.width", 250)
print("== Rules: 15:45 entry -> 15:59 close (SPX index pts / lagged daily ATR) ==")
print(pd.DataFrame(rows).to_string(index=False))

# ---- best short rule: yearly detail ----
best = s[(s["last_hr"] <= -0.10) & s["new_ll"]].copy()
best["pnl_atr"] = -best["fwd_atr"]
best["pnl_pts"] = -best["fwd_pts"]
yr = best.groupby("year").agg(
    n=("pnl_pts", "size"), win=("pnl_pts", lambda x: round(100 * (x > 0).mean(), 0)),
    mean_atr=("pnl_atr", "mean"), sum_pts=("pnl_pts", "sum"),
)
print("\n== S3 (last_hr<=-0.10 & new afternoon low) by year ==")
print(yr.round(3).to_string())

# ---- entry-time sensitivity for S3-style signal ----
print("\n== Entry-time sensitivity: signal at T-1 close [last-hr mom & new aft low measured to T-1], short T open -> 15:59 close ==")
df_all = df.copy()
rows2 = []
for entry_t in ["15:30", "15:35", "15:40", "15:45", "15:50", "15:55"]:
    sig_t = (pd.Timestamp(f"2000-01-01 {entry_t}") - pd.Timedelta(minutes=1)).strftime("%H:%M")
    recs = []
    for date, gg in df_all.groupby("date"):
        tt = gg["time"]
        if entry_t not in tt.values or "15:59" not in tt.values:
            continue
        sig = gg[tt <= sig_t]
        if len(sig) < 300:
            continue
        p = sig["close"].iloc[-1]
        atrv = gg["atr_14"].iloc[0]
        hr_ago = sig[sig["time"] <= f"{int(sig_t[:2]) - 1:02d}{sig_t[2:]}"]
        if not len(hr_ago):
            continue
        lh = (p - hr_ago["close"].iloc[-1]) / atrv
        aft = sig[tt[tt <= sig_t] >= "13:00"]
        cut = (pd.Timestamp(f"2000-01-01 {sig_t}") - pd.Timedelta(minutes=30)).strftime("%H:%M")
        leg1, leg2 = aft[aft["time"] <= cut], aft[aft["time"] > cut]
        if not len(leg1) or not len(leg2):
            continue
        new_ll = leg2["low"].min() < leg1["low"].min()
        if lh <= -0.10 and new_ll:
            entry = gg.loc[tt == entry_t, "open"].iloc[0]
            exit_ = gg.loc[tt == "15:59", "close"].iloc[0]
            recs.append((entry - exit_) / atrv)
    arr = np.array(recs)
    rows2.append(dict(entry=entry_t, n=len(arr), win=round(100 * (arr > 0).mean(), 1),
                      atr=round(arr.mean(), 4), t=round(arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr))), 2)))
print(pd.DataFrame(rows2).to_string(index=False))
