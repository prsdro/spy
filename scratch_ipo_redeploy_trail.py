"""Variants on the headline IPO strategy (nontech >=250M, entry close d126):

Stop rules (daily-close basis):
  fixed  : stop at entry*0.90
  be     : start entry*0.90; once close >= entry*1.10, raise stop to entry
  trail  : stop = 0.90 * running max close since entry (indefinite trail)
  none   : no stop (delist exits only)

Redeployment of exit proceeds (stops + delistings), same day at close:
  all    : equally across all open positions
  win10  : equally across open positions currently >10% above their entry
           (fallback: all open; else cash until next opportunity)

Outputs per variant: final wealth per external $1 (everything reinvested to
2026-05-07), external-flow XIRR vs SPY-hold, stop rate, median days held for
stopped positions, end concentration (top-1/top-5 weight).
"""
import json, pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

OUT = Path('/root/spy/analyst/ipo_study')
T_END = date(2026, 5, 7)
E = 126

events = pd.read_csv(OUT / 'ipo_events.csv')
core = events[~events.is_spac].copy()
def is_tech(s):
    try:
        c = int(str(s)[:4])
    except (ValueError, TypeError):
        return False
    return 3570 <= c <= 3579 or 3660 <= c <= 3699 or 7370 <= c <= 7379
sub = core[(core.offer_size >= 2.5e8) & ~core.sic_code.apply(is_tech)]
bars = pickle.loads((OUT / 'curve_bars_cache.pkl').read_bytes())

rep = pd.read_csv('/root/spy/data/candles_daily.csv.gz')
rep['date'] = pd.to_datetime(rep.timestamp).dt.date
api = pd.DataFrame(json.load(open(OUT / 'spy_daily.json')))
api['date'] = pd.to_datetime(api['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
api = api.rename(columns={'c': 'close'})
spy = pd.concat([rep[rep.date < api.date.min()][['date', 'close']],
                 api[['date', 'close']]], ignore_index=True)
spy = spy[spy.date <= T_END].reset_index(drop=True)
spy_ord = np.array([d.toordinal() for d in spy.date], np.int64)
spy_close = spy.close.to_numpy(float)
cal = spy_ord[spy_ord >= date(2021, 7, 1).toordinal()]
spy_cal = spy_close[np.searchsorted(spy_ord, cal, side='right') - 1]

def xirr(fl):
    t0 = fl[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - t0) / 365.25) for d, a in fl)
    try:
        return brentq(f, -0.9999, 10.0)
    except ValueError:
        return None

# ---- positions with per-rule exits ----
def stop_exit(closes, ei, entry_px, rule):
    """(exit_idx or None-for-natural, stopped) on daily closes."""
    if rule == 'none':
        return None, False
    level = entry_px * 0.90
    hi = entry_px
    for k in range(ei + 1, len(closes)):
        c = closes[k]
        if np.isnan(c):
            continue
        if c <= level:
            return k, True
        if rule == 'be' and c >= entry_px * 1.10:
            level = max(level, entry_px)
        elif rule == 'trail':
            hi = max(hi, c)
            level = max(level, 0.90 * hi)
    return None, False

def build_positions(rule):
    T_ORD = T_END.toordinal()
    pos = []
    for r in sub.itertuples():
        b = bars.get((r.ticker, r.listing_date))
        if b is None:
            continue
        dts, opens, closes = b
        if E >= len(dts):
            continue
        entry_px = closes[E]
        if not entry_px or entry_px <= 0 or np.isnan(entry_px):
            continue
        xi, stopped = stop_exit(closes, E, entry_px, rule)
        if xi is None:
            xi = len(dts) - 1
            if dts[xi] >= T_ORD - 10:
                xi = None            # held to end
        x_ord = int(dts[xi]) if xi is not None else None
        pos.append({'t': r.ticker, 'e_ord': int(dts[E]), 'entry_px': entry_px,
                    'x_ord': x_ord, 'stopped': stopped, 'dts': dts, 'closes': closes})
    return pos

def sim(positions, redeploy):
    n = len(positions)
    P = np.empty((n, len(cal)))
    entry_px = np.array([p['entry_px'] for p in positions])
    ent_k, ex_k = {}, {}
    for i, p in enumerate(positions):
        gi = np.searchsorted(p['dts'], cal, side='right') - 1
        P[i] = np.nan_to_num(p['closes'][np.clip(gi, 0, None)], nan=0.0)
        ent_k.setdefault(int(np.searchsorted(cal, p['e_ord'])), []).append(i)
        if p['x_ord'] is not None:
            ex_k.setdefault(int(np.searchsorted(cal, p['x_ord'])), []).append(i)
    shares = np.zeros(n); is_open = np.zeros(n, bool); cash = 0.0
    spy_units = 0.0; invested = 0
    for k in range(len(cal)):
        for i in ent_k.get(k, ()):
            shares[i] = 1.0 / positions[i]['entry_px']
            is_open[i] = True; invested += 1
            spy_units += 1.0 / spy_cal[k]
        pool = cash; cash = 0.0
        for i in ex_k.get(k, ()):
            pool += shares[i] * P[i, k]
            is_open[i] = False; shares[i] = 0.0
        if pool > 0:
            ok = is_open & (P[:, k] > 0)
            idx = np.where(ok & (P[:, k] / entry_px > 1.10))[0] if redeploy == 'win10' \
                else np.where(ok)[0]
            if redeploy == 'win10' and not len(idx):
                idx = np.where(ok)[0]
            if len(idx):
                shares[idx] += (pool / len(idx)) / P[idx, k]
            else:
                cash = pool
    vals = shares * P[:, -1]
    V = float(vals.sum() + cash)
    w = np.sort(vals[vals > 0])[::-1]
    top1 = w[0] / V if len(w) else 0
    top5 = w[:5].sum() / V if len(w) else 0
    return V, invested, top1, top5, int(is_open.sum())

T_ORD = T_END.toordinal()
print(f'{"stop":>6} {"redeploy":>8} | {"$/1":>6} {"XIRR":>7} | {"stopped":>7} '
      f'{"med d-held":>10} | {"top1":>5} {"top5":>5} {"open@end":>8}')
spy_x = None
for rule in ['none', 'fixed', 'be', 'trail']:
    positions = build_positions(rule)
    st = [p for p in positions if p['stopped']]
    med_held = np.median([p['x_ord'] - p['e_ord'] for p in st]) if st else float('nan')
    for redeploy in (['all', 'win10'] if rule != 'none' else ['all']):
        V, inv, top1, top5, n_open = sim(positions, redeploy)
        fl = sorted([(p['e_ord'], -1.0) for p in positions]) + [(T_ORD, V)]
        x = xirr(fl)
        if spy_x is None:
            sf = sorted([(p['e_ord'], -1.0) for p in positions]) + \
                 [(T_ORD, sum(spy_close[-1] / spy_close[np.searchsorted(spy_ord, p['e_ord'], side='right') - 1] for p in positions))]
            spy_x = xirr(sf)
        print(f'{rule:>6} {redeploy:>8} | {V/inv:6.3f} {100*x:6.1f}% | '
              f'{100*len(st)/len(positions):6.0f}% {med_held:10.0f} | '
              f'{100*top1:4.0f}% {100*top5:4.0f}% {n_open:8d}')
print(f'\nSPY same dollars/dates, held: XIRR {100*spy_x:.1f}%, '
      f'per $1 = {sum(spy_close[-1]/spy_close[np.searchsorted(spy_ord, p["e_ord"], side="right")-1] for p in build_positions("none"))/len(build_positions("none")):.3f}')
