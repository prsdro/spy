#!/usr/bin/env python3
"""Bias quantification pass 2: fixed bracket TP100/SL50 under realistic fills,
same-bar TP/SL ties, censoring/exclusion counts, strike snapping, and the
close-confirmed + spread recovery variant."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
STUDY = Path('/root/spy/analyst/po_comp_options')
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
cache = {}


def bars(k):
    if k not in cache:
        cache[k] = np.array(con.execute(
            "SELECT t,o,h,l,c FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return cache[k]


def stats(v, dates=None, label=''):
    v = pd.Series(v).astype(float).dropna()
    n = len(v)
    if n < 3:
        return f"{label:52s} n={n}"
    t = v.mean() / (v.std(ddof=1) / np.sqrt(n))
    line = (f"{label:52s} n={n:4d} mean={100*v.mean():+6.2f}% t={t:+5.2f} "
            f"win={100*(v>0).mean():4.0f}%")
    if dates is not None:
        g = v.groupby(pd.Series(dates).loc[v.index].values).mean()
        tc = g.mean() / (g.std(ddof=1) / np.sqrt(len(g)))
        line += f" tclust={tc:+5.2f}"
    return line


# ---- population: same as resim (headline W1 ATM immediate intraday) ----
frames = []
for cohort, path in [('orig8', 'v3_eth_trades.parquet'),
                     ('new12', 'v3_new12_trades.parquet')]:
    df = pd.read_parquet(STUDY / path)
    df = df[(df.variant == 'immediate') & (df.bucket == 'W1') & (df.offset == 0.0)]
    df['cohort'] = cohort
    frames.append(df)
pop_all = pd.concat(frames, ignore_index=True)
longs_all = pop_all[pop_all.vehicle == 'long'].drop_duplicates(
    subset=['cohort', 'ep_id', 'contract'])
print("=== exclusion accounting (long W1 ATM immediate legs) ===")
print(f"all: {len(longs_all)}; rolled_to_open: {longs_all.rolled_to_open.sum()} "
      f"({longs_all.rolled_to_open.mean()*100:.1f}%); censored (of intraday): "
      f"{longs_all[~longs_all.rolled_to_open].censored.sum()}")
ro = longs_all[longs_all.rolled_to_open & ~longs_all.censored]
print(stats(ro.pnl_tp100_stop50, label='excluded overnight (rolled) fixed bracket'))
print(stats(ro.pnl_hold, label='excluded overnight (rolled) hold'))

pop = longs_all[(~longs_all.censored) & (~longs_all.rolled_to_open)].copy()
pop['date'] = pd.to_datetime(pop.entry_ts.str[:10])

# ---- strike snapping: how far is "ATM" from spot? ----
snap = (pop.strike - pop.spot).abs() / pop.spot * 100
print(f"\nATM snap |strike-spot|/spot %: median {snap.median():.2f}, "
      f"p90 {snap.quantile(.9):.2f}, p99 {snap.quantile(.99):.2f}, "
      f">2% of spot: {(snap > 2).sum()} legs")

# ---- fixed bracket realistic + same-bar ties ----
recs = []
for _, r in pop.iterrows():
    arr = bars(r.contract)
    if not len(arr):
        continue
    t = arr[:, 0]
    sig_ms = int(pd.Timestamp(r.entry_ts).timestamp() * 1000)
    expiry_ms = int((pd.Timestamp(r.expiry, tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    epx = r.entry_px
    # published path basis: recover fill_ms like entry_fill
    from backtest_po_comp_options import entry_fill
    f = entry_fill(np.c_[t, arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]], sig_ms)
    if f is None:
        continue
    _, fill_ms = f
    p = arr[(t > fill_ms) & (t <= expiry_ms)]
    if not len(p):
        continue
    hi, lo, cl = p[:, 2] / epx, p[:, 3] / epx, p[:, 4] / epx
    tp_hit = hi >= 2.0
    sl_hit = lo <= 0.5
    ti = int(np.argmax(tp_hit)) if tp_hit.any() else -1
    si = int(np.argmax(sl_hit)) if sl_hit.any() else -1
    hold = r.pnl_hold
    tie = ti >= 0 and si >= 0 and ti == si
    # published semantics (bilbo leg(): tp wins ties)
    if ti >= 0 and (si < 0 or ti <= si):
        pub = 1.0
    elif si >= 0:
        pub = -0.5
    else:
        pub = hold
    # realistic: stop wins ties (conservative), fills at min(level, close)
    if si >= 0 and (ti < 0 or si <= ti):
        real = min(0.5, cl[si]) - 1
    elif ti >= 0:
        real = 1.0  # limit at TP: high touched target; keep (mild optimism)
    else:
        real = hold
    recs.append({'cohort': r.cohort, 'ep_id': r.ep_id, 'date': r.date,
                 'pub': pub, 'real': real, 'tie': tie,
                 'pnl_col': r.pnl_tp100_stop50})
fx = pd.DataFrame(recs)
print("\n=== fixed bracket TP100/SL50, single leg ===")
print(stats(fx.pnl_col, fx.date, 'stored pnl_tp100_stop50 (repro check)'))
print(stats(fx.pub, fx.date, 'replicated published semantics'))
print(stats(fx.real, fx.date, 'realistic: stop-first ties + next-print stop fill'))
print(f"same-bar TP&SL ties: {fx.tie.sum()} / {len(fx)} ({fx.tie.mean()*100:.1f}%)")
for c, g in fx.groupby('cohort'):
    print(stats(g.real, g.date, f'  realistic {c}'))

# ---- close-confirmed + strict entry + spread (recovery candidate) ----
d = pd.read_parquet(STUDY / 'scratch_bias_resim_legs.parquet')
d['date'] = pd.to_datetime(d.entry_ts.str[:10])
e1ok = d.L_e1_wait_min <= 5
d['xc_spr'] = d.L_e1_xc - 2 * d.L_hs_frac
wl, ws = d.L_e1_px, d.S_e1_px
d['strad_xc_spr'] = (d.L_e1_xc * wl + d.S_e1_xc * ws) / (wl + ws) - 2 * (
    d.L_hs_frac * wl + d.S_hs_frac * ws) / (wl + ws)
bothok = e1ok & (d.S_e1_wait_min <= 5)
print("\n=== recovery: close-confirmed trail + strict entry + spread ===")
print(stats(d.loc[e1ok, 'xc_spr'], d.date[e1ok], 'single XC+E1<=5m+spread'))
print(stats(d.loc[bothok, 'strad_xc_spr'], d.date[bothok], 'straddle XC+E1<=5m+spread'))
liq = (d.L_prints_day >= 100) & (d.S_prints_day >= 100)
print(stats(d.loc[bothok & liq, 'strad_xc_spr'], d.date[bothok & liq],
            'straddle XC realistic + >=100 prints/day'))
for c, g in d[bothok].groupby('cohort'):
    print(stats(g.strad_xc_spr, g.date, f'  straddle XC realistic {c}'))
