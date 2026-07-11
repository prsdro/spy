#!/usr/bin/env python3
"""Do arm-then-trail and the straddle survive live entry semantics?

Applies the published exits — single leg 'trail30 after +100%' (SL-50% until
+100%, then trail 30% off prior-bar HWM) and the both-legs straddle version —
to the strict-live entry variants from scratch_po_comp_flip_rerun.py, and to
the published v3_eth immediate entries as the apples-to-apples baseline.
Headline population: W1, ATM (offset 0), intraday, uncensored.
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import entry_fill

STUDY = Path('/root/spy/analyst/po_comp_options')
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
cache = {}


def bars(k):
    if k not in cache:
        cache[k] = np.array(con.execute(
            "SELECT t,h,l FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return cache[k]


def armtrail(hi, lo, hold_pnl, arm=1.0, trail=0.30, init_sl=0.5):
    n = len(hi)
    if n == 0:
        return hold_pnl
    hwm_prev = np.empty(n)
    hwm_prev[0] = 1.0
    if n > 1:
        hwm_prev[1:] = np.maximum.accumulate(hi)[:-1]
    init = 1 - init_sl
    act = hwm_prev >= (1 + arm)
    level = np.where(act, hwm_prev * (1 - trail), init)
    m = lo <= level
    si = int(np.argmax(m)) if m.any() else -1
    if si >= 0:
        return float(level[si]) - 1
    return hold_pnl


def leg_pnl(r, hold_long):
    arr = bars(r.contract)
    if not len(arr):
        return None
    sig_ms = int(pd.Timestamp(r.entry_ts).timestamp() * 1000)
    f = entry_fill(np.c_[arr[:, 0], arr[:, 1], arr[:, 1], arr[:, 2], arr[:, 2]], sig_ms)
    if f is None:
        return None
    _, fill_ms = f
    expiry_ms = int((pd.Timestamp(r.expiry, tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > fill_ms) & (arr[:, 0] <= expiry_ms)]
    hi, lo = (p[:, 1] / r.entry_px, p[:, 2] / r.entry_px) if len(p) else \
             (np.array([]), np.array([]))
    return armtrail(hi, lo, hold_long)


def run(name, path, variant=None):
    t = pd.read_parquet(STUDY / path)
    if variant:
        t = t[t.variant == variant]
    t = t[(t.bucket == 'W1') & (t.offset == 0.0) & (~t.censored)
          & (~t.rolled_to_open)]
    t = t.drop_duplicates(subset=['ep_id', 'vehicle', 'contract'])
    if 'attempt_seq' in t.columns:
        t = t[t.attempt_seq == t.groupby('ep_id').attempt_seq.transform('min')]
    single, strad = [], []
    for ep, g in t.groupby('ep_id'):
        gl = g[g.vehicle == 'long']
        gs = g[g.vehicle == 'short']
        pl = ps = None
        if len(gl):
            r = gl.iloc[0]
            pl = leg_pnl(r, r.pnl_hold)
            if pl is not None:
                single.append(pl)
        if len(gl) and len(gs):
            r2 = gs.iloc[0]
            ps = leg_pnl(r2, -r2.pnl_hold)   # short rows store short-side hold
            if pl is not None and ps is not None:
                w1, w2 = gl.iloc[0].entry_px, r2.entry_px
                strad.append((pl * w1 + ps * w2) / (w1 + w2))
    for lbl, v in [('single leg arm-trail', pd.Series(single)),
                   ('straddle arm-trail  ', pd.Series(strad))]:
        v = v.dropna()
        if len(v) < 3:
            print(f"  {lbl}: n={len(v)}")
            continue
        tt = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
        pf = v[v > 0].sum() / max(1e-9, -v[v < 0].sum())
        print(f"  {lbl} n={len(v):4d} mean={100*v.mean():+6.2f}% "
              f"t={tt:+.2f} win={100*(v>0).mean():.0f}% PF={pf:.2f}")


for name, path, var in [
        ('PUBLISHED entries (v3_eth immediate) — repro', 'v3_eth_trades.parquet', 'immediate'),
        ('E: strict-live pure price', 'flip8_noflag_trades.parquet', None),
        ('A: intrabar flip flag, every poke', 'flip8_trades.parquet', None),
        ('D: close-confirmed', 'flip8_confirm_trades.parquet', None),
        ('F: full 5-bar box, then first poke', 'flip8_fullbox_trades.parquet', None)]:
    print(f"\n{name}")
    run(name, path, var)
con.close()
