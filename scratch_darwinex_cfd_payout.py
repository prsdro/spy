#!/usr/bin/env python3
"""Darwinex CFD feasibility, stage 3: position sizing + DarwinIA payout sim.

Takes the blind-selected config (rank-1 per cohort from stage 2) plus the two
benchmarks, sweeps per-trade sizing w (fraction of equity as notional per
entry), finds the w whose NATIVE monthly VaR(95) hits the 6.5% DARWIN target
(so no engine up-scaling is even needed; engine cap 9.75x for >60min holds is
reported for reference), then simulates DarwinIA Silver economics month by
month on the historical equity curve:

  - qualification proxy at each month-end (labelled proxy — the real rating
    is proprietary): trailing-6m return > 0 AND trailing-6m DD > -10% AND
    current month > -6.5%.
  - each qualifying month grants a 3-month allocation tranche of size A
    (tranches stack); fee = 15% x max(0, tranche profit over its 3 months)
    ~ quarterly high-water-mark per tranche.
  - payouts reported for A = EUR 30k (guaranteed at rating>=75) and larger
    allocations as rank sensitivity, per year, base-cost model.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from scratch_darwinex_cfd_analyze import (COHORTS, g, metrics,  # noqa: E402
                                          net_pnl, portfolio, tclust)

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
STD = 'opp_0.75_0.50_5_0.0'
UPG = 'opp_1.00_0.25_10_0.0'
LEV_CAP = 9.75
ALLOCS = [30_000, 90_000, 187_500, 375_000]

# stage-2 verdict: every fresh blind pick lost to the two already-validated
# benchmark configs OOS — so payouts are simulated on the benchmarks only.
picks = [('gated', STD), ('gated', UPG),
         ('gated_grey5', STD), ('gated_grey5', UPG)]
print('configs under payout sim:', picks)


def monthly(eq):
    return eq.resample('ME').last().pct_change().dropna()


def darwinia(eq, alloc):
    m = monthly(eq)
    qual, tranches, fees = [], [], {}
    for i in range(len(m)):
        w6 = m.iloc[max(0, i - 5):i + 1]
        cum6 = (1 + w6).prod() - 1
        eq6 = (1 + w6).cumprod()
        dd6 = (eq6 / eq6.cummax() - 1).min()
        ok = (i >= 5) and cum6 > 0 and dd6 > -0.10 and m.iloc[i] > -0.065
        qual.append(ok)
        if ok:
            tranches.append(i + 1)                 # active months i+1..i+3
    for t0 in tranches:
        seg = m.iloc[t0:t0 + 3]
        if not len(seg):
            continue
        profit = alloc * ((1 + seg).prod() - 1)
        yr = m.index[min(t0 + len(seg) - 1, len(m) - 1)].year
        fees[yr] = fees.get(yr, 0) + 0.15 * max(0.0, profit)
    return pd.Series(qual, index=m.index), pd.Series(fees).sort_index()


results = []
for coh, cfg in picks:
    df = g[COHORTS[coh]]
    # --- sizing sweep: find w with native monthly VaR95 ~ 6.5% ---
    sweep = []
    for w in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60]:
        eq = portfolio(df, cfg, 'base', w)
        mt = metrics(eq)
        sweep.append({'cohort': coh, 'cfg': cfg, 'w': w, **mt,
                      'exp_mean': eq.attrs['exp_mean'],
                      'exp_p95': eq.attrs['exp_p95'],
                      'maxconc': eq.attrs['maxconc'],
                      'scale_to_target': min(0.065 / mt['var95'],
                                             LEV_CAP / max(eq.attrs['exp_p95'],
                                                           1e-9))})
    sw = pd.DataFrame(sweep)
    results.append(sw)
    print(f'\n== {coh} / {cfg} sizing sweep (base costs) ==')
    print(sw.drop(columns=['cohort', 'cfg']).round(3).to_string(index=False))
    # --- payout sim at the VaR-matched sizing ---
    ix = (sw.var95 - 0.065).abs().idxmin()
    wstar = sw.loc[ix, 'w']
    eq = portfolio(df, cfg, 'base', wstar)
    m = monthly(eq)
    qual, _ = darwinia(eq, 30_000)
    print(f'\n-- {coh}: w*={wstar} native VaR95={sw.loc[ix, "var95"]:.3f} '
          f'mret={m.mean():+.3%} posm={(m > 0).mean():.0%} '
          f'qualified months={qual.mean():.0%} '
          f'({int(qual.sum())}/{len(qual)}) --')
    for A in ALLOCS:
        _, fees = darwinia(eq, A)
        fy = fees.reindex(range(m.index[0].year, m.index[-1].year + 1),
                          fill_value=0.0)
        print(f'   A=EUR{A / 1000:.0f}k: fees/yr EUR{fy.mean():,.0f} '
              f'(min {fy.min():,.0f} / max {fy.max():,.0f}) | by yr: '
              + ' '.join(f'{y}:{v:,.0f}' for y, v in fy.items()))
    qs = qual.astype(int)
    print('   qualification by year: '
          + ' '.join(f'{y}:{int(v.sum())}/{len(v)}'
                     for y, v in qs.groupby(qs.index.year)))

pd.concat(results).to_csv(OUTDIR / 'darwinex_sizing_sweep.csv', index=False)
print('\nDONE stage3')
