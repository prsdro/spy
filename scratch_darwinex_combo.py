#!/usr/bin/env python3
"""Combined-DARWIN portfolio: Bilbo stock CFD strategy + three validated
futures sleeves traded as index proxies in the SAME MT5 CFD account
(US500/USTEC index CFDs standing in for ES/NQ/MES; sleeve $-series are net
of futures-grade costs — see proxy-cost caveat in the report).

Sleeves (all holdout-era 2019+, $/day per 1 contract):
  fade236 : /root/saints/work3 ES+NQ put-trigger fade, validated long cfg
  drift   : ES 3m compression aligned_cont/brk10, ATR>=2.0 gate (recon from
            events CSV via the study's own simulate_exit)
  momentum: NQ SSRN intraday momentum + skip-expansion (rr6_60<=1.21|NaN)

Mixing: each sleeve scaled to a daily-vol budget relative to Bilbo's daily
vol (whole-period vols — mild lookahead, labelled). Futures risk share
f in {0, .15, .25, .35, .5} of Bilbo vol TOTAL, split equally across the 3
sleeves. Combined monthly series -> engine-scaled to 6.5% VaR -> same
DarwinIA proxy qualification + tranche fee model. Window = overlap
(Bilbo start .. ES data end 2026-01).
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import scratch_darwinex_cfd_analyze as H
from scratch_darwinex_account_compare import darwinia_m

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
ALLOC = [30_000, 375_000]

# ---------- Bilbo daily returns (gated / frozen cfg, base CFD, w=0.30) ----
bil_eq = H.portfolio(H.g[H.COHORTS['gated']], H.STD, 'base', 0.30)
bil = bil_eq.pct_change().fillna(0.0)

# ---------- sleeve 1: fade236 ----------
f_es = pd.read_parquet(
    '/root/saints/work3/atr_ES_fade236_STRAT_0.236_0.5_0.0_long.parquet')
f_nq = pd.read_parquet(
    '/root/saints/work3/atr_NQ_fade236_STRAT_0.236_0.5_0.0_long.parquet')
fade = (pd.concat([f_es, f_nq])
        .query('year >= 2019').groupby('date').net.sum())
fade.index = pd.to_datetime(fade.index)

# ---------- sleeve 2: ES compression drift (reconstruct) ----------
sys.path.insert(0, '/root/spy')
from backtest_es_po_comp_drift import load_3m, add_indicators  # noqa: E402
from backtest_es_po_comp_drift_strategy import (COST_PTS,      # noqa: E402
                                                simulate_exit)

tf = add_indicators(load_3m())
tf['date'] = tf.index.date
o, h_, l_, c_ = (tf[k].values for k in 'ohlc')
pos = {ts: i for i, ts in enumerate(tf.index)}
dates_arr = tf['date'].values
day_end_map = {d: int(gi.iloc[-1]) for d, gi in
               pd.Series(range(len(tf)), index=dates_arr).groupby(level=0)}
ev = pd.read_csv('/root/spy/analyst/es_po_comp_drift_events.csv',
                 parse_dates=['exp_ts'])
ev = ev[(ev['align'] == 'aligned') & (ev['atr'] >= 2.0)
        & (ev['exp_ts'].dt.year >= 2019)]
drift_rows = []
for _, e in ev.iterrows():
    i = pos.get(e['exp_ts'])
    if i is None:
        continue
    day_end = day_end_map[dates_arr[i]]
    if i + 1 > day_end:
        continue
    res = simulate_exit(o, h_, l_, c_, i + 1, day_end, int(e['sign']),
                        e['atr'], 'brk10')
    if res is None:
        continue
    exit_px, _ = res
    net_pts = int(e['sign']) * (exit_px - o[i + 1]) - COST_PTS
    drift_rows.append((e['exp_ts'].date(), net_pts * 50))
drift = (pd.DataFrame(drift_rows, columns=['date', 'usd'])
         .groupby('date').usd.sum())
drift.index = pd.to_datetime(drift.index)
print(f'drift recon: {len(drift_rows)} trades, {len(drift)} days, '
      f'mean ${np.mean([r[1] for r in drift_rows]):+.1f}/trade', flush=True)

# ---------- sleeve 3: NQ intraday momentum ----------
mom = pd.read_csv('/root/spy/analyst/intraday_momentum/'
                  'nq_vm1.0_i30_band_vwap_daily.csv', parse_dates=['date'])
mom = mom[(mom.rr6_60.isna()) | (mom.rr6_60 <= 1.21)]
mom = mom[mom.date.dt.year >= 2019].set_index('date').net_usd

# ---------- align on common window ----------
end = min(fade.index.max(), drift.index.max(), mom.index.max())
idx = bil.index[(bil.index >= bil.index.min()) & (bil.index <= end)]
sleeves = {'fade236': fade, 'drift': drift, 'momentum': mom}
S = pd.DataFrame({k: v.reindex(idx).fillna(0.0) for k, v in sleeves.items()})
B = bil.reindex(idx).fillna(0.0)
print(f'window {idx[0].date()} .. {idx[-1].date()} ({len(idx)} days)')
svol = S.std()
print('sleeve daily $sd per contract:',
      {k: round(v) for k, v in svol.items()})
Sr = S / svol / np.sqrt(3)          # unit: equal-risk, combined sd ~ sqrtsum
corr = pd.concat([B.rename('bilbo'), S], axis=1).corr()
print('\ndaily corr matrix:')
print(corr.round(3).to_string())
mB = (1 + B).resample('ME').prod() - 1
mS = S.resample('ME').sum() / svol / np.sqrt(3)
print('\nmonthly corr with bilbo:',
      {k: round(pd.concat([mB, mS[k]], axis=1).corr().iloc[0, 1], 3)
       for k in S.columns})

rows = []
for f in [0.0, 0.15, 0.25, 0.35, 0.50]:
    comb = B + Sr.sum(axis=1) * f * B.std()
    eqc = (1 + comb).cumprod()
    m = eqc.resample('ME').last().pct_change().dropna()
    var95 = -np.quantile(m, 0.05)
    scale = min(0.065 / var95, 9.75)
    md = m * scale
    qual, _ = darwinia_m(md, 30_000)
    dd = (eqc / eqc.cummax() - 1).min()
    yrs = range(md.index[0].year, md.index[-1].year + 1)
    f30 = darwinia_m(md, 30_000)[1].reindex(yrs, fill_value=0.0).mean()
    f375 = darwinia_m(md, 375_000)[1].reindex(yrs, fill_value=0.0).mean()
    sharpe = comb.mean() / comb.std() * np.sqrt(252)
    rows.append({'fut_share': f, 'mret': m.mean(), 'mstd': m.std(),
                 'var95': var95, 'maxdd': dd, 'sharpe': sharpe,
                 'posm': (m > 0).mean(), 'scale': scale,
                 'darwin_mret': md.mean(), 'qual': qual.mean(),
                 'fees30': f30, 'fees375': f375})
    r = rows[-1]
    print(f"\nf={f:4.2f}: mret{100 * r['mret']:+5.2f}% "
          f"msd{100 * r['mstd']:4.2f} dd{100 * r['maxdd']:5.1f}% "
          f"sharpe{sharpe:5.2f} posm{r['posm']:.2f} | scale{scale:4.2f} "
          f"Dmret{100 * r['darwin_mret']:+5.2f}% qual{r['qual']:.0%} "
          f"fees30 EUR{f30:,.0f} fees375 EUR{f375:,.0f}", flush=True)
    if f > 0:
        qy = qual.astype(int)
        print('   qual by yr: ' + ' '.join(
            f'{y}:{int(v.sum())}/{len(v)}' for y, v in qy.groupby(qy.index.year)))
pd.DataFrame(rows).to_csv(OUTDIR / 'darwinex_combo_sweep.csv', index=False)
print('\nDONE combo')
