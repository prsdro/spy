#!/usr/bin/env python3
"""Spread-conditioned cuts of the 7-year real-execution results.
For every entry, compute straddle P&L at full-spread AND midpoint execution
in one pass, keep the entry spread (live-visible), then bucket:
P&L by entry-spread bucket x execution, by year, and spread-by-year/name maps.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
ARM, TRAIL, INIT = 1.0, 0.30, 0.5
GRACE_S = 300

con = sqlite3.connect(OUTDIR / 'quotes.sqlite')
legs = pd.read_sql('SELECT * FROM entry_legs', con)
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].merge(
    legs.pivot_table(index='ep_id', columns='right', values='contract',
                     aggfunc='first').reset_index(), on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))

qcache = {}
def quotes(cid):
    if cid not in qcache:
        if len(qcache) > 4000:
            qcache.clear()
        r = con.execute('SELECT t,bid,ask FROM quotes WHERE contract=? ORDER BY t',
                        (cid,)).fetchall()
        q = np.array(r, float) if r else np.zeros((0, 3))
        q = q[(q[:, 1] > 0) & (q[:, 2] > 0)] if len(q) else q
        qcache[cid] = q
    return qcache[cid]


def leg(cid, t_s, exec_frac):
    q = quotes(cid)
    if not len(q):
        return None
    i = np.searchsorted(q[:, 0], t_s)
    if i >= len(q) or q[i, 0] > t_s + GRACE_S:
        return None
    mid0 = (q[i, 1] + q[i, 2]) / 2
    ask0 = mid0 + exec_frac * (q[i, 2] - mid0)
    spread = (q[i, 2] - q[i, 1]) / mid0 * 100
    path = q[i + 1:]
    sell0 = mid0 - exec_frac * (mid0 - q[i, 1])
    if not len(path):
        return ask0, sell0 / ask0 - 1, spread
    pmid = (path[:, 1] + path[:, 2]) / 2
    bid = pmid - exec_frac * (pmid - path[:, 1])
    hwm = np.empty(len(bid))
    hwm[0] = sell0
    if len(bid) > 1:
        hwm[1:] = np.maximum.accumulate(bid)[:-1]
        hwm[0] = sell0
    level = np.where(hwm >= (1 + ARM) * ask0, hwm * (1 - TRAIL), (1 - INIT) * ask0)
    m = bid <= level
    si = int(np.argmax(m)) if m.any() else -1
    px = bid[si] if si >= 0 else bid[-1]
    return ask0, px / ask0 - 1, spread


rows = []
for n, r in enumerate(ent.itertuples()):
    cc, cp = getattr(r, 'C', None), getattr(r, 'P', None)
    if not isinstance(cc, str) or not isinstance(cp, str):
        continue
    out = {}
    ok = True
    for ef, tag in [(1.0, 'full'), (0.0, 'mid')]:
        lc, lp = leg(cc, r.t_s, ef), leg(cp, r.t_s, ef)
        if lc is None or lp is None:
            ok = False
            break
        (ac, pc, sc), (ap, pp, sp) = lc, lp
        out[f'strad_{tag}'] = (pc * ac + pp * ap) / (ac + ap)
        out[f'single_{tag}'] = pc if r.direction == 1 else pp
        if tag == 'full':
            out['spread'] = (sc + sp) / 2
            out['prem_pct'] = (ac + ap) / r.spot * 100
    if not ok:
        continue
    out.update({'pop': r.pop, 'ticker': r.ticker, 'year': r.ts.year,
                'date': str(r.ts.date())})
    rows.append(out)
    if (n + 1) % 4000 == 0:
        print(f'...{n+1}/{len(ent)}', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_spread_cuts.parquet')


def stat(v):
    v = pd.Series(v).dropna()
    if len(v) < 20:
        return f'n={len(v):5d}  (thin)'
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    return f'n={len(v):5d} mean={100*v.mean():+7.2f}% t={t:+.2f} win={100*(v>0).mean():.0f}%'


g = d[d['pop'] == 'box30']
print(f'\nbox30 straddles scored both ways: {len(g)}')
print('\n== P&L by ENTRY SPREAD bucket (live-visible filter) ==')
print(f"{'spread bucket':16s} {'FULL-SPREAD exec':50s} {'MIDPOINT exec'}")
for lo, hi in [(0, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 99)]:
    m = (g.spread >= lo) & (g.spread < hi)
    print(f'  {lo}-{hi}%{"":9s} {stat(g[m].strad_full):50s} {stat(g[m].strad_mid)}')
print('\n== spread<1.5% cut, by year (FULL-SPREAD exec) ==')
tight = g[g.spread < 1.5]
for y, gy in tight.groupby('year'):
    print(f'  {y} {stat(gy.strad_full)}')
print('\n  pooled tight:', stat(tight.strad_full))
by = tight.groupby('date').strad_full.mean()
print(f'  date-clustered t: {by.mean()/(by.std(ddof=1)/np.sqrt(len(by))):+.2f} ({len(by)} dates)')
print('\n== median entry spread by year (all box30) ==')
print((g.groupby('year').spread.median()).round(2).to_string())
print('\n== tickers by share of entries with spread<1.5% (2024+) ==')
rec = g[g.year >= 2024]
print((rec.groupby('ticker').spread.apply(lambda s: (s < 1.5).mean())
       .sort_values(ascending=False).round(2).to_string()))
con.close()
print('\nSPREAD CUTS COMPLETE')
