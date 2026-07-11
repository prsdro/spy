#!/usr/bin/env python3
"""Analysis: LTF-confirmation entries vs D (hourly close-confirmed), plus
OOS of the flag-gated bail+re-arm chain. Level-fill convention (same as page;
bias-audit haircut applies to levels, not rankings)."""
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
    return (p[:, 0], p[:, 1] / r.entry_px, p[:, 2] / r.entry_px, p[:, 3] / r.entry_px)


def sim(path, hold, init_pre=0.5, bail_ms=None, arm=1.0, trail=0.30):
    if path is None:
        return hold, 'hold'
    t, hi, lo, cl = path
    n = len(t)
    if n == 0:
        return hold, 'hold'
    hp = np.empty(n)
    hp[0] = 1.0
    if n > 1:
        hp[1:] = np.maximum.accumulate(hi)[:-1]
    level = np.where(hp >= 1 + arm, hp * (1 - trail), 1 - init_pre)
    m = lo <= level
    si = int(np.argmax(m)) if m.any() else -1
    if bail_ms is not None:
        ib = np.searchsorted(t, bail_ms, side='right') - 1
        if ib >= 0 and (si < 0 or t[si] > bail_ms) and cl[ib] < 1.0:
            return float(cl[ib]) - 1, 'bail'
    if si >= 0:
        return float(level[si]) - 1, 'stop'
    return hold, 'hold'


def cstat(v):
    v = pd.Series(v).dropna()
    if len(v) < 3:
        return None
    tt = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    pf = v[v > 0].sum() / max(1e-9, -v[v < 0].sum())
    return {'n': int(len(v)), 'mean': round(float(v.mean()), 4),
            't': round(float(tt), 2), 'win': round(float((v > 0).mean()), 3),
            'pf': round(float(pf), 2)}


def load(files, chains=False):
    dfs = [pd.read_parquet(STUDY / f) for f in files if (STUDY / f).exists()]
    missing = [f for f in files if not (STUDY / f).exists()]
    if missing:
        print(f"  !! missing: {missing}")
    if not dfs:
        return None
    t = pd.concat(dfs, ignore_index=True)
    t = t[(t.bucket == 'W1') & (t.offset == 0.0) & (~t.censored) & (~t.rolled_to_open)]
    keys = ['ep_id', 'vehicle'] + (['attempt_seq'] if chains else [])
    return t.drop_duplicates(subset=keys)


def grid(t):
    res = {}
    gl = t[t.vehicle == 'long']
    for lbl, init in [('trail_sl50', 0.5), ('trail_sl35', 0.35)]:
        vals, split = [], {}
        for _, r in gl.iterrows():
            p = path_for(r)
            if p is None:
                continue
            v = sim(p, r.pnl_hold, init)[0]
            vals.append(v)
            split.setdefault(r.ticker in ORIG8, []).append(v)
        res[f'single_{lbl}'] = cstat(vals)
        if lbl == 'trail_sl50':
            res['single_sl50_orig8'] = cstat(split.get(True, []))
            res['single_sl50_new12'] = cstat(split.get(False, []))
    vals, split = [], {}
    for ep, g in t.groupby('ep_id'):
        a, b = g[g.vehicle == 'long'], g[g.vehicle == 'short']
        if not (len(a) and len(b)):
            continue
        ra, rb = a.iloc[0], b.iloc[0]
        pa, pb = path_for(ra), path_for(rb)
        if pa is None or pb is None:
            continue
        va = sim(pa, ra.pnl_hold, 0.5)[0]
        vb = sim(pb, -rb.pnl_hold, 0.5)[0]
        v = (va * ra.entry_px + vb * rb.entry_px) / (ra.entry_px + rb.entry_px)
        vals.append(v)
        split.setdefault(ra.ticker in ORIG8, []).append(v)
    res['straddle_sl50'] = cstat(vals)
    res['straddle_sl50_orig8'] = cstat(split.get(True, []))
    res['straddle_sl50_new12'] = cstat(split.get(False, []))
    return res


def vs_d(lt, dt):
    """Timing/fill edge vs D for shared episodes (long leg)."""
    a = lt[lt.vehicle == 'long'].set_index('ep_id')
    b = dt[dt.vehicle == 'long'].set_index('ep_id')
    common = a.index.intersection(b.index)
    if not len(common):
        return {}
    mins, fill = [], []
    for ep in common:
        ra, rb = a.loc[ep], b.loc[ep]
        if isinstance(ra, pd.DataFrame):
            ra = ra.iloc[0]
        if isinstance(rb, pd.DataFrame):
            rb = rb.iloc[0]
        dm = (pd.Timestamp(rb.entry_ts) - pd.Timestamp(ra.entry_ts)).total_seconds() / 60
        bh = ra.box_hi - ra.box_lo
        f = ra.direction * (rb.spot - ra.spot) / bh if bh > 0 else np.nan
        mins.append(dm)
        fill.append(f)
    mins, fill = pd.Series(mins), pd.Series(fill).dropna()
    return {'shared_eps': int(len(common)),
            'ltf_only_eps': int(len(a.index.difference(b.index))),
            'd_only_eps': int(len(b.index.difference(a.index))),
            'median_min_earlier': round(float(mins.median()), 1),
            'median_fill_edge_boxh': round(float(fill.median()), 3),
            'fill_better_pct': round(float((fill > 0).mean()), 3)}


def chain_rearm(t):
    t = t[t.vehicle == 'long']
    vals, split = [], {}
    for ep, g in t.groupby('ep_id'):
        g = g.sort_values('attempt_seq')
        total, resolved = 0.0, False
        for _, r in g.iterrows():
            p = path_for(r)
            if p is None:
                continue
            if not r.flip_bar_closed_grey:
                total += sim(p, r.pnl_hold, 0.5)[0]
                resolved = True
                break
            bc = pd.Timestamp(r.entry_bar_close_ts).value // 10**6
            pnl, kind = sim(p, r.pnl_hold, 0.5, bail_ms=bc)
            total += pnl
            if kind in ('bail',) or (kind == 'stop' and pnl <= -0.49):
                continue
            resolved = True
            break
        if resolved or total != 0.0:
            vals.append(total)
            split.setdefault(g.iloc[0].ticker in ORIG8, []).append(total)
    return {'chain': cstat(vals), 'chain_orig8': cstat(split.get(True, [])),
            'chain_new12': cstat(split.get(False, []))}


def show(title, res):
    print(f"\n== {title} ==")
    for k, v in res.items():
        if isinstance(v, dict) and 'mean' in v:
            print(f"  {k:22s} n={v['n']:4d} mean={100*v['mean']:+7.2f}% "
                  f"t={v['t']:+.2f} win={100*v['win']:.0f}% PF={v['pf']:.2f}")
        elif isinstance(v, dict):
            print(f"  {k:22s} {v}")
        else:
            print(f"  {k:22s} {v}")


results = {}
dpool = load(['flip8_confirm_trades.parquet', 'flip12_confirm_trades.parquet'])
for name in ['ltf10', 'ltf10po', 'ltf30', 'ltf30po']:
    t = load([f'{name}_o8_trades.parquet', f'{name}_n12_trades.parquet'])
    if t is None or not len(t):
        print(f"\n== {name}: no data ==")
        continue
    results[name] = grid(t)
    results[name]['vs_D'] = vs_d(t, dpool)
    show(name, results[name])

results['rearm_gated'] = chain_rearm(
    load(['flip8_multi_trades.parquet', 'flip12_multi_trades.parquet'], chains=True))
show('flag-gated bail+re-arm chain (OOS check)', results['rearm_gated'])

out = STUDY / 'flip_ltf_results.json'
out.write_text(json.dumps(results, indent=1))
print(f"\nsaved -> {out}")
con.close()
