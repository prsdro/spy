"""Decade-back run of the headline strategy: non-tech >=$250M IPOs listed
2011-01-01..2021-06-30, entry at close of trading day 126 (+6 months),
variants: no stop / fixed -10% stop (redeploy all / winners>+10%).
Self-financing (exit proceeds redeployed same day), held to 2026-05-07.
Bars: Yahoo only (survivors) -> prints the survivorship gap explicitly.
"""
import json, re, pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from backtest_ipo_5yr import load_yahoo_bars, truncate_at_gap

OUT = Path('/root/spy/analyst/ipo_study')
T_END = date(2026, 5, 7)
E = 126

cohort = json.load(open(OUT / 'decade_cohort.json'))
sub = [c for c in cohort if not c['spac'] and not c['tech']]
print(f'cohort >=250M non-SPAC non-tech: {len(sub)} '
      f'(of {len(cohort)}; {sum(1 for c in sub if c["sic"] is None)} with unknown SIC)')

# ---- SPY ----
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
cal = spy_ord[spy_ord >= date(2011, 1, 1).toordinal()]
spy_cal = spy_close[np.searchsorted(spy_ord, cal, side='right') - 1]

def xirr(fl):
    t0 = fl[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - t0) / 365.25) for d, a in fl)
    try:
        return brentq(f, -0.9999, 10.0)
    except ValueError:
        return None

# ---- load bars (Yahoo, listing-date guard, gap truncation, clip to T_END) ----
T_ORD = T_END.toordinal()
loaded, no_bars, bad_start = {}, [], []
for c in sub:
    t, ld = c['ticker'], c['listing_date']
    df = load_yahoo_bars(t, ld)
    if df is None or not len(df):
        no_bars.append(t)
        continue
    ldd = date.fromisoformat(ld)
    df = df[(df.date >= ldd) & (df.date <= T_END)].reset_index(drop=True)
    if not len(df):
        no_bars.append(t)
        continue
    df = truncate_at_gap(df)
    if (df.date.iloc[0] - ldd).days > 7 or len(df) < 2:
        bad_start.append(t)      # recycled ticker / truncated series
        continue
    loaded[t] = (np.array([d.toordinal() for d in df.date], np.int64),
                 df.close.to_numpy(float))
print(f'bars: {len(loaded)} usable, {len(no_bars)} missing (delisted), '
      f'{len(bad_start)} rejected by listing-date guard '
      f'-> coverage {100*len(loaded)/len(sub):.0f}%')
by_yr = {}
for c in sub:
    y = c['listing_date'][:4]
    by_yr.setdefault(y, [0, 0])[1] += 1
    if c['ticker'] in loaded:
        by_yr[y][0] += 1
print('coverage by vintage:', {y: f'{a}/{b}' for y, (a, b) in sorted(by_yr.items())})

def stop_exit(closes, ei, entry_px, rule):
    if rule == 'none':
        return None, False
    level = entry_px * 0.90
    for k in range(ei + 1, len(closes)):
        c = closes[k]
        if np.isnan(c):
            continue
        if c <= level:
            return k, True
    return None, False

def build_positions(rule):
    pos = []
    for c in sub:
        b = loaded.get(c['ticker'])
        if b is None:
            continue
        dts, closes = b
        if E >= len(dts):
            continue
        entry_px = closes[E]
        if not entry_px or entry_px <= 0 or np.isnan(entry_px):
            continue
        xi, stopped = stop_exit(closes, E, entry_px, rule)
        if xi is None:
            xi = len(dts) - 1
            if dts[xi] >= T_ORD - 10:
                xi = None
        pos.append({'t': c['ticker'], 'e_ord': int(dts[E]), 'entry_px': entry_px,
                    'x_ord': int(dts[xi]) if xi is not None else None,
                    'stopped': stopped, 'dts': dts, 'closes': closes})
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
    invested = 0
    for k in range(len(cal)):
        for i in ent_k.get(k, ()):
            shares[i] = 1.0 / positions[i]['entry_px']
            is_open[i] = True; invested += 1
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
    return V, invested, (w[0] / V if len(w) else 0), (w[:5].sum() / V if len(w) else 0)

print(f'\n{"variant":>22} | {"$/1":>6} {"XIRR":>7} | {"stopped":>7} {"top1":>5} {"top5":>5}')
spy_line = None
for rule, redeps in [('none', ['all']), ('fixed', ['all', 'win10'])]:
    positions = build_positions(rule)
    st = sum(1 for p in positions if p['stopped'])
    for redeploy in redeps:
        V, inv, top1, top5 = sim(positions, redeploy)
        fl = sorted([(p['e_ord'], -1.0) for p in positions]) + [(T_ORD, V)]
        x = xirr(fl)
        if spy_line is None:
            tot = sum(spy_close[-1] / spy_close[np.searchsorted(spy_ord, p['e_ord'], side='right') - 1]
                      for p in positions)
            sf = sorted([(p['e_ord'], -1.0) for p in positions]) + [(T_ORD, tot)]
            spy_line = (tot / len(positions), xirr(sf))
        print(f'{rule+" / "+redeploy:>22} | {V/inv:6.3f} {100*x:6.1f}% | '
              f'{100*st/len(positions):6.0f}% {100*top1:4.0f}% {100*top5:4.0f}%')
print(f'{"SPY same $ & dates":>22} | {spy_line[0]:6.3f} {100*spy_line[1]:6.1f}%')

# per-vintage 1y raw/excess from entry (context)
rows = []
for c in sub:
    b = loaded.get(c['ticker'])
    if b is None:
        continue
    dts, closes = b
    if E + 252 >= len(dts) or not closes[E] or np.isnan(closes[E]):
        continue
    s0 = spy_close[np.searchsorted(spy_ord, dts[E], side='right') - 1]
    s1 = spy_close[np.searchsorted(spy_ord, dts[E + 252], side='right') - 1]
    rows.append({'y': c['listing_date'][:4],
                 'ex': closes[E + 252] / closes[E] - 1 - (s1 / s0 - 1)})
df = pd.DataFrame(rows)
print('\n1y excess vs SPY from +6mo entry, by vintage (survivors only):')
for y, g in df.groupby('y'):
    print(f'  {y}: n={len(g):3d} median {100*g.ex.median():+5.1f}%  beat {100*(g.ex>0).mean():3.0f}%')
