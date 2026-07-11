#!/usr/bin/env python3
"""Directional (single-leg) parameter tuning on 7-year NBBO data.
Computes per-entry single-leg P&L for a grid of exits x execution levels,
with all live-knowable metadata for filtering (spread, era, pop, direction,
box width, grey bars, ticker). Saves theta_directional.parquet; the grid
search runs on the saved frame.
Exits: ref trail30 | trail50 | no-trail SL50 | no-trail SL35 | no-stop hold.
Exec: full spread, half, mid.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
GRACE_S = 300
EXITS = [
    ('trail30', 1.00, 0.30, 0.50),
    ('trail50', 1.00, 0.50, 0.50),
    ('hold_sl50', None, None, 0.50),
    ('hold_sl35', None, None, 0.65),
    ('hold_nostop', None, None, None),
]
EXECS = [('full', 1.0), ('half', 0.5), ('mid', 0.0)]

con = sqlite3.connect(OUTDIR / 'quotes.sqlite')
legs = pd.read_sql('SELECT * FROM entry_legs', con)
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].merge(
    legs.pivot_table(index='ep_id', columns='right', values='contract',
                     aggfunc='first').reset_index(), on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
ent['dir_contract'] = np.where(ent.direction == 1, ent.C, ent.P)
ent = ent.sort_values('dir_contract')

qcache = {}
def quotes(cid):
    if cid not in qcache:
        if len(qcache) > 3000:
            qcache.clear()
        r = con.execute('SELECT t,bid,ask FROM quotes WHERE contract=? ORDER BY t',
                        (cid,)).fetchall()
        q = np.array(r, float) if r else np.zeros((0, 3))
        q = q[(q[:, 1] > 0) & (q[:, 2] > 0)] if len(q) else q
        qcache[cid] = q
    return qcache[cid]


rows = []
for n, r in enumerate(ent.itertuples()):
    cid = r.dir_contract
    if not isinstance(cid, str):
        continue
    q = quotes(cid)
    if not len(q):
        continue
    i = np.searchsorted(q[:, 0], r.t_s)
    if i >= len(q) or q[i, 0] > r.t_s + GRACE_S:
        continue
    rec = {'pop': r.pop, 'ticker': r.ticker, 'direction': r.direction,
           'date': str(r.ts.date()), 'year': r.ts.year,
           'grey': min(int(r.grey_bars), 8),
           'boxw': (r.box_hi - r.box_lo) / r.datr14_prior,
           'datr_pct': r.datr14_prior / r.spot * 100,
           'spread': (q[i, 2] - q[i, 1]) / ((q[i, 1] + q[i, 2]) / 2) * 100}
    path = q[i + 1:]
    for etag, ef in EXECS:
        mid0 = (q[i, 1] + q[i, 2]) / 2
        buy = mid0 + ef * (q[i, 2] - mid0)
        sell0 = mid0 - ef * (mid0 - q[i, 1])
        if not len(path):
            for xl, *_ in EXITS:
                rec[f'{xl}|{etag}'] = sell0 / buy - 1
            continue
        pmid = (path[:, 1] + path[:, 2]) / 2
        sell = pmid - ef * (pmid - path[:, 1])
        hwm = np.empty(len(sell))
        hwm[0] = sell0
        if len(sell) > 1:
            hwm[1:] = np.maximum.accumulate(sell)[:-1]
            hwm[0] = sell0
        for xl, arm, trail, init in EXITS:
            if init is None:
                rec[f'{xl}|{etag}'] = sell[-1] / buy - 1
                continue
            if arm is None:
                level = np.full(len(sell), (1 - init) * buy)
            else:
                level = np.where(hwm >= (1 + arm) * buy, hwm * (1 - trail),
                                 (1 - init) * buy)
            m = sell <= level
            si = int(np.argmax(m)) if m.any() else -1
            rec[f'{xl}|{etag}'] = (sell[si] if si >= 0 else sell[-1]) / buy - 1
    rows.append(rec)
    if (n + 1) % 4000 == 0:
        print(f'...{n+1}/{len(ent)}', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_directional.parquet')
print(f'saved {len(d)} directional trades -> theta_directional.parquet')
con.close()
print('DIRECTIONAL BASE COMPLETE')
