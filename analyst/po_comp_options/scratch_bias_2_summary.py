#!/usr/bin/env python3
"""Summarize the bias re-simulation: reproduce published headline (V0), then
quantify each bias layer and the combined realistic variant."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

STUDY = Path('/root/spy/analyst/po_comp_options')
df = pd.read_parquet(STUDY / 'scratch_bias_resim_legs.parquet')
df['date'] = pd.to_datetime(df.entry_ts.str[:10])

# published cross-check
pub = pd.read_parquet(STUDY / 'straddle_armtrail.parquet')
print(f"resim boxes: {len(df)}; published boxes: {len(pub)}")
m = df.merge(pub[['ep_id', 'cohort', 'single_at', 'strad_at']],
             on=['ep_id', 'cohort'], how='inner')
print(f"matched: {len(m)}; single V0 corr vs published: "
      f"{m['L_e0_x0'].corr(m['single_at']):.4f}, "
      f"max abs diff {np.nanmax(np.abs(m['L_e0_x0']-m['single_at'])):.4f}")


def strad(df, tag, xk):
    """Premium-weighted straddle pnl for entry tag + exit variant xk."""
    lw = df[f'L_{tag}_px'] if tag == 'e0' else df[f'L_{tag}_px']
    pass


def straddle_col(d, tag, xk):
    lp, sp = d[f'L_{tag}_{xk}'], d[f'S_{tag}_{xk}']
    lw = d[f'L_{tag}_px'.replace('_px', '_px')]
    lw = d[f'L_{tag}_px'] if f'L_{tag}_px' in d else None
    return None


def stats(v, dates=None, label=''):
    v = pd.Series(v).astype(float)
    ok = v.notna()
    v = v[ok]
    n = len(v)
    if n < 3:
        return f"{label:46s} n={n}"
    t = v.mean() / (v.std(ddof=1) / np.sqrt(n))
    line = f"{label:46s} n={n:4d} mean={100*v.mean():+6.2f}% t={t:+5.2f} win={100*(v>0).mean():4.0f}%"
    if dates is not None:
        dd = pd.Series(dates)[ok.values]
        g = v.groupby(dd.values).mean()
        tc = g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))
        line += f" tclust={tc:+5.2f} (d={len(g)})"
    return line


# straddle weights: entry premiums per variant
for tag in ('e0', 'e1'):
    wl = df[f'L_{tag}_px'].astype(float)
    ws = df[f'S_{tag}_px'].astype(float) if f'S_{tag}_px' in df else np.nan
    for xk in ('x0', 'x1', 'xl', 'xc'):
        lp = df[f'L_{tag}_{xk}']
        sp = df[f'S_{tag}_{xk}'] if f'S_{tag}_{xk}' in df else np.nan
        df[f'STRAD_{tag}_{xk}'] = (lp * wl + sp * ws) / (wl + ws)
    # spread-adjusted (round trip = 2x half-spread per leg)
    df[f'L_{tag}_x1_spr'] = df[f'L_{tag}_x1'] - 2 * df['L_hs_frac']
    if 'S_hs_frac' in df:
        df[f'STRAD_{tag}_x1_spr'] = df[f'STRAD_{tag}_x1'] - 2 * (
            df['L_hs_frac'] * wl + df['S_hs_frac'] * ws) / (wl + ws)

print("\n=== half-spread estimates (fraction of premium, per side) ===")
print(df[['L_hs_frac', 'S_hs_frac']].describe(percentiles=[.25, .5, .75, .9]).round(4).to_string())
print("\nfill_lag (min; + = stale print BEFORE signal):")
print(df[['L_fill_lag_min', 'S_fill_lag_min']].describe(percentiles=[.5, .75, .9, .99]).round(2).to_string())
print("e1 wait (min to first print after signal):")
print(df[['L_e1_wait_min', 'S_e1_wait_min']].describe(percentiles=[.5, .75, .9, .99]).round(2).to_string())
print("\nentry px change stale->strict (L): median "
      f"{((df.L_e1_px-df.L_e0_px)/df.L_e0_px).median()*100:+.2f}%, "
      f"mean {((df.L_e1_px-df.L_e0_px)/df.L_e0_px).mean()*100:+.2f}%")

D = df['date']
print("\n=== SINGLE LEG (break direction, W1 ATM, arm100/trail30) ===")
print(stats(df['L_e0_x0'], D, 'V0 published: stale entry, exit AT level'))
print(stats(df['L_e0_x1'], D, 'X1 exit at next print (min(level,close))'))
print(stats(df['L_e0_xl'], D, 'XL exit at trigger-bar LOW (worst bound)'))
print(stats(df['L_e0_xc'], D, 'XC close-confirmed trail (close trigger+fill)'))
print(stats(df['L_e1_x0'], D, 'E1 strict-after entry, exit at level'))
print(stats(df['L_e1_x1'], D, 'E1 + X1 (strict entry + next-print exits)'))
e1ok = df['L_e1_wait_min'] <= 5
print(stats(df.loc[e1ok, 'L_e1_x1'], D[e1ok], 'E1<=5min wait + X1'))
print(stats(df['L_e1_x1_spr'] if 'L_e1_x1_spr' in df else df['L_e0_x1_spr'], D, '  (spread column check)'))
df['L_e1_x1_sprd'] = df['L_e1_x1'] - 2 * df['L_hs_frac']
print(stats(df['L_e1_x1_sprd'], D, 'E1 + X1 + spread (2x half-spread)'))
print(stats(df.loc[e1ok, 'L_e1_x1_sprd'], D[e1ok], 'REALISTIC: E1<=5m + X1 + spread'))
lag2 = df['L_fill_lag_min'].abs() <= 2
print(stats(df.loc[lag2, 'L_e0_x0'], D[lag2], 'V0, liquidity |fill_lag|<=2min'))
liq = df['L_prints_day'] >= 100
print(stats(df.loc[liq, 'L_e0_x0'], D[liq], 'V0, >=100 prints on entry day'))
print(stats(df.loc[liq, 'L_e1_x1_sprd'], D[liq], 'REALISTIC + >=100 prints/day'))

print("\n=== STRADDLE (both legs, premium-weighted) ===")
both = df['S_e0_x0'].notna()
print(stats(df['STRAD_e0_x0'], D, 'V0 published'))
print(stats(df['STRAD_e0_x1'], D, 'X1 next-print exits'))
print(stats(df['STRAD_e0_xl'], D, 'XL worst bound'))
print(stats(df['STRAD_e0_xc'], D, 'XC close-confirmed'))
print(stats(df['STRAD_e1_x0'], D, 'E1 strict entry'))
print(stats(df['STRAD_e1_x1'], D, 'E1 + X1'))
print(stats(df['STRAD_e1_x1_spr'], D, 'E1 + X1 + spread'))
bothok = e1ok & (df['S_e1_wait_min'] <= 5)
print(stats(df.loc[bothok, 'STRAD_e1_x1_spr'], D[bothok], 'REALISTIC: both legs E1<=5m + X1 + spread'))
liq2 = liq & (df['S_prints_day'] >= 100)
print(stats(df.loc[liq2, 'STRAD_e1_x1_spr'], D[liq2], 'REALISTIC + >=100 prints/day both'))

print("\n=== cohort split (REALISTIC straddle) ===")
for c, g in df[bothok].groupby('cohort'):
    print(stats(g['STRAD_e1_x1_spr'], g['date'], f'  {c}'))
print("\n=== cohort split (REALISTIC single) ===")
for c, g in df[e1ok].groupby('cohort'):
    print(stats(g['L_e1_x1_sprd'], g['date'], f'  {c}'))

print("\nexit-kind mix (published single): "
      f"{df['L_e0_kind'].value_counts(normalize=True).round(3).to_dict()}")
print(f"E1 attrition: single legs no-print<=5m: {(~e1ok).sum()} "
      f"({(~e1ok).mean()*100:.1f}%); straddle both-legs: {(~bothok).sum()}")
