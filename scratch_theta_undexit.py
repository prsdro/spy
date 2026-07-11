#!/usr/bin/env python3
"""Underlying-keyed exits on the 7-year NBBO set — directional legs.

PRE-REGISTERED primary spec (from BIAS_REVIEW.md, chosen on other data):
  arm when favorable underlying excursion >= 0.75 x box height;
  after arming, exit when 5m close retraces 50% of best excursion;
  always-on invalidation: 5m close beyond the OPPOSITE box edge;
  otherwise ride to the option data window end (~W1 expiry).
Entry: the validated close-confirmed signal; option = W1 ATM leg in break
direction; fills at ask/half/mid, exits marked at the first two-sided quote
at/after the underlying trigger. Distribution stats reported (anti-lottery).
Secondary (declared upfront): same with arm = 0.75 x daily ATR.
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
ARM_RETRACE = 0.50

con = sqlite3.connect(OUTDIR / 'quotes.sqlite')
legs = pd.read_sql('SELECT * FROM entry_legs', con)
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].merge(
    legs.pivot_table(index='ep_id', columns='right', values='contract',
                     aggfunc='first').reset_index(), on='ep_id', how='inner')
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
ent['dir_contract'] = np.where(ent.direction == 1, ent.C, ent.P)


def load5(tkr):
    frames = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            frames.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'high', 'low', 'close']))
    for top in ['underlying_5m_topup_v2.parquet', 'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            frames.append(t[['metric_ts_et', 'high', 'low', 'close']])
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True)
    df = df.drop_duplicates(subset='ts').sort_values('ts')
    return (df.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            df.high.to_numpy(float), df.low.to_numpy(float),
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


def trigger_ts(r, arm_amt):
    """Underlying-keyed exit trigger time (epoch s) or None (ride to end)."""
    t, hi, lo, cl = U[r.ticker]
    i0 = np.searchsorted(t, r.t_s, side='right')
    j = i0
    best = 0.0
    n = len(t)
    while j < n and t[j] <= r.t_s + 9 * 86400:
        if r.direction == 1:
            best = max(best, hi[j] - r.spot)
            if cl[j] < r.box_lo:
                return t[j] + 300
            if best >= arm_amt and cl[j] <= r.spot + ARM_RETRACE * best:
                return t[j] + 300
        else:
            best = max(best, r.spot - lo[j])
            if cl[j] > r.box_hi:
                return t[j] + 300
            if best >= arm_amt and cl[j] >= r.spot - ARM_RETRACE * best:
                return t[j] + 300
        j += 1
    return None


def run(spec_name, arm_of):
    rows = []
    for r in ent.itertuples():
        cid = r.dir_contract
        if not isinstance(cid, str):
            continue
        q = quotes(cid)
        if not len(q):
            continue
        i = np.searchsorted(q[:, 0], r.t_s)
        if i >= len(q) or q[i, 0] > r.t_s + GRACE_S:
            continue
        trg = trigger_ts(r, arm_of(r))
        if trg is None:
            k = len(q) - 1
        else:
            k = min(np.searchsorted(q[:, 0], trg), len(q) - 1)
        rec = {'pop': r.pop, 'ticker': r.ticker, 'direction': r.direction,
               'date': str(r.ts.date()), 'year': r.ts.year,
               'spread': (q[i, 2] - q[i, 1]) / ((q[i, 1] + q[i, 2]) / 2) * 100}
        for tag, ef in [('full', 1.0), ('half', 0.5), ('mid', 0.0)]:
            m0 = (q[i, 1] + q[i, 2]) / 2
            buy = m0 + ef * (q[i, 2] - m0)
            mx = (q[k, 1] + q[k, 2]) / 2
            sell = mx - ef * (mx - q[k, 1])
            rec[tag] = sell / buy - 1
        rows.append(rec)
    d = pd.DataFrame(rows)
    d.to_parquet(OUTDIR / f'theta_undexit_{spec_name}.parquet')

    def st(g, col):
        v = g[col].dropna()
        if len(v) < 50:
            return f'n={len(v)} thin'
        t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
        by = g.groupby('date')[col].mean()
        tc = by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))
        return (f'n={len(v):5d} mean={100*v.mean():+7.2f}% t={t:+.2f} '
                f'tclust={tc:+.2f} win={100*(v>0).mean():.0f}% '
                f'med={100*v.median():+.1f}%')

    print(f'\n===== {spec_name} =====')
    for pop in ['box30', 'hourly']:
        g = d[d['pop'] == pop]
        print(f'  {pop} all directions:')
        for tag in ['half', 'full']:
            print(f'    {tag:4s} {st(g, tag)}')
        gb = g[g.direction == 1]
        print(f'  {pop} BULL only:')
        for tag in ['half', 'full']:
            print(f'    {tag:4s} {st(gb, tag)}')
        for era, m in [('2019-22', g.year <= 2022), ('2023-26', g.year >= 2023)]:
            print(f'    bull {era} half: {st(g[m & (g.direction==1)], "half")}')
        v = gb['half'].dropna()
        if len(v):
            print(f'    bull distribution(half): p10={100*v.quantile(.1):+.0f}% '
                  f'p25={100*v.quantile(.25):+.0f}% p75={100*v.quantile(.75):+.0f}% '
                  f'p90={100*v.quantile(.9):+.0f}% | >90%-loss share: '
                  f'{100*(v<=-0.9).mean():.0f}%')
    return d


run('boxh', lambda r: 0.75 * (r.box_hi - r.box_lo))     # primary, audit spec
run('datr', lambda r: 0.75 * r.datr14_prior)            # declared secondary
con.close()
print('\nUNDEXIT COMPLETE')
