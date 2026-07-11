"""
Does a violent downside drop that also reaches the -0.5 ATR ("Put Midrange")
WITHIN THE OPEN WEEK make the Swing GG (-61.8%) more likely to complete?

Fair-window basis (clock-truncated opens dropped), matching the published study.
-0.5 ATR sits INSIDE the gate (between -0.382 open and -0.618 complete), so this
conditions on how hard the drop kept going in the opening week — an intra-week
confirmation, not a pure at-open signal. We also report how often the gate had
ALREADY completed within that week, to gauge how mechanical the condition is.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from backtest_spx_double_gg_revert import read_firstrate_zip, find_one
from backtest_swing_gg_wom import build_months, FIBS, HORIZON_DAYS

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
    n = len(g)
    week = ts.to_period("W")                  # Mon-Sun weekly bucket per session

    lvl_open = pmc - FIBS["0382"] * atr
    lvl_05   = pmc - 0.5 * atr
    lvl_comp = pmc - FIBS["0618"] * atr
    lvl_trig = pmc - FIBS["trig"] * atr

    open_hits = lows <= lvl_open
    if not open_hits.any():
        continue
    oi = int(np.argmax(open_hits))
    remaining = n - oi
    completes = bool((lows[oi:] <= lvl_comp).any())

    # speed: sessions from first put-trigger touch to gate open (this month)
    trig_hits = lows[:oi + 1] <= lvl_trig
    days_trig_to_open = (oi - int(np.argmax(trig_hits))) if trig_hits.any() else None

    # open-week window: sessions in the SAME calendar week as the open, on/after it
    idx = np.arange(n)
    in_open_week = (week == week[oi]) & (idx >= oi)
    reached_05_week   = bool((lows[in_open_week] <= lvl_05).any())
    reached_05_sameday = bool(lows[oi] <= lvl_05)
    completed_in_week  = bool((lows[in_open_week] <= lvl_comp).any())

    rows.append(dict(direction="down", remaining=remaining,
                     fair=remaining >= HORIZON_DAYS, completes=completes,
                     fast=(days_trig_to_open is not None and days_trig_to_open <= 1),
                     reached_05_week=reached_05_week,
                     reached_05_sameday=reached_05_sameday,
                     completed_in_week=completed_in_week))

ev = pd.DataFrame(rows)
dn = ev[(ev.direction == "down") & ev.fair].copy()
base = dn.completes.mean() * 100
print(f"Fair-window downside gates: n={len(dn)}  base completion={base:.1f}%\n")

def rate(mask, label):
    s = dn[mask]
    if len(s) == 0:
        print(f"  {label:<46} n=  0   --"); return
    c = s.completes.mean() * 100
    print(f"  {label:<46} n={len(s):>3}  {c:5.1f}%  ({s.completes.sum()} of {len(s)})  lift {c-base:+.1f}")

print("Reached -0.5 ATR within the OPEN WEEK?")
rate(dn.reached_05_week,  "  YES — hit -0.5 in open week")
rate(~dn.reached_05_week, "  NO  — did not reach -0.5 in open week")
print()
print("Sub-split of the YES bucket (how mechanical is it?):")
rate(dn.reached_05_week & dn.completed_in_week,  "  hit -0.5 AND already completed in-week")
rate(dn.reached_05_week & ~dn.completed_in_week, "  hit -0.5 but NOT yet completed that week")
print("    ^ the second row is the honest test: -0.5 reached, gate still open at week end.\n")

print("Same-day violence — reached -0.5 ATR on the OPEN DAY itself:")
rate(dn.reached_05_sameday,  "  YES — -0.5 tagged same day as open")
rate(~dn.reached_05_sameday, "  NO")
print()
print("Cross with traversal speed (put-trigger -> gate):")
rate(dn.fast & dn.reached_05_week,   "  fast (<=1d) & hit -0.5 in week")
rate(dn.fast & ~dn.reached_05_week,  "  fast (<=1d) & no -0.5 in week")
rate(~dn.fast & dn.reached_05_week,  "  slow (>=2d) & hit -0.5 in week")
rate(~dn.fast & ~dn.reached_05_week, "  slow (>=2d) & no -0.5 in week")
