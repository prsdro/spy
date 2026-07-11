#!/usr/bin/env python3
"""Distance from the DAILY 21 EMA as a breakout-quality predictor.

Pre-registered (before outcomes): hypothesis = FAR ABOVE the daily 21 EMA is
BETTER (consistent with the earlier hourly-21EMA proximity finding), against
the extended-mean-reversion intuition. Quintiles shown either way; a result
that is non-monotone or era-inconsistent is noise.

Feature: (entry spot - EMA21 of RTH daily closes THROUGH THE PRIOR completed
day) / prior-day dATR. Live-knowable; no same-day daily data used.
Cohort: the fixed 3,087 deep-ITM option trades (base|half / base|full from
theta_day1_cut.parquet). Interaction with the production volume gate shown.
Outputs: theta/theta_d21dist.parquet, theta/d21dist_summary.csv.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
import sys
sys.path.insert(0, '/root/spy')
from indicators import ema

STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
ET = 'America/New_York'

base = pd.read_parquet(OUTDIR / 'theta_day1_cut.parquet')[
    ['ticker', 'entry_s', 'date', 'year', 'grey', 'base|half', 'base|full']]
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
base = base.merge(ent[['ticker', 'entry_s', 'spot', 'datr14_prior']],
                  on=['ticker', 'entry_s'], how='left')
vol = pd.read_parquet(OUTDIR / 'theta_volume_features.parquet')[
    ['ticker', 'entry_s', 'f_hourrel']]
base = base.merge(vol, on=['ticker', 'entry_s'], how='left')


def daily_ema(tkr):
    fr = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            fr.append(pd.read_parquet(p, columns=['metric_ts_et', 'close']))
    for top in ['underlying_5m_topup_v2.parquet',
                'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            fr.append(t[['metric_ts_et', 'close']])
    df = pd.concat(fr, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True).dt.tz_convert(ET)
    df = df.drop_duplicates(subset='ts').sort_values('ts').set_index('ts')
    dly = df.between_time('09:30', '15:55')['close'].resample('1D').last().dropna()
    e = ema(dly, 21)
    return {d.date(): v for d, v in e.items()}


feat = []
for tkr, g in base.groupby('ticker'):
    em = daily_ema(tkr)
    days = np.array(sorted(em))
    for r in g.itertuples():
        ed = pd.Timestamp(r.entry_s, unit='s', tz='UTC').tz_convert(ET).date()
        i = np.searchsorted(days, ed) - 1          # strictly PRIOR day
        if i < 0:
            feat.append({'ticker': tkr, 'entry_s': r.entry_s})
            continue
        feat.append({'ticker': tkr, 'entry_s': r.entry_s,
                     'ema_day': str(days[i]),
                     'd21dist': (r.spot - em[days[i]]) / r.datr14_prior})
F = pd.DataFrame(feat)
d = base.merge(F, on=['ticker', 'entry_s'], how='left')
d.to_parquet(OUTDIR / 'theta_d21dist.parquet')
# no-lookahead assertion: EMA day strictly before entry date
chk = d.dropna(subset=['ema_day'])
assert (pd.to_datetime(chk.ema_day).dt.date <
        pd.to_datetime(chk.date).dt.date).all()
print(f'cohort {len(d)}, feature coverage {d.d21dist.notna().sum()}, '
      f'median dist {d.d21dist.median():+.2f} dATR')
print('NO-LOOKAHEAD OK')


def stat(g, col):
    v = g[col].dropna()
    if len(v) < 40:
        return dict(n=len(v))
    by = g.loc[v.index].groupby('date')[col].mean()
    mo = g.loc[v.index].assign(m=g.loc[v.index, 'date'].str.slice(0, 7)) \
        .groupby('m')[col].agg(['mean', 'size'])
    mo = mo[mo['size'] >= 3]['mean']
    return dict(n=len(v), mean=round(100 * v.mean(), 2),
                med=round(100 * v.median(), 1), win=round(100 * (v > 0).mean()),
                tclust=round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2),
                pos_mo=round(100 * (mo > 0).mean()) if len(mo) > 6 else np.nan)


rows = []
d['era'] = np.where(d.year <= 2022, 'E1', 'E2')
for cname, g in [('all', d), ('grey5+', d[d.grey >= 5]),
                 ('gated (f_hourrel>=1)', d[d.f_hourrel >= 1])]:
    gg = g[g.d21dist.notna()].copy()
    gg['q'] = pd.qcut(gg.d21dist, 5, labels=False, duplicates='drop')
    for q, gq in gg.groupby('q'):
        rows.append({'cohort': cname, 'row': f'Q{q+1}',
                     'range': f'{gq.d21dist.min():+.2f}..{gq.d21dist.max():+.2f}',
                     **stat(gq, 'base|half')})
    med = gg.d21dist.median()
    for era, ge in gg.groupby('era'):
        hi = ge[ge.d21dist >= med]['base|half'].mean()
        lo = ge[ge.d21dist < med]['base|half'].mean()
        rows.append({'cohort': cname, 'row': f'{era} hi-lo',
                     'range': '', 'n': len(ge),
                     'mean': round(100 * (hi - lo), 2)})
    for tag in ['half', 'full']:
        for lbl, m in [('below EMA (dist<0)', gg.d21dist < 0),
                       ('0..1 dATR above', (gg.d21dist >= 0) & (gg.d21dist < 1)),
                       ('>1 dATR above', gg.d21dist >= 1)]:
            rows.append({'cohort': cname, 'row': f'{lbl} [{tag}]',
                         'range': '', **stat(gg[m], f'base|{tag}')})
S = pd.DataFrame(rows)
S.to_csv(OUTDIR / 'd21dist_summary.csv', index=False)
pd.set_option('display.width', 220)
print(S.to_string(index=False))
print('\nD21DIST COMPLETE')
