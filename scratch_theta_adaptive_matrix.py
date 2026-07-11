#!/usr/bin/env python3
"""Stage 1 of the adaptive-tuning test: per-trade P&L across a management
grid, so selectors can be replayed walk-forward without re-touching bars.

Cohort: all hourly bull box breaks (strict conventions: entry next 5m
close, RTH bars only, exit fills next bar, 4bps cost).
Grid: arm in {0.50,0.75,1.00} dATR x retrace in {0.25,0.50,0.75} x cap in
{2,5,10} trading days = 27 configs (the validated arm-then-trail family;
'std' = arm0.75/ret0.50/cap5 is the frozen production config).
Exit rule per config: invalidation 5m close < box_lo; after best excursion
>= arm*dATR, exit on 5m close <= entry + retrace*best; else time cap.
Output: theta/theta_adaptive_matrix.parquet (one row per trade, one pnl
column per config, plus keys/features).
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
ET = 'America/New_York'
COST = 0.0004
ARMS = [0.50, 0.75, 1.00]
RETS = [0.25, 0.50, 0.75]
CAPS = [2, 5, 10]
CFGS = [(a, r, c) for a in ARMS for r in RETS for c in CAPS]
MAXCAP_S = 10 * 86400 * 7 // 5

ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
print(f'hourly bull entries: {len(ent)}', flush=True)


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
    df = df.set_index(df.ts.dt.tz_convert(ET)).between_time('09:30', '15:55') \
           .reset_index(drop=True)
    return (df.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            df.high.to_numpy(float), df.close.to_numpy(float))


rows = []
for tkr, g in ent.groupby('ticker'):
    t, hi, cl = load5(tkr)
    for r in g.itertuples():
        i0 = np.searchsorted(t, r.t_s, side='right')
        if i0 + 1 >= len(t):
            continue
        entry_px = cl[i0]                       # ENTRY_DELAY
        i0 += 1
        end_max = min(np.searchsorted(t, r.t_s + MAXCAP_S), len(t))
        if end_max <= i0:
            continue
        seg_t = t[i0:end_max]
        seg_c = cl[i0:end_max]
        best = np.maximum.accumulate(hi[i0:end_max]) - entry_px
        inval = seg_c < r.box_lo
        out = {'ticker': tkr, 'entry_s': int(r.t_s),
               'date': str(r.ts.tz_convert(ET).date()),
               'year': r.ts.tz_convert(ET).year,
               'grey': min(int(r.grey_bars), 8),
               'datr_pct': r.datr14_prior / r.spot * 100}
        for a, rt, c in CFGS:
            end_c = np.searchsorted(seg_t, r.t_s + c * 86400 * 7 // 5)
            if end_c == 0:
                continue
            armed = best[:end_c] >= a * r.datr14_prior
            hit = inval[:end_c] | (armed &
                                   (seg_c[:end_c] <= entry_px + rt * best[:end_c]))
            w = np.flatnonzero(hit)
            j = min(w[0] + 1, len(seg_c) - 1) if len(w) else end_c - 1  # nextbar
            out[f'p_{a:.2f}_{rt:.2f}_{c}'] = \
                (seg_c[j] - entry_px) / entry_px - COST
        rows.append(out)
    print(f'{tkr} done ({len(rows)})', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_adaptive_matrix.parquet')
std = d['p_0.75_0.50_5']
by = d.assign(p=std).groupby('date').p.mean()
print(f'\nmatrix: {d.shape}; std config {1e4*std.mean():+.1f}bps '
      f'tclust {by.mean()/(by.std(ddof=1)/np.sqrt(len(by))):+.2f} '
      f'(expect ~+38.8bps / +2.33)')
print('MATRIX COMPLETE')
