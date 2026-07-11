"""
Pre-registered NQ holdout for the EMA/PO ribbon-riding long.
Spec frozen in analyst/es_ema_po_ribbon_holdout_prereg.md BEFORE this run.

Config: arm entry | windows 09:30-12:00 & 15:00-15:45 ET | exit after 2
consecutive 3m closes below 10m EMA21 | stop 2.5x ATR14(3m) | ATR >= 2.6 NQ pts.
Cost 0.405 NQ pts RT. PASS = avg net > 0 AND day-clustered t >= 1.5.
"""

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
import backtest_es_ema_po_pullback_round5b as r5b
from backtest_es_ema_po_pullback_round5 import prep5, win_arr

NQ = "/srv/ftp/ossicones/futures-data/NQ_full_1min_continuous_ratio_adjusted.txt"
r5b.COST = 0.405
r5b.ATR_MIN = 2.6
PT_VALUE = 20.0

A = prep5(NQ)
m = win_arr(A, "both")
t = r5b.simulate5b(A, m, "arm", "r10m21", 2, 2.5)
t["entry_ts"] = pd.to_datetime(t["entry_ts"])
t["exit_ts"] = pd.to_datetime(t["exit_ts"])
t["year"] = t.entry_ts.dt.year
t.to_csv("/root/spy/analyst/es_ema_po_ribbon_holdout_nq_trades.csv", index=False)

pnl = t.pnl_pts
daily = t.groupby(t.entry_ts.dt.date).pnl_pts.sum()
tday = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))
wins = pnl[pnl > 0].sum(); losses = -pnl[pnl <= 0].sum()
yr = t.groupby("year").pnl_pts.agg(["size", "mean", "sum"])
eq = pnl.cumsum() * PT_VALUE
dd = (eq - eq.cummax()).min()

print(f"NQ HOLDOUT  n={len(t)} ({len(t)/t.year.nunique():.0f}/yr)")
print(f"  avg net    : {pnl.mean():+.3f} NQ pts (${pnl.mean()*PT_VALUE:+.2f}/trade)")
print(f"  t (day)    : {tday:.2f}")
print(f"  win rate   : {(pnl>0).mean()*100:.1f}%   PF {wins/losses:.3f}")
print(f"  total      : {pnl.sum():+,.0f} pts (${pnl.sum()*PT_VALUE:+,.0f})  maxDD ${dd:,.0f}")
print(f"  halves     : 08-19 {t[t.year<=2019].pnl_pts.mean():+.3f}  "
      f"20-26 {t[t.year>=2020].pnl_pts.mean():+.3f}")
print(f"  pos years  : {(yr['sum']>0).mean()*100:.0f}%")
print(f"  exits      : {t.reason.value_counts().to_dict()}")
print("\n  by year:")
for y, r in yr.iterrows():
    print(f"    {y}: n={r['size']:>4.0f}  avg {r['mean']:+7.3f}  tot {r['sum']:+9.1f}")

passed = pnl.mean() > 0 and tday >= 1.5
print(f"\n  RESULT: {'PASS' if passed else 'FAIL'} "
      f"(avg {pnl.mean():+.3f} > 0: {pnl.mean() > 0}; t {tday:.2f} >= 1.5: {tday >= 1.5})")
