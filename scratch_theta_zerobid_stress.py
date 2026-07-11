#!/usr/bin/env python3
"""Zero-bid exit stress (Codex finding #1). The base sims mark exits only on
two-sided quotes, which lets a held loser 'wait out' a no-bid market. Stress:
for hold-to-end exits, mark the exit at the RAW final row in the window —
bid 0 counts as ~worthless liquidation. Quantifies the optimism bound."""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
GRACE_S = 300
con = sqlite3.connect(f"file:{OUTDIR/'quotes.sqlite'}?mode=ro", uri=True)
con.execute('PRAGMA busy_timeout=60000')
legs = pd.read_sql("SELECT * FROM entry_legs WHERE right IN ('C','P')", con)
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].merge(
    legs.pivot_table(index='ep_id', columns='right', values='contract',
                     aggfunc='first').reset_index(), on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
ent['dir_contract'] = np.where(ent.direction == 1, ent.C, ent.P)
ent = ent.sort_values('dir_contract')

qcache = {}
def quotes_raw(cid):
    if cid not in qcache:
        if len(qcache) > 3000:
            qcache.clear()
        r = con.execute('SELECT t,bid,ask FROM quotes WHERE contract=? ORDER BY t',
                        (cid,)).fetchall()
        qcache[cid] = np.array(r, float) if r else np.zeros((0, 3))
    return qcache[cid]


rows = []
for r in ent.itertuples():
    cid = r.dir_contract
    if not isinstance(cid, str):
        continue
    raw = quotes_raw(cid)
    if not len(raw):
        continue
    two = raw[(raw[:, 1] > 0) & (raw[:, 2] > 0)]
    if not len(two):
        continue
    i = np.searchsorted(two[:, 0], r.t_s)
    if i >= len(two) or two[i, 0] > r.t_s + GRACE_S:
        continue
    mid0 = (two[i, 1] + two[i, 2]) / 2
    buy_half = mid0 + 0.5 * (two[i, 2] - mid0)
    # base exit: last two-sided bid-side price in window
    last2 = two[-1]
    m2 = (last2[1] + last2[2]) / 2
    sell_base = m2 - 0.5 * (m2 - last2[1])
    # stress exit: RAW final row; if no bid there, liquidation ~ its bid (0)
    lastr = raw[-1]
    sell_stress = lastr[1] if lastr[1] > 0 else 0.0
    if lastr[1] > 0 and lastr[2] > 0:
        mr = (lastr[1] + lastr[2]) / 2
        sell_stress = mr - 0.5 * (mr - lastr[1])
    rows.append({'pop': r.pop, 'direction': r.direction, 'boxw':
                 (r.box_hi - r.box_lo) / r.datr14_prior,
                 'date': str(r.ts.date()),
                 'base': sell_base / buy_half - 1,
                 'stress': sell_stress / buy_half - 1,
                 'final_nobid': bool(lastr[1] <= 0)})

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_zerobid_stress.parquet')


def st(v):
    v = pd.Series(v).dropna()
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    return f'n={len(v)} mean={100*v.mean():+.2f}% t={t:+.2f}'


print(f'trades: {len(d)}, final row is NO-BID on {100*d.final_nobid.mean():.1f}%')
for pop, g in d.groupby('pop'):
    print(f'\n{pop} hold-to-end, half-spread entries:')
    print(f'  base   {st(g.base)}')
    print(f'  stress {st(g.stress)}')
    fam = g[(g.direction == 1) & (g.boxw < 0.3)]
    print(f'  bull+narrow family: base {st(fam.base)} | stress {st(fam.stress)}')
con.close()
print('ZEROBID STRESS COMPLETE')
