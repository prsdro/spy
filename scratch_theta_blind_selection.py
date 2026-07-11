#!/usr/bin/env python3
"""Reproducible blind-selection protocol for the directional grid
(Codex finding #2: the scan previously lived only in an ad-hoc heredoc).

Protocol (frozen):
  - Grid: pop {box30, hourly} x exit {trail30, trail50, hold_sl50, hold_sl35,
    hold_nostop} x filter combos of size 0-3 drawn from the 8 live-knowable
    filters below. Filters use FIXED thresholds (no full-sample quantiles).
  - Selection metric: date-clustered t of the half-spread P&L, computed on
    the SELECTION window only. Minimum 100 trades in both windows.
  - Selection window: 2019-01..2022-12. Evaluation window: 2023-01..2026-07.
  - Report: top-K selected cells with their evaluation-window stats; the
    evaluation numbers of cells never seen by selection are the only numbers
    quotable as out-of-sample.
Input: theta_directional.parquet (built by scratch_theta_directional_tune.py).
"""
import itertools
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
MIN_N = 100
TOP_K = 10

d = pd.read_parquet(OUTDIR / 'theta_directional.parquet')
early, late = d[d.year <= 2022], d[d.year >= 2023]

FILTER_DEFS = {
    'band1-2': lambda x: (x.spread >= 1) & (x.spread < 2),
    'spr<2': lambda x: x.spread < 2,
    'bull': lambda x: x.direction == 1,
    'bear': lambda x: x.direction == -1,
    'boxw<0.3': lambda x: x.boxw < 0.3,
    'boxw>0.6': lambda x: x.boxw > 0.6,
    'vol_hi': lambda x: x.datr_pct > 3.0,        # fixed, not a quantile
    'grey5+': lambda x: x.grey >= 5,
}
EXITS = ['trail30', 'trail50', 'hold_sl50', 'hold_sl35', 'hold_nostop']


def tclust(g, col):
    v = g[col].dropna()
    if len(v) < MIN_N:
        return None
    by = g.groupby('date')[col].mean()
    return dict(n=len(v), mean=float(v.mean()),
                tclust=float(by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))))


FE = {k: f(early).values for k, f in FILTER_DEFS.items()}
FL = {k: f(late).values for k, f in FILTER_DEFS.items()}
names = list(FILTER_DEFS)
combos = [()] + [(a,) for a in names] \
    + list(itertools.combinations(names, 2)) + list(itertools.combinations(names, 3))

rows = []
for pop in ['box30', 'hourly']:
    pe = (early['pop'] == pop).values
    pl = (late['pop'] == pop).values
    for x in EXITS:
        col = f'{x}|half'
        for c in combos:
            me, ml = pe.copy(), pl.copy()
            for f in c:
                me &= FE[f]
                ml = ml & FL[f]
            se = tclust(early[me], col)
            if se is None:
                continue
            sl = tclust(late[ml], col)
            rows.append({'pop': pop, 'exit': x, 'filt': '+'.join(c) or 'none',
                         'sel_n': se['n'], 'sel_mean': se['mean'],
                         'sel_tclust': se['tclust'],
                         'oos_n': sl['n'] if sl else 0,
                         'oos_mean': sl['mean'] if sl else np.nan,
                         'oos_tclust': sl['tclust'] if sl else np.nan})

r = pd.DataFrame(rows).sort_values('sel_tclust', ascending=False)
r.to_csv(OUTDIR / 'blind_selection_grid.csv', index=False)
top = r.head(TOP_K)
pd.set_option('display.width', 200)
print(f'grid cells evaluated: {len(r)}')
print(f'\nTOP {TOP_K} by selection-window clustered t, with OOS:')
print(top.to_string(index=False, float_format=lambda x: f'{x:+.3f}'))
sel = top[top.oos_n >= MIN_N]
print(f'\nOOS summary of top-{TOP_K} picks: mean of means '
      f'{100*sel.oos_mean.mean():+.2f}%, positive {int((sel.oos_mean>0).sum())}/{len(sel)}')
print(f'-> {OUTDIR/"blind_selection_grid.csv"}')
