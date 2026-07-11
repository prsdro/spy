"""
Downside Swing GG completion conditioned on:
  - opens on a FRIDAY,
  - during WEEK 1 of the month (days 1-7),
  - and CLOSES below -0.59 ATR on that open day (a strong close into the gate,
    i.e. not bought back -- the gate completes at -0.618, so -0.59 = closing
    almost on the completion line).
Fair-window basis (clock-truncated opens dropped), downside only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one
from backtest_swing_gg_wom import build_months, FIBS, HORIZON_DAYS, week_of_month

daily = read_firstrate_zip(find_one("SPX_full_1day_*.zip"), intraday=False)
d = daily.copy()
d["month"] = d["timestamp"].dt.to_period("M")
months = build_months(daily)
mo = months.copy(); mo.index = mo.index.to_period("M")

rows = []
for period, g in d.groupby("month", sort=True):
    if period not in mo.index:
        continue
    m = mo.loc[period]
    pmc, atr = m["pmc"], m["atr_14"]
    if pd.isna(pmc) or pd.isna(atr) or atr <= 0:
        continue
    g = g.sort_values("timestamp")
    ts = pd.to_datetime(g["timestamp"].to_numpy())
    lows = g["low"].to_numpy()
    closes = g["close"].to_numpy()
    n = len(g)

    lvl_open = pmc - FIBS["0382"] * atr
    lvl_comp = pmc - FIBS["0618"] * atr
    lvl_59   = pmc - 0.59 * atr

    open_hits = lows <= lvl_open
    if not open_hits.any():
        continue
    oi = int(np.argmax(open_hits))
    remaining = n - oi
    completes = bool((lows[oi:] <= lvl_comp).any())

    rows.append(dict(
        fair=remaining >= HORIZON_DAYS,
        completes=completes,
        wom=week_of_month(int(ts[oi].day)),
        is_friday=(ts[oi].weekday() == 4),
        close_below_59=bool(closes[oi] <= lvl_59),
        close_below_open=bool(closes[oi] <= lvl_open),  # held the gate-open into close
    ))

ev = pd.DataFrame(rows)
dn = ev[ev.fair].copy()
base = dn.completes.mean() * 100
print(f"Fair-window downside gates: n={len(dn)}  base completion={base:.1f}%\n")

def rate(mask, label):
    s = dn[mask]
    if len(s) == 0:
        print(f"  {label:<44} n=  0   --"); return
    c = s.completes.mean() * 100
    flag = "*" if len(s) < 15 else " "
    print(f" {flag}{label:<44} n={len(s):>3}  {c:5.1f}%  ({s.completes.sum()} of {len(s)})  lift {c-base:+.1f}")

print("Day-of-week / week-of-month of the open:")
rate(dn.is_friday,            "Friday open (any week)")
rate(~dn.is_friday,           "non-Friday open")
rate(dn.wom == 1,             "Week-1 open (any day)")
rate(dn.is_friday & (dn.wom == 1), "Friday open in Week 1")
print()
print("Strong-close signal (close on the OPEN day, known at that close):")
rate(dn.close_below_59,       "close <= -0.59 ATR on open day (deep)")
rate(dn.close_below_open & ~dn.close_below_59, "close between -0.382 and -0.59 (held gate)")
rate(~dn.close_below_open,    "close back above -0.382 (rejected)")
print()
print("Stacked — the asked setup and its building blocks:")
rate(dn.is_friday & (dn.wom == 1) & dn.close_below_59, "Friday + Week 1 + close <= -0.59 ATR")
rate((dn.wom == 1) & dn.close_below_59, "Week 1 + close <= -0.59 ATR (drop Friday req.)")
rate(dn.is_friday & dn.close_below_59,  "Friday + close <= -0.59 ATR (drop week req.)")
