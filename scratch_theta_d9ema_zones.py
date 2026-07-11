#!/usr/bin/env python3
"""Pedro's zone hypothesis: size UP above d21 but below d9 (pullback pocket);
far above d9 = extended, size down. Adds daily 9 EMA distance to the d21
feature set and cuts trades into live-knowable zones.

Zones (all from PRIOR completed day's EMAs, dATR units):
  Z1 below d21                      (already shown: noise)
  Z2 above d21, below d9            (Pedro's size-up pocket; needs d9>d21 i.e. uptrend)
  Z3 above both, d9dist 0..1 dATR   (riding the trend, not extended)
  Z4 above both, d9dist 1..2 dATR   (getting extended)
  Z5 above both, d9dist >2 dATR     (Pedro's "too extended")
Also: d9dist quintiles for the raw gradient, era splits, half+full exec.
Outputs: theta/theta_d9zones.parquet, theta/d9zones_summary.csv.
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

d = pd.read_parquet(OUTDIR / 'theta_d21dist.parquet')


def daily_closes(tkr):
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
    return df.between_time('09:30', '15:55')['close'].resample('1D').last().dropna()


feat = []
for tkr, g in d.groupby('ticker'):
    dly = daily_closes(tkr)
    e9 = ema(dly, 9)
    e21 = ema(dly, 21)
    days = np.array([x.date() for x in dly.index])
    v9, v21 = e9.values, e21.values
    for r in g.itertuples():
        ed = pd.Timestamp(r.entry_s, unit='s', tz='UTC').tz_convert(ET).date()
        i = np.searchsorted(days, ed) - 1          # strictly PRIOR day
        if i < 0:
            continue
        feat.append({'ticker': tkr, 'entry_s': r.entry_s,
                     'd9dist': (r.spot - v9[i]) / r.datr14_prior,
                     'stacked': v9[i] > v21[i]})    # d9>d21 = daily uptrend
F = pd.DataFrame(feat)
z = d.merge(F, on=['ticker', 'entry_s'], how='inner')
# sanity: d9 recompute should agree in spirit with stored d21dist (same store)
z['era'] = np.where(z.year <= 2022, 'E1', 'E2')


def zone(r):
    if r.d21dist < 0:
        return 'Z1 below d21'
    if r.d9dist < 0:
        return 'Z2 pocket (>d21,<d9)'
    if r.d9dist < 1:
        return 'Z3 d9+0..1'
    if r.d9dist < 2:
        return 'Z4 d9+1..2'
    return 'Z5 d9>+2 ext'


z['zone'] = z.apply(zone, axis=1)
z.to_parquet(OUTDIR / 'theta_d9zones.parquet')
print(f'n={len(z)}, zones:\n{z.zone.value_counts().sort_index().to_string()}')
print(f'Z2 in daily uptrend (d9>d21): '
      f'{100 * z[z.zone.str.startswith("Z2")].stacked.mean():.0f}%')


def stat(g, col):
    v = g[col].dropna()
    if len(v) < 30:
        return dict(n=len(v))
    by = g.loc[v.index].groupby('date')[col].mean()
    return dict(n=len(v), mean=round(100 * v.mean(), 2),
                med=round(100 * v.median(), 1), win=round(100 * (v > 0).mean()),
                tclust=round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2))


rows = []
for cname, g in [('all', z), ('gated (f_hourrel>=1)', z[z.f_hourrel >= 1])]:
    for tag in ['half', 'full']:
        for zn, gz in g.groupby('zone'):
            rows.append({'cohort': cname, 'row': f'{zn} [{tag}]',
                         **stat(gz, f'base|{tag}')})
    # d9dist quintiles (half) for the raw gradient
    gg = g.copy()
    gg['q'] = pd.qcut(gg.d9dist, 5, labels=False, duplicates='drop')
    for q, gq in gg.groupby('q'):
        rows.append({'cohort': cname,
                     'row': f'd9 Q{q+1} {gq.d9dist.min():+.2f}..{gq.d9dist.max():+.2f}',
                     **stat(gq, 'base|half')})
    # era stability of the zones (half)
    for zn, gz in g.groupby('zone'):
        for era, ge in gz.groupby('era'):
            s = stat(ge, 'base|half')
            rows.append({'cohort': cname, 'row': f'{zn} {era} [half]', **s})
S = pd.DataFrame(rows)
S.to_csv(OUTDIR / 'd9zones_summary.csv', index=False)
pd.set_option('display.width', 220)
print(S.to_string(index=False))
print('\nD9ZONES COMPLETE')
