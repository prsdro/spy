#!/usr/bin/env python3
"""Quantify the box-freeze ambiguity lookahead: for k<5 boxes the box is only
confirmable at the close of the FIRST non-compression hourly bar (bar i+k), but
the backtest admits entries from the close of bar i+k-1. Entries inside that
confirmation hour use a box the trader could not yet know was final; pokes that
got re-absorbed (compression continued -> box grew) are silently excluded ->
survivorship on the entry bar. Classify every headline box and re-stat."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F
from indicators import compute_phase_oscillator

STUDY = Path('/root/spy/analyst/po_comp_options')

CFG = [('orig8', 'events_v2_eth.csv', 'underlying_5m_topup_v2.parquet'),
       ('new12', 'events_new12.csv', 'underlying_5m_topup_new12.parquet')]

rows = []
for cohort, evf, topup in CFG:
    F.TOPUP = STUDY / topup
    ev = pd.read_csv(STUDY / evf)
    for tkr in ev.ticker.unique():
        df5 = F.load_5m(tkr)
        h, _ = F.hourly_and_daily(df5, session='ETH')
        h = compute_phase_oscillator(h)
        sub = ev[ev.ticker == tkr]
        for _, e in sub.iterrows():
            start = pd.Timestamp(e['start_ts_et'])
            try:
                i = h.index.get_loc(start)
            except KeyError:
                continue
            k = 0
            while i + k < len(h) and k < 5 and h['po_compression'].iloc[i + k] == 1:
                k += 1
            if k == 0 or i + k >= len(h):
                continue
            confirm_close = h.index[i + k] + pd.Timedelta(minutes=60)
            rows.append({'cohort': cohort, 'ep_id': e['ep_id'], 'k': k,
                         'confirm_close': confirm_close.isoformat()})
    print(f"{cohort} done: {len(rows)} boxes so far", flush=True)

bx = pd.DataFrame(rows)
bx.to_parquet(STUDY / 'scratch_bias_freeze_class.parquet')

d = pd.read_parquet(STUDY / 'scratch_bias_resim_legs.parquet')
d = d.merge(bx, on=['cohort', 'ep_id'], how='left')
d['date'] = pd.to_datetime(d.entry_ts.str[:10])
ets = pd.to_datetime(d.entry_ts.str.replace('T', ' ', regex=False), utc=True)
cc = pd.to_datetime(d.confirm_close.str.replace('T', ' ', regex=False), utc=True)
d['ambiguous'] = (d.k < 5) & (ets <= cc)
print(f"\nheadline boxes: {len(d)}; k<5: {(d.k<5).sum()}; "
      f"ambiguous (k<5 & entry <= confirm-bar close): {d.ambiguous.sum()}")

e1ok = d.L_e1_wait_min <= 5
bothok = e1ok & (d.S_e1_wait_min <= 5)
wl, ws = d.L_e1_px, d.S_e1_px
d['R_strad'] = (d.L_e1_x1 * wl + d.S_e1_x1 * ws) / (wl + ws) - 2 * (
    d.L_hs_frac * wl + d.S_hs_frac * ws) / (wl + ws)
d['R_sing'] = d.L_e1_x1 - 2 * d.L_hs_frac
wl0, ws0 = d.L_e0_px, d.S_e0_px
d['V0_strad'] = (d.L_e0_x0 * wl0 + d.S_e0_x0 * ws0) / (wl0 + ws0)


def stats(v, dates, label):
    v = pd.Series(v).astype(float).dropna()
    n = len(v)
    if n < 3:
        print(f"{label:52s} n={n}")
        return
    t = v.mean() / (v.std(ddof=1) / np.sqrt(n))
    g = v.groupby(pd.Series(dates).loc[v.index].values).mean()
    tc = g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))
    print(f"{label:52s} n={n:4d} mean={100*v.mean():+6.2f}% t={t:+5.2f} "
          f"tclust={tc:+5.2f} win={100*(v>0).mean():3.0f}%")


amb = d.ambiguous.fillna(False)
print("\n=== published V0 by freeze class ===")
stats(d.loc[~amb, 'L_e0_x0'], d.date[~amb], 'V0 single, TRADEABLE (confirmed box)')
stats(d.loc[amb, 'L_e0_x0'], d.date[amb], 'V0 single, AMBIGUOUS (inside confirm bar)')
stats(d.loc[~amb, 'V0_strad'], d.date[~amb], 'V0 straddle, TRADEABLE')
stats(d.loc[amb, 'V0_strad'], d.date[amb], 'V0 straddle, AMBIGUOUS')
print("\n=== realistic fills by freeze class ===")
stats(d.loc[e1ok & ~amb, 'R_sing'], d.date[e1ok & ~amb], 'realistic single, TRADEABLE')
stats(d.loc[e1ok & amb, 'R_sing'], d.date[e1ok & amb], 'realistic single, AMBIGUOUS')
stats(d.loc[bothok & ~amb, 'R_strad'], d.date[bothok & ~amb], 'realistic straddle, TRADEABLE')
stats(d.loc[bothok & amb, 'R_strad'], d.date[bothok & amb], 'realistic straddle, AMBIGUOUS')
print("\n=== realistic, TRADEABLE, by box size ===")
for lbl, m in [('k=5', (d.k >= 5)), ('k<5 entry after confirm', (d.k < 5) & ~amb)]:
    stats(d.loc[bothok & m & ~amb, 'R_strad'], d.date[bothok & m & ~amb], f'straddle {lbl}')
    stats(d.loc[e1ok & m & ~amb, 'R_sing'], d.date[e1ok & m & ~amb], f'single {lbl}')
