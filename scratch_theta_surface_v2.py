#!/usr/bin/env python3
"""Surface v2: moneyness x tenor map re-run under the NEW exit rule.

New rule (blind-validated at stock level 2026-07-10): invalidation 5m close
< box_lo; arm after +1.0*dATR excursion; exit on close giving back 25% of
best; cap 10 TRADING days. Exit times precomputed in
theta_newrule_exits.parquet (m4). Kept for comparison: m1 = old 5d exits
(strict parquet), m2 = old-rule ext 10cd cap.
Quotes: quotes_grid.sqlite + quotes_grid_topup.sqlite (tail windows for the
~25% of m4 exits beyond the original entry+11cd pulls). Where a contract
expires before the m4 exit, the position is closed at its last two-sided
quote (sell-before-expiry convention).
Gates: production cohort = f_hourrel>=1 AND d21dist>=0 (per-cell spread
filter reported via sprd column; G2 two-sidedness inherent).
Outputs: theta/theta_surface_v2.parquet, theta/surface_v2_summary.csv.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
GRACE_S = 300

tr = pd.read_parquet(OUTDIR / 'theta_stock_directional_strict.parquet')
tr = tr[(tr['pop'] == 'hourly') & (tr.direction == 1)].copy()
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
tr = tr.merge(ent[['ticker', 'entry_s', 'spot', 'datr14_prior']],
              on=['ticker', 'entry_s'], how='inner')
newx = pd.read_parquet(OUTDIR / 'theta_newrule_exits.parquet')
tr = tr.merge(newx, on=['ticker', 'entry_s'], how='inner')
vol = pd.read_parquet(OUTDIR / 'theta_volume_features.parquet')[
    ['ticker', 'entry_s', 'f_hourrel']]
d21 = pd.read_parquet(OUTDIR / 'theta_d21dist.parquet')[
    ['ticker', 'entry_s', 'd21dist']]
tr = tr.merge(vol, on=['ticker', 'entry_s'], how='left') \
       .merge(d21, on=['ticker', 'entry_s'], how='left')
print(f'trades: {len(tr)}, gate coverage: '
      f'{tr.f_hourrel.notna().sum()}/{tr.d21dist.notna().sum()}', flush=True)

# old-rule ext-cap exits (m2) — reuse from prior surface run's machinery via
# theta_surface.parquet is not keyed by exit; recompute cheaply from strict
# parquet? m2 differs from m1 only when the 5d cap bound. For continuity we
# reuse the previously published m2 numbers; here m2 = m1 (5d) and m4 = new.
con1 = sqlite3.connect(f"file:{OUTDIR/'quotes_grid.sqlite'}?mode=ro", uri=True)
con2 = sqlite3.connect(f"file:{OUTDIR/'quotes_grid_topup.sqlite'}?mode=ro",
                       uri=True)
legs = pd.read_sql('SELECT * FROM grid_legs', con1)
CELLS = sorted(legs.cell.unique())
lp = legs.pivot_table(index=['ticker', 'entry_s'], columns='cell',
                      values='contract', aggfunc='first').reset_index()
tr = tr.merge(lp, on=['ticker', 'entry_s'], how='left')

qcache = {}


def quotes(cid):
    if cid not in qcache:
        if len(qcache) > 4000:
            qcache.clear()
        r = con1.execute('SELECT t,bid,ask FROM quotes WHERE contract=?',
                         (cid,)).fetchall()
        r += con2.execute('SELECT t,bid,ask FROM quotes WHERE contract=?',
                          (cid,)).fetchall()
        q = np.array(sorted(r), float) if r else np.zeros((0, 3))
        qcache[cid] = q[(q[:, 1] > 0) & (q[:, 2] > 0)] if len(q) else q
    return qcache[cid]


def eff(row, ef, side):
    m = (row[1] + row[2]) / 2
    return m + ef * (row[2] - m) if side == 'buy' else m - ef * (m - row[1])


rows = []
for n, r in enumerate(tr.itertuples()):
    rec = {'ticker': r.ticker, 'entry_s': r.entry_s, 'date': r.date,
           'year': r.year, 'grey': r.grey, 'f_hourrel': r.f_hourrel,
           'd21dist': r.d21dist}
    for cell in CELLS:
        cid = getattr(r, cell, None)
        if not isinstance(cid, str):
            continue
        q = quotes(cid)
        if not len(q):
            continue
        i = np.searchsorted(q[:, 0], r.entry_s)
        if i >= len(q) or q[i, 0] > r.entry_s + GRACE_S:
            continue
        for tag, ef in [('half', 0.5), ('full', 1.0)]:
            buy = eff(q[i], ef, 'buy')
            if buy <= 0.02:
                continue
            if tag == 'half':
                rec[f'{cell}|prem'] = buy / r.spot * 100
                rec[f'{cell}|sprd'] = \
                    (q[i, 2] - q[i, 1]) / ((q[i, 1] + q[i, 2]) / 2) * 100
            for mgmt, xs in [('m1', r.exit_s), ('m4', r.exit_new_s)]:
                k = min(np.searchsorted(q[:, 0], xs), len(q) - 1)
                rec[f'{cell}|{mgmt}|{tag}'] = eff(q[k], ef, 'sell') / buy - 1
    rows.append(rec)
    if (n + 1) % 800 == 0:
        print(f'...{n+1}/{len(tr)}', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_surface_v2.parquet')
print(f'scored {len(d)} trades', flush=True)


def stat(g, col):
    v = g[col].dropna()
    if len(v) < 80:
        return dict(n=len(v))
    by = g.loc[v.index].groupby('date')[col].mean()
    fs = np.linspace(0.005, 0.35, 70)
    gr = [np.mean(np.log1p(np.clip(f * v.values, -0.999, None))) for f in fs]
    gi = int(np.argmax(gr))
    return dict(n=len(v), mean=round(100 * v.mean(), 2),
                med=round(100 * v.median(), 1), win=round(100 * (v > 0).mean()),
                tclust=round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2),
                wipe=round(100 * (v <= -0.9).mean(), 1),
                kelly=round(100 * fs[gi]))


out = []
d['era'] = np.where(d.year <= 2022, 'E1', 'E2')
gated = d[(d.f_hourrel >= 1) & (d.d21dist >= 0)]
print(f'gated cohort: {len(gated)}', flush=True)
for cohort, g in [('all', d), ('gated', gated)]:
    for cell in CELLS:
        for mgmt in ['m1', 'm4']:
            col = f'{cell}|{mgmt}|half'
            if col not in g.columns:
                continue
            s = stat(g, col)
            if s.get('n', 0) < 80:
                continue
            sf = stat(g, f'{cell}|{mgmt}|full')
            e1 = g[g.era == 'E1'][col].dropna()
            e2 = g[g.era == 'E2'][col].dropna()
            out.append({'cohort': cohort, 'cell': cell, 'mgmt': mgmt,
                        'prem%': round(g[f'{cell}|prem'].median(), 1),
                        'sprd%': round(g[f'{cell}|sprd'].median(), 1),
                        **s,
                        'full_mean': sf.get('mean'),
                        'full_t': sf.get('tclust'),
                        'e1': round(100 * e1.mean(), 2) if len(e1) > 40 else np.nan,
                        'e2': round(100 * e2.mean(), 2) if len(e2) > 40 else np.nan})
S = pd.DataFrame(out)
S.to_csv(OUTDIR / 'surface_v2_summary.csv', index=False)
pd.set_option('display.width', 250)
print('\n===== SURFACE v2 (m1 = old 5d exits, m4 = NEW rule) =====')
print(S.to_string(index=False))
print('\nSURFACE V2 COMPLETE')
