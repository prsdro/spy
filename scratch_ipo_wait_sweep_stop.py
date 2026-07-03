"""A) Wait-window sweep: entry at close of trading day N after listing,
N = 0(d1 open),21,42,...,252; XIRR vs SPY-mirror + 1y median excess per cohort.

B) Inverted pop rule: buy pop>=th IPOs at day-1 open, STOP at first daily
close <= issue price (sell at that close), survivors held to T_END/delisting.
XIRR vs SPY mirror with identical dated flows (money-weighted, so early-freed
dollars don't distort — they simply stop earning).
"""
import json, pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

OUT = Path('/root/spy/analyst/ipo_study')
T_END = date(2026, 5, 7)

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
spy = spy[spy.date <= T_END].reset_index(drop=True)
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

COHORTS = {
    'all': core,
    '>=100M': core[core.offer_size >= 1e8],
    '>=250M': core[core.offer_size >= 2.5e8],
    'nontech>=250M': core[(core.offer_size >= 2.5e8) & ~core.tech],
}

# ---------------- A: wait sweep ----------------
DELAYS = [0, 21, 42, 63, 84, 105, 126, 147, 168, 189, 210, 252]
print('=== A) entry-delay sweep: XIRR vs SPY-mirror  [1y median excess | beat%] ===')
print(f'{"entry":>10}', *[f'{c:^34}' for c in COHORTS])
for N in DELAYS:
    row = []
    for cname, sub in COHORTS.items():
        fl, sf, exs = [], [], []
        for r in sub.itertuples():
            b = bars.get((r.ticker, r.listing_date))
            if b is None:
                continue
            dts, opens, closes = b
            if N >= len(dts):
                continue
            entry_px = opens[0] if N == 0 else closes[N]
            if not entry_px or entry_px <= 0 or np.isnan(entry_px):
                continue
            e_ord = int(dts[N])
            spy0 = spy_asof(e_ord)
            fl += [(e_ord, -1.0), (int(dts[-1]), closes[-1] / entry_px)]
            sf += [(e_ord, -1.0), (int(dts[-1]), spy_asof(int(dts[-1])) / spy0)]
            j = N + 252
            if j < len(dts):
                exs.append(closes[j] / entry_px - spy_asof(int(dts[j])) / spy0)
            elif r.delisted:
                exs.append(closes[-1] / entry_px - spy_asof(int(dts[-1])) / spy0)
        fl.sort(); sf.sort()
        x, s = (xirr(fl), xirr(sf)) if fl else (None, None)
        exs = np.array(exs)
        med = f'{100*np.median(exs):+4.0f}%|{100*(exs>0).mean():2.0f}%' if len(exs) >= 5 else '   —   '
        row.append(f'{fx(x)} vs {fx(s)} [{med}]')
    lbl = 'day-1 open' if N == 0 else f'+{N}d~{N/21:.0f}mo'
    print(f'{lbl:>10}', *[f'{c:^34}' for c in row])

# ---------------- B: pop entry + stop at issue ----------------
print('\n=== B) buy day-1 open, STOP at first close <= issue price ===')
valid = core[(core.issue_price >= 1) & core.pop_open.notna() & (core.pop_open.abs() < 10)]
for size_lbl, size_lo in [('all sizes', 0), ('>=100M', 1e8), ('>=250M', 2.5e8)]:
    print(f'\n--- {size_lbl} ---')
    for th in [0.10, 0.20, 0.30]:
        sub = valid[valid.pop_open >= th]
        if size_lo:
            sub = sub[sub.offer_size.fillna(0) >= size_lo]
        fl, sf = [], []
        n = stopped = 0
        stop_days, stop_pnls, surv_mult = [], [], []
        for r in sub.itertuples():
            b = bars.get((r.ticker, r.listing_date))
            if b is None:
                continue
            dts, opens, closes = b
            entry_px = opens[0]
            if not entry_px or entry_px <= 0 or np.isnan(entry_px):
                continue
            n += 1
            e_ord = int(dts[0])
            spy0 = spy_asof(e_ord)
            hit = np.where(closes <= r.issue_price)[0]
            if len(hit):
                i = int(hit[0]); stopped += 1
                x_ord, x_px = int(dts[i]), closes[i]
                stop_days.append(x_ord - e_ord)
                stop_pnls.append(x_px / entry_px - 1)
            else:
                x_ord, x_px = int(dts[-1]), closes[-1]
                surv_mult.append(x_px / entry_px)
            fl += [(e_ord, -1.0), (x_ord, x_px / entry_px)]
            sf += [(e_ord, -1.0), (x_ord, spy_asof(x_ord) / spy0)]
        if n < 10:
            continue
        fl.sort(); sf.sort()
        x, s = xirr(fl), xirr(sf)
        sm = np.array(surv_mult)
        print(f'pop>={int(th*100)}%: n={n}, stopped {100*stopped/n:.0f}% '
              f'(med {np.median(stop_days):.0f}d, med loss {100*np.median(stop_pnls):.0f}%)'
              f' | survivors n={len(sm)}, med multiple {np.median(sm):.2f}x'
              f' | XIRR {fx(x)} vs SPY {fx(s)}')
