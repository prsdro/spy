#!/usr/bin/env python3
"""Darwinex CFD feasibility, stage 2: cost overlay + DarwinIA-objective
tuning + sizing/payout simulation on darwinex_cfd_grid.parquet.

Cost models (bracketed; exact Darwinex stock-CFD table lives behind the MT5
spec — update BASE when known). Per SIDE, bps of notional; swap per calendar
night on notional (long stock CFD pays benchmark + markup):
    opt : comm 2.0 + half-spread 1.0 ; swap 4.0%+1.5% -> 1.53 bps/night
    base: comm 4.0 + half-spread 1.5 ; swap 4.0%+2.5% -> 1.81 bps/night
    pess: comm 8.0 + half-spread 2.5 ; swap 4.0%+3.5% -> 2.08 bps/night

Protocol: blind selection — rank configs on 2019-2022 ONLY (per cohort, base
costs) by the DarwinIA-style objective (Calmar = annualized return / maxDD of
the daily portfolio equity at reference sizing), then evaluate 2023-2026.
Frozen production config (opp_0.75_0.50_5_0.0) and the previously
blind-validated upgrade (opp_1.00_0.25_10_0.0) are always reported as
benchmarks. Sizing sweep + DarwinIA payout table run on the selected config.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
ET = 'America/New_York'
SPLIT = '2023-01-01'
REF_W = 0.25          # reference sizing for config scoring (scale-invariantish)
COSTS = {'opt': (2.0, 1.0, 0.055), 'base': (4.0, 1.5, 0.065),
         'pess': (8.0, 2.5, 0.075)}
STD = 'opp_0.75_0.50_5_0.0'
UPG = 'opp_1.00_0.25_10_0.0'

g = pd.read_parquet(OUTDIR / 'darwinex_cfd_grid.parquet')
daily_px = pd.read_parquet(OUTDIR / 'darwinex_daily_closes.parquet')
cfg_cols = sorted(c[2:] for c in g.columns if c.startswith('g_'))
g['gated'] = (g.f_hourrel >= 1) & (g.d21dist >= 0)
COHORTS = {'all': np.ones(len(g), bool), 'grey5': (g.grey >= 5).to_numpy(),
           'gated': g.gated.to_numpy(),
           'gated_grey5': (g.gated & (g.grey >= 5)).to_numpy()}
px = {t: s.set_index('date').close for t, s in daily_px.groupby('ticker')}
ALLDAYS = np.array(sorted(daily_px.date.unique()))


def nights(entry_s, exit_s):
    e = pd.to_datetime(entry_s, unit='s', utc=True).tz_convert(ET).date
    x = pd.to_datetime(exit_s, unit='s', utc=True).tz_convert(ET).date
    return np.array([(b - a).days for a, b in zip(e, x)])


def net_pnl(df, cfg, cost):
    comm, half, swapann = COSTS[cost]
    df = df[df[f'x_{cfg}'].notna()]
    n = nights(df.entry_s.to_numpy(), df[f'x_{cfg}'].to_numpy())
    return (df[f'g_{cfg}'] - 2 * (comm + half) / 1e4
            - n * swapann / 360), n


def tclust(pnl, dates):
    by = pd.Series(pnl.values, index=dates).groupby(level=0).mean()
    return by.mean() / (by.std(ddof=1) / np.sqrt(len(by)))


def portfolio(df, cfg, cost, w, start_eq=1.0):
    """Daily-mark compounding portfolio. Returns daily equity Series."""
    comm, half, swapann = COSTS[cost]
    per_night = swapann / 360
    tr = df[df[f'x_{cfg}'].notna()][
        ['ticker', 'entry_s', 'entry_px', f'g_{cfg}', f'x_{cfg}']].copy()
    tr.columns = ['ticker', 'entry_s', 'entry_px', 'gross', 'exit_s']
    tr['exit_px'] = tr.entry_px * (1 + tr.gross)
    tr['d_in'] = pd.to_datetime(tr.entry_s, unit='s', utc=True) \
        .dt.tz_convert(ET).dt.date.astype(str)
    tr['d_out'] = pd.to_datetime(tr.exit_s, unit='s', utc=True) \
        .dt.tz_convert(ET).dt.date.astype(str)
    by_day_in = {d: t for d, t in tr.groupby('d_in')}
    days = ALLDAYS[(ALLDAYS >= tr.d_in.min()) & (ALLDAYS <= tr.d_out.max())]
    eq, open_pos, curve, maxconc, gross_exp = start_eq, [], [], 0, []
    for day in days:
        pnl = 0.0
        for pos in open_pos:                      # mark/settle existing
            closed = pos['d_out'] == day
            m1 = pos['exit_px'] if closed else px[pos['tkr']].get(day, pos['mark'])
            pnl += (m1 - pos['mark']) * pos['sh']
            if closed:
                pnl -= pos['sh'] * m1 * (comm + half) / 1e4
                pos['dead'] = True
            else:
                pos['mark'] = m1
                pnl -= pos['sh'] * m1 * per_night   # swap tonight
        open_pos = [p for p in open_pos if not p.get('dead')]
        if day in by_day_in:                       # new entries
            for r in by_day_in[day].itertuples():
                sh = w * eq / r.entry_px
                pnl -= sh * r.entry_px * (comm + half) / 1e4
                if r.d_out == day:
                    pnl += (r.exit_px - r.entry_px) * sh
                    pnl -= sh * r.exit_px * (comm + half) / 1e4
                else:
                    m1 = px[r.ticker].get(day, r.entry_px)
                    pnl += (m1 - r.entry_px) * sh
                    pnl -= sh * m1 * per_night
                    open_pos.append({'tkr': r.ticker, 'sh': sh, 'mark': m1,
                                     'exit_px': r.exit_px, 'd_out': r.d_out})
        eq += pnl
        maxconc = max(maxconc, len(open_pos))
        gross_exp.append(sum(p['sh'] * p['mark'] for p in open_pos) / eq)
        curve.append(eq)
    s = pd.Series(curve, index=pd.to_datetime(days))
    s.attrs['maxconc'] = maxconc
    s.attrs['exp_mean'] = float(np.mean(gross_exp))
    s.attrs['exp_p95'] = float(np.quantile(gross_exp, 0.95))
    return s


def metrics(eq):
    ret = eq.pct_change().fillna(0)
    m = eq.resample('ME').last().pct_change().dropna()
    dd = (eq / eq.cummax() - 1).min()
    yrs = len(eq) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    var95 = -np.quantile(m, 0.05) if len(m) > 12 else 1.645 * m.std()
    return {'cagr': cagr, 'maxdd': dd, 'calmar': cagr / abs(dd) if dd else np.nan,
            'sharpe': ret.mean() / ret.std() * np.sqrt(252),
            'mret': m.mean(), 'mstd': m.std(), 'posm': (m > 0).mean(),
            'worstm': m.min(), 'var95': var95, 'n_months': len(m)}


if __name__ == '__main__':
    # ------------ 1. per-trade cost overlay table ------------
    rows = []
    for cost in COSTS:
        for coh, mask in COHORTS.items():
            df = g[mask]
            for cfg in [STD, UPG]:
                p, n = net_pnl(df, cfg, cost)
                rows.append({'cost': cost, 'cohort': coh, 'cfg': cfg,
                             'n': len(df), 'bps': 1e4 * p.mean(),
                             'med': 1e4 * p.median(), 'win': (p > 0).mean(),
                             'tclust': tclust(p, df.loc[p.index, "date"]),
                             'nights_med': float(np.median(n))})
    bench = pd.DataFrame(rows)
    bench.to_csv(OUTDIR / 'darwinex_bench_configs.csv', index=False)
    print('== benchmark configs under cost brackets ==')
    print(bench.round(3).to_string(index=False))

    # ---------------- 2. blind config selection (base costs) ----------------
    sel_rows = []
    for coh in ['grey5', 'gated', 'gated_grey5']:
        df = g[COHORTS[coh]]
        early, late = df[df.date < SPLIT], df[df.date >= SPLIT]
        scores = []
        for cfg in cfg_cols:
            eq = portfolio(early, cfg, 'base', REF_W)
            mt = metrics(eq)
            p, _ = net_pnl(early, cfg, 'base')
            scores.append({'cfg': cfg, 'calmar': mt['calmar'], 'cagr': mt['cagr'],
                           'maxdd': mt['maxdd'], 'posm': mt['posm'],
                           'bps': 1e4 * p.mean()})
        sc = pd.DataFrame(scores).sort_values('calmar', ascending=False)
        sc.to_csv(OUTDIR / f'darwinex_select_{coh}.csv', index=False)
        for rank, r in enumerate(sc.head(5).itertuples(), 1):
            eqo = portfolio(late, r.cfg, 'base', REF_W)
            mo = metrics(eqo)
            po, _ = net_pnl(late, r.cfg, 'base')
            sel_rows.append({'cohort': coh, 'rank': rank, 'cfg': r.cfg,
                             'sel_calmar': r.calmar, 'sel_bps': r.bps,
                             'oos_calmar': mo['calmar'], 'oos_cagr': mo['cagr'],
                             'oos_maxdd': mo['maxdd'], 'oos_posm': mo['posm'],
                             'oos_bps': 1e4 * po.mean(),
                             'oos_tclust': tclust(po, late.loc[po.index, "date"])})
        for cfg in [STD, UPG]:                       # benchmarks on same split
            eqo = portfolio(late, cfg, 'base', REF_W)
            mo = metrics(eqo)
            po, _ = net_pnl(late, cfg, 'base')
            sel_rows.append({'cohort': coh, 'rank': 0, 'cfg': f'BENCH:{cfg}',
                             'sel_calmar': np.nan, 'sel_bps': np.nan,
                             'oos_calmar': mo['calmar'], 'oos_cagr': mo['cagr'],
                             'oos_maxdd': mo['maxdd'], 'oos_posm': mo['posm'],
                             'oos_bps': 1e4 * po.mean(),
                             'oos_tclust': tclust(po, late.loc[po.index, "date"])})
        print(f'{coh}: selection done', flush=True)
    sel = pd.DataFrame(sel_rows)
    sel.to_csv(OUTDIR / 'darwinex_blind_selection.csv', index=False)
    print('\n== blind selection (select 2019-22 by Calmar, evaluate 2023-26) ==')
    print(sel.round(3).to_string(index=False))
    print('\nDONE stage2-selection')
