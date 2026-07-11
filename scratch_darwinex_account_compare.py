#!/usr/bin/env python3
"""Darwinex account-type comparison for the Bilbo stock strategy:

  CFD account : base cost model (4.0 + 1.5 bps/side + 1.81 bps/night swap),
                leverage available -> size to native VaR95 = 6.5% (w*),
                engine scale ~ 1.
  CASH account: US stocks & ETFs, no leverage -> cap w so p95 gross
                exposure <= 1.0x; costs ~ $0.005/share (~0.5 bps) + 1.0 bps
                half-spread per side, ZERO swap; the DARWIN engine scales
                the (lower-VaR) track to the 6.5% target (cap 9.75x for
                >60min holds — never close to binding here).

DarwinIA payout sim runs on the ENGINE-SCALED monthly series in both cases
(scale = min(6.5% / native VaR95, 9.75 / exp_p95)), same proxy qualification
rule and 3-month stacking tranche fee model as scratch_darwinex_cfd_payout.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import scratch_darwinex_cfd_analyze as H

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
H.COSTS['cash'] = (0.5, 1.0, 0.0)
STD, UPG, LEV_CAP = H.STD, H.UPG, 9.75
ALLOCS = [30_000, 90_000, 187_500, 375_000]


def darwinia_m(m, alloc):
    qual, tranches, fees = [], [], {}
    for i in range(len(m)):
        w6 = m.iloc[max(0, i - 5):i + 1]
        cum6 = (1 + w6).prod() - 1
        eq6 = (1 + w6).cumprod()
        dd6 = (eq6 / eq6.cummax() - 1).min()
        ok = (i >= 5) and cum6 > 0 and dd6 > -0.10 and m.iloc[i] > -0.065
        qual.append(ok)
        if ok:
            tranches.append(i + 1)
    for t0 in tranches:
        seg = m.iloc[t0:t0 + 3]
        if not len(seg):
            continue
        profit = alloc * ((1 + seg).prod() - 1)
        yr = m.index[min(t0 + len(seg) - 1, len(m) - 1)].year
        fees[yr] = fees.get(yr, 0) + 0.15 * max(0.0, profit)
    return (pd.Series(qual, index=m.index),
            pd.Series(fees).sort_index() if fees else pd.Series(dtype=float))


def evaluate(coh, cfg, cost, w):
    df = H.g[H.COHORTS[coh]]
    eq = H.portfolio(df, cfg, cost, w)
    mt = H.metrics(eq)
    m = eq.resample('ME').last().pct_change().dropna()
    scale = min(0.065 / mt['var95'], LEV_CAP / max(eq.attrs['exp_p95'], 1e-9))
    md = m * scale
    qual, _ = darwinia_m(md, 30_000)
    fees = {A: darwinia_m(md, A)[1] for A in ALLOCS}
    return mt, eq, scale, md, qual, fees


if __name__ == '__main__':
    print('account | cohort/cfg | w | native VaR | exp_p95 | engine scale | '
          'DARWIN mret | qual% | fees/yr @30k | @375k')
    rows = []
    for coh, cfg in [('gated', STD), ('gated_grey5', UPG)]:
        for acct, cost, wpick in [('CFD', 'base', None), ('CASH', 'cash', None)]:
            # pick w: CFD -> native VaR ~ 6.5%; CASH -> max w with exp_p95 <= 1.0
            best = None
            for w in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]:
                mt, eq, scale, md, qual, fees = evaluate(coh, cfg, cost, w)
                if acct == 'CFD':
                    key = abs(mt['var95'] - 0.065)
                    if best is None or key < best[0]:
                        best = (key, w, mt, eq, scale, md, qual, fees)
                else:
                    if eq.attrs['exp_p95'] <= 1.0:
                        best = (0, w, mt, eq, scale, md, qual, fees)
            _, w, mt, eq, scale, md, qual, fees = best
            f30 = fees[30_000]
            f375 = fees[375_000]
            yrs = range(md.index[0].year, md.index[-1].year + 1)
            f30y = f30.reindex(yrs, fill_value=0.0)
            f375y = f375.reindex(yrs, fill_value=0.0)
            print(f'{acct:4} | {coh}/{cfg} | w={w} | VaR {mt["var95"]:.3f} | '
                  f'exp_p95 {eq.attrs["exp_p95"]:.2f} | scale {scale:.2f} | '
                  f'mret {md.mean():+.3%} | qual {qual.mean():.0%} | '
                  f'EUR{f30y.mean():,.0f} | EUR{f375y.mean():,.0f}')
            print('      by-year @30k: '
                  + ' '.join(f'{y}:{v:,.0f}' for y, v in f30y.items()))
            rows.append({'acct': acct, 'cohort': coh, 'cfg': cfg, 'w': w,
                         'var95': mt['var95'], 'exp_p95': eq.attrs['exp_p95'],
                         'scale': scale, 'darwin_mret': md.mean(),
                         'qual': qual.mean(), 'fees30': f30y.mean(),
                         'fees375': f375y.mean()})
    pd.DataFrame(rows).to_csv(OUTDIR / 'darwinex_account_compare.csv', index=False)
    print('DONE account-compare')
