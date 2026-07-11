#!/usr/bin/env python3
"""Apply the realistic-fill stack (strict-after entry, next-print exits,
effective-spread haircut) to the strict-live entry populations produced by
scratch_po_comp_flip_rerun.py (orig8 cohort, ETH events):
  flip8_noflag  = pure-price first poke of the running box (no flag knowledge)
  flip8_confirm = enter only at hourly close that breaks box + ends compression
  flip8_fullbox = wait for locked 5-bar box, then first poke
Same W1/ATM/intraday/uncensored population rules as the headline."""
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
            "SELECT t,o,h,l,c,COALESCE(n,1) FROM bars WHERE ticker=? ORDER BY t",
            (k,)).fetchall(), float)
    return cache[k]


def half_spread_est(arr, fill_ms, entry_px):
    t = arr[:, 0]
    near = arr[(t >= fill_ms - 45 * 60000) & (t <= fill_ms + 45 * 60000)]
    multi = near[near[:, 5] >= 2]
    if len(multi) >= 3:
        hs = np.median((multi[:, 2] - multi[:, 3]) / 2)
    else:
        c = near[:, 4]
        hs = np.nan
        if len(c) >= 6:
            d = np.diff(c)
            cov = np.cov(d[1:], d[:-1])[0, 1]
            hs = np.sqrt(-cov) if cov < 0 else np.nan
    if not np.isfinite(hs):
        hs = 0.03
    return max(hs, 0.01) / entry_px


def leg_real(r, hold_long):
    """Strict-after entry (<=5min) + arm-trail with next-print exit + spread."""
    arr = bars(r['contract'])
    if not len(arr):
        return None
    t = arr[:, 0]
    sig_ms = int(pd.Timestamp(r['entry_ts']).timestamp() * 1000)
    aft = np.where(t > sig_ms)[0]
    if not len(aft) or (t[aft[0]] - sig_ms) > 5 * 60000:
        return None
    e_ms, epx = t[aft[0]], arr[aft[0], 1]
    if epx <= 0.01:
        return None
    expiry_ms = int((pd.Timestamp(r['expiry'], tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    exit_mark = (hold_long + 1) * r['entry_px']
    p = arr[(t > e_ms) & (t <= expiry_ms)]
    hold = exit_mark / epx - 1
    if len(p):
        hi, lo, cl = p[:, 2] / epx, p[:, 3] / epx, p[:, 4] / epx
        n = len(hi)
        hwm = np.empty(n)
        hwm[0] = 1.0
        if n > 1:
            hwm[1:] = np.maximum.accumulate(hi)[:-1]
        level = np.where(hwm >= 2.0, hwm * 0.70, 0.5)
        m = lo <= level
        si = int(np.argmax(m)) if m.any() else -1
        pnl = float(min(level[si], cl[si])) - 1 if si >= 0 else hold
    else:
        pnl = hold
    return pnl - 2 * half_spread_est(arr, e_ms, epx), epx


def stats(v, dates, label):
    v = pd.Series(v, dtype=float).dropna()
    n = len(v)
    if n < 3:
        print(f"{label:46s} n={n}")
        return
    tt = v.mean() / (v.std(ddof=1) / np.sqrt(n))
    g = v.groupby(pd.Series(dates).loc[v.index].values).mean()
    tc = g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))
    print(f"{label:46s} n={n:4d} mean={100*v.mean():+6.2f}% t={tt:+5.2f} "
          f"tclust={tc:+5.2f} win={100*(v>0).mean():3.0f}%")


for name, path in [('E strict-live pure price (noflag)', 'flip8_noflag_trades.parquet'),
                   ('D close-confirmed', 'flip8_confirm_trades.parquet'),
                   ('F full 5-bar locked box', 'flip8_fullbox_trades.parquet'),
                   ('A intrabar flip flag', 'flip8_trades.parquet')]:
    try:
        tdf = pd.read_parquet(STUDY / path)
    except Exception as ex:
        print(f"{name}: unreadable ({ex})")
        continue
    tdf = tdf[(tdf.bucket == 'W1') & (tdf.offset == 0.0) & (~tdf.censored)
              & (~tdf.rolled_to_open)]
    tdf = tdf.drop_duplicates(subset=['ep_id', 'vehicle', 'contract'])
    singles, strads, dates_s, dates_b = [], [], [], []
    for ep, g in tdf.groupby('ep_id'):
        gl, gs = g[g.vehicle == 'long'], g[g.vehicle == 'short']
        if not len(gl):
            continue
        rl = gl.iloc[0]
        a = leg_real(rl, rl.pnl_hold)
        dt = rl.entry_ts[:10]
        if a is not None:
            singles.append(a[0])
            dates_s.append(dt)
        if len(gs) and a is not None:
            rs = gs.iloc[0]
            b = leg_real(rs, -rs.pnl_hold)
            if b is not None:
                strads.append((a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1]))
                dates_b.append(dt)
    print(f"\n{name} [{path}]")
    stats(pd.Series(singles), pd.Series(dates_s), '  single realistic (E1<=5m+X1+spread)')
    stats(pd.Series(strads), pd.Series(dates_b), '  straddle realistic')
