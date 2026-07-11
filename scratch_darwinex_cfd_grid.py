#!/usr/bin/env python3
"""Darwinex CFD feasibility, stage 1: re-walk the hourly-bull stock exits
under a wider stop/trail/TP grid, recording per-config EXIT TIMESTAMPS so a
cost overlay can charge overnight swap per calendar night actually held.

Cohort + conventions IDENTICAL to scratch_theta_adaptive_matrix.py (strict:
entry at NEXT 5m close after the signal bar, RTH bars only, exit fills next
bar). P&L stored GROSS (no cost deduction) — costs are applied by the
analyzer (scratch_darwinex_cfd_analyze.py) under bracketed Darwinex models.

Grid (270 configs):
  stop  in {opp (box_lo), mid (box midpoint), d50 (entry - 0.50*dATR)}
  arm   in {0.50, 0.75, 1.00} dATR x retrace in {0.25, 0.50, 0.75}
        + 'notrail' (stop/TP/cap only)
  cap   in {2, 5, 10} trading days
  tp    in {none, 1.5, 2.0} dATR (hard take-profit on 5m close, next-bar fill)

Outputs:
  theta/darwinex_cfd_grid.parquet   one row per trade; per config:
                                    g_<cfg> (gross pnl), x_<cfg> (exit epoch s)
  theta/darwinex_daily_closes.parquet  per-ticker RTH daily closes for the
                                    portfolio mark-to-market sim.
Gate features (f_hourrel, d21dist) joined from theta_d21dist.parquet.
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
ARMS = [0.50, 0.75, 1.00]
RETS = [0.25, 0.50, 0.75]
CAPS = [2, 5, 10]
STOPS = ['opp', 'mid', 'd50']
TPS = [0.0, 1.5, 2.0]
CFGS = ([(s, a, r, c, tp) for s in STOPS for a in ARMS for r in RETS
         for c in CAPS for tp in TPS]
        + [(s, None, None, c, tp) for s in STOPS for c in CAPS for tp in TPS])
MAXCAP_S = 10 * 86400 * 7 // 5


def tag(s, a, r, c, tp):
    trail = 'nt' if a is None else f'{a:.2f}_{r:.2f}'
    return f'{s}_{trail}_{c}_{tp:.1f}'


ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))
d21 = pd.read_parquet(OUTDIR / 'theta_d21dist.parquet')
feat = d21.set_index(['ticker', 'entry_s'])[['f_hourrel', 'd21dist']]
print(f'hourly bull entries: {len(ent)}; grid: {len(CFGS)} configs', flush=True)


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
    df = df.set_index(df.ts.dt.tz_convert(ET)).between_time('09:30', '15:55')
    daily = df.close.groupby(df.index.date).last()
    df = df.reset_index(drop=True)
    return (df.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            df.high.to_numpy(float), df.close.to_numpy(float), daily)


rows, dailies = [], []
for tkr, g in ent.groupby('ticker'):
    t, hi, cl, daily = load5(tkr)
    dailies.append(pd.DataFrame(
        {'ticker': tkr, 'date': daily.index.astype(str), 'close': daily.values}))
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
        stop_px = {'opp': r.box_lo, 'mid': (r.box_hi + r.box_lo) / 2,
                   'd50': entry_px - 0.50 * r.datr14_prior}
        fh, dd = (feat.loc[(tkr, r.t_s)] if (tkr, r.t_s) in feat.index
                  else (np.nan, np.nan))
        out = {'ticker': tkr, 'entry_s': int(r.t_s),
               'date': str(r.ts.tz_convert(ET).date()),
               'year': r.ts.tz_convert(ET).year,
               'grey': min(int(r.grey_bars), 8),
               'datr_pct': r.datr14_prior / r.spot * 100,
               'entry_px': entry_px, 'box_lo': r.box_lo, 'box_hi': r.box_hi,
               'f_hourrel': fh, 'd21dist': dd}
        stop_hit = {s: seg_c < stop_px[s] for s in STOPS}
        tp_hit = {tp: (seg_c >= entry_px + tp * r.datr14_prior) if tp else
                  np.zeros(len(seg_c), bool) for tp in TPS}
        for s, a, rt, c, tp in CFGS:
            end_c = np.searchsorted(seg_t, r.t_s + c * 86400 * 7 // 5)
            if end_c == 0:
                continue
            hit = stop_hit[s][:end_c] | tp_hit[tp][:end_c]
            if a is not None:
                armed = best[:end_c] >= a * r.datr14_prior
                hit = hit | (armed &
                             (seg_c[:end_c] <= entry_px + rt * best[:end_c]))
            w = np.flatnonzero(hit)
            j = min(w[0] + 1, len(seg_c) - 1) if len(w) else end_c - 1  # nextbar
            k = tag(s, a, rt, c, tp)
            out[f'g_{k}'] = (seg_c[j] - entry_px) / entry_px
            out[f'x_{k}'] = int(seg_t[j])
        rows.append(out)
    print(f'{tkr} done ({len(rows)})', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'darwinex_cfd_grid.parquet')
pd.concat(dailies, ignore_index=True).to_parquet(
    OUTDIR / 'darwinex_daily_closes.parquet')
std = d['g_opp_0.75_0.50_5_0.0'] - 0.0004
by = d.assign(p=std).groupby('date').p.mean()
print(f'\ngrid: {d.shape}; std-config check (4bps deducted) '
      f'{1e4 * std.mean():+.1f}bps '
      f'tclust {by.mean() / (by.std(ddof=1) / np.sqrt(len(by))):+.2f} '
      f'(expect ~+38.8 / +2.33)')
print('GRID COMPLETE')
