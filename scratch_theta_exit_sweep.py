#!/usr/bin/env python3
"""Exit re-tune for a spread-aware world, on the 7-year NBBO data.
The published arm/trail params were tuned on level fills. Wider trails and
different arms churn less through the spread. Sweep on box30 straddles,
scored at full-spread and midpoint execution, all trades + the 1-2%%
entry-spread band.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
GRACE_S = 300
VARIANTS = [   # (arm, trail, init_sl, label)
    (1.00, 0.30, 0.50, 'ref arm100/trail30/sl50'),
    (1.00, 0.40, 0.50, 'trail40'),
    (1.50, 0.40, 0.50, 'arm150/trail40'),
    (0.75, 0.40, 0.50, 'arm75/trail40'),
    (1.00, 0.50, 0.50, 'trail50'),
    (1.00, 0.30, 0.65, 'wider stop sl35'),
    (None, None, 0.50, 'no-trail: hold to end, sl50'),
]

con = sqlite3.connect(OUTDIR / 'quotes.sqlite')
legs = pd.read_sql('SELECT * FROM entry_legs', con)
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'box30')].merge(
    legs.pivot_table(index='ep_id', columns='right', values='contract',
                     aggfunc='first').reset_index(), on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
ent = ent.sort_values('C')          # cache locality

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


def leg_all(cid, t_s, exec_frac):
    """Returns (entry_px, spread, dict label->pnl) or None."""
    q = quotes(cid)
    if not len(q):
        return None
    i = np.searchsorted(q[:, 0], t_s)
    if i >= len(q) or q[i, 0] > t_s + GRACE_S:
        return None
    mid0 = (q[i, 1] + q[i, 2]) / 2
    buy = mid0 + exec_frac * (q[i, 2] - mid0)
    spread = (q[i, 2] - q[i, 1]) / mid0 * 100
    path = q[i + 1:]
    sell0 = mid0 - exec_frac * (mid0 - q[i, 1])
    out = {}
    if not len(path):
        for *_ , lbl in VARIANTS:
            out[lbl] = sell0 / buy - 1
        return buy, spread, out
    pmid = (path[:, 1] + path[:, 2]) / 2
    sell = pmid - exec_frac * (pmid - path[:, 1])
    hwm = np.empty(len(sell))
    hwm[0] = sell0
    if len(sell) > 1:
        hwm[1:] = np.maximum.accumulate(sell)[:-1]
        hwm[0] = sell0
    for arm, trail, init, lbl in VARIANTS:
        if arm is None:
            level = np.full(len(sell), (1 - init) * buy)
        else:
            level = np.where(hwm >= (1 + arm) * buy, hwm * (1 - trail),
                             (1 - init) * buy)
        m = sell <= level
        si = int(np.argmax(m)) if m.any() else -1
        out[lbl] = (sell[si] if si >= 0 else sell[-1]) / buy - 1
    return buy, spread, out


rows = []
for n, r in enumerate(ent.itertuples()):
    cc, cp = getattr(r, 'C', None), getattr(r, 'P', None)
    if not isinstance(cc, str) or not isinstance(cp, str):
        continue
    rec = {'date': str(r.ts.date())}
    ok = True
    for ef, tag in [(1.0, 'full'), (0.0, 'mid')]:
        lc = leg_all(cc, r.t_s, ef)
        lp = leg_all(cp, r.t_s, ef)
        if lc is None or lp is None:
            ok = False
            break
        (bc, sc, oc), (bp, sp, op) = lc, lp
        for *_ , lbl in VARIANTS:
            rec[f'{lbl}|{tag}'] = (oc[lbl] * bc + op[lbl] * bp) / (bc + bp)
        if tag == 'full':
            rec['spread'] = (sc + sp) / 2
    if ok:
        rows.append(rec)
    if (n + 1) % 4000 == 0:
        print(f'...{n+1}/{len(ent)}', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_exit_sweep.parquet')


def stat(v, dates):
    v = pd.Series(v).dropna()
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    by = pd.DataFrame({'v': v, 'd': dates}).groupby('d').v.mean()
    tc = by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))
    return f'mean={100*v.mean():+7.2f}% t={t:+.2f} tclust={tc:+.2f}'


band = (d.spread >= 1) & (d.spread < 2)
print(f'\nbox30 straddles: {len(d)} all, {band.sum()} in 1-2%% spread band')
for *_, lbl in VARIANTS:
    print(f'\n{lbl}')
    for tag in ['full', 'mid']:
        print(f'  {tag:5s} all : {stat(d[f"{lbl}|{tag}"], d.date)}')
        print(f'  {tag:5s} band: {stat(d[band][f"{lbl}|{tag}"], d[band].date)}')
con.close()
print('\nEXIT SWEEP COMPLETE')
