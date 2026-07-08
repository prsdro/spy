#!/usr/bin/env python3
"""Validation of arm-then-trail (SL50 until +100%, then trail 30% off HWM):
(a) year splits, (b) per-ticker vs fixed bracket, (c) parameter neighborhood,
(d) conservative fills (exit at trigger-bar CLOSE print, not the level)."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import entry_fill

STUDY = Path('/root/spy/analyst/po_comp_options')
tr = pd.read_parquet(STUDY / 'v3_eth_trades.parquet')
tr = tr.drop_duplicates(subset=['ep_id', 'variant', 'direction', 'bucket',
                                'vehicle', 'contract'])
c = tr[(tr.variant == 'immediate') & (tr.vehicle == 'long') &
       (~tr.rolled_to_open) & (~tr.censored)].copy()

con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
cache = {}
def bars(k):
    if k not in cache:
        cache[k] = np.array(con.execute(
            "SELECT t,h,l,c FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return cache[k]


def arm_trail(hi, lo, cl, hold_pnl, arm, trail, init_sl=0.5, cap=None, real_fill=False):
    n = len(hi)
    if n == 0:
        return hold_pnl
    hwm = np.empty(n); hwm[0] = 1.0
    if n > 1:
        hwm[1:] = np.maximum.accumulate(hi)[:-1]
    level = np.where(hwm >= 1 + arm, hwm * (1 - trail), 1 - init_sl) if arm < 99 \
        else np.full(n, 1 - init_sl)
    m = lo <= level
    si = int(np.argmax(m)) if m.any() else -1
    ti = -1
    if cap:
        mc = hi >= 1 + cap
        ti = int(np.argmax(mc)) if mc.any() else -1
    if ti >= 0 and (si < 0 or ti < si):
        return cap
    if si >= 0:
        return (min(float(cl[si]), float(level[si])) if real_fill else float(level[si])) - 1
    return hold_pnl


CFG = {
    'fixed TP100|SL50': dict(arm=99, trail=0, cap=1.0),
    'arm100_trail30':   dict(arm=1.0, trail=0.30),
    'arm75_trail30':    dict(arm=0.75, trail=0.30),
    'arm150_trail30':   dict(arm=1.5, trail=0.30),
    'arm100_trail25':   dict(arm=1.0, trail=0.25),
    'arm100_trail35':   dict(arm=1.0, trail=0.35),
    'arm100_trail30_REALFILL': dict(arm=1.0, trail=0.30, real_fill=True),
    'fixed_REALFILL TP100|SL50': dict(arm=99, trail=0, cap=1.0, real_fill=True),
}

recs = []
for _, r in c.iterrows():
    arr = bars(r.contract)
    if not len(arr):
        continue
    sig_ms = int(pd.Timestamp(r.entry_ts).timestamp() * 1000)
    f = entry_fill(np.c_[arr[:, 0], arr[:, 1], arr[:, 1], arr[:, 2], arr[:, 2]], sig_ms)
    if f is None:
        continue
    _, fill_ms = f
    expiry_ms = int((pd.Timestamp(r.expiry, tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > fill_ms) & (arr[:, 0] <= expiry_ms)]
    hi, lo, cl = (p[:, 1] / r.entry_px, p[:, 2] / r.entry_px, p[:, 3] / r.entry_px) \
        if len(p) else (np.array([]),) * 3
    out = {'ep_id': r.ep_id, 'ticker': r.ticker, 'year1': r.entry_ts < '2025-07-07'}
    for name, kw in CFG.items():
        out[name] = arm_trail(hi, lo, cl, r.pnl_hold, **kw)
    recs.append(out)
con.close()

g = pd.DataFrame(recs)
def cs(df, col):
    ep = df.groupby('ep_id')[col].mean()
    n = len(ep)
    t = ep.mean() / (ep.std(ddof=1) / np.sqrt(n)) if n > 4 else np.nan
    return f"{ep.mean()*100:+6.1f}% (t={t:4.2f}, n={n})"

print("== (a) year split ==")
for name in ['fixed TP100|SL50', 'arm100_trail30']:
    print(f"{name:22s} Y1(24-25): {cs(g[g.year1], name)}   Y2(25-26): {cs(g[~g.year1], name)}")
print("\n== (b) per ticker: arm100_trail30 vs fixed ==")
wins = 0
for tkr, d in g.groupby('ticker'):
    a, f_ = d.groupby('ep_id')['arm100_trail30'].mean().mean(), \
            d.groupby('ep_id')['fixed TP100|SL50'].mean().mean()
    wins += a > f_
    print(f"  {tkr:6s} trail {a*100:+6.1f}%  fixed {f_*100:+6.1f}%  {'TRAIL' if a>f_ else 'fixed'}")
print(f"  trail beats fixed in {wins}/8 tickers")
print("\n== (c) parameter neighborhood ==")
for name in ['arm75_trail30', 'arm100_trail30', 'arm150_trail30',
             'arm100_trail25', 'arm100_trail35']:
    print(f"  {name:18s} {cs(g, name)}")
print("\n== (d) conservative fills (exit at trigger-bar close print) ==")
for name in ['arm100_trail30', 'arm100_trail30_REALFILL',
             'fixed TP100|SL50', 'fixed_REALFILL TP100|SL50']:
    print(f"  {name:28s} {cs(g, name)}")
