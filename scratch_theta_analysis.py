#!/usr/bin/env python3
"""Real-execution 7-year analysis of the Bilbo box options recipe.

Fills: BUY at the ASK on the first quote minute at/after the signal (drop if
none within 5 minutes). Exits: everything marked on the BID — the initial
−50% stop, the +100% arm (bid must reach 2× the entry ask), the 30%-off-HWM
trail (HWM tracked on prior-minute bids), and exit AT THE BID of the breach
minute (not at the level). Expiry fallback: last bid. No level fills, no
spread proxy — actual NBBO throughout.

Outputs analyst/po_comp_options/theta/theta_trades.parquet (per-entry results)
and prints: yearly + pooled single/straddle (plain + date-clustered t),
walk-forward trailing-6mo ATR%% vol screen, per-name half-year regime map,
and entry spread stats.
"""
import os
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
DB = OUTDIR / 'quotes.sqlite'
ARM, TRAIL, INIT = 1.0, 0.30, 0.5
FILL_GRACE_MS = 5 * 60_000
# EXEC: what fraction of the half-spread you pay each way.
#   1.0 = buy full ask / sell full bid (worst case)
#   0.5 = halfway between mid and the touch (decent limit-order execution)
#   0.0 = midpoint fills both ways (best realistic case)
EXEC = float(os.environ.get('EXEC', '1.0'))

con = sqlite3.connect(DB)
legs = pd.read_sql('SELECT * FROM entry_legs', con)
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].merge(
    legs.pivot_table(index='ep_id', columns='right', values='contract',
                     aggfunc='first').reset_index(), on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
# quotes table t is epoch SECONDS (pandas us-resolution / 10**6 in the pull)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
FILL_GRACE_S = 5 * 60
print(f'entries with contracts: {len(ent)}', flush=True)

qcache = {}
def quotes(cid):
    if cid not in qcache:
        if len(qcache) > 4000:
            qcache.clear()
        r = con.execute('SELECT t,bid,ask FROM quotes WHERE contract=? ORDER BY t',
                        (cid,)).fetchall()
        qcache[cid] = np.array(r, float) if r else np.zeros((0, 3))
    return qcache[cid]


def leg_result(cid, t_s):
    """(entry_ask, pnl, spread_pct) with bid-marked arm-trail; None if no fill.
    Only two-sided rows (bid>0 and ask>0) count: bid=0 means no market to
    sell into, not a price of zero."""
    q = quotes(cid)
    if not len(q):
        return None
    q = q[(q[:, 1] > 0) & (q[:, 2] > 0)]
    if not len(q):
        return None
    i = np.searchsorted(q[:, 0], t_s)
    if i >= len(q) or q[i, 0] > t_s + FILL_GRACE_S:
        return None
    mid0 = (q[i, 1] + q[i, 2]) / 2
    ask0 = mid0 + EXEC * (q[i, 2] - mid0)          # effective buy price
    spread = (q[i, 2] - q[i, 1]) / mid0 * 100
    path = q[i + 1:]
    if not len(path):
        sell0 = mid0 - EXEC * (mid0 - q[i, 1])
        return ask0, sell0 / ask0 - 1, spread
    pmid = (path[:, 1] + path[:, 2]) / 2
    bid = pmid - EXEC * (pmid - path[:, 1])        # effective sell prices
    sell0 = mid0 - EXEC * (mid0 - q[i, 1])
    hwm = np.empty(len(bid))
    hwm[0] = sell0
    if len(bid) > 1:
        hwm[1:] = np.maximum.accumulate(bid)[:-1]
        hwm[0] = sell0
    armed = hwm >= (1 + ARM) * ask0
    level = np.where(armed, hwm * (1 - TRAIL), (1 - INIT) * ask0)
    m = bid <= level
    si = int(np.argmax(m)) if m.any() else -1
    exit_px = bid[si] if si >= 0 else bid[-1]
    return ask0, exit_px / ask0 - 1, spread


rows = []
for n, r in enumerate(ent.itertuples()):
    cc = getattr(r, 'C', None)
    cp = getattr(r, 'P', None)
    if not isinstance(cc, str) or not isinstance(cp, str):
        continue
    lc = leg_result(cc, r.t_s)
    lp = leg_result(cp, r.t_s)
    if lc is None or lp is None:
        continue
    (ac, pc, sc), (ap, pp, sp) = lc, lp
    single = pc if r.direction == 1 else pp
    strad = (pc * ac + pp * ap) / (ac + ap)
    rows.append({'pop': r.pop, 'ticker': r.ticker, 'ep_id': r.ep_id,
                 'entry_ts': r.entry_ts, 'date': str(r.ts.date()),
                 'single': single, 'straddle': strad,
                 'spread_pct': np.nanmean([sc, sp]),
                 'datr_pct': r.datr14_prior / r.spot * 100})
    if (n + 1) % 2000 == 0:
        print(f'...{n+1}/{len(ent)}', flush=True)

d = pd.DataFrame(rows)
d['ts'] = pd.to_datetime(d.entry_ts.map(pd.Timestamp), utc=True)
d['year'] = d.ts.dt.year
d['month'] = d.ts.dt.tz_convert('America/New_York').dt.to_period('M')
d['half'] = d.ts.dt.year.astype(str) + np.where(d.ts.dt.month <= 6, 'H1', 'H2')
d.drop(columns=['ts']).to_parquet(OUTDIR / 'theta_trades.parquet')
print(f'\nscored entries: {len(d)} (fill rate {len(d)/len(ent):.0%}), '
      f'median entry spread {d.spread_pct.median():.1f}%')


def stat(v, dates=None):
    v = pd.Series(v).dropna()
    if len(v) < 3:
        return f'n={len(v)}'
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    s = f'n={len(v):5d} mean={100*v.mean():+7.2f}% t={t:+.2f} win={100*(v>0).mean():.0f}%'
    if dates is not None:
        by = pd.DataFrame({'v': v, 'd': dates}).groupby('d').v.mean()
        tc = by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))
        s += f' tclust={tc:+.2f}'
    return s


for pop, g in d.groupby('pop'):
    print(f'\n===== {pop} — REAL EXECUTION (ask entries, bid exits) =====')
    print('  single  ', stat(g.single, g.date))
    print('  straddle', stat(g.straddle, g.date))
    print('  by year (straddle):')
    for y, gy in g.groupby('year'):
        print(f'    {y}', stat(gy.straddle))
    # walk-forward trailing-6mo vol screen, monthly refresh, top-5
    months = sorted(g.month.unique())
    test = [m for m in months if m >= months[0] + 6]
    picks, base = [], []
    for m in test:
        w = g[(g.month >= m - 6) & (g.month < m)]
        rank = w.groupby('ticker').datr_pct.median().sort_values(ascending=False)
        cur = g[g.month == m]
        picks.extend(cur[cur.ticker.isin(rank.index[:5])].straddle.tolist())
        base.extend(cur.straddle.tolist())
    print('  walk-forward vol screen (top-5, monthly refresh):')
    print('    screened', stat(picks))
    print('    basket  ', stat(base))

# per-name half-year regime map (box30 straddle)
g = d[d['pop'] == 'box30']
piv = g.pivot_table(index='ticker', columns='half', values='straddle',
                    aggfunc='mean')
print('\n===== per-name half-year regime map (box30 straddle, mean %) =====')
print((100 * piv).round(1).to_string())
con.close()
print('\nTHETA ANALYSIS COMPLETE')
