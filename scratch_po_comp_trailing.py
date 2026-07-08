#!/usr/bin/env python3
"""Trailing-stop and scale-out+runner variants on the headline cell
(ETH intraday immediate longs). Same legs/fills as the TP/SL grid.
Trail levels use the PRIOR bar's high-water mark (no same-bar lookahead);
stop fills at the level, TP fills at the target, expiry -> hold mark."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import entry_fill

STUDY = Path('/root/spy/analyst/po_comp_options')

tr = pd.read_parquet(STUDY / 'v3_eth_trades.parquet')
tr = tr.drop_duplicates(subset=['ep_id', 'variant', 'direction', 'bucket',
                                'vehicle', 'contract'])
c = tr[(tr.variant == 'immediate') & (tr.vehicle == 'long') &
       (~tr.rolled_to_open) & (~tr.censored)].copy()

con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
cache = {}
def bars(k):
    if k not in cache:
        cache[k] = np.array(con.execute(
            "SELECT t,h,l FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return cache[k]


def first_le(lo, level):
    """First index where lo_i <= level_i (level may be array)."""
    m = lo <= level
    return int(np.argmax(m)) if m.any() else -1


def sim(hi, lo, hold_pnl, kind, **kw):
    """Return pnl fraction for one leg under a variant. hi/lo normalized to entry=1."""
    n = len(hi)
    if n == 0:
        return hold_pnl
    hwm_prev = np.empty(n)
    hwm_prev[0] = 1.0
    if n > 1:
        hwm_prev[1:] = np.maximum.accumulate(hi)[:-1]
    init = 1 - kw.get('init_sl', 0.5)

    if kind == 'trail':
        level = np.maximum(init, hwm_prev * (1 - kw['trail']))
    elif kind == 'ladder':
        level = np.select([hwm_prev >= 3.0, hwm_prev >= 2.0, hwm_prev >= 1.5],
                          [2.0, 1.25, 1.0], init)
    elif kind == 'trail_after':
        act = hwm_prev >= (1 + kw['arm'])
        level = np.where(act, hwm_prev * (1 - kw['trail']), init)
    else:
        raise ValueError(kind)

    si = first_le(lo, level)
    cap = kw.get('cap')
    ti = -1
    if cap:
        m = hi >= (1 + cap)
        ti = int(np.argmax(m)) if m.any() else -1
    if ti >= 0 and (si < 0 or ti < si):
        return cap
    if si >= 0:
        return float(level[si]) - 1
    return hold_pnl


VARIANTS = {
    'ref TP100|SL50':      lambda h, l, hp: sim(h, l, hp, 'trail', trail=9.9, cap=1.0),
    'ref TP150|SL40':      lambda h, l, hp: sim(h, l, hp, 'trail', trail=9.9, cap=1.5, init_sl=0.4),
    'trail30':             lambda h, l, hp: sim(h, l, hp, 'trail', trail=0.30),
    'trail40':             lambda h, l, hp: sim(h, l, hp, 'trail', trail=0.40),
    'trail50':             lambda h, l, hp: sim(h, l, hp, 'trail', trail=0.50),
    'ladder(BE@50,+25@100,+100@200)': lambda h, l, hp: sim(h, l, hp, 'ladder'),
    'trail40 after +100%': lambda h, l, hp: sim(h, l, hp, 'trail_after', arm=1.0, trail=0.40),
    'trail30 after +100%': lambda h, l, hp: sim(h, l, hp, 'trail_after', arm=1.0, trail=0.30),
    'runner(TP200,trail40)': lambda h, l, hp: sim(h, l, hp, 'trail', trail=0.40, cap=2.0),
}
# scale-out combos: 2/3 base TP + 1/3 runner
COMBOS = {
    '2/3@TP50 + 1/3 runner':  ('ref50', 'runner(TP200,trail40)'),
    '2/3@TP75 + 1/3 runner':  ('ref75', 'runner(TP200,trail40)'),
}

recs = []
for _, r in c.iterrows():
    arr = bars(r.contract)
    if not len(arr):
        continue
    sig_ms = int(pd.Timestamp(r.entry_ts).timestamp() * 1000)
    f = entry_fill(np.c_[arr[:, 0], arr[:, 1], arr[:, 1], arr[:, 2], arr[:, 2]], sig_ms)
    if f is None:
        continue
    _, fill_ms = f
    entry_px = r.entry_px
    expiry_ms = int((pd.Timestamp(r.expiry, tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > fill_ms) & (arr[:, 0] <= expiry_ms)]
    hi, lo = (p[:, 1] / entry_px, p[:, 2] / entry_px) if len(p) else \
             (np.array([]), np.array([]))
    out = {'ep_id': r.ep_id, 'ticker': r.ticker}
    for name, fn in VARIANTS.items():
        out[name] = fn(hi, lo, r.pnl_hold)
    out['ref50'] = sim(hi, lo, r.pnl_hold, 'trail', trail=9.9, cap=0.5)
    out['ref75'] = sim(hi, lo, r.pnl_hold, 'trail', trail=9.9, cap=0.75)
    for name, (base, run) in COMBOS.items():
        out[name] = (2 / 3) * out[base] + (1 / 3) * out[run]
    recs.append(out)
con.close()

g = pd.DataFrame(recs)
g.to_parquet(STUDY / 'trailing_variants_legs.parquet')
cols = list(VARIANTS) + list(COMBOS)
ep = g.groupby('ep_id')[cols].mean()
n = len(ep)
print(f"boxes: {n}, legs: {len(g)}\n")
print(f"{'variant':34s} {'avg%':>7s} {'t':>6s} {'win%':>5s}")
for k in sorted(cols, key=lambda k: -ep[k].mean()):
    t = ep[k].mean() / (ep[k].std(ddof=1) / np.sqrt(n))
    print(f"{k:34s} {ep[k].mean()*100:+7.1f} {t:6.2f} {(g[k]>0).mean()*100:5.0f}")
