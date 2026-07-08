#!/usr/bin/env python3
"""TP x SL sensitivity for the headline cell (ETH intraday immediate longs),
per ticker. Everything else fixed: same legs, same fills; exits re-simulated
on option minute bars. Tie (same minute hits both) -> stop first."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import entry_fill

STUDY = Path('/root/spy/analyst/po_comp_options')
TPS = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00]
SLS = [0.25, 0.40, 0.50, 0.60, 0.75, None]   # None = no stop (hold as floor)

tr = pd.read_parquet(STUDY / 'v3_eth_trades.parquet')
tr = tr.drop_duplicates(subset=['ep_id', 'variant', 'direction', 'bucket',
                                'vehicle', 'contract'])
c = tr[(tr.variant == 'immediate') & (tr.vehicle == 'long') &
       (~tr.rolled_to_open) & (~tr.censored)].copy()
print(f"legs: {len(c)}, boxes: {c.ep_id.nunique()}")

con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
cache = {}
def bars(k):
    if k not in cache:
        cache[k] = np.array(con.execute(
            "SELECT t,o,h,l,c FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(),
            float)
    return cache[k]

recs = []
for _, r in c.iterrows():
    arr = bars(r.contract)
    if not len(arr):
        continue
    sig_ms = int(pd.Timestamp(r.entry_ts).timestamp() * 1000)
    f = entry_fill(arr, sig_ms)
    if f is None:
        continue
    entry_px, fill_ms = f
    if abs(entry_px - r.entry_px) > 0.01:   # guard: same fill as v3
        entry_px = r.entry_px
    expiry_ms = int((pd.Timestamp(r.expiry, tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > fill_ms) & (arr[:, 0] <= expiry_ms)]
    hold_mark = entry_px * (1 + r.pnl_hold)
    t_, hi, lo = (p[:, 0], p[:, 2], p[:, 3]) if len(p) else \
                 (np.array([]), np.array([]), np.array([]))
    tp_hit = {tp: (t_[hi >= entry_px * (1 + tp)][0]
                   if (hi >= entry_px * (1 + tp)).any() else np.inf) for tp in TPS}
    sl_hit = {sl: (t_[lo <= entry_px * (1 - sl)][0]
                   if sl is not None and (lo <= entry_px * (1 - sl)).any() else np.inf)
              for sl in SLS}
    out = {'ep_id': r.ep_id, 'ticker': r.ticker}
    for tp in TPS:
        for sl in SLS:
            th, sh = tp_hit[tp], sl_hit[sl]
            if sh <= th:                      # stop first (ties -> stop)
                pnl = -sl if sh < np.inf else (hold_mark / entry_px - 1)
            elif th < np.inf:
                pnl = tp
            else:
                pnl = hold_mark / entry_px - 1
            out[f"{int(tp*100)}|{'H' if sl is None else int(sl*100)}"] = pnl
    recs.append(out)
con.close()
g = pd.DataFrame(recs)
g.to_parquet(STUDY / 'tp_sl_grid_legs.parquet')

cols = [f"{int(tp*100)}|{'H' if sl is None else int(sl*100)}" for tp in TPS for sl in SLS]
def grid(df):
    ep = df.groupby('ep_id')[cols].mean()
    return ep.mean() * 100, ep

print("\n=== POOLED (all 8 tickers) — avg % premium per trade ===")
m, ep = grid(g)
tab = pd.DataFrame({f"TP{int(tp*100)}": [round(m[f"{int(tp*100)}|{'H' if sl is None else int(sl*100)}"], 1)
                    for sl in SLS] for tp in TPS},
                   index=[f"SL{'-none' if sl is None else int(sl*100)}" for sl in SLS])
print(tab.to_string())
best = m.idxmax()
n = ep.shape[0]
tstat = ep[best].mean() / (ep[best].std(ddof=1) / np.sqrt(n)) * 1
print(f"pooled best: {best} -> {m[best]:.1f}%/trade (t={tstat:.2f}, n={n})")

print("\n=== per-ticker best cells (top 3 each) ===")
for tkr, df in g.groupby('ticker'):
    m2, ep2 = grid(df)
    top = m2.sort_values(ascending=False).head(3)
    fixed = m2.get('100|50', np.nan)
    print(f"{tkr:6s} baseline TP100|SL50={fixed:+.1f}%  best: " +
          "  ".join(f"{k}={v:+.1f}%" for k, v in top.items()) +
          f"  (n={ep2.shape[0]})")
