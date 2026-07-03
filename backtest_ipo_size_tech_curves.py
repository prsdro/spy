"""IPO 5-year study, angle 2: size-threshold strategies, tech split, equity curves.

Builds on backtest_ipo_5yr.py output (analyst/ipo_study/ipo_events.csv) plus the
same bar stores, and answers:
  - Only buy IPOs raising >= $250M / $500M / $1B: how many per year, XIRR vs SPY,
    and does waiting (1d/1w/1m/3m/6m) help within each bucket?
  - Same wait question for tech vs non-tech (SIC 3570-3579, 3660-3699, 7370-7379).
  - Weekly equity curves ($1 per IPO at entry, SPY mirror with identical cashflow
    dates; delisted/exited proceeds sit in cash on BOTH legs).
  - Scatter: per-IPO 1y forward return vs SPY 1y return over the same window.

Output: site/data/ipo-5yr-curves.json (+ analyst/ipo_study/size_tech_summary.json)
"""
import json, math, pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from backtest_ipo_5yr import (OUT, T_END, load_local_bars, load_api_bars,
                              load_yahoo_bars, load_stooq_bars, truncate_at_gap)

SITE = Path('/root/spy/site/data')
DELAYS = [('e0', 0, 'Day-1 open'), ('e1', 1, '+1 day'), ('e5', 5, '+1 week'),
          ('e21', 21, '+1 month'), ('e63', 63, '+3 months'), ('e126', 126, '+6 months')]
CURVE_DELAYS = ['e0', 'e21', 'e126']


def is_tech(sic):
    try:
        c = int(str(sic)[:4])
    except (ValueError, TypeError):
        return False
    return 3570 <= c <= 3579 or 3660 <= c <= 3699 or 7370 <= c <= 7379


def xirr(flows):
    t0 = flows[0][0]
    def npv(r):
        return sum(a / (1 + r) ** ((d - t0).days / 365.25) for d, a in flows)
    try:
        return brentq(npv, -0.9999, 10.0)
    except ValueError:
        return None


def strat_xirr(sub, tag):
    s = sub.dropna(subset=[f'{tag}_ret_end', f'{tag}_date'])
    flows, sflows = [], []
    for _, r in s.iterrows():
        ed, xd = date.fromisoformat(r[f'{tag}_date']), date.fromisoformat(r['last_date'])
        flows += [(ed, -1.0), (xd, 1.0 + r[f'{tag}_ret_end'])]
        sflows += [(ed, -1.0), (xd, 1.0 + r[f'{tag}_spy_end'])]
    if not flows:
        return None, None
    flows.sort(); sflows.sort()
    x, sx = xirr(flows), xirr(sflows)
    return (round(x, 4) if x is not None else None,
            round(sx, 4) if sx is not None else None)


def ladder(sub):
    out = {}
    for tag, _, _ in DELAYS:
        rc, sc = f'{tag}_ret_252', f'{tag}_spy_252'
        s = sub[[rc, sc]].dropna()
        if len(s) < 5:
            out[tag] = None
            continue
        ex = s[rc] - s[sc]
        out[tag] = {'n': int(len(s)),
                    'median_ret': round(float(s[rc].median()), 4),
                    'median_excess': round(float(ex.median()), 4),
                    'beat_spy': round(float((ex > 0).mean()), 4)}
    return out


def group_stats(sub):
    g = {'n': int(len(sub)), 'ladder': ladder(sub), 'xirr': {}}
    for tag in CURVE_DELAYS:
        x, sx = strat_xirr(sub, tag)
        g['xirr'][tag] = {'strat': x, 'spy': sx,
                          'n': int(sub[f'{tag}_ret_end'].notna().sum())}
    yrs = sub.listing_date.str[:4].value_counts().sort_index()
    g['per_year'] = {y: int(c) for y, c in yrs.items()}
    return g


def main():
    df = pd.read_csv(OUT / 'ipo_events.csv')
    core = df[~df.is_spac].copy()
    core['tech'] = core.sic_code.apply(is_tech)

    groups = {
        'ge250':  core[core.offer_size >= 250e6],
        'ge500':  core[core.offer_size >= 500e6],
        'ge1000': core[core.offer_size >= 1e9],
        'r250_500':  core[(core.offer_size >= 250e6) & (core.offer_size < 500e6)],
        'r500_1000': core[(core.offer_size >= 500e6) & (core.offer_size < 1e9)],
        'tech_all':    core[core.tech],
        'nontech_all': core[~core.tech],
        'tech_ge250':    core[core.tech & (core.offer_size >= 250e6)],
        'nontech_ge250': core[~core.tech & (core.offer_size >= 250e6)],
    }

    summary = {'groups': {k: group_stats(v) for k, v in groups.items()}}

    # universe-level size counts (incl. names without usable bars) for coverage note
    uni = json.load(open(OUT / 'ipo_universe.json'))
    def usize(r):
        return r.get('total_offer_size') or (
            (r.get('max_shares_offered') or 0) * (r.get('final_issue_price') or 0) or None)
    summary['universe_counts'] = {
        k: sum(1 for r in uni if (usize(r) or 0) >= th)
        for k, th in [('ge250', 250e6), ('ge500', 500e6), ('ge1000', 1e9)]}

    # ---- SPY series (same construction as base study) ----
    rep = pd.read_csv('/root/spy/data/candles_daily.csv.gz')
    rep['date'] = pd.to_datetime(rep.timestamp).dt.date
    api = pd.DataFrame(json.load(open(OUT / 'spy_daily.json')))
    api['date'] = pd.to_datetime(api['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
    api = api.rename(columns={'o': 'open', 'c': 'close'})
    cut = api.date.min()
    spy = pd.concat([rep[rep.date < cut][['date', 'close']], api[['date', 'close']]],
                    ignore_index=True)
    spy = spy[spy.date <= T_END].reset_index(drop=True)
    spy_ord = np.array([d.toordinal() for d in spy.date], np.int64)
    spy_close = spy.close.to_numpy(float)

    def spy_asof(o):
        i = int(np.searchsorted(spy_ord, o, side='right')) - 1
        return spy_close[i] if i >= 0 else None

    start = date(2021, 7, 1)
    grid_all = [d for d in spy.date if d >= start]
    grid = grid_all[::5]
    if grid[-1] != grid_all[-1]:
        grid.append(grid_all[-1])
    grid_ord = np.array([d.toordinal() for d in grid], np.int64)
    spy_grid_vals = spy_close[np.searchsorted(spy_ord, grid_ord, side='right') - 1]

    # ---- load bars once per ticker needed by any curve group (pickle-cached) ----
    cache_p = OUT / 'curve_bars_cache.pkl'
    if cache_p.exists():
        bars = pickle.loads(cache_p.read_bytes())
        print(f'bars cache hit: {len(bars)}', flush=True)
    else:
        need = sorted(set().union(*[set(g.ticker) for g in groups.values()]))
        bars = {}
        for i, t in enumerate(need):
            for _, r in core[core.ticker == t].iterrows():
                ld = r.listing_date
                ldd = date.fromisoformat(ld)
                dfb = None
                for loader in (lambda: load_local_bars(t, ldd.year),
                               lambda: load_api_bars(t, ld),
                               lambda: load_yahoo_bars(t, ld),
                               lambda: load_stooq_bars(t, ld)):
                    cand = loader()
                    if cand is None or not len(cand):
                        continue
                    cand = cand[(cand.date >= ldd) & (cand.date <= T_END)].reset_index(drop=True)
                    if not len(cand):
                        continue
                    cand = truncate_at_gap(cand)
                    if (cand.date.iloc[0] - ldd).days > 7 or len(cand) < 2:
                        continue
                    dfb = cand
                    break
                if dfb is not None:
                    bars[(t, ld)] = (np.array([d.toordinal() for d in dfb.date], np.int64),
                                     dfb.open.to_numpy(float), dfb.close.to_numpy(float))
            if (i + 1) % 50 == 0:
                print(f'bars {i+1}/{len(need)}', flush=True)
        cache_p.write_bytes(pickle.dumps(bars))

    T_END_ORD = T_END.toordinal()
    cal = spy_ord[spy_ord >= start.toordinal()]          # daily trading calendar
    cal_grid_idx = np.searchsorted(cal, grid_ord)        # weekly sample points
    spy_cal = spy_close[np.searchsorted(spy_ord, cal, side='right') - 1]

    def build_positions(sub, tag, stop_pct=None):
        """One dict per fillable position: entry/exit ords, prices, bar series."""
        pos = []
        for r in sub.itertuples():
            b = bars.get((r.ticker, r.listing_date))
            ed_s = getattr(r, f'{tag}_date')
            if b is None or not isinstance(ed_s, str):
                continue
            dts, opens, closes = b
            ed = date.fromisoformat(ed_s).toordinal()
            ei = int(np.searchsorted(dts, ed))
            if ei >= len(dts) or dts[ei] != ed:
                continue
            entry_px = opens[ei] if tag == 'e0' else closes[ei]
            if not entry_px or entry_px <= 0 or math.isnan(entry_px):
                continue
            if not spy_asof(ed):
                continue
            xi, stopped = len(dts) - 1, False
            if stop_pct:
                hit = np.where(closes[ei + 1:] <= entry_px * (1 - stop_pct))[0]
                if len(hit):
                    xi, stopped = ei + 1 + int(hit[0]), True
            # exit event only if stopped or the series dies early (delist/splice);
            # otherwise the position is simply held through the end of the sample
            x_ord = int(dts[xi]) if (stopped or dts[xi] < T_END_ORD - 10) else None
            pos.append({'e_ord': ed, 'entry_px': entry_px, 'x_ord': x_ord,
                        'stopped': stopped, 'dts': dts, 'closes': closes})
        return pos

    def sim(positions):
        """Self-financing portfolio: $1 external at each entry; exit proceeds
        (stops and delistings) redeployed equally across open positions the
        same day (held as cash only while nothing is open). SPY leg = the same
        external dollars into SPY, held to the end of the sample."""
        n = len(positions)
        P = np.empty((n, len(cal)))
        ent_k, ex_k = {}, {}
        for i, p in enumerate(positions):
            gi = np.searchsorted(p['dts'], cal, side='right') - 1
            P[i] = np.nan_to_num(p['closes'][np.clip(gi, 0, None)], nan=0.0)
            k = int(np.searchsorted(cal, p['e_ord']))
            ent_k.setdefault(k, []).append(i)
            if p['x_ord'] is not None:
                ex_k.setdefault(int(np.searchsorted(cal, p['x_ord'])), []).append(i)
        shares = np.zeros(n); is_open = np.zeros(n, bool); cash = 0.0
        inv_ctr = 0; spy_units = 0.0
        v_out, s_out, inv_out = [], [], []
        samples = set(cal_grid_idx.tolist())
        for k in range(len(cal)):
            for i in ent_k.get(k, ()):
                shares[i] = 1.0 / positions[i]['entry_px']
                is_open[i] = True
                inv_ctr += 1
                spy_units += 1.0 / spy_cal[k]
            pool = cash; cash = 0.0
            for i in ex_k.get(k, ()):
                pool += shares[i] * P[i, k]
                is_open[i] = False; shares[i] = 0.0
            if pool > 0:
                idx = np.where(is_open & (P[:, k] > 0))[0]
                if len(idx):
                    shares[idx] += (pool / len(idx)) / P[idx, k]
                else:
                    cash = pool
            if k in samples:
                v_out.append(float((shares * P[:, k]).sum() + cash))
                s_out.append(float(spy_units * spy_cal[k]))
                inv_out.append(inv_ctr)
        n_stopped = sum(1 for p in positions if p['stopped'])
        return {'v': [round(x, 3) for x in v_out],
                's': [round(x, 3) for x in s_out],
                'inv': inv_out, 'n': n,
                **({'stopped': n_stopped} if n_stopped else {})}

    curves = {}
    for gk, sub in groups.items():
        curves[gk] = {tag: sim(build_positions(sub, tag)) for tag in CURVE_DELAYS}
        print('curves', gk, {t: curves[gk][t]['n'] for t in CURVE_DELAYS}, flush=True)

    # headline strategy: nontech >=250M, +6mo entry, -10% daily-close stop,
    # stopped proceeds reinvested equally into the remaining open positions
    strat = sim(build_positions(groups['nontech_ge250'], 'e126', stop_pct=0.10))
    curves['strat_stop10'] = strat
    print('strat_stop10', {k: strat[k] for k in ('n', 'stopped')},
          'final/$', round(strat['v'][-1] / max(strat['inv'][-1], 1), 3),
          'spy/$', round(strat['s'][-1] / max(strat['inv'][-1], 1), 3), flush=True)

    # ---- scatter: 1y IPO return vs SPY 1y return over identical window ----
    sc = core.dropna(subset=['e0_ret_252', 'e0_spy_252'])
    scatter = [{'t': r.ticker,
                'nm': (r.issuer or '')[:40] if isinstance(r.issuer, str) else '',
                'y': int(r.listing_date[:4]),
                'sz': round(r.offer_size / 1e6, 1) if r.offer_size == r.offer_size else None,
                'tech': bool(r.tech),
                'ipo': round(float(r.e0_ret_252), 4),
                'spy': round(float(r.e0_spy_252), 4),
                'early': bool(getattr(r, 'e0_early_252', False) is True)}
               for r in sc.itertuples()]

    out = {'meta': {'valued_at': str(T_END), 'grid_start': str(grid[0]),
                    'universe_counts': summary['universe_counts'],
                    'tech_def': 'SIC 3570-3579, 3660-3699, 7370-7379'},
           'groups': summary['groups'],
           'grid': [str(d) for d in grid],
           'curves': curves,
           'scatter': scatter}
    SITE.joinpath('ipo-5yr-curves.json').write_text(json.dumps(out))
    json.dump({'groups': summary['groups'],
               'universe_counts': summary['universe_counts']},
              open(OUT / 'size_tech_summary.json', 'w'), indent=1)

    for k in ['ge250', 'ge500', 'ge1000', 'tech_all', 'nontech_all']:
        g = summary['groups'][k]
        print(f"\n{k}: n={g['n']} per_year={g['per_year']}")
        for tag in CURVE_DELAYS:
            print(f"  {tag}: xirr={g['xirr'][tag]['strat']} vs spy {g['xirr'][tag]['spy']}",
                  f"| 1y med excess={g['ladder'][tag] and g['ladder'][tag]['median_excess']}")


if __name__ == '__main__':
    main()
