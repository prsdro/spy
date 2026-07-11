#!/usr/bin/env python3
"""Entry-search analysis harness: per-episode straddle P&L with the
underlying-keyed exit, generalized from analyst/po_comp_options/scratch_bias_6_undexit.py.

Differences vs the bias_6 original:
  - central case = NO spread haircut (Pedro's cost stance); the measured
    effective-spread version is computed alongside as `strad_sp` (sensitivity).
  - arm multiple / retrace fraction parameterized (default 0.75 / 0.50).
  - per-episode feature columns for gates: box_h_atr, grey_bars_at_entry,
    VIX at entry (vix_1h.parquet, merge_asof backward), box RTH fraction,
    signal hour (ET), direction.
  - importable: run_cells.py-style drivers call run(...) with caching.

Fill mechanics are IDENTICAL to bias_6 (strict-after entry print <=5min or
skip; per leg on underlying 5m closes: arm at ARM*box_h favorable excursion,
exit at RETR retrace of best, pre-arm invalidation at opposite box edge,
expiry fallback; option exit at first print within 15min after trigger bar
close, else last prior print).
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F

STUDY = Path('/root/spy/analyst/po_comp_options')
_con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
_ocache = {}
_m5cache = {}   # (topup, ticker) -> {'t','cl'}
_vix = None


def bars(k):
    if k not in _ocache:
        _ocache[k] = np.array(_con.execute(
            "SELECT t,o,h,l,c,COALESCE(n,1) FROM bars WHERE ticker=? ORDER BY t",
            (k,)).fetchall(), float)
    return _ocache[k]


def m5(topup, tkr):
    key = (str(topup), tkr)
    if key not in _m5cache:
        F.TOPUP = Path(topup)
        df5 = F.load_5m(tkr).between_time('04:00', '19:55')
        _m5cache[key] = {'t': df5.index.as_unit('ns').asi8 // 10**6,
                         'cl': df5['close'].to_numpy(float)}
    return _m5cache[key]


def vix_at(ts_utc_ms):
    global _vix
    if _vix is None:
        v = pd.read_parquet(STUDY / 'vix_1h.parquet').sort_values('ts')
        _vix = {'t': v['ts'].dt.as_unit('ns').astype('int64').to_numpy() // 10**6,
                'v': v['vix'].to_numpy(float)}
    i = np.searchsorted(_vix['t'], ts_utc_ms, side='right') - 1
    return _vix['v'][i] if i >= 0 else np.nan


def half_spread_est(arr, fill_ms, entry_px):
    t = arr[:, 0]
    near = arr[(t >= fill_ms - 45 * 60000) & (t <= fill_ms + 45 * 60000)]
    multi = near[near[:, 5] >= 2]
    if len(multi) >= 3:
        hs = np.median((multi[:, 2] - multi[:, 3]) / 2)
    else:
        c = near[:, 4]
        hs = np.nan
        if len(c) >= 6:
            d = np.diff(c)
            cov = np.cov(d[1:], d[:-1])[0, 1]
            hs = np.sqrt(-cov) if cov < 0 else np.nan
    if not np.isfinite(hs):
        hs = 0.03
    return max(hs, 0.01) / entry_px


def opt_exit_px(arr, ms):
    t = arr[:, 0]
    idx = np.where((t >= ms) & (t <= ms + 15 * 60000))[0]
    if len(idx):
        return arr[idx[0], 4]
    idx = np.where(t <= ms)[0]
    return arr[idx[-1], 4] if len(idx) else None


def leg(r, sign, M, arm, retr):
    """sign=+1 favorable-up (call leg), -1 favorable-down (put leg).
    Returns (ret_no_spread, ret_spread, entry_px) or None."""
    arr = bars(r['contract'])
    if not len(arr):
        return None
    t = arr[:, 0]
    sig_ms = int(pd.Timestamp(r['entry_ts']).timestamp() * 1000)
    aft = np.where(t > sig_ms)[0]
    if not len(aft) or (t[aft[0]] - sig_ms) > 5 * 60000:
        return None
    e_ms, epx = t[aft[0]], arr[aft[0], 1]
    if epx <= 0.01:
        return None
    expiry_ms = int((pd.Timestamp(r['expiry'], tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    sel = (M['t'] > e_ms) & (M['t'] <= expiry_ms)
    uc = M['cl'][sel]
    ut = M['t'][sel] + 300_000
    spot0, bh = r['spot'], r['box_hi'] - r['box_lo']
    exc = sign * (uc - spot0)
    inval_lvl = r['box_lo'] if sign == 1 else r['box_hi']
    exit_ms = None
    armed, best = False, 0.0
    for i in range(len(uc)):
        if not armed:
            if exc[i] >= arm * bh:
                armed, best = True, exc[i]
            elif (sign == 1 and uc[i] < inval_lvl) or (sign == -1 and uc[i] > inval_lvl):
                exit_ms = ut[i]
                break
        else:
            best = max(best, exc[i])
            if exc[i] <= retr * best:
                exit_ms = ut[i]
                break
    if exit_ms is None:
        exit_ms = expiry_ms
    xpx = opt_exit_px(arr, exit_ms)
    if xpx is None:
        return None
    ret = xpx / epx - 1
    return ret, ret - 2 * half_spread_est(arr, e_ms, epx), epx


def rth_frac(start_ts, nb):
    """Fraction of the box's nb hourly ETH bars whose bar-start hour is
    9..15 ET (RTH-ish), stepping the 4:00-19:00 grid."""
    h = pd.Timestamp(start_ts).hour
    tot = 0
    for _ in range(max(1, int(nb))):
        tot += 1 if 9 <= h <= 15 else 0
        h = 4 if h >= 19 else h + 1
    return tot / max(1, int(nb))


def run(trades_file, topup, events_csv=None, arm=0.75, retr=0.5, verbose=False):
    """Returns per-episode DataFrame: strad (no spread), strad_sp, single,
    plus feature columns."""
    tr = pd.read_parquet(STUDY / trades_file if not str(trades_file).startswith('/')
                         else trades_file)
    tr = tr[(tr.bucket == 'W1') & (tr.offset == 0.0) & (~tr.censored)
            & (~tr.rolled_to_open)]
    if 'attempt_seq' in tr.columns:
        tr = tr[tr.attempt_seq.fillna(0) == 0]
    tr = tr.drop_duplicates(subset=['ep_id', 'vehicle', 'contract'])
    evmap = {}
    if events_csv is not None:
        ev = pd.read_csv(STUDY / events_csv if not str(events_csv).startswith('/')
                         else events_csv)
        evmap = ev.set_index('ep_id')[['start_ts_et', 'datr14_prior']].to_dict('index')
    recs = []
    for ep, g in tr.groupby('ep_id'):
        gl, gs = g[g.vehicle == 'long'], g[g.vehicle == 'short']
        if not (len(gl) and len(gs)):
            continue
        rl, rs = gl.iloc[0], gs.iloc[0]
        M = m5(topup, rl.ticker)
        csign = 1 if rl.direction == 1 else -1
        a = leg(rl, csign, M, arm, retr)
        b = leg(rs, -csign, M, arm, retr)
        if a is None or b is None:
            continue
        ets = pd.Timestamp(rl['entry_ts'])
        grey = rl['grey_bars_at_entry'] if 'grey_bars_at_entry' in rl.index else np.nan
        e0 = evmap.get(ep)
        recs.append({
            'ep_id': ep, 'ticker': rl.ticker, 'date': rl.entry_ts[:10],
            'entry_ts': rl.entry_ts, 'sig_hour': ets.hour,
            'direction': int(rl.direction),
            'box_h_atr': float(rl.box_h_atr), 'grey_bars': grey,
            'vix': vix_at(int(ets.timestamp() * 1000)),
            'box_rth_frac': rth_frac(e0['start_ts_et'],
                                     min(grey, 5) if np.isfinite(grey) else 5)
                            if e0 else np.nan,
            'strad': (a[0] * a[2] + b[0] * b[2]) / (a[2] + b[2]),
            'strad_sp': (a[1] * a[2] + b[1] * b[2]) / (a[2] + b[2]),
            'single': a[0], 'prem': a[2] + b[2]})
        if verbose and len(recs) % 200 == 0:
            print(f"  ...{len(recs)} eps", flush=True)
    return pd.DataFrame(recs)


def stats(d, col='strad'):
    v = d[col].dropna()
    n = len(v)
    if n < 3:
        return dict(n=n, mean=np.nan, t=np.nan, tc=np.nan, win=np.nan, nd=0)
    tt = v.mean() / (v.std(ddof=1) / np.sqrt(n))
    gdt = v.groupby(d['date'][v.index]).mean()
    tc = gdt.mean() / (gdt.std(ddof=1) / np.sqrt(len(gdt))) if len(gdt) > 2 else np.nan
    return dict(n=n, mean=100 * v.mean(), t=tt, tc=tc,
                win=100 * (v > 0).mean(), nd=len(gdt))


def fmt(s):
    return (f"{s['mean']:+.1f}% (n={s['n']}, t {s['t']:+.2f}, tc {s['tc']:+.2f}, "
            f"win {s['win']:.0f}%, d={s['nd']})")


if __name__ == '__main__':
    trades, topup = sys.argv[1], sys.argv[2]
    events = sys.argv[3] if len(sys.argv) > 3 else None
    arm = float(sys.argv[4]) if len(sys.argv) > 4 else 0.75
    retr = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
    d = run(trades, topup, events, arm, retr, verbose=True)
    print(trades, f"arm={arm} retr={retr}")
    for c in ('strad', 'strad_sp', 'single'):
        print(f"  {c:9s}", fmt(stats(d, c)))
