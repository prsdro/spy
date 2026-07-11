#!/usr/bin/env python3
"""Shorts: is below-the-daily-21-EMA the flag that makes bear box breaks
tradeable, and do they need quicker profit-taking?

Baseline known: hourly bear breaks under the long-mirrored management lose
-30.3bps/trade (tclust -4.7). Pre-declared tests (strict conventions:
entry next 5m close, RTH bars only, exits next bar, 4bps cost):
  Conditioning: d21dist = (spot - daily21EMA_prior)/dATR; short thesis
  cohorts d21<0 and d21<-1 vs the d21>=0 complement.
  Managements (small fixed grid, quicker profits):
    std   : arm 0.75 dATR, retrace 50%, cap 5d   (the long mirror)
    quick : arm 0.50 dATR, retrace 25%, cap 2d
    eod   : exit last RTH bar of entry day (no targets)
    tgt   : exit first 5m close <= entry - 0.5 dATR (target), else cap 2d
    tgt1  : target 1.0 dATR, cap 3d
  All use invalidation = 5m close > box_hi.
Verdict bar: cohort must be positive with |tclust|>=2 in BOTH eras to be
called anything more than exploratory.
Outputs: theta/theta_short_d21.parquet, short_d21_summary.csv.
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
COST = 0.0004
CAP1 = 1 * 86400 * 7 // 5
CAP2 = 2 * 86400 * 7 // 5
CAP3 = 3 * 86400 * 7 // 5
CAP5 = 5 * 86400 * 7 // 5

ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == -1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
print(f'hourly bear entries: {len(ent)}')


def load5(tkr):
    frames = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            frames.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'high', 'low', 'close']))
    for top in ['underlying_5m_topup_v2.parquet',
                'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            frames.append(t[['metric_ts_et', 'high', 'low', 'close']])
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True)
    df = df.drop_duplicates(subset='ts').sort_values('ts')
    df = df.set_index(df.ts.dt.tz_convert(ET))
    rth = df.between_time('09:30', '15:55')
    dly = rth['close'].resample('1D').last().dropna()
    e21 = ema(dly, 21)
    emap = {d.date(): v for d, v in e21.items()}
    days = np.array(sorted(emap))
    rth = rth.reset_index(drop=True)
    return (rth.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            rth.high.to_numpy(float), rth.low.to_numpy(float),
            rth.close.to_numpy(float),
            np.array([d.toordinal() for d in
                      rth.ts.dt.tz_convert(ET).dt.date]),
            emap, days)


MGMTS = {
    'std':  dict(arm=0.75, retrace=0.50, cap=CAP5, tgt=None, eod=False),
    'quick': dict(arm=0.50, retrace=0.25, cap=CAP2, tgt=None, eod=False),
    'eod':  dict(arm=None, retrace=None, cap=CAP1, tgt=None, eod=True),
    'tgt':  dict(arm=None, retrace=None, cap=CAP2, tgt=0.5, eod=False),
    'tgt1': dict(arm=None, retrace=None, cap=CAP3, tgt=1.0, eod=False),
}

rows = []
for tkr, g in ent.groupby('ticker'):
    t, hi, lo, cl, dord, emap, days = load5(tkr)
    for r in g.itertuples():
        ed = pd.Timestamp(r.t_s, unit='s', tz='UTC').tz_convert(ET).date()
        di = np.searchsorted(days, ed) - 1
        if di < 0:
            continue
        d21 = (r.spot - emap[days[di]]) / r.datr14_prior
        i0 = np.searchsorted(t, r.t_s, side='right')
        if i0 + 1 >= len(t):
            continue
        entry_px = cl[i0]          # ENTRY_DELAY: next 5m close
        i0 += 1
        out = {'ticker': tkr, 'date': str(ed), 'year': ed.year,
               'grey': min(int(r.grey_bars), 8), 'd21dist': d21,
               'entry_s': int(r.t_s)}
        for mn, m in MGMTS.items():
            end = np.searchsorted(t, r.t_s + m['cap'])
            exit_j = None
            best = 0.0
            for j in range(i0, min(end, len(t))):
                if m['eod'] and dord[j] > dord[i0]:
                    exit_j = j          # first bar of next day = missed EOD
                    break
                if cl[j] > r.box_hi:
                    exit_j = min(j + 1, len(cl) - 1)
                    break
                if m['eod'] and j + 1 < len(t) and dord[j + 1] > dord[j]:
                    exit_j = j          # last RTH bar of entry day
                    break
                if m['tgt'] is not None and \
                        cl[j] <= entry_px - m['tgt'] * r.datr14_prior:
                    exit_j = min(j + 1, len(cl) - 1)
                    break
                if m['arm'] is not None:
                    best = max(best, entry_px - lo[j])
                    if best >= m['arm'] * r.datr14_prior and \
                            cl[j] >= entry_px - m['retrace'] * best:
                        exit_j = min(j + 1, len(cl) - 1)
                        break
            if exit_j is None:
                exit_j = min(end, len(t)) - 1
                if exit_j < i0:
                    continue
            out[f'pnl_{mn}'] = -(cl[exit_j] - entry_px) / entry_px - COST
        rows.append(out)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_short_d21.parquet')
d['era'] = np.where(d.year <= 2022, 'E1', 'E2')
print(f'trades: {len(d)}, d21<0: {(d.d21dist < 0).sum()}, '
      f'd21<-1: {(d.d21dist < -1).sum()}')


def st(g, col):
    v = g[col].dropna()
    if len(v) < 40:
        return dict(n=len(v))
    by = g.loc[v.index].groupby('date')[col].mean()
    return dict(n=len(v), bps=round(1e4 * v.mean(), 1),
                med=round(1e4 * v.median()), win=round(100 * (v > 0).mean()),
                tclust=round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2))


res = []
cohorts = [('all shorts', d), ('d21>=0', d[d.d21dist >= 0]),
           ('d21<0', d[d.d21dist < 0]), ('d21<-1', d[d.d21dist < -1])]
for cn, g in cohorts:
    for mn in MGMTS:
        row = {'cohort': cn, 'mgmt': mn, **st(g, f'pnl_{mn}')}
        for era, ge in g.groupby('era'):
            s = st(ge, f'pnl_{mn}')
            row[f'{era}_bps'] = s.get('bps')
            row[f'{era}_t'] = s.get('tclust')
        res.append(row)
S = pd.DataFrame(res)
S.to_csv(OUTDIR / 'short_d21_summary.csv', index=False)
pd.set_option('display.width', 220)
print(S.to_string(index=False))

# d21 quintiles under the best-looking quick mgmt AND std, for the gradient
for mn in ['std', 'tgt']:
    gg = d.copy()
    gg['q'] = pd.qcut(gg.d21dist, 5, labels=False, duplicates='drop')
    print(f'\nd21dist quintiles [{mn}]:')
    for q, gq in gg.groupby('q'):
        s = st(gq, f'pnl_{mn}')
        print(f'  Q{q+1} {gq.d21dist.min():+.2f}..{gq.d21dist.max():+.2f}: {s}')
print('\nSHORT D21 COMPLETE')
