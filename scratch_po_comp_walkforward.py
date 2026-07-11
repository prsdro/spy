#!/usr/bin/env python3
"""Walk-forward name selection: does a trailing screen (refreshed monthly)
identify which names to trade next month? Tests Pedro's regime hypothesis —
edge cycles per name; we need an adaptive size-up/skip rule, not a fixed list.

Populations: hourly D (close-confirmed) and 30m confirm boxes, straddle +
arm-then-trail per episode (level-fill convention).
Screens, computed on a trailing 6-month window, applied to the next month:
  pnl6     trailing mean strategy P&L per ticker (min 5 trades)
  vol6     trailing median daily ATR%% (from events)
  combo    average of the two ranks
Portfolios: top-8 and top-5 names per screen, vs the full basket.
Also reports monthly membership turnover (regime-cycling evidence).
Caches per-episode P&L to flip_episode_pnl.parquet for reuse.
"""
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
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
bc = {}


def bars(k):
    if k not in bc:
        bc[k] = np.array(con.execute(
            "SELECT t,h,l FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return bc[k]


def path(r):
    arr = bars(r.contract)
    if not len(arr):
        return None
    f = entry_fill(np.c_[arr[:, 0], arr[:, 1], arr[:, 1], arr[:, 2], arr[:, 2]],
                   int(pd.Timestamp(r.entry_ts).timestamp() * 1000))
    if f is None:
        return None
    em = int((pd.Timestamp(r.expiry, tz='America/New_York')
              + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > f[1]) & (arr[:, 0] <= em)]
    return p[:, 1] / r.entry_px, p[:, 2] / r.entry_px


def trail(p, hold):
    if p is None:
        return hold
    hi, lo = p
    n = len(hi)
    if n == 0:
        return hold
    hp = np.empty(n)
    hp[0] = 1.0
    if n > 1:
        hp[1:] = np.maximum.accumulate(hi)[:-1]
    lvl = np.where(hp >= 2.0, hp * 0.7, 0.5)
    m = lo <= lvl
    si = int(np.argmax(m)) if m.any() else -1
    return float(lvl[si]) - 1 if si >= 0 else hold


def episode_pnl(files, tag):
    t = pd.concat([pd.read_parquet(STUDY / f) for f in files], ignore_index=True)
    t = t[(t.bucket == 'W1') & (t.offset == 0.0) & (~t.censored)
          & (~t.rolled_to_open)].drop_duplicates(subset=['ep_id', 'vehicle'])
    recs = []
    for ep, g in t.groupby('ep_id'):
        gl, gs = g[g.vehicle == 'long'], g[g.vehicle == 'short']
        if not (len(gl) and len(gs)):
            continue
        rl, rs = gl.iloc[0], gs.iloc[0]
        pl, ps = path(rl), path(rs)
        if pl is None or ps is None:
            continue
        a, b = trail(pl, rl.pnl_hold), trail(ps, -rs.pnl_hold)
        v = (a * rl.entry_px + b * rs.entry_px) / (rl.entry_px + rs.entry_px)
        recs.append({'pop': tag, 'ep_id': ep, 'ticker': rl.ticker,
                     'entry_ts': str(rl.entry_ts), 'pnl': v})
    print(f"{tag}: {len(recs)} episodes", flush=True)
    return pd.DataFrame(recs)


cache = STUDY / 'flip_episode_pnl.parquet'
if cache.exists():
    d = pd.read_parquet(cache)
    print(f"loaded cache: {len(d)} rows")
else:
    d = pd.concat([
        episode_pnl(['flip8_confirm_trades.parquet',
                     'flip12_confirm_trades.parquet'], 'hourlyD'),
        episode_pnl(['box30_confirm_o8_trades.parquet',
                     'box30_confirm_n12_trades.parquet'], 'box30'),
    ], ignore_index=True)
    d.to_parquet(cache)
    print(f"cached -> {cache}")

d['ts'] = pd.to_datetime(d.entry_ts.map(lambda s: pd.Timestamp(s)), utc=True)
d['month'] = d.ts.dt.tz_convert('America/New_York').dt.to_period('M')

ev = pd.concat([pd.read_csv(STUDY / 'events_v2_eth.csv'),
                pd.read_csv(STUDY / 'events_new12.csv')], ignore_index=True)
ev['ts'] = pd.to_datetime(ev.start_ts_et, utc=True)
ev['month'] = ev.ts.dt.tz_convert('America/New_York').dt.to_period('M')
ev['atr_pct'] = ev.datr14_prior / ev.spot_start * 100


def tstat(v):
    v = pd.Series(v).dropna()
    if len(v) < 3:
        return np.nan
    return v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))


for pop, g in d.groupby('pop'):
    months = sorted(g.month.unique())
    test_months = [m for m in months if m >= months[0] + 6]
    port = {('pnl6', 8): [], ('pnl6', 5): [], ('vol6', 8): [], ('vol6', 5): [],
            ('combo', 8): [], ('combo', 5): []}
    turnover = {k: [] for k in ['pnl6', 'vol6', 'combo']}
    prev_sets = {}
    for m in test_months:
        w = g[(g.month >= m - 6) & (g.month < m)]
        pnl_rank = w.groupby('ticker').agg(mu=('pnl', 'mean'), n=('pnl', 'size'))
        pnl_rank = pnl_rank[pnl_rank.n >= 5]['mu'].rank(ascending=False)
        we = ev[(ev.month >= m - 6) & (ev.month < m)]
        vol_rank = we.groupby('ticker').atr_pct.median().rank(ascending=False)
        combo = pd.concat([pnl_rank, vol_rank], axis=1).mean(axis=1).dropna()
        ranks = {'pnl6': pnl_rank.sort_values(),
                 'vol6': vol_rank.sort_values(),
                 'combo': combo.rank().sort_values()}
        cur = g[g.month == m]
        for s, rk in ranks.items():
            for K in [8, 5]:
                names = set(rk.index[:K])
                port[(s, K)].extend(cur[cur.ticker.isin(names)].pnl.tolist())
            key = (s, 8)
            names8 = set(ranks[s].index[:8])
            if s in prev_sets:
                turnover[s].append(len(names8 - prev_sets[s]))
            prev_sets[s] = names8
    base = g[g.month.isin(test_months)].pnl
    print(f"\n== {pop}: walk-forward (6mo trailing, monthly refresh, "
          f"{len(test_months)} test months) ==")
    print(f"  {'full basket':16s} n={len(base):4d} mean={100*base.mean():+7.2f}% "
          f"t={tstat(base):+.2f}")
    for (s, K), v in port.items():
        v = pd.Series(v)
        print(f"  {s+f' top-{K}':16s} n={len(v):4d} mean={100*v.mean():+7.2f}% "
              f"t={tstat(v):+.2f}")
    for s, tv in turnover.items():
        print(f"  {s} monthly turnover of top-8: mean {np.mean(tv):.1f} names swapped")
con.close()
