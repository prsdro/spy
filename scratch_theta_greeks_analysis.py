#!/usr/bin/env python3
"""Greeks analysis on the ridge cells (Pedro: gamma, charm regimes, IV crush,
conviction/sizing filters). Pre-declared hypotheses (before outcomes read):
  H1 charm: within the OTM sleeve (p07_28), repressive charm (negative for
     long calls, normalized by delta) at entry -> worse outcomes; within the
     deep-ITM sleeve charm should be weakly predictive at most.
  H2 gamma: gamma-per-premium-dollar at entry higher -> better (cheap
     convexity thesis); explanatory decomposition per cell.
  H3 IV crush: exit IV < entry IV on average; drag largest on the
     longest-vega cells (a0_28, p07_28).
  Features framed as SIZE MULTIPLIERS (quintiles), not binary skips.
Cohort: surface trades with production gates (f_hourrel>=1, spread<=5%),
half-spread P&L; era split shown. Entry greeks = last hourly greek row with
t <= entry signal (no lookahead); exit IV = last row <= exit_s.
Outputs: theta/theta_greeks_features.parquet, theta/greeks_summary.csv.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
CELL_MGMT = {'m2_09': 'm1', 'a0_09': 'm1', 'a0_28': 'm2', 'p07_28': 'm2'}

s = pd.read_parquet(OUTDIR / 'theta_surface.parquet')
v = pd.read_parquet(OUTDIR / 'theta_volume_features.parquet')[
    ['ticker', 'entry_s', 'f_hourrel']]
s = s.merge(v, on=['ticker', 'entry_s'], how='left')
tr = pd.read_parquet(OUTDIR / 'theta_stock_directional_strict.parquet')
tr = tr[(tr['pop'] == 'hourly') & (tr.direction == 1)][
    ['ticker', 'entry_s', 'exit_s']]
s = s.merge(tr, on=['ticker', 'entry_s'], how='left')
gl = pd.read_sql('SELECT * FROM grid_legs', sqlite3.connect(
    f"file:{OUTDIR/'quotes_grid.sqlite'}?mode=ro", uri=True))
gl = gl[gl.cell.isin(CELL_MGMT)]
lp = gl.pivot_table(index=['ticker', 'entry_s'], columns='cell',
                    values='contract', aggfunc='first').reset_index()
lp.columns = ['ticker', 'entry_s'] + [f'c_{c}' for c in lp.columns[2:]]
s = s.merge(lp, on=['ticker', 'entry_s'], how='left')

gcon = sqlite3.connect(f"file:{OUTDIR/'greeks.sqlite'}?mode=ro", uri=True)
G = pd.read_sql('SELECT * FROM greeks', gcon)
G = G[(G.iv > 0.01) & (G.iv < 5)]
G1 = G[G['ord'] == 'first_order'].sort_values('t')
G2 = G[G['ord'] == 'second_order'].sort_values('t')
g1 = {k: gg[['t', 'iv', 'delta', 'theta', 'vega']].to_numpy()
      for k, gg in G1.groupby('contract')}
g2 = {k: gg[['t', 'gamma', 'vanna', 'charm', 'iv', 'und']].to_numpy()
      for k, gg in G2.groupby('contract')}
print(f'greek series: {len(g1)} contracts (1st), {len(g2)} (2nd)', flush=True)


def at_or_before(arr, t):
    # greeks t was stored as floor(epoch_seconds/1000) (pandas us-resolution
    # bug in the pull); rescale to seconds with +1000s slack and REQUIRE the
    # matched row to be strictly before/at the target and within 26h of it
    if len(arr):
        arr = arr.copy()
        arr[:, 0] = arr[:, 0] * 1000
    i = np.searchsorted(arr[:, 0], t + 1000, side='right') - 1
    if i >= 0 and arr[i, 0] < t - 26 * 3600:
        return None
    return arr[i] if i >= 0 else None


# rename piped columns to safe identifiers so itertuples keeps them
ren = {}
for cell, mg in CELL_MGMT.items():
    ren[f'{cell}|{mg}|half'] = f'pnl_{cell}'
    ren[f'{cell}|sprd'] = f'sprd_{cell}'
    ren[f'{cell}|prem'] = f'prem_{cell}'
s = s.rename(columns=ren)

rows = []
for r in s.itertuples():
    rec = {'ticker': r.ticker, 'entry_s': r.entry_s, 'date': r.date,
           'year': r.year, 'gated': bool((r.f_hourrel or 0) >= 1)}
    any_cell = False
    for cell, mg in CELL_MGMT.items():
        cid = getattr(r, f'c_{cell}', None)
        pnl = getattr(r, f'pnl_{cell}', None)
        sprd = getattr(r, f'sprd_{cell}', None)
        prem = getattr(r, f'prem_{cell}', None)
        if not isinstance(cid, str) or pnl is None or np.isnan(pnl):
            continue
        a1 = at_or_before(g1.get(cid, np.zeros((0, 5))), r.entry_s)
        a2 = at_or_before(g2.get(cid, np.zeros((0, 6))), r.entry_s)
        if a1 is None or a2 is None:
            continue
        x1 = at_or_before(g1.get(cid, np.zeros((0, 5))), r.exit_s)
        _, iv0, delta, theta, vega = a1
        _, gamma, vanna, charm, iv2, und = a2
        if not (0.01 < delta < 0.999):
            continue
        prem_d = prem / 100 * und if prem else np.nan
        rec[f'{cell}_pnl'] = pnl
        rec[f'{cell}_sprd'] = sprd
        rec[f'{cell}_delta'] = delta
        rec[f'{cell}_gamma_pp'] = gamma * und / prem_d if prem_d else np.nan
        rec[f'{cell}_theta_pd'] = theta / prem_d if prem_d else np.nan
        rec[f'{cell}_vega_pp'] = vega / prem_d if prem_d else np.nan
        rec[f'{cell}_charm_n'] = charm / max(delta, 1e-6)
        rec[f'{cell}_vanna'] = vanna
        rec[f'{cell}_iv0'] = iv0
        rec[f'{cell}_ivx'] = x1[1] if x1 is not None else np.nan
        any_cell = True
    if any_cell:
        rows.append(rec)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_greeks_features.parquet')
print(f'trades with greeks: {len(d)}')


def st(g, col):
    x = g[col].dropna()
    if len(x) < 60:
        return dict(n=len(x))
    by = g.loc[x.index].groupby('date')[col].mean()
    return dict(n=len(x), mean=round(100 * x.mean(), 2),
                med=round(100 * x.median(), 1), win=round(100 * (x > 0).mean()),
                tclust=round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2))


print('\n===== per-cell greek profile at entry (gated cohort medians) =====')
prof = []
for cell in CELL_MGMT:
    g = d[d.gated & d[f'{cell}_pnl'].notna()]
    if not len(g):
        continue
    crush = (g[f'{cell}_ivx'] - g[f'{cell}_iv0']).dropna()
    prof.append({
        'cell': cell, 'n': len(g),
        'delta': round(g[f'{cell}_delta'].median(), 2),
        'gamma/prem$': round(g[f'{cell}_gamma_pp'].median(), 2),
        'theta%/day': round(100 * g[f'{cell}_theta_pd'].median(), 2),
        'vega/prem$': round(g[f'{cell}_vega_pp'].median(), 2),
        'charm_norm': round(g[f'{cell}_charm_n'].median(), 4),
        'entryIV': round(g[f'{cell}_iv0'].median(), 2),
        'IVcrush(exit-entry)': round(crush.median(), 4),
        'crush<0 share': round(100 * (crush < 0).mean())})
P = pd.DataFrame(prof)
print(P.to_string(index=False))

print('\n===== conviction features: quintiles on gated cohort (pnl half) =====')
out = []
FEATS = {'charm_n': 'H1 charm (higher=more supportive)',
         'gamma_pp': 'H2 gamma per premium $',
         'vanna': 'vanna', 'iv0': 'entry IV level'}
for cell in ['m2_09', 'p07_28', 'a0_28']:
    g = d[d.gated & d[f'{cell}_pnl'].notna()].copy()
    for f, lbl in FEATS.items():
        col = f'{cell}_{f}'
        gg = g[g[col].notna()].copy()
        if len(gg) < 300:
            continue
        gg['q'] = pd.qcut(gg[col], 5, labels=False, duplicates='drop')
        e_split = []
        med = gg[col].median()
        for era, ge in gg.groupby(gg.year <= 2022):
            hi = ge[ge[col] >= med][f'{cell}_pnl'].mean()
            lo = ge[ge[col] < med][f'{cell}_pnl'].mean()
            e_split.append(round(100 * (hi - lo), 2))
        qmeans = [round(100 * gg[gg.q == q][f'{cell}_pnl'].mean(), 2)
                  for q in sorted(gg.q.unique())]
        out.append({'cell': cell, 'feature': f, 'label': lbl,
                    'Q1..Q5': qmeans, 'era_hi-lo (E2,E1)': e_split})
for o in out:
    print(f"  {o['cell']:7s} {o['feature']:9s} Q1..Q5={o['Q1..Q5']} era_hi-lo={o['era_hi-lo (E2,E1)']}  ({o['label']})")

# IV crush vs pnl relationship (vega drag measured)
print('\n===== IV crush impact =====')
for cell in ['a0_28', 'p07_28', 'm2_09']:
    g = d[d.gated & d[f'{cell}_pnl'].notna()].copy()
    g['crush'] = g[f'{cell}_ivx'] - g[f'{cell}_iv0']
    gg = g.dropna(subset=['crush'])
    if len(gg) < 100:
        continue
    from scipy.stats import spearmanr
    rho = spearmanr(gg.crush, gg[f'{cell}_pnl']).statistic
    print(f"  {cell}: median crush {gg.crush.median():+.3f} IV pts, "
          f"crush<0 on {100*(gg.crush<0).mean():.0f}% of trades, "
          f"spearman(crush, pnl)={rho:+.2f}")
pd.DataFrame(out).to_csv(OUTDIR / 'greeks_summary.csv', index=False)
print('\nGREEKS ANALYSIS COMPLETE')
