#!/usr/bin/env python3
"""Codex round-2 recovery experiment: F locked 5-bar box straddle with
UNDERLYING-price-based exits (removes option-print HWM/outlier dependence).

Population: flip8_fullbox_trades.parquet, W1, ATM, intraday, uncensored,
both legs. Entry: first option print strictly after entry_ts, <=5 min wait.
Per leg (call/put independently), on underlying 5m closes after entry:
  arm   when favorable close excursion >= 0.75 * box_h from entry spot
  trail after arming: exit when excursion retraces to 50% of best excursion
  pre-arm invalidation: 5m close through the OPPOSITE side of the locked box
  time exit: expiry (last pre-expiry print)
Option execution: first option print within 15 min after the exit bar close
(else last prior print); spread haircut = 2x measured effective half-spread.
Pass bar (set in advance by Codex): straddle mean > +4% AND date-clustered
t > 1.5 on this orig8 cohort."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F

STUDY = Path('/root/spy/analyst/po_comp_options')
F.TOPUP = STUDY / 'underlying_5m_topup_v2.parquet'
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


tr = pd.read_parquet(STUDY / 'flip8_fullbox_trades.parquet')
tr = tr[(tr.bucket == 'W1') & (tr.offset == 0.0) & (~tr.censored)
        & (~tr.rolled_to_open)]
tr = tr.drop_duplicates(subset=['ep_id', 'vehicle', 'contract'])

m5 = {}
for tkr in tr.ticker.unique():
    df5 = F.load_5m(tkr).between_time('04:00', '19:55')
    m5[tkr] = {'t': df5.index.as_unit('ns').asi8 // 10**6,
               'cl': df5['close'].to_numpy(float)}
    print(f"5m ready {tkr}", flush=True)


def opt_exit_px(arr, ms):
    """First option print within 15 min after ms, else last prior print."""
    t = arr[:, 0]
    idx = np.where((t >= ms) & (t <= ms + 15 * 60000))[0]
    if len(idx):
        return arr[idx[0], 4]
    idx = np.where(t <= ms)[0]
    return arr[idx[-1], 4] if len(idx) else None


def leg(r, sign):
    """sign=+1 call leg (favorable=up), -1 put leg (favorable=down)."""
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
    M = m5[r['ticker']]
    sel = (M['t'] > e_ms) & (M['t'] <= expiry_ms)
    uc = M['cl'][sel]
    ut = M['t'][sel] + 300_000  # 5m bar close time
    spot0, bh = r['spot'], r['box_hi'] - r['box_lo']
    exc = sign * (uc - spot0)               # favorable close excursion
    inval_lvl = r['box_lo'] if sign == 1 else r['box_hi']
    exit_ms = None
    armed, best = False, 0.0
    for i in range(len(uc)):
        if not armed:
            if exc[i] >= 0.75 * bh:
                armed, best = True, exc[i]
            elif (sign == 1 and uc[i] < inval_lvl) or (sign == -1 and uc[i] > inval_lvl):
                exit_ms = ut[i]
                break
        else:
            best = max(best, exc[i])
            if exc[i] <= 0.5 * best:
                exit_ms = ut[i]
                break
    if exit_ms is None:
        exit_ms = expiry_ms
    xpx = opt_exit_px(arr, exit_ms)
    if xpx is None:
        return None
    return xpx / epx - 1 - 2 * half_spread_est(arr, e_ms, epx), epx


recs = []
for ep, g in tr.groupby('ep_id'):
    gl, gs = g[g.vehicle == 'long'], g[g.vehicle == 'short']
    if not (len(gl) and len(gs)):
        continue
    rl, rs = gl.iloc[0], gs.iloc[0]
    csign = 1 if rl.direction == 1 else -1   # long row = break-dir option
    a = leg(rl, csign)
    b = leg(rs, -csign)
    if a is None or b is None:
        continue
    recs.append({'ep_id': ep, 'ticker': rl.ticker, 'date': rl.entry_ts[:10],
                 'strad': (a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1]),
                 'single': a[0]})
d = pd.DataFrame(recs)
for col in ('strad', 'single'):
    v = d[col].dropna()
    n = len(v)
    tt = v.mean() / (v.std(ddof=1) / np.sqrt(n))
    gdt = v.groupby(d.date[v.index]).mean()
    tc = gdt.mean() / (gdt.std(ddof=1) / np.sqrt(len(gdt)))
    print(f"F + underlying-exit {col:6s}: n={n} mean={100*v.mean():+.2f}% "
          f"t={tt:+.2f} tclust={tc:+.2f} (d={len(gdt)}) win={100*(v>0).mean():.0f}%")
