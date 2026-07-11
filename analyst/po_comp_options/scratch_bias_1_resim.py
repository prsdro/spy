#!/usr/bin/env python3
"""Bias quantification pass 1: rebuild the arm-then-trail headline population
(2,345 boxes, 20 tickers, W1 ATM immediate intraday) from raw minute prints and
re-simulate under bias-robust fill variants.

Published mechanics (replicated as V0, must match straddle_armtrail.parquet):
  entry  = entry_fill(): last print <= sig_ms within 20min, else first after;
           60-min fallback. Price = stale close / forward open.
  exits  = initial stop -50% until HWM >= 2x, then trail 30% off prior-bar HWM;
           exit price = the LEVEL itself at first bar whose low <= level.
  hold   = settlement mark (from row pnl_hold).

Variants:
  entry E0 = published; E1 = first print STRICTLY after sig_ms (price = bar open),
             dropped if none within N minutes (N=5 default, 15 sensitivity).
  exit  X0 = published (fill at level); X1 = fill at min(level, trigger-bar close)
             ("next actual print"); XL = fill at trigger-bar low (worst bound);
             XC = close-confirmed trail (hwm on closes, trigger + fill on close).
  spread = per-leg effective half-spread estimate from multi-print minute bars
           near entry ((h-l)/2, n>=2, +-45min), fallback Roll estimator,
           fallback dollar floor; round trip = 2x half-spread.
Outputs: scratch_bias_resim_legs.parquet + printed summary tables.
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import entry_fill

STUDY = Path('/root/spy/analyst/po_comp_options')
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
cache = {}


def bars(k):
    if k not in cache:
        cache[k] = np.array(con.execute(
            "SELECT t,o,h,l,c,COALESCE(n,1) FROM bars WHERE ticker=? ORDER BY t",
            (k,)).fetchall(), float)
    return cache[k]


def half_spread_est(arr, fill_ms, entry_px):
    """Effective half-spread as fraction of entry premium."""
    t = arr[:, 0]
    near = arr[(t >= fill_ms - 45 * 60000) & (t <= fill_ms + 45 * 60000)]
    multi = near[near[:, 5] >= 2]
    if len(multi) >= 3:
        hs = np.median((multi[:, 2] - multi[:, 3]) / 2)
    else:
        # Roll estimator on close-to-close diffs same window
        c = near[:, 4]
        if len(c) >= 6:
            d = np.diff(c)
            cov = np.cov(d[1:], d[:-1])[0, 1]
            hs = np.sqrt(-cov) if cov < 0 else np.nan
        else:
            hs = np.nan
    if not np.isfinite(hs):
        hs = 0.03  # $0.03 floor half-spread fallback
    hs = max(hs, 0.01)  # at least a penny
    return hs / entry_px


def trail_paths(hi, lo, cl, hold_pnl, arm=1.0, trail=0.30, init_sl=0.5):
    """Return dict of pnl under X0/X1/XL/XC given normalized path arrays."""
    n = len(hi)
    if n == 0:
        return {'x0': hold_pnl, 'x1': hold_pnl, 'xl': hold_pnl, 'xc': hold_pnl,
                'exit_kind': 'hold'}
    hwm_prev = np.empty(n)
    hwm_prev[0] = 1.0
    if n > 1:
        hwm_prev[1:] = np.maximum.accumulate(hi)[:-1]
    init = 1 - init_sl
    level = np.where(hwm_prev >= 1 + arm, hwm_prev * (1 - trail), init)
    m = lo <= level
    si = int(np.argmax(m)) if m.any() else -1
    out = {}
    if si >= 0:
        out['x0'] = float(level[si]) - 1
        out['x1'] = float(min(level[si], cl[si])) - 1
        out['xl'] = float(lo[si]) - 1
        out['exit_kind'] = 'trail' if hwm_prev[si] >= 1 + arm else 'stop'
    else:
        out['x0'] = out['x1'] = out['xl'] = hold_pnl
        out['exit_kind'] = 'hold'
    # close-confirmed: hwm on prior closes, trigger + fill on close
    hwm_c = np.empty(n)
    hwm_c[0] = 1.0
    if n > 1:
        hwm_c[1:] = np.maximum.accumulate(cl)[:-1]
    lvl_c = np.where(hwm_c >= 1 + arm, hwm_c * (1 - trail), init)
    mc = cl <= lvl_c
    ci = int(np.argmax(mc)) if mc.any() else -1
    out['xc'] = float(cl[ci]) - 1 if ci >= 0 else hold_pnl
    return out


def leg_variants(r, hold_long):
    """All entry x exit variants for one contract leg. hold_long = long-side
    hold pnl of THIS contract (settle mark / published entry px - 1)."""
    arr = bars(r['contract'])
    if not len(arr):
        return None
    t = arr[:, 0]
    sig_ms = int(pd.Timestamp(r['entry_ts']).timestamp() * 1000)
    expiry_ms = int((pd.Timestamp(r['expiry'], tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    e0_px = r['entry_px']
    exit_mark = (hold_long + 1) * e0_px  # settlement/censor mark in $
    # E0: published fill (recover fill_ms; price = published entry_px)
    f = entry_fill(np.c_[t, arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]], sig_ms)
    if f is None:
        return None
    _, e0_ms = f
    # E1: first print strictly after signal
    aft = np.where(t > sig_ms)[0]
    e1_ms = t[aft[0]] if len(aft) else None
    e1_px = arr[aft[0], 1] if len(aft) else None  # bar open
    e1_wait = (e1_ms - sig_ms) / 60000 if e1_ms is not None else np.inf
    out = {'contract': r['contract'], 'e0_px': e0_px,
           'fill_lag_min': (sig_ms - e0_ms) / 60000,
           'e1_px': e1_px, 'e1_wait_min': e1_wait,
           'hs_frac': half_spread_est(arr, e0_ms, e0_px)}
    # entry-day print count (liquidity)
    day0 = pd.Timestamp(sig_ms, unit='ms', tz='America/New_York').date()
    dsel = pd.to_datetime(t, unit='ms', utc=True).tz_convert(
        'America/New_York').date == day0
    out['prints_day'] = int(dsel.sum())
    for tag, ems, epx in [('e0', e0_ms, e0_px), ('e1', e1_ms, e1_px)]:
        if ems is None or epx is None or epx <= 0.01:
            for k in ('x0', 'x1', 'xl', 'xc'):
                out[f'{tag}_{k}'] = np.nan
            out[f'{tag}_kind'] = 'nofill'
            continue
        p = arr[(t > ems) & (t <= expiry_ms)]
        hi, lo, cl = (p[:, 2] / epx, p[:, 3] / epx, p[:, 4] / epx) if len(p) \
            else (np.array([]), np.array([]), np.array([]))
        hold = exit_mark / epx - 1
        v = trail_paths(hi, lo, cl, hold)
        for k in ('x0', 'x1', 'xl', 'xc'):
            out[f'{tag}_{k}'] = v[k]
        out[f'{tag}_kind'] = v['exit_kind']
    return out


def population():
    frames = []
    for cohort, path in [('orig8', 'v3_eth_trades.parquet'),
                         ('new12', 'v3_new12_trades.parquet')]:
        df = pd.read_parquet(STUDY / path)
        df = df[(df.variant == 'immediate') & (df.bucket == 'W1') &
                (df.offset == 0.0) & (~df.censored) & (~df.rolled_to_open)]
        df = df.drop_duplicates(subset=['ep_id', 'vehicle', 'contract'])
        df['cohort'] = cohort
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main():
    pop = population()
    recs = []
    for (cohort, ep), g in pop.groupby(['cohort', 'ep_id']):
        gl = g[g.vehicle == 'long']
        gs = g[g.vehicle == 'short']
        if not len(gl):
            continue
        rl = gl.iloc[0]
        vl = leg_variants(rl, rl.pnl_hold)
        if vl is None:
            continue
        rec = {'cohort': cohort, 'ep_id': ep, 'ticker': rl.ticker,
               'entry_ts': rl.entry_ts, 'direction': rl.direction,
               'expiry': rl.expiry}
        for k, v in vl.items():
            rec[f'L_{k}'] = v
        if len(gs):
            rs = gs.iloc[0]
            vs = leg_variants(rs, -rs.pnl_hold)  # short rows store short-side hold
            if vs is not None:
                for k, v in vs.items():
                    rec[f'S_{k}'] = v
        recs.append(rec)
        if len(recs) % 300 == 0:
            print(f"...{len(recs)} boxes", flush=True)
    df = pd.DataFrame(recs)
    df.to_parquet(STUDY / 'scratch_bias_resim_legs.parquet')
    print(f"boxes: {len(df)} -> scratch_bias_resim_legs.parquet")


if __name__ == '__main__':
    main()
