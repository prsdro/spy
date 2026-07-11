#!/usr/bin/env python3
"""Stock-level directional strategy on the box signal — the no-options
candidate (Codex's 'most defensible non-lottery benchmark').

Spec (pre-registered; exits are the bias-audit's underlying-keyed rules):
  Enter the stock (long on bull break, short on bear) at the close-confirmed
  signal price. Exit on: (a) 5m close beyond the OPPOSITE box edge
  (invalidation); (b) after favorable excursion >= 0.75 x dATR, a 5m close
  retracing 50% of best excursion; (c) time cap = 5 trading days (~W1
  horizon), exit at last 5m close. Cost: 4 bps round trip (liquid megacaps).
  P&L in % of entry price, direction-signed.
Evaluation: pooled + era split + committed blind protocol (fixed-threshold
filters, select 2019-22 by clustered t, evaluate 2023-26) + portfolio path.
"""
import itertools
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
COST = 0.0004
import os
ENTRY_DELAY = os.environ.get('ENTRY_DELAY', '0') == '1'   # fill at next 5m close
RTH_EXITS = os.environ.get('RTH_EXITS', '0') == '1'       # exit bars 09:30-15:55 only
EXIT_NEXTBAR = os.environ.get('EXIT_NEXTBAR', '0') == '1' # fill exits at bar j+1 close
ARM_DATR = 0.75
RETRACE = 0.50
CAP_S = 5 * 86400 * 7 // 5          # 5 trading days ~ 7 calendar days
MIN_N = 100

ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['t_s'] = ent.ts.map(lambda x: int(x.timestamp()))


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
    if RTH_EXITS:
        df = df.set_index(df.ts.dt.tz_convert('America/New_York')) \
               .between_time('09:30', '15:55').reset_index(drop=True)
    return (df.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            df.high.to_numpy(float), df.low.to_numpy(float),
            df.close.to_numpy(float))


U = {t: load5(t) for t in ent.ticker.unique()}
print('underlying loaded', flush=True)

rows = []
for r in ent.itertuples():
    t, hi, lo, cl = U[r.ticker]
    i0 = np.searchsorted(t, r.t_s, side='right')
    if i0 >= len(t):
        continue
    end = np.searchsorted(t, r.t_s + CAP_S)
    entry_px = r.spot
    if ENTRY_DELAY:
        entry_px = cl[i0]
        i0 += 1
        if i0 >= len(t):
            continue
    best = 0.0
    exit_px = None
    arm = ARM_DATR * r.datr14_prior
    exit_j = None
    for j in range(i0, min(end, len(t))):
        if r.direction == 1:
            best = max(best, hi[j] - entry_px)
            if cl[j] < r.box_lo or (best >= arm and cl[j] <= entry_px + RETRACE * best):
                exit_px = cl[min(j + 1, len(cl) - 1)] if EXIT_NEXTBAR else cl[j]
                exit_j = min(j + 1, len(cl) - 1) if EXIT_NEXTBAR else j
                break
        else:
            best = max(best, entry_px - lo[j])
            if cl[j] > r.box_hi or (best >= arm and cl[j] >= entry_px - RETRACE * best):
                exit_px = cl[min(j + 1, len(cl) - 1)] if EXIT_NEXTBAR else cl[j]
                exit_j = min(j + 1, len(cl) - 1) if EXIT_NEXTBAR else j
                break
    if exit_px is None:
        j = min(end, len(t)) - 1
        if j < i0:
            continue
        exit_px = cl[j]
        exit_j = j
    pnl = r.direction * (exit_px - entry_px) / entry_px - COST
    rows.append({'pop': r.pop, 'ticker': r.ticker, 'direction': r.direction,
                 'date': str(r.ts.date()), 'year': r.ts.year,
                 'grey': min(int(r.grey_bars), 8),
                 'boxw': (r.box_hi - r.box_lo) / r.datr14_prior,
                 'datr_pct': r.datr14_prior / r.spot * 100,
                 'pnl': pnl, 'pnl_datr': pnl * 100 / (r.datr14_prior / r.spot * 100),
                 'entry_s': int(r.t_s), 'exit_s': int(t[exit_j])})

d = pd.DataFrame(rows)
suffix = '_strict' if (ENTRY_DELAY and RTH_EXITS and EXIT_NEXTBAR) else \
         ('_delay' if ENTRY_DELAY else '')
d.to_parquet(OUTDIR / f'theta_stock_directional{suffix}.parquet')
print(f'stock trades: {len(d)}')


def st(g, col='pnl'):
    v = g[col].dropna()
    if len(v) < 50:
        return f'n={len(v)} thin'
    t = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    by = g.groupby('date')[col].mean()
    tc = by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))
    return (f'n={len(v):5d} mean={10000*v.mean():+7.1f}bps t={t:+.2f} tclust={tc:+.2f} '
            f'win={100*(v>0).mean():.0f}% med={10000*v.median():+.0f}bps')


print('\n===== STOCK directional, underlying-keyed exits, 4bps cost =====')
for pop in ['box30', 'hourly']:
    g = d[d['pop'] == pop]
    print(f'  {pop} all : {st(g)}')
    for dirn, dl in [(1, 'bull'), (-1, 'bear')]:
        gd = g[g.direction == dirn]
        print(f'  {pop} {dl}: {st(gd)}')
    gb = g[g.direction == 1]
    for era, m in [('2019-22', gb.year <= 2022), ('2023-26', gb.year >= 2023)]:
        print(f'    bull {era}: {st(gb[m])}')

# blind protocol
FILTER_DEFS = {
    'bull': lambda x: x.direction == 1,
    'bear': lambda x: x.direction == -1,
    'boxw<0.3': lambda x: x.boxw < 0.3,
    'boxw>0.6': lambda x: x.boxw > 0.6,
    'vol_hi': lambda x: x.datr_pct > 3.0,
    'grey5+': lambda x: x.grey >= 5,
}
early, late = d[d.year <= 2022], d[d.year >= 2023]
FE = {k: f(early).values for k, f in FILTER_DEFS.items()}
FL = {k: f(late).values for k, f in FILTER_DEFS.items()}
names = list(FILTER_DEFS)
combos = [()] + [(a,) for a in names] \
    + list(itertools.combinations(names, 2)) + list(itertools.combinations(names, 3))


def tclust(g):
    v = g['pnl'].dropna()
    if len(v) < MIN_N:
        return None
    by = g.groupby('date')['pnl'].mean()
    return dict(n=len(v), mean=float(v.mean()),
                tclust=float(by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))))


res = []
for pop in ['box30', 'hourly']:
    pe = (early['pop'] == pop).values
    pl = (late['pop'] == pop).values
    for c in combos:
        me, ml = pe.copy(), pl.copy()
        for f in c:
            me &= FE[f]
            ml = ml & FL[f]
        se = tclust(early[me])
        if se is None:
            continue
        sl = tclust(late[ml])
        res.append({'pop': pop, 'filt': '+'.join(c) or 'none',
                    'sel_n': se['n'], 'sel_bps': 10000 * se['mean'],
                    'sel_tclust': se['tclust'],
                    'oos_n': sl['n'] if sl else 0,
                    'oos_bps': 10000 * sl['mean'] if sl else np.nan,
                    'oos_tclust': sl['tclust'] if sl else np.nan})
r = pd.DataFrame(res).sort_values('sel_tclust', ascending=False)
r.to_csv(OUTDIR / 'stock_blind_grid.csv', index=False)
print('\n===== BLIND protocol (select 2019-22 -> evaluate 2023-26) =====')
print(r.head(8).to_string(index=False, float_format=lambda x: f'{x:+.2f}'))

# portfolio path for #1 pick OOS
best = r.iloc[0]
mask = (late['pop'] == best['pop']).values.copy()
for f in ([] if best['filt'] == 'none' else
          best['filt'].replace('grey5+', 'grey5plus').split('+')):
    key = 'grey5+' if f == 'grey5plus' else f
    mask &= FL[key]
g = late[mask]
v = g['pnl'].dropna()
print(f"\n#1 blind pick OOS: {best['pop']} [{best['filt']}] {st(g)}")
if len(v) > MIN_N:
    print(f'  dist: p10={10000*v.quantile(.1):+.0f} p25={10000*v.quantile(.25):+.0f} '
          f'p75={10000*v.quantile(.75):+.0f} p90={10000*v.quantile(.9):+.0f} bps')
    mon = g.assign(m=g.date.str.slice(0, 7)).groupby('m')['pnl'].agg(['mean', 'size'])
    mon = mon[mon['size'] >= 3]['mean']
    rng = np.random.RandomState(11)
    boots = [mon.sample(len(mon), replace=True, random_state=rng.randint(10**9)).mean()
             for _ in range(3000)]
    lo_, hi_ = np.percentile(boots, [2.5, 97.5])
    daily = g.groupby('date')['pnl'].mean().sort_index()
    eq = daily.cumsum()
    dd = (eq - eq.cummax()).min()
    print(f'  months={len(mon)} positive={100*(mon>0).mean():.0f}% '
          f'worst={10000*mon.min():+.0f}bps bootCI=[{10000*lo_:+.1f},{10000*hi_:+.1f}]bps')
    print(f'  cum={10000*eq.iloc[-1]:+.0f}bps maxDD={10000*dd:+.0f}bps')
print('\nSTOCK DIRECTIONAL COMPLETE')
