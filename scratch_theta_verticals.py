#!/usr/bin/env python3
"""Debit vertical spreads on the 7-year NBBO set — the anti-lottery
directional structure. PRE-REGISTERED spec (declared before pricing):
  Long W1 ATM leg in break direction (existing quotes), short leg at strike
  nearest spot + direction*0.75*dATR (SC/SP pull). Entry at the confirmed
  close-confirmation signal. PRIMARY exit: hold to window end (~expiry).
  SECONDARY (declared): exit both legs when a 5m underlying close crosses the
  short strike (target-touch). P&L as % of debit paid. Report full/half/mid
  execution, era split, spread bands, monthly texture, distribution.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
GRACE_S = 300

con = sqlite3.connect(f"file:{OUTDIR/'quotes.sqlite'}?mode=ro", uri=True)
con.execute('PRAGMA busy_timeout=60000')
legs = pd.read_sql('SELECT * FROM entry_legs', con)
piv = legs.pivot_table(index='ep_id', columns='right', values='contract',
                       aggfunc='first').reset_index()
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].merge(piv, on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
ent['long_c'] = np.where(ent.direction == 1, ent.get('C'), ent.get('P'))
sc = ent.get('SC')
sp = ent.get('SP')
ent['short_c'] = np.where(ent.direction == 1, sc, sp)
ent = ent[ent.long_c.notna() & ent.short_c.notna()]
print(f'entries with both legs: {len(ent)}', flush=True)


def load5(tkr):
    frames = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            frames.append(pd.read_parquet(p, columns=['metric_ts_et', 'close']))
    for top in ['underlying_5m_topup_v2.parquet', 'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            frames.append(t[['metric_ts_et', 'close']])
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True)
    df = df.drop_duplicates(subset='ts').sort_values('ts')
    return (df.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            df.close.to_numpy(float))


U = {t: load5(t) for t in ent.ticker.unique()}
print('underlying loaded', flush=True)

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


def px(q, idx, ef, side):
    m = (q[idx, 1] + q[idx, 2]) / 2
    return m + ef * (q[idx, 2] - m) if side == 'buy' else m - ef * (m - q[idx, 1])


rows = []
for r in ent.itertuples():
    qL, qS = quotes(r.long_c), quotes(r.short_c)
    if not len(qL) or not len(qS):
        continue
    iL = np.searchsorted(qL[:, 0], r.t_s)
    iS = np.searchsorted(qS[:, 0], r.t_s)
    if iL >= len(qL) or iS >= len(qS) or qL[iL, 0] > r.t_s + GRACE_S \
            or qS[iS, 0] > r.t_s + GRACE_S:
        continue
    k_short = float(r.short_c.split('|')[2])
    k_long = float(r.long_c.split('|')[2])
    width = abs(k_short - k_long)
    if width < 0.01:                 # same-strike snap: not a vertical, skip
        continue
    # target-touch trigger (secondary exit)
    t5, c5 = U[r.ticker]
    j0 = np.searchsorted(t5, r.t_s, side='right')
    seg = slice(j0, np.searchsorted(t5, r.t_s + 9 * 86400))
    hit = np.where(c5[seg] >= k_short if r.direction == 1
                   else c5[seg] <= k_short)[0]
    trg = int(t5[j0 + hit[0]] + 300) if len(hit) else None
    rec = {'pop': r.pop, 'ticker': r.ticker, 'direction': r.direction,
           'date': str(r.ts.date()), 'year': r.ts.year,
           'spread': (qL[iL, 2] - qL[iL, 1]) / ((qL[iL, 1] + qL[iL, 2]) / 2) * 100}
    rec['width_datr'] = width / r.datr14_prior
    for tag, ef in [('full', 1.0), ('half', 0.5), ('mid', 0.0)]:
        debit = px(qL, iL, ef, 'buy') - px(qS, iS, ef, 'sell')
        # sane debit: a call/put debit spread costs between ~15% and ~95%
        # of the width; outside that is quote noise or mispriced snap
        if not (0.15 * width <= debit <= 0.95 * width):
            rec[f'hold|{tag}'] = np.nan
            rec[f'tt|{tag}'] = np.nan
            continue
        # primary: hold to end; structural value bounds [0, width]
        eL, eS = len(qL) - 1, len(qS) - 1
        val_end = np.clip(px(qL, eL, ef, 'sell') - px(qS, eS, ef, 'buy'),
                          0.0, width)
        rec[f'hold|{tag}'] = val_end / debit - 1
        # secondary: exit at target touch (else end)
        if trg is not None:
            kL = min(np.searchsorted(qL[:, 0], trg), eL)
            kS = min(np.searchsorted(qS[:, 0], trg), eS)
            val = np.clip(px(qL, kL, ef, 'sell') - px(qS, kS, ef, 'buy'),
                          0.0, width)
            rec[f'tt|{tag}'] = val / debit - 1
        else:
            rec[f'tt|{tag}'] = rec[f'hold|{tag}']
    rows.append(rec)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_verticals.parquet')
print(f'scored verticals: {len(d)}')


def st(g, col):
    v = g[col].dropna()
    if len(v) < 50:
        return f'n={len(v)} thin'
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    by = g.groupby('date')[col].mean()
    tc = by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))
    return (f'n={len(v):5d} mean={100*v.mean():+7.2f}% t={t:+.2f} tclust={tc:+.2f} '
            f'win={100*(v>0).mean():.0f}% med={100*v.median():+.1f}%')


for pop in ['box30', 'hourly']:
    for dirn, dl in [(1, 'BULL'), (-1, 'BEAR')]:
        g = d[(d['pop'] == pop) & (d.direction == dirn)]
        if not len(g):
            continue
        print(f'\n== {pop} {dl} verticals ==')
        for ex in ['hold', 'tt']:
            for tag in ['half', 'full']:
                print(f'  {ex:4s} {tag:4s} {st(g, f"{ex}|{tag}")}')
        for era, m in [('2019-22', g.year <= 2022), ('2023-26', g.year >= 2023)]:
            print(f'  hold half {era}: {st(g[m], "hold|half")}')
        v = g['hold|half'].dropna()
        if len(v) > 100:
            print(f'  hold|half dist: p10={100*v.quantile(.1):+.0f}% p25={100*v.quantile(.25):+.0f}% '
                  f'p75={100*v.quantile(.75):+.0f}% p90={100*v.quantile(.9):+.0f}% '
                  f'| >90%-loss: {100*(v<=-0.9).mean():.0f}%')
        gm = g.dropna(subset=['hold|half']).copy()
        gm['month'] = gm.date.str.slice(0, 7)
        mo = gm.groupby('month')['hold|half'].mean()
        mo = mo[gm.groupby('month')['hold|half'].size() >= 4]
        if len(mo) > 12:
            print(f'  monthly: {100*(mo>0).mean():.0f}% positive, '
                  f't={mo.mean()/(mo.std(ddof=1)/np.sqrt(len(mo))):+.2f}, '
                  f'worst={100*mo.min():+.1f}%')
con.close()
print('\nVERTICALS COMPLETE')
