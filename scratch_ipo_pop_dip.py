"""Pop-then-dip entry: buy big-pop IPOs only when they close back at/below the
issue price. Compare vs day-1 open and +6mo entries on the same cohorts.

Entry rule: IPO with valid issue price (>=$1, |pop|<10x) and day-1 open pop >=
threshold; buy at the first daily close <= issue price (day 1 onward); skip if
it never dips. Forward: 1y (252 bars, delisting = terminal early) + to-date XIRR
vs SPY over identical dates.
"""
import json, pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

OUT = Path('/root/spy/analyst/ipo_study')
T_END = date(2026, 5, 7)

df = pd.read_csv(OUT / 'ipo_events.csv')
core = df[~df.is_spac].copy()
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

valid = core[(core.issue_price >= 1) & core.pop_open.notna() & (core.pop_open.abs() < 10)].copy()

rows = []
for r in valid.itertuples():
    b = bars.get((r.ticker, r.listing_date))
    if b is None:
        continue
    dts, opens, closes = b
    ip = r.issue_price
    dip = np.where(closes <= ip)[0]
    rec = {'ticker': r.ticker, 'ld': r.listing_date, 'pop': r.pop_open,
           'size': r.offer_size, 'delisted': r.delisted, 'n_bars': len(dts),
           'e0_ret_252': r.e0_ret_252, 'e0_spy_252': r.e0_spy_252,
           'e126_ret_252': r.e126_ret_252, 'e126_spy_252': r.e126_spy_252,
           'dipped': len(dip) > 0}
    if len(dip):
        i = int(dip[0])
        entry_px, e_ord = closes[i], int(dts[i])
        spy0 = spy_asof(e_ord)
        rec.update(days_to_dip=e_ord - date.fromisoformat(r.listing_date).toordinal(),
                   entry_ord=e_ord, entry_px=entry_px,
                   ret_end=closes[-1] / entry_px - 1,
                   spy_end=spy_asof(int(dts[-1])) / spy0 - 1,
                   last_ord=int(dts[-1]))
        j = i + 252
        if j < len(dts):
            rec['ret_1y'] = closes[j] / entry_px - 1
            rec['spy_1y'] = spy_asof(int(dts[j])) / spy0 - 1
        elif r.delisted:
            rec['ret_1y'] = rec['ret_end']
            rec['spy_1y'] = rec['spy_end']
    rows.append(rec)
d = pd.DataFrame(rows)

def agg(sub, rc, sc):
    s = sub[[rc, sc]].dropna()
    if len(s) < 5:
        return None
    ex = s[rc] - s[sc]
    return (f"n={len(s)} med={100*s[rc].median():.0f}% "
            f"med_ex={100*ex.median():.0f}% beat={100*(ex>0).mean():.0f}%")

def strat_xirr(sub):
    fl, sf = [], []
    for r in sub.dropna(subset=['ret_end']).itertuples():
        fl += [(r.entry_ord, -1.0), (r.last_ord, 1.0 + r.ret_end)]
        sf += [(r.entry_ord, -1.0), (r.last_ord, 1.0 + r.spy_end)]
    if not fl:
        return None, None
    fl.sort(); sf.sort()
    return xirr(fl), xirr(sf)

def e_xirr(ev_sub, tag):
    fl, sf = [], []
    for r in ev_sub.dropna(subset=[f'{tag}_ret_end', f'{tag}_date']).itertuples():
        ed = date.fromisoformat(getattr(r, f'{tag}_date')).toordinal()
        xd = date.fromisoformat(r.last_date).toordinal()
        fl += [(ed, -1.0), (xd, 1.0 + getattr(r, f'{tag}_ret_end'))]
        sf += [(ed, -1.0), (xd, 1.0 + getattr(r, f'{tag}_spy_end'))]
    if not fl:
        return None, None
    fl.sort(); sf.sort()
    return xirr(fl), xirr(sf)

fx = lambda p: '—' if p is None else f'{100*p:.1f}%'
for size_lbl, size_lo in [('all sizes', 0), ('>=100M', 1e8), ('>=250M', 2.5e8)]:
    print(f'\n================ {size_lbl} ================')
    for th in [0.10, 0.20, 0.30, 0.50]:
        sub = d[(d['pop'] >= th) & (d['size'].fillna(0) >= size_lo if size_lo else True)]
        if size_lo:
            sub = d[(d['pop'] >= th) & (d['size'].fillna(0) >= size_lo)]
        else:
            sub = d[d['pop'] >= th]
        if len(sub) < 10:
            continue
        dippers = sub[sub.dipped]
        never = sub[~sub.dipped]
        keys = set(zip(sub.ticker, sub.ld))
        ev = valid[[ (t, l) in keys for t, l in zip(valid.ticker, valid.listing_date)]]
        x, sxp = strat_xirr(dippers)
        ex0, es0 = e_xirr(ev, 'e0')
        ex126, es126 = e_xirr(ev, 'e126')
        med_days = dippers.days_to_dip.median()
        print(f'pop>={int(th*100)}%: n={len(sub)}, dip-to-issue {100*sub.dipped.mean():.0f}% '
              f'(med {med_days:.0f}d)')
        print(f'   dip-entry 1y : {agg(dippers, "ret_1y", "spy_1y")}   '
              f'XIRR {fx(x)} vs SPY {fx(sxp)}')
        print(f'   same-cohort e0  : {agg(ev, "e0_ret_252", "e0_spy_252")}   XIRR {fx(ex0)} vs {fx(es0)}')
        print(f'   same-cohort e126: {agg(ev, "e126_ret_252", "e126_spy_252")}   XIRR {fx(ex126)} vs {fx(es126)}')
        nv = never.dropna(subset=['e0_ret_252'])
        if len(nv) >= 3:
            print(f'   never-dipped ({len(never)}): e0 1y med {100*nv.e0_ret_252.median():.0f}%, '
                  f'med_ex {100*(nv.e0_ret_252-nv.e0_spy_252).median():.0f}%, '
                  f'beat {100*((nv.e0_ret_252-nv.e0_spy_252)>0).mean():.0f}%')

d.to_csv(OUT / 'pop_dip_events.csv', index=False)
print('\nwrote', OUT / 'pop_dip_events.csv')
