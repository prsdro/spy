#!/usr/bin/env python3
"""v3 digest: retest confirmation (in/OOS), RTH vs ETH, overnight class,
PO position/slope/alignment conditioning. Event-clustered, contract-deduped."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path('/root/spy/analyst/po_comp_options')
V1_TICKERS = {'AMZN', 'NVDA', 'MSFT'}
EXITS = ['pnl_tp100_stop50', 'pnl_sc50_80', 'pnl_hold', 'pnl_tp100_boxstop']


def load(sess):
    tr = pd.read_parquet(STUDY / f'v3_{sess}_trades.parquet')
    tr = tr.drop_duplicates(subset=['ep_id', 'variant', 'direction', 'bucket',
                                    'vehicle', 'contract'])
    tr['sess'] = sess
    tr['insample'] = tr.ticker.isin(V1_TICKERS) & (tr.entry_ts >= '2025-07-07')
    tr['box5'] = tr.n_box_bars >= 5
    tr['align'] = np.sign(tr.po_slope3) == tr.direction
    return tr


def cs(df, col='pnl_tp100_stop50'):
    df = df[~df.censored]
    g = df.groupby('ep_id')[col].mean()
    n = len(g)
    if n < 5:
        return f"n={n} (thin)"
    t = g.mean() / (g.std(ddof=1) / np.sqrt(n))
    return f"{g.mean():+.3f} (t={t:.2f}, n={n})"


R, E = load('rth'), load('eth')
ALL = pd.concat([R, E])
out = {}

print("="*30, "1. MATURE-BOX RETEST LONGS (the lead) — tp100_stop50", "="*30)
for sess, tr in [('RTH', R), ('ETH', E)]:
    rl = tr[(tr.variant == 'retest') & (tr.vehicle == 'long') & tr.box5]
    print(f"[{sess}] all: {cs(rl)} | in-sample(v1): {cs(rl[rl.insample])} | OOS: {cs(rl[~rl.insample])}")
    print(f"      dir: down {cs(rl[rl.direction==-1])} | up {cs(rl[rl.direction==1])}")
    print(f"      bucket: W1 {cs(rl[rl.bucket=='W1'])} | W2 {cs(rl[rl.bucket=='W2'])}")
    print(f"      1-4 bar boxes (contrast): {cs(tr[(tr.variant=='retest')&(tr.vehicle=='long')&~tr.box5])}")
rl = R[(R.variant == 'retest') & (R.vehicle == 'long') & R.box5]
print("per-ticker (RTH, tp100_stop50):",
      {k: cs(g) for k, g in rl.groupby('ticker')})

print("\n", "="*30, "2. DOWN-BREAK PUT CELL (most mined v2 cell) — W1 retest", "="*30)
for sess, tr in [('RTH', R), ('ETH', E)]:
    c = tr[(tr.variant == 'retest') & (tr.vehicle == 'long') & tr.box5 &
           (tr.direction == -1) & (tr.bucket == 'W1')]
    print(f"[{sess}] {cs(c)} | OOS only: {cs(c[~c.insample])}")

print("\n", "="*30, "3. OVERNIGHT-COIL CLASS (ETH only) — immediate longs", "="*30)
im = E[(E.variant == 'immediate') & (E.vehicle == 'long')]
print("overnight break (rolled to open):", cs(im[im.rolled_to_open]))
print("intraday break:                  ", cs(im[~im.rolled_to_open]))
print("overnight by dir: down", cs(im[im.rolled_to_open & (im.direction == -1)]),
      "| up", cs(im[im.rolled_to_open & (im.direction == 1)]))
print("overnight retests:", cs(E[(E.variant == 'retest') & (E.vehicle == 'long') &
                                 E.rolled_to_open]))

print("\n", "="*30, "4. PO CONDITIONING — retest longs (both sessions pooled)", "="*30)
fam = ALL[(ALL.variant == 'retest') & (ALL.vehicle == 'long')]
print("-- PO zone at episode start --")
for z, g in fam.groupby('phase_zone'):
    print(f"  {z:14s} {cs(g)}")
print("-- PO 3-bar slope terciles --")
fam2 = fam.dropna(subset=['po_slope3']).copy()
fam2['slope_bin'] = pd.qcut(fam2.po_slope3, 3, labels=['falling', 'flat', 'rising'])
for z, g in fam2.groupby('slope_bin', observed=True):
    print(f"  {z:14s} {cs(g)}")
print("-- alignment: break direction vs PO slope --")
print("  with-slope   ", cs(fam[fam.align]))
print("  against-slope", cs(fam[~fam.align]))
print("-- same, for IMMEDIATE longs --")
imf = ALL[(ALL.variant == 'immediate') & (ALL.vehicle == 'long')]
print("  with-slope   ", cs(imf[imf.align]))
print("  against-slope", cs(imf[~imf.align]))
print("-- PO position x direction (retest longs, zone grouped coarse) --")
fam3 = fam.copy()
fam3['pos'] = np.select([fam3.po < -23.6, fam3.po > 23.6], ['low', 'high'], 'mid')
for (p, d), g in fam3.groupby(['pos', 'direction']):
    print(f"  PO {p:4s} dir {'up' if d==1 else 'dn'}: {cs(g)}")

print("\n", "="*30, "5. CREDIT SIDE + THIRDS quick check (RTH)", "="*30)
sh = R[(R.vehicle == 'short') & (R.variant == 'comp_start')]
print("comp_start shorts (sell into compression) hold:", cs(sh, 'pnl_hold'))
tl = ALL[(ALL.variant == 'third_long') & (ALL.vehicle == 'long')]
print("third_long:", cs(tl))
ts_ = ALL[(ALL.variant == 'third_short') & (ALL.vehicle == 'long')]
print("third_short:", cs(ts_))

print("\n", "="*30, "6. no-fill drops by variant (ETH) — selection check", "="*30)
print("ETH legs by variant:", E.groupby('variant').size().to_dict())
print("RTH legs by variant:", R.groupby('variant').size().to_dict())
