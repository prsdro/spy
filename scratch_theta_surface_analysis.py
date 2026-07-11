#!/usr/bin/env python3
"""Moneyness x tenor SURFACE ANALYSIS — the mapping Pedro commissioned.

Cells (strike offset in dATR from spot; tenor DTE band target):
  {-2,-1,0,+0.75} x 9DTE ; {-2,-1,0,+0.75,+1.5} x 28DTE ; {-1,0,+0.75} x 45DTE
Universe: same 3,833 strict hourly-bull entries. Quotes: quotes_grid.sqlite.

Managements (underlying-keyed; premium never managed):
  M1 5d cap  — the validated baseline exits (exit_s from strict parquet)
  M2 ext cap — same rules, cap extended to 10 CALENDAR days (~7 trading
               days; quote windows were pulled to entry+11d, so this is the
               longest honestly-priceable extension; labeled 'ext', not 10td)
  M3 strike-touch (OTM cells only): exit when a 5m close >= strike, else M2.
Exec: half-spread primary, full-touch stress. P&L = % of premium.
Per cell: coverage/3833, premium %spot, entry spread %, mean/med/win,
date-clustered t, wipeout share, Kelly f* (grid<=0.35, ceilings), era split.
Outputs: theta/theta_surface.parquet, theta/surface_summary.csv.
"""
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
GRACE_S = 300
ARM_DATR, RETRACE = 0.75, 0.50
CAP_EXT = 10 * 86400
ET = 'America/New_York'

tr = pd.read_parquet(OUTDIR / 'theta_stock_directional_strict.parquet')
tr = tr[(tr['pop'] == 'hourly') & (tr.direction == 1)].copy()
ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
tr = tr.merge(ent[['ticker', 'entry_s', 'spot', 'box_lo', 'box_hi',
                   'datr14_prior']],
              on=['ticker', 'entry_s'], how='inner', suffixes=('', '_e'))
print(f'trades: {len(tr)}', flush=True)


def load5(tkr):
    fr = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            fr.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'high', 'low', 'close']))
    for top in ['underlying_5m_topup_v2.parquet', 'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            fr.append(t[['metric_ts_et', 'high', 'low', 'close']])
    df = pd.concat(fr, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True)
    df = df.drop_duplicates(subset='ts').sort_values('ts')
    df = df.set_index(df.ts.dt.tz_convert(ET)).between_time('09:30', '15:55')
    return (df.ts.map(lambda x: int(x.timestamp())).to_numpy(),
            df.high.to_numpy(float), df.low.to_numpy(float),
            df.close.to_numpy(float))


U = {t: load5(t) for t in tr.ticker.unique()}
print('underlying loaded', flush=True)

# extended-cap exit + per-strike touch times (strict conventions: delayed
# entry px, next-bar exit fills)
ext_exit, entry_px_map = {}, {}
for r in tr.itertuples():
    t, hi, lo, cl = U[r.ticker]
    i0 = np.searchsorted(t, r.entry_s, side='right')
    if i0 >= len(t):
        continue
    epx = cl[i0]
    i0 += 1
    if i0 >= len(t):
        continue
    entry_px_map[(r.ticker, r.entry_s)] = (epx, i0)
    end = np.searchsorted(t, r.entry_s + CAP_EXT)
    best, xj = 0.0, None
    arm = ARM_DATR * r.datr14_prior
    for j in range(i0, min(end, len(t))):
        best = max(best, hi[j] - epx)
        if cl[j] < r.box_lo or (best >= arm and cl[j] <= epx + RETRACE * best):
            xj = min(j + 1, len(cl) - 1)
            break
    if xj is None:
        xj = min(end, len(t)) - 1
    ext_exit[(r.ticker, r.entry_s)] = int(t[xj])
print('extended exits computed', flush=True)

con = sqlite3.connect(f"file:{OUTDIR/'quotes_grid.sqlite'}?mode=ro", uri=True)
legs = pd.read_sql('SELECT * FROM grid_legs', con)
CELLS = sorted(legs.cell.unique())
lp = legs.pivot_table(index=['ticker', 'entry_s'], columns='cell',
                      values='contract', aggfunc='first').reset_index()
tr = tr.merge(lp, on=['ticker', 'entry_s'], how='left')

qcache = {}
def quotes(cid):
    if cid not in qcache:
        if len(qcache) > 4000:
            qcache.clear()
        r = con.execute('SELECT t,bid,ask FROM quotes WHERE contract=? ORDER BY t',
                        (cid,)).fetchall()
        q = np.array(r, float) if r else np.zeros((0, 3))
        qcache[cid] = q[(q[:, 1] > 0) & (q[:, 2] > 0)] if len(q) else q
    return qcache[cid]


def eff(row, ef, side):
    m = (row[1] + row[2]) / 2
    return m + ef * (row[2] - m) if side == 'buy' else m - ef * (m - row[1])


rows = []
for n, r in enumerate(tr.itertuples()):
    key = (r.ticker, r.entry_s)
    if key not in ext_exit:
        continue
    x5 = U[r.ticker]
    rec = {'ticker': r.ticker, 'entry_s': r.entry_s, 'date': r.date,
           'year': r.year, 'grey': r.grey}
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
        strike = float(cid.split('|')[2])
        # strike-touch time (OTM cells): first 5m close >= strike after entry
        t5, hi5, lo5, cl5 = x5
        j0 = np.searchsorted(t5, r.entry_s, side='right') + 1
        jend = np.searchsorted(t5, r.entry_s + CAP_EXT)
        touch_s = None
        if strike > r.spot:
            m = cl5[j0:jend] >= strike
            if m.any():
                touch_s = int(t5[j0 + int(np.argmax(m))])
        for tag, ef in [('half', 0.5), ('full', 1.0)]:
            buy = eff(q[i], ef, 'buy')
            if buy <= 0.02:
                continue
            if tag == 'half':
                rec[f'{cell}|prem'] = buy / r.spot * 100
                rec[f'{cell}|sprd'] = (q[i, 2] - q[i, 1]) / ((q[i, 1] + q[i, 2]) / 2) * 100
            for mgmt, xs in [('m1', r.exit_s), ('m2', ext_exit[key]),
                             ('m3', min(touch_s, ext_exit[key]) if touch_s
                              else ext_exit[key])]:
                if mgmt == 'm3' and strike <= r.spot:
                    continue
                k = min(np.searchsorted(q[:, 0], xs), len(q) - 1)
                rec[f'{cell}|{mgmt}|{tag}'] = eff(q[k], ef, 'sell') / buy - 1
    rows.append(rec)
    if (n + 1) % 800 == 0:
        print(f'...{n+1}/{len(tr)}', flush=True)

d = pd.DataFrame(rows)
d.to_parquet(OUTDIR / 'theta_surface.parquet')
print(f'scored {len(d)} trades x {len(CELLS)} cells', flush=True)


def stat(g, col):
    v = g[col].dropna()
    if len(v) < 100:
        return dict(n=len(v))
    by = g.loc[v.index].groupby('date')[col].mean()
    fs = np.linspace(0.005, 0.35, 70)
    gr = [np.mean(np.log1p(np.clip(f * v.values, -0.999, None))) for f in fs]
    gi = int(np.argmax(gr))
    return dict(n=len(v), mean=round(100 * v.mean(), 2),
                med=round(100 * v.median(), 1), win=round(100 * (v > 0).mean()),
                tclust=round(by.mean() / (by.std(ddof=1) / np.sqrt(len(by))), 2),
                wipe=round(100 * (v <= -0.9).mean(), 1),
                kelly=round(100 * fs[gi]), kgrow=round(
                    100 * (np.exp(gr[gi] * 390) - 1)))


out = []
d['era'] = np.where(d.year <= 2022, 'E1', 'E2')
for cell in CELLS:
    for mgmt in ['m1', 'm2', 'm3']:
        col = f'{cell}|{mgmt}|half'
        if col not in d.columns:
            continue
        s = stat(d, col)
        if s.get('n', 0) < 100:
            continue
        sf = stat(d, f'{cell}|{mgmt}|full')
        e1 = d[d.era == 'E1'][col].dropna()
        e2 = d[d.era == 'E2'][col].dropna()
        out.append({'cell': cell, 'mgmt': mgmt,
                    'cov%': round(100 * s['n'] / 3833),
                    'prem%': round(d[f'{cell}|prem'].median(), 1),
                    'sprd%': round(d[f'{cell}|sprd'].median(), 1),
                    **s, 'full_mean': sf.get('mean'), 'full_tclust': sf.get('tclust'),
                    'e1_mean': round(100 * e1.mean(), 2) if len(e1) > 50 else np.nan,
                    'e2_mean': round(100 * e2.mean(), 2) if len(e2) > 50 else np.nan})
S = pd.DataFrame(out)
S.to_csv(OUTDIR / 'surface_summary.csv', index=False)
pd.set_option('display.width', 250)
print('\n===== THE SURFACE (half-spread; full as stress; Kelly = ceiling) =====')
print(S.sort_values(['mgmt', 'cell']).to_string(index=False))
print('\nSURFACE ANALYSIS COMPLETE')
