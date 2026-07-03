"""Buy at +6 months (close of trading day 126) conditioned on the issue price:
  V1 'above at 6mo'  : close[126] > issue price
  V2 'never dipped'  : no close <= issue in days 0..126
plus the rejected complement and the unconditional e126 baseline.

Then stop-loss grid on the conditioned entries: exit at first close below
  - issue price
  - entry * (1-s) for s in 10/15/20/25/35%
vs no stop. XIRR on dated flows vs SPY mirror with identical flows.
"""
import json, pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

OUT = Path('/root/spy/analyst/ipo_study')
events = pd.read_csv(OUT / 'ipo_events.csv')
core = events[~events.is_spac].copy()
def is_tech(s):
    try:
        c = int(str(s)[:4])
    except (ValueError, TypeError):
        return False
    return 3570 <= c <= 3579 or 3660 <= c <= 3699 or 7370 <= c <= 7379
core['tech'] = core.sic_code.apply(is_tech)
bars = pickle.loads((OUT / 'curve_bars_cache.pkl').read_bytes())

rep = pd.read_csv('/root/spy/data/candles_daily.csv.gz')
rep['date'] = pd.to_datetime(rep.timestamp).dt.date
api = pd.DataFrame(json.load(open(OUT / 'spy_daily.json')))
api['date'] = pd.to_datetime(api['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
api = api.rename(columns={'o': 'open', 'c': 'close'})
cut = api.date.min()
spy = pd.concat([rep[rep.date < cut][['date', 'close']], api[['date', 'close']]], ignore_index=True)
spy_ord = np.array([d.toordinal() for d in spy.date], np.int64)
spy_close = spy.close.to_numpy(float)
def spy_asof(o):
    i = int(np.searchsorted(spy_ord, o, side='right')) - 1
    return spy_close[i] if i >= 0 else None

def xirr(fl):
    t0 = fl[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - t0) / 365.25) for d, a in fl)
    try:
        return brentq(f, -0.9999, 10.0)
    except ValueError:
        return None
fx = lambda p: '  —  ' if p is None else f'{100*p:5.1f}%'

E = 126
valid = core[core.issue_price >= 1]

def positions(sub, cond):
    """cond(closes, issue) -> bool, applied at entry day E."""
    out = []
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
        if not cond(closes, r.issue_price):
            continue
        out.append((dts, closes, entry_px, r.issue_price, bool(r.delisted)))
    return out

def evaluate(pos, stop=None):
    """stop: None | ('issue',) | ('pct', s). Exit at first close <= level after E."""
    fl, sf, exs = [], [], []
    stopped, stop_pnl = 0, []
    for dts, closes, entry_px, issue, delisted in pos:
        e_ord = int(dts[E]); spy0 = spy_asof(e_ord)
        level = None
        if stop:
            level = issue if stop[0] == 'issue' else entry_px * (1 - stop[1])
        xi = len(dts) - 1
        if level is not None:
            hit = np.where(closes[E + 1:] <= level)[0]
            if len(hit):
                xi = E + 1 + int(hit[0])
                stopped += 1
                stop_pnl.append(closes[xi] / entry_px - 1)
        x_ord, x_px = int(dts[xi]), closes[xi]
        fl += [(e_ord, -1.0), (x_ord, x_px / entry_px)]
        sf += [(e_ord, -1.0), (x_ord, spy_asof(x_ord) / spy0)]
        # 1y window (unstopped path only meaningful for no-stop; for stops use exit if earlier)
        j = min(E + 252, len(dts) - 1) if delisted else E + 252
        if j < len(dts):
            jj = min(j, xi)
            exs.append(closes[jj] / entry_px - spy_asof(int(dts[jj])) / spy0)
    fl.sort(); sf.sort()
    x, s = (xirr(fl), xirr(sf)) if fl else (None, None)
    exs = np.array(exs)
    med = (f'1y_ex {100*np.median(exs):+3.0f}% beat {100*(exs>0).mean():2.0f}%'
           if len(exs) >= 5 else '1y —')
    st = (f' stopped {100*stopped/len(pos):3.0f}% (med {100*np.median(stop_pnl):+3.0f}%)'
          if stop and stopped else '')
    return f'n={len(pos):3d}  XIRR {fx(x)} vs {fx(s)}  [{med}]{st}'

COHORTS = {
    'all(w/issue)': valid,
    '>=100M': valid[valid.offer_size >= 1e8],
    '>=250M': valid[valid.offer_size >= 2.5e8],
    'nontech>=250M': valid[(valid.offer_size >= 2.5e8) & ~valid.tech],
}
above = lambda c, ip: c[E] > ip
never = lambda c, ip: c[:E + 1].min() > ip
below = lambda c, ip: c[E] <= ip

for cname, sub in COHORTS.items():
    print(f'\n=== {cname} ===')
    print('  e126 uncond   :', evaluate(positions(sub, lambda c, ip: True)))
    print('  V1 above@6mo  :', evaluate(positions(sub, above)))
    print('  V2 never<=iss :', evaluate(positions(sub, never)))
    print('  rejected(<=)  :', evaluate(positions(sub, below)))

print('\n=== stop-loss grid on V1 (nontech>=250M and >=100M) ===')
for cname in ['>=100M', 'nontech>=250M']:
    pos = positions(COHORTS[cname], above)
    print(f'\n--- {cname}, V1 entries ---')
    print('  no stop       :', evaluate(pos))
    print('  stop@issue    :', evaluate(pos, ('issue',)))
    for s in [0.10, 0.15, 0.20, 0.25, 0.35]:
        print(f'  stop -{int(s*100):2d}%     :', evaluate(pos, ('pct', s)))
