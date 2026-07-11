#!/usr/bin/env python3
"""Stage 2: replay tuning processes over the config matrix, walk-forward.

Selectors (config chosen fresh at EVERY trade, using only trades whose
entry is >= 14 calendar days old — outcome fully realized under the max
10-trading-day cap — and within a trailing 2-year window):
  fixed_std      : frozen production config (arm.75/ret.50/cap5)
  wf_global      : argmax trailing mean pnl, all tickers        (min 60)
  wf_global_t    : argmax trailing t-stat                       (min 60)
  wf_stock       : argmax trailing mean, SAME ticker only       (min 15,
                   fallback = wf_global choice)
  wf_regime      : argmax trailing mean among trades sharing today's SPY
                   d21-EMA-slope regime (rising/falling)        (min 40,
                   fallback = wf_global choice)
  oracle_stock   : per-stock BEST config over the FULL 7 years (the
                   in-sample "tuned to individual stocks" mirage)
  oracle_trade   : per-trade best config (absolute ceiling, pure lookahead)
Verdict standard: a tuning process earns its place only if it beats
fixed_std out-of-sample (pooled + both eras).
Output: theta/adaptive_select_summary.csv
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
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/SPY.parquet'
ET = 'America/New_York'
LAG_S = 14 * 86400
WIN_S = 730 * 86400
STD = 'p_0.75_0.50_5'

d = pd.read_parquet(OUTDIR / 'theta_adaptive_matrix.parquet')
d = d.sort_values('entry_s').reset_index(drop=True)
pcols = [c for c in d.columns if c.startswith('p_')]
M = d[pcols].to_numpy(float)
n, k = M.shape
std_i = pcols.index(STD)
print(f'{n} trades x {k} configs, NaN cells: {np.isnan(M).sum()}')

# SPX d21-EMA slope regime (prior completed day vs the day before it)
import io
import zipfile
with zipfile.ZipFile('/root/spy/data/SPX_full_1day_tabbitf.zip') as z:
    txt = z.read(z.namelist()[0]).decode()
spx = pd.read_csv(io.StringIO(txt), header=None,
                  names=['d', 'o', 'h', 'l', 'c'])
dly = pd.Series(spx.c.values, index=pd.to_datetime(spx.d))
e21 = ema(dly, 21)
slope_by_day = {dly.index[i].date(): bool(e21.iloc[i - 1] > e21.iloc[i - 2])
                for i in range(2, len(dly))}
days_sorted = np.array(sorted(slope_by_day))
ent_day = pd.to_datetime(d.date).dt.date.to_numpy()
reg = np.array([slope_by_day[days_sorted[np.searchsorted(days_sorted, x) - 1]]
                if np.searchsorted(days_sorted, x) > 0 else True
                for x in ent_day])
print(f'SPY regime rising on {100 * reg.mean():.0f}% of trades')

es = d.entry_s.to_numpy()
tk = d.ticker.to_numpy()
choices = {s: np.full(n, std_i) for s in
           ['wf_global', 'wf_global_t', 'wf_stock', 'wf_regime']}
fallbacks = {s: 0 for s in choices}


def argmax_mean(sub):
    mu = np.nanmean(sub, axis=0)
    return int(np.nanargmax(mu))


for i in range(n):
    past = (es < es[i] - LAG_S) & (es >= es[i] - LAG_S - WIN_S)
    npast = past.sum()
    if npast >= 60:
        sub = M[past]
        g = argmax_mean(sub)
        choices['wf_global'][i] = g
        mu = np.nanmean(sub, axis=0)
        sd = np.nanstd(sub, axis=0, ddof=1)
        cnt = np.sum(~np.isnan(sub), axis=0)
        choices['wf_global_t'][i] = int(np.nanargmax(mu / (sd / np.sqrt(cnt))))
    else:
        g = std_i
        fallbacks['wf_global'] += 1
        fallbacks['wf_global_t'] += 1
    ps = past & (tk == tk[i])
    if ps.sum() >= 15:
        choices['wf_stock'][i] = argmax_mean(M[ps])
    else:
        choices['wf_stock'][i] = g
        fallbacks['wf_stock'] += 1
    pr = past & (reg == reg[i])
    if pr.sum() >= 40:
        choices['wf_regime'][i] = argmax_mean(M[pr])
    else:
        choices['wf_regime'][i] = g
        fallbacks['wf_regime'] += 1

# oracles
stock_best = {t: argmax_mean(M[tk == t]) for t in np.unique(tk)}
oracle_stock = np.array([stock_best[t] for t in tk])
oracle_trade = np.nanargmax(np.where(np.isnan(M), -9, M), axis=1)

d['era'] = np.where(d.year <= 2022, 'E1', 'E2')


def evalsel(idx):
    p = M[np.arange(n), idx]
    out = {}
    for lbl, m in [('pooled', np.ones(n, bool)),
                   ('E1', (d.era == 'E1').to_numpy()),
                   ('E2', (d.era == 'E2').to_numpy())]:
        v = pd.Series(p[m], index=d.index[m])
        by = d[m].assign(p=v).groupby('date').p.mean()
        out[f'{lbl}_bps'] = round(1e4 * np.nanmean(v), 1)
        out[f'{lbl}_t'] = round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2)
    return out


rows = []
sels = {'fixed_std': np.full(n, std_i), **choices,
        'oracle_stock (IS mirage)': oracle_stock,
        'oracle_trade (ceiling)': oracle_trade}
for name, idx in sels.items():
    churn = np.mean(idx[1:] != idx[:-1]) if name.startswith('wf') else np.nan
    rows.append({'selector': name, **evalsel(idx),
                 'fallback%': round(100 * fallbacks.get(name, 0) / n)
                 if name in fallbacks else np.nan,
                 'churn%': round(100 * churn) if churn == churn else np.nan})
S = pd.DataFrame(rows)
S.to_csv(OUTDIR / 'adaptive_select_summary.csv', index=False)
pd.set_option('display.width', 200)
print(S.to_string(index=False))

# config landscape: full-period global means, best/worst spread
mu = np.nanmean(M, axis=0)
order = np.argsort(mu)[::-1]
print('\nfull-period config landscape (global, in-sample):')
for j in order[:4]:
    print(f'  {pcols[j]}: {1e4*mu[j]:+.1f}bps')
print('   ...')
for j in order[-3:]:
    print(f'  {pcols[j]}: {1e4*mu[j]:+.1f}bps')
print(f'  std rank: {list(order).index(std_i)+1}/{k}')

# what wf_stock actually picked (top picks by frequency)
picks = pd.Series([pcols[j] for j in choices['wf_stock']]).value_counts()
print(f'\nwf_stock pick distribution (top 6 of {picks.size}):')
print(picks.head(6).to_string())
print('\nADAPTIVE SELECT COMPLETE')
