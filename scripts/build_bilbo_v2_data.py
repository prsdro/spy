#!/usr/bin/env python3
"""Data for the updated Bilbo Box options study page (v2 draft).

Cohort: production-gated trades (f_hourrel>=1, d21dist>=0) in the final
cell/management: ~1-strike-OTM 28-DTE call (p07_28) under the new exits
(m4). Outputs site/data/bilbo-box-options-v2.json:
  - headline stats (half + full exec, eras)
  - equity curve: account growth at 4% premium allocation per trade,
    chronological, both exec levels + per-trade points
  - Monte Carlo: 10,000 paths of 150 trades, DAY-block bootstrap (sample
    trading dates with replacement, keep all same-day trades together),
    4% sizing; fan percentiles per step + terminal/drawdown stats
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

d = pd.read_parquet('/root/spy/analyst/po_comp_options/theta/theta_surface_v2.parquet')
g = d[(d.f_hourrel >= 1) & (d.d21dist >= 0)].copy()
g = g.dropna(subset=['p07_28|m4|half']).sort_values('entry_s')
ALLOC = 0.04
r_half = g['p07_28|m4|half'].to_numpy()
r_full = g['p07_28|m4|full'].to_numpy()
dates = g.date.to_numpy()
print(f'trades: {len(g)}, {dates[0]} .. {dates[-1]}')


def stats(r):
    by = pd.Series(r, index=dates)
    byd = by.groupby(level=0).mean()
    t = byd.mean() / (byd.std(ddof=1) / np.sqrt(len(byd)))
    return dict(n=len(r), mean=round(100 * r.mean(), 2),
                med=round(100 * np.median(r), 1),
                win=round(100 * (r > 0).mean()), tclust=round(t, 2),
                wipe=round(100 * (r <= -0.9).mean(), 2))


def equity(r):
    eq = np.cumprod(1 + ALLOC * r)
    peak = np.maximum.accumulate(eq)
    return eq, float((eq / peak - 1).min())


eq_h, dd_h = equity(r_half)
eq_f, dd_f = equity(r_full)
years = g.year.to_numpy()
era = dict(
    e1_half=round(100 * r_half[years <= 2022].mean(), 2),
    e2_half=round(100 * r_half[years >= 2023].mean(), 2),
    e1_full=round(100 * r_full[years <= 2022].mean(), 2),
    e2_full=round(100 * r_full[years >= 2023].mean(), 2))

# thin the curve for the page (every trade kept; fine at ~1k points)
curve = [{'i': int(i), 'd': str(dates[i]), 't': g.ticker.iloc[i],
          'r': round(100 * float(r_half[i]), 1),
          'eq': round(float(eq_h[i]), 4), 'eqf': round(float(eq_f[i]), 4)}
         for i in range(len(g))]

# ---- Monte Carlo: day-block bootstrap ----
rng = np.random.default_rng(7)
by_day = {}
for dt, r in zip(dates, r_half):          # half-spread exec (page shows only this)
    by_day.setdefault(dt, []).append(r)
day_keys = list(by_day)
N_PATH, N_TRADE = 10000, 150
paths = np.empty((N_PATH, N_TRADE + 1))
paths[:, 0] = 1.0
maxdd = np.empty(N_PATH)
for p in range(N_PATH):
    rs = []
    while len(rs) < N_TRADE:
        rs.extend(by_day[day_keys[rng.integers(len(day_keys))]])
    rs = np.array(rs[:N_TRADE])
    eq = np.cumprod(1 + ALLOC * rs)
    paths[p, 1:] = eq
    peak = np.maximum.accumulate(eq)
    maxdd[p] = (eq / peak - 1).min()
pcts = [5, 25, 50, 75, 95]
fan = {f'p{q}': np.percentile(paths, q, axis=0).round(4).tolist() for q in pcts}
term = paths[:, -1]
mc = {
    'n_paths': N_PATH, 'n_trades': N_TRADE, 'alloc_pct': 100 * ALLOC,
    'exec': 'half-spread fills',
    'fan': fan,
    'terminal': {f'p{q}': round(float(np.percentile(term, q)), 3)
                 for q in pcts},
    'p_loss': round(100 * float((term < 1).mean()), 1),
    'p_up25': round(100 * float((term > 1.25).mean()), 1),
    'maxdd': {f'p{q}': round(100 * float(np.percentile(maxdd, q)), 1)
              for q in [5, 25, 50, 75, 95]},
}

out = {
    'built_utc': pd.Timestamp.utcnow().isoformat(),
    'cell': '~1 strike OTM (spot+0.75 dATR), 28 DTE, new exits',
    'alloc_pct': 100 * ALLOC,
    'half': stats(r_half), 'full': stats(r_full), 'era': era,
    'final_eq_half': round(float(eq_h[-1]), 3),
    'final_eq_full': round(float(eq_f[-1]), 3),
    'maxdd_half': round(100 * dd_h, 1), 'maxdd_full': round(100 * dd_f, 1),
    'curve': curve, 'mc': mc,
}
Path('/root/spy/site/data/bilbo-box-options-v2.json').write_text(
    json.dumps(out))
print(json.dumps({k: out[k] for k in
                  ['half', 'full', 'era', 'final_eq_half', 'final_eq_full',
                   'maxdd_half', 'maxdd_full']}, indent=1))
print('MC terminal:', mc['terminal'], 'P(loss):', mc['p_loss'],
      'maxDD med:', mc['maxdd']['p50'])
print('DONE')
