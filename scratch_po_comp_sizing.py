#!/usr/bin/env python3
"""(1) 30m-box results (arm-trail single + straddle, orig8/new12 split).
(2) Position-sizing scores on the validated hourly close-confirmed entry:
    entry-time features -> tercile buckets (cut points from orig8, applied to
    new12 as validation) -> sized-vs-flat comparison on new12.
Level-fill convention throughout."""
import json
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import entry_fill

STUDY = Path('/root/spy/analyst/po_comp_options')
ORIG8 = {'AMZN', 'NVDA', 'MSFT', 'AAPL', 'META', 'GOOGL', 'TSLA', 'AMD'}
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
bcache = {}


def bars(k):
    if k not in bcache:
        bcache[k] = np.array(con.execute(
            "SELECT t,h,l,c FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return bcache[k]


def path_for(r):
    arr = bars(r.contract)
    if not len(arr):
        return None
    sig = int(pd.Timestamp(r.entry_ts).timestamp() * 1000)
    f = entry_fill(np.c_[arr[:, 0], arr[:, 1], arr[:, 1], arr[:, 2], arr[:, 2]], sig)
    if f is None:
        return None
    _, fm = f
    em = int((pd.Timestamp(r.expiry, tz='America/New_York')
              + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > fm) & (arr[:, 0] <= em)]
    return (p[:, 1] / r.entry_px, p[:, 2] / r.entry_px)


def armtrail(path, hold, init=0.5, arm=1.0, trail=0.30):
    if path is None:
        return hold
    hi, lo = path
    n = len(hi)
    if n == 0:
        return hold
    hp = np.empty(n)
    hp[0] = 1.0
    if n > 1:
        hp[1:] = np.maximum.accumulate(hi)[:-1]
    level = np.where(hp >= 1 + arm, hp * (1 - trail), 1 - init)
    m = lo <= level
    si = int(np.argmax(m)) if m.any() else -1
    return float(level[si]) - 1 if si >= 0 else hold


def cstat(v):
    v = pd.Series(v).dropna()
    if len(v) < 3:
        return None
    tt = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    pf = v[v > 0].sum() / max(1e-9, -v[v < 0].sum())
    return {'n': int(len(v)), 'mean': round(float(v.mean()), 4),
            't': round(float(tt), 2), 'win': round(float((v > 0).mean()), 3),
            'pf': round(float(pf), 2)}


def load(files):
    dfs = [pd.read_parquet(STUDY / f) for f in files if (STUDY / f).exists()]
    miss = [f for f in files if not (STUDY / f).exists()]
    if miss:
        print(f"  !! missing {miss}")
    t = pd.concat(dfs, ignore_index=True)
    return t[(t.bucket == 'W1') & (t.offset == 0.0) & (~t.censored)
             & (~t.rolled_to_open)].drop_duplicates(subset=['ep_id', 'vehicle'])


def score_trades(t):
    """Per-episode single-leg + straddle arm-trail P&L with metadata."""
    recs = []
    for ep, g in t.groupby('ep_id'):
        gl, gs = g[g.vehicle == 'long'], g[g.vehicle == 'short']
        if not len(gl):
            continue
        rl = gl.iloc[0]
        pl = path_for(rl)
        if pl is None:
            continue
        single = armtrail(pl, rl.pnl_hold)
        strad = None
        if len(gs):
            rs = gs.iloc[0]
            ps = path_for(rs)
            if ps is not None:
                a, b = armtrail(pl, rl.pnl_hold), armtrail(ps, -rs.pnl_hold)
                strad = (a * rl.entry_px + b * rs.entry_px) / (rl.entry_px + rs.entry_px)
        recs.append({'ep_id': ep, 'ticker': rl.ticker, 'direction': rl.direction,
                     'orig8': rl.ticker in ORIG8, 'box_h_atr': rl.box_h_atr,
                     'ema21_d_slope3': rl.ema21_d_slope3,
                     'single': single, 'straddle': strad})
    return pd.DataFrame(recs)


def show(title, res):
    print(f"\n== {title} ==")
    for k, v in res.items():
        if isinstance(v, dict) and 'mean' in v:
            print(f"  {k:26s} n={v['n']:4d} mean={100*v['mean']:+7.2f}% "
                  f"t={v['t']:+.2f} win={100*v['win']:.0f}% PF={v['pf']:.2f}")
        else:
            print(f"  {k:26s} {v}")


results = {}

# ---------- part 1: 30m box ----------
for name, files in [
        ('box30_confirm', ['box30_confirm_o8_trades.parquet',
                           'box30_confirm_n12_trades.parquet']),
        ('box30_ltf10po', ['box30_ltf10po_o8_trades.parquet',
                           'box30_ltf10po_n12_trades.parquet'])]:
    t = load(files)
    if not len(t):
        continue
    d = score_trades(t)
    res = {'single': cstat(d.single), 'straddle': cstat(d.straddle),
           'single_orig8': cstat(d[d.orig8].single),
           'single_new12': cstat(d[~d.orig8].single),
           'straddle_orig8': cstat(d[d.orig8].straddle),
           'straddle_new12': cstat(d[~d.orig8].straddle)}
    results[name] = res
    show(name, res)

# ---------- part 2: sizing scores on hourly D ----------
t = load(['flip8_confirm_trades.parquet', 'flip12_confirm_trades.parquet'])
d = score_trades(t)
ev = pd.concat([pd.read_csv(STUDY / 'events_v2_eth.csv'),
                pd.read_csv(STUDY / 'events_new12.csv')], ignore_index=True)
d = d.merge(ev[['ep_id', 'po', 'po_slope3', 'ema9_h', 'ema21_h', 'spot_start',
                'datr14_prior']], on='ep_id', how='left')
d['f_trend'] = d.ema21_d_slope3 / d.datr14_prior * d.direction
d['f_prox'] = (d.spot_start - d.ema21_h).abs() / d.datr14_prior
d['f_poslope'] = d.po_slope3 * d.direction
d['f_po'] = d.po * d.direction
d['f_width'] = d.box_h_atr
FEATS = ['f_trend', 'f_prox', 'f_poslope', 'f_po', 'f_width']
STRAD_FEATS = {'f_prox': d.f_prox, 'f_width': d.f_width,
               'f_po_abs': d.po.abs(), 'f_poslope_abs': d.po_slope3.abs(),
               'f_trend_abs': (d.ema21_d_slope3 / d.datr14_prior).abs()}
for k, v in STRAD_FEATS.items():
    d[k] = v

tr8 = d[d.orig8]
sizing = {}
for outcome, feats in [('single', FEATS), ('straddle', list(STRAD_FEATS))]:
    for f in feats:
        q = tr8[f].quantile([1 / 3, 2 / 3]).values
        lab = np.select([d[f] <= q[0], d[f] <= q[1]], ['lo', 'mid'], 'hi')
        rows = {}
        for split, mask in [('orig8', d.orig8), ('new12', ~d.orig8)]:
            for b in ['lo', 'mid', 'hi']:
                s = cstat(d[mask & (lab == b)][outcome])
                rows[f'{split}_{b}'] = s
        sizing[f'{outcome}|{f}'] = rows
        o8 = [rows[f'orig8_{b}']['mean'] if rows[f'orig8_{b}'] else np.nan
              for b in ['lo', 'mid', 'hi']]
        n12 = [rows[f'new12_{b}']['mean'] if rows[f'new12_{b}'] else np.nan
               for b in ['lo', 'mid', 'hi']]
        print(f"{outcome:9s} {f:14s} orig8 lo/mid/hi: "
              f"{' '.join(f'{100*x:+6.1f}%' for x in o8)}   new12: "
              f"{' '.join(f'{100*x:+6.1f}%' for x in n12)}")

# sized-vs-flat on new12 for features monotone on orig8
print("\n-- sized (0.5/1.0/1.5 by orig8 tercile) vs flat, new12 only --")
for key, rows in sizing.items():
    o8 = [rows[f'orig8_{b}']['mean'] if rows[f'orig8_{b}'] else np.nan
          for b in ['lo', 'mid', 'hi']]
    if any(np.isnan(o8)):
        continue
    up = o8[0] < o8[1] < o8[2]
    dn = o8[0] > o8[1] > o8[2]
    if not (up or dn):
        continue
    outcome, f = key.split('|')
    q = tr8[f].quantile([1 / 3, 2 / 3]).values
    sub = d[~d.orig8].dropna(subset=[f, outcome])
    lab = np.select([sub[f] <= q[0], sub[f] <= q[1]], ['lo', 'mid'], 'hi')
    wmap = {'lo': 0.5, 'mid': 1.0, 'hi': 1.5} if up else \
           {'lo': 1.5, 'mid': 1.0, 'hi': 0.5}
    w = np.array([wmap[x] for x in lab])
    flat = cstat(sub[outcome])
    swt = float((sub[outcome] * w).sum() / w.sum())
    sized_series = sub[outcome] * w / w.mean()      # same avg capital as flat
    sized = cstat(sized_series)
    sizing[key]['sized_new12'] = {'flat_mean': flat['mean'], 'flat_t': flat['t'],
                                  'sized_capwt_mean': round(swt, 4),
                                  'sized_t': sized['t'] if sized else None,
                                  'monotone': 'up' if up else 'down'}
    print(f"  {key:26s} monotone={'up' if up else 'down'} flat={100*flat['mean']:+.2f}% "
          f"(t={flat['t']}) sized={100*swt:+.2f}% (t={sized['t'] if sized else '?'})")

results['sizing'] = sizing
out = STUDY / 'flip_box30_sizing_results.json'
out.write_text(json.dumps(results, indent=1, default=str))
print(f"\nsaved -> {out}")
con.close()
