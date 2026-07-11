#!/usr/bin/env python3
"""Trade-management grid on live-executable Bilbo box entries, 20 tickers.

Populations (all W1 ATM, intraday, uncensored):
  F      full 5-bar box, then first 5m poke (pure price)   flip{8,12}_fullbox
  D      close-confirmed break                              flip{8,12}_confirm
  Fchain F with multi-entry re-arm attempts                 flip{8,12}_fbmulti

Management variants (Pedro: "tighter stop until expansion is confirmed"):
  fixed_tp100_sl50   published fixed bracket (stored column, reference)
  trail_sl50         arm-then-trail: SL-50% until +100%, then trail 30% off HWM
  trail_sl35         same, initial stop -35%
  trail_sl25         same, initial stop -25%
  trail_bail         trail_sl50 + exit at entry bar's close if it closed grey
                     AND premium is red there (no re-arm)
  confirm_widen      SL-25% until the first hourly close out of compression
                     at/after the entry bar, then SL-50%; trail as usual
  chain_rearm        (Fchain only) trail_sl50 + bail-if-red-at-grey-close,
                     re-enter on the next valid attempt; per-episode P&L

Straddle (both legs long, per-leg exits, premium-weighted):
  trail_sl50 / trail_sl35 / confirm_widen, and trail_bail with the red check
  on COMBINED premium at the entry bar close (approximation: legs already
  stopped before that close keep their stop exits).
"""
import json
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F
from fetch_po_comp_options import load_5m, hourly_and_daily
from backtest_po_comp_options import entry_fill
from indicators import compute_phase_oscillator

STUDY = Path('/root/spy/analyst/po_comp_options')
ORIG8 = {'AMZN', 'NVDA', 'MSFT', 'AAPL', 'META', 'GOOGL', 'TSLA', 'AMD'}
con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
bcache, hcache = {}, {}


def bars(k):
    if k not in bcache:
        bcache[k] = np.array(con.execute(
            "SELECT t,h,l,c FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall(), float)
    return bcache[k]


def hourly_comp(tkr):
    """(close_ts_ms array, po_compression array) for a ticker, ETH grid."""
    if tkr not in hcache:
        F.TOPUP = STUDY / ('underlying_5m_topup_v2.parquet' if tkr in ORIG8
                           else 'underlying_5m_topup_new12.parquet')
        h, _ = hourly_and_daily(load_5m(tkr), session='ETH')
        h = compute_phase_oscillator(h)
        cts = (h.index + pd.Timedelta(minutes=60)).as_unit('ns').asi8 // 10**6
        hcache[tkr] = (cts, h['po_compression'].to_numpy(int))
    return hcache[tkr]


def confirm_ms_for(r):
    """First hourly close out of compression at/after the entry bar (live-valid)."""
    bc = pd.Timestamp(r.entry_bar_close_ts).value // 10**6
    if not r.flip_bar_closed_grey:
        return bc
    cts, comp = hourly_comp(r.ticker)
    m = (cts >= bc) & (comp == 0)
    return int(cts[np.argmax(m)]) if m.any() else None


def path_for(r):
    """(t, hi, lo, cl) normalized to entry_px, fill→expiry. None if no fill."""
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


def sim(path, hold, init_pre=0.5, init_post=None, confirm_ms=None,
        bail_ms=None, arm=1.0, trail=0.30):
    """Arm-then-trail with optional confirmation-widening stop and optional
    bail-at-bar-close-if-red. Returns (pnl, exit_kind)."""
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
    if init_post is None or confirm_ms is None:
        floor = np.full(n, 1 - init_pre)
        if init_post is not None:          # never confirmed: stay tight
            pass
    else:
        floor = np.where(t >= confirm_ms, 1 - init_post, 1 - init_pre)
    level = np.where(hp >= 1 + arm, hp * (1 - trail), floor)
    m = lo <= level
    si = int(np.argmax(m)) if m.any() else -1
    if bail_ms is not None:
        ib = np.searchsorted(t, bail_ms, side='right') - 1
        if ib >= 0 and (si < 0 or t[si] > bail_ms) and cl[ib] < 1.0:
            return float(cl[ib]) - 1, 'bail'
    if si >= 0:
        return float(level[si]) - 1, 'stop'
    return hold, 'hold'


def load_pop(files, chains=False):
    dfs = []
    for f in files:
        p = STUDY / f
        if p.exists():
            dfs.append(pd.read_parquet(p))
        else:
            print(f"  !! missing {f}")
    t = pd.concat(dfs, ignore_index=True)
    t = t[(t.bucket == 'W1') & (t.offset == 0.0) & (~t.censored) & (~t.rolled_to_open)]
    keys = ['ep_id', 'vehicle'] + (['attempt_seq'] if chains else [])
    return t.drop_duplicates(subset=keys)


def cstat(v):
    v = pd.Series(v).dropna()
    if len(v) < 3:
        return None
    tt = v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))
    pf = v[v > 0].sum() / max(1e-9, -v[v < 0].sum())
    return {'n': int(len(v)), 'mean': round(float(v.mean()), 4),
            't': round(float(tt), 2), 'win': round(float((v > 0).mean()), 3),
            'pf': round(float(pf), 2)}


def single_leg_grid(t):
    t = t[t.vehicle == 'long']
    out = {k: [] for k in ['fixed_tp100_sl50', 'trail_sl50', 'trail_sl35',
                           'trail_sl25', 'trail_bail', 'confirm_widen']}
    tick = {}
    for _, r in t.iterrows():
        p = path_for(r)
        if p is None:
            continue
        bc = pd.Timestamp(r.entry_bar_close_ts).value // 10**6
        cms = confirm_ms_for(r)
        out['fixed_tp100_sl50'].append(r.pnl_tp100_stop50)
        v50 = sim(p, r.pnl_hold, 0.5)[0]
        out['trail_sl50'].append(v50)
        out['trail_sl35'].append(sim(p, r.pnl_hold, 0.35)[0])
        out['trail_sl25'].append(sim(p, r.pnl_hold, 0.25)[0])
        out['trail_bail'].append(
            v50 if not r.flip_bar_closed_grey
            else sim(p, r.pnl_hold, 0.5, bail_ms=bc)[0])
        out['confirm_widen'].append(sim(p, r.pnl_hold, 0.25, init_post=0.5,
                                        confirm_ms=cms)[0])
        tick.setdefault(r.ticker in ORIG8, []).append(v50)
    res = {k: cstat(v) for k, v in out.items()}
    res['trail_sl50_orig8'] = cstat(tick.get(True, []))
    res['trail_sl50_new12'] = cstat(tick.get(False, []))
    return res


def straddle_grid(t):
    out = {k: [] for k in ['trail_sl50', 'trail_sl35', 'trail_bail', 'confirm_widen']}
    tick = {}
    for ep, g in t.groupby('ep_id'):
        gl, gs = g[g.vehicle == 'long'], g[g.vehicle == 'short']
        if not (len(gl) and len(gs)):
            continue
        rl, rs = gl.iloc[0], gs.iloc[0]
        pl, ps = path_for(rl), path_for(rs)
        if pl is None or ps is None:
            continue
        wl, ws = rl.entry_px, rs.entry_px
        holds = {'l': rl.pnl_hold, 's': -rs.pnl_hold}
        bc = pd.Timestamp(rl.entry_bar_close_ts).value // 10**6
        cms = confirm_ms_for(rl)

        def comb(**kw):
            a = sim(pl, holds['l'], **kw)[0]
            b = sim(ps, holds['s'], **kw)[0]
            return (a * wl + b * ws) / (wl + ws)
        v50 = comb(init_pre=0.5)
        out['trail_sl50'].append(v50)
        out['trail_sl35'].append(comb(init_pre=0.35))
        out['confirm_widen'].append(comb(init_pre=0.25, init_post=0.5, confirm_ms=cms))
        if not rl.flip_bar_closed_grey:
            out['trail_bail'].append(v50)
        else:
            # combined mark at entry-bar close; legs stopped earlier keep stops
            marks, done = [], []
            for p, w, h in [(pl, wl, holds['l']), (ps, ws, holds['s'])]:
                pnl, kind = sim(p, h, 0.5, bail_ms=bc)
                marks.append((pnl, kind, w, p, h))
            combined_bc = sum((1 + pnl) * w for pnl, k, w, _, _ in marks) / (wl + ws)
            if combined_bc < 1.0:
                out['trail_bail'].append(combined_bc - 1)
            else:
                out['trail_bail'].append(v50)
        tick.setdefault(rl.ticker in ORIG8, []).append(v50)
    res = {k: cstat(v) for k, v in out.items()}
    res['trail_sl50_orig8'] = cstat(tick.get(True, []))
    res['trail_sl50_new12'] = cstat(tick.get(False, []))
    return res


def chain_rearm(t):
    t = t[t.vehicle == 'long']
    ep_pnl, oos = {}, {}
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
            if kind == 'bail' or (kind == 'stop' and pnl <= -0.49):
                total += pnl
                continue                     # bailed or stopped fast: re-arm
            total += pnl
            resolved = True
            break
        if resolved or total != 0.0:
            ep_pnl[ep] = total
            oos.setdefault(g.iloc[0].ticker in ORIG8, []).append(total)
    return {'chain_rearm': cstat(list(ep_pnl.values())),
            'chain_rearm_orig8': cstat(oos.get(True, [])),
            'chain_rearm_new12': cstat(oos.get(False, []))}


def show(title, res):
    print(f"\n== {title} ==")
    for k, v in res.items():
        if v:
            print(f"  {k:22s} n={v['n']:4d} mean={100*v['mean']:+6.2f}% "
                  f"t={v['t']:+.2f} win={100*v['win']:.0f}% PF={v['pf']:.2f}")
        else:
            print(f"  {k:22s} (insufficient n)")


results = {}
POPS = [
    ('F_single', ['flip8_fullbox_trades.parquet', 'flip12_fullbox_trades.parquet'],
     'single'),
    ('F_straddle', ['flip8_fullbox_trades.parquet', 'flip12_fullbox_trades.parquet'],
     'straddle'),
    ('D_single', ['flip8_confirm_trades.parquet', 'flip12_confirm_trades.parquet'],
     'single'),
    ('D_straddle', ['flip8_confirm_trades.parquet', 'flip12_confirm_trades.parquet'],
     'straddle'),
    ('Fchain_single', ['flip8_fbmulti_trades.parquet', 'flip12_fbmulti_trades.parquet'],
     'chain'),
]
for name, files, kind in POPS:
    t = load_pop(files, chains=(kind == 'chain'))
    if kind == 'single':
        results[name] = single_leg_grid(t)
    elif kind == 'straddle':
        results[name] = straddle_grid(t)
    else:
        results[name] = chain_rearm(t)
    show(name, results[name])

out = STUDY / 'flip_mgmt_grid_results.json'
out.write_text(json.dumps(results, indent=1))
print(f"\nsaved -> {out}")
con.close()
