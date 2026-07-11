"""ATR-in-points filter test for the compression-drift strategy candidates.
Hypothesis: edge is ~constant in ATR units, cost fixed at 0.31 pts, so the
strategy only clears friction when 3m ATR (points) is large. If true, the
'2nd-half-only' profits are mechanical, and an ATR>=X filter (live-knowable)
should show a stable edge across the whole sample.
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
from backtest_es_po_comp_drift import load_3m, add_indicators
from backtest_es_po_comp_drift_strategy import simulate_exit, COST_PTS

EV_CSV = "/root/spy/analyst/es_po_comp_drift_events.csv"

tf = load_3m()
tf = add_indicators(tf)
tf["date"] = tf.index.date
o = tf["o"].values; h = tf["h"].values; l = tf["l"].values; c = tf["c"].values
dates = tf["date"].values
pos = {ts: i for i, ts in enumerate(tf.index)}
day_end_map = {}
for d, gi in pd.Series(range(len(tf)), index=dates).groupby(level=0):
    day_end_map[d] = int(gi.iloc[-1])

ev = pd.read_csv(EV_CSV, parse_dates=["exp_ts"])
ev["year"] = ev["exp_ts"].dt.year
ev["drift_dir"] = np.where(ev["cls"] == "drift_up", 1,
                   np.where(ev["cls"] == "drift_dn", -1, 0))

CONFIGS = [
    ("flat_break", "fix1"), ("flat_break", "fix10"), ("flat_break", "eod"),
    ("aligned_cont", "brk10"), ("aligned_cont", "eod"),
    ("antidrift_fade_cc", "brk10"), ("antidrift_fade_cc", "eod"),
]

def get_trades(sig, mode):
    if sig == "flat_break":
        sub = ev[ev["cls"] == "flat"]; dir_col = "sign"
    elif sig == "aligned_cont":
        sub = ev[ev["align"] == "aligned"]; dir_col = "sign"
    else:
        sub = ev[(ev["drift_dir"] != 0) & (ev["dir_candle"] != 0)
                 & (ev["dir_candle"] == -ev["drift_dir"])]
        dir_col = "drift_dir"
    out = []
    for _, e in sub.iterrows():
        i = pos.get(e["exp_ts"])
        if i is None:
            continue
        day_end = day_end_map[dates[i]]
        if i + 1 > day_end:
            continue
        direction = int(e[dir_col])
        res = simulate_exit(o, h, l, c, i + 1, day_end, direction, e["atr"], mode)
        if res is None:
            continue
        exit_px, nb = res
        out.append((direction * (exit_px - o[i + 1]), e["atr"], e["year"]))
    return pd.DataFrame(out, columns=["gross", "atr", "year"])

def report(df, label):
    if len(df) < 30:
        print(f"  {label:22s} n={len(df)} (too few)")
        return
    net = df["gross"] - COST_PTS
    net_atr = net / df["atr"]
    t = net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))
    ta = net_atr.mean() / (net_atr.std(ddof=1) / np.sqrt(len(net_atr)))
    half = len(df) // 2
    yr = net.groupby(df["year"]).sum()
    nyr = df["year"].nunique()
    print(f"  {label:22s} n={len(df):5d} ({len(df)/nyr:5.1f}/yr over {nyr} yrs)  "
          f"net {net.mean():+.3f} pts (${net.mean()*50:+7.2f}) t={t:+.2f}  "
          f"netATR t={ta:+.2f}  win {(net>0).mean()*100:.0f}%  "
          f"1st {net.iloc[:half].mean():+.3f} / 2nd {net.iloc[half:].mean():+.3f}  "
          f"posYrs {(yr>0).mean()*100:.0f}%")

for sig, mode in CONFIGS:
    tr = get_trades(sig, mode)
    print(f"\n=== {sig} / {mode} ===")
    report(tr, "all")
    for thr in [1.5, 2.0, 3.0, 4.0]:
        report(tr[tr["atr"] >= thr], f"atr>={thr}")
    # which years does atr>=3 cover?
    cov = tr[tr["atr"] >= 3.0].groupby("year").size()
    print(f"  atr>=3 trades by year: " +
          " ".join(f"{y}:{n}" for y, n in cov.items()))
