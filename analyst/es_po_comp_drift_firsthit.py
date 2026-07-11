"""Addendum: path-order test for the compression drift study.
From expansion close, within the next 10 bars (same session): does price
touch +X ATR (expansion direction) before -X ATR (mean reversion)?
Also medians of signed returns by group.
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
from backtest_es_po_comp_drift import load_3m, add_indicators

EV = "/root/spy/analyst/es_po_comp_drift_events.csv"

tf = load_3m()
tf = add_indicators(tf)
tf["date"] = tf.index.date
ev = pd.read_csv(EV, parse_dates=["exp_ts"])

# index lookup
pos = {ts: i for i, ts in enumerate(tf.index)}
h = tf["h"].values; l = tf["l"].values
dates = tf["date"].values

rows = []
for X in [0.33, 0.5]:
    first_hit = []
    for _, e in ev.iterrows():
        i = pos.get(e["exp_ts"])
        if i is None:
            first_hit.append(np.nan); continue
        sign, base, atr = e["sign"], e["exp_close"], e["atr"]
        up = base + sign * X * atr   # continuation level (signed)
        dn = base - sign * X * atr   # reversion level
        res = np.nan
        d0 = dates[i]
        for j in range(i + 1, min(i + 11, len(h))):
            if dates[j] != d0:
                break
            if sign == 1:
                hit_c = h[j] >= up; hit_r = l[j] <= dn
            else:
                hit_c = l[j] <= up; hit_r = h[j] >= dn
            if hit_c and hit_r:
                res = 0.5  # ambiguous same bar
                break
            if hit_c:
                res = 1.0; break
            if hit_r:
                res = 0.0; break
        first_hit.append(res)
    ev[f"fh_{X}"] = first_hit

def grp(label, sub):
    print(f"\n{label} (n={len(sub)})")
    for X in [0.33, 0.5]:
        s = sub[f"fh_{X}"].dropna()
        amb = (s == 0.5).sum()
        dec = s[s != 0.5]
        print(f"  +/-{X} ATR bracket, 10 bars: continuation first "
              f"{(dec == 1).mean()*100:.1f}%  (decided n={len(dec)}, "
              f"ambiguous {amb}, no-hit {sub[f'fh_{X}'].isna().sum()})")
    for k in [1, 2, 3]:
        s = sub[f"ret_{k}"]
        print(f"  ret_{k}: median {s.median():+.3f}  >0: {(s > 0).mean()*100:.1f}%")

grp("FLAT", ev[ev["cls"] == "flat"])
grp("ALIGNED", ev[ev["align"] == "aligned"])
grp("OPPOSED", ev[ev["align"] == "opposed"])
grp("MIXED", ev[ev["cls"] == "mixed"])
grp("ALL", ev)
