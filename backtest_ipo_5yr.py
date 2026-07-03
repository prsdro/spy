"""IPO 5-year study: buy every IPO — day-1 vs delayed entry, vs SPY, by industry.

Universe: Massive vX/reference/ipos, ipo_status=history, listing 2021-07-01..2026-06-30,
security_type CS/ADRC, exchange XNAS/XNYS/XASE (SPAC units/OTC excluded from universe;
blank-check CS identified via SIC 6770 and segmented out).

Bars: local parquet store (/srv/ftp/ossicones/stock-data/bars_1d_adjusted) when the
ticker has full year coverage listing->2026, else API-fetched json in
analyst/ipo_study/bars/. All adjusted. Terminal valuation date = T_END (last local bar).

Outputs:
  analyst/ipo_study/ipo_events.csv   - one row per IPO with entry/exit returns
  analyst/ipo_study/ipo_summary.json - aggregate stats per strategy
"""
import json, glob, os, re, math
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import numpy as np

OUT = Path('/root/spy/analyst/ipo_study')
LOCAL = Path('/srv/ftp/ossicones/stock-data/bars_1d_adjusted')
T_END = date(2026, 5, 7)          # last local bar date; common terminal valuation
ENTRY_DELAYS = [0, 1, 5, 21, 63, 126]   # trading days after listing (0=d1 open, others=close of idx)
HORIZONS = [21, 63, 126, 252]     # trading days after entry
GAP_DAYS = 30                     # calendar-gap => treat as ticker splice, truncate

def load_local_bars(t, y0):
    frames = []
    for y in range(y0, 2027):
        p = LOCAL / f'year={y}' / f'{t}.parquet'
        if p.exists():
            frames.append(pd.read_parquet(p, columns=['metric_ts_et', 'open', 'high', 'low', 'close', 'volume']))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df['date'] = pd.to_datetime(df.metric_ts_et.str[:10]).dt.date
    return df[['date', 'open', 'close']].sort_values('date').reset_index(drop=True)

def load_api_bars(t, ld):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    p = OUT / 'bars' / f'{safe}__{ld}.json'
    if not p.exists():
        return None
    rows = json.loads(p.read_text())
    if not rows:
        return None
    df = pd.DataFrame(rows)
    # t = ms epoch UTC of bar start; daily bars stamp midnight ET -> convert via ET
    df['date'] = pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
    df = df.rename(columns={'o': 'open', 'c': 'close'})
    return df[['date', 'open', 'close']].sort_values('date').reset_index(drop=True)

def load_yahoo_bars(t, ld):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    p = OUT / 'bars_yahoo' / f'{safe}__{ld}.json'
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    ts = d.get('timestamp')
    if not ts:
        return None
    q = d['indicators']['quote'][0]
    adj = d['indicators']['adjclose'][0]['adjclose']
    df = pd.DataFrame({'date': pd.to_datetime(ts, unit='s', utc=True).tz_convert('America/New_York').date,
                       'open_raw': q['open'], 'close_raw': q['close'], 'adjclose': adj})
    df = df.dropna(subset=['close_raw', 'adjclose'])
    f = df.adjclose / df.close_raw
    df['open'] = df.open_raw * f
    df['close'] = df.adjclose
    return df[['date', 'open', 'close']].sort_values('date').reset_index(drop=True)

def load_stooq_bars(t, ld):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    p = OUT / 'bars_stooq' / f'{safe}__{ld}.csv'
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if 'Date' not in df.columns or not len(df):
        return None
    df['date'] = pd.to_datetime(df.Date).dt.date
    df = df.rename(columns={'Open': 'open', 'Close': 'close'})
    return df[['date', 'open', 'close']].sort_values('date').reset_index(drop=True)

def truncate_at_gap(df):
    d = pd.to_datetime(pd.Series(df.date))
    gaps = d.diff().dt.days
    bad = gaps[gaps > GAP_DAYS]
    if len(bad):
        df = df.iloc[:bad.index[0]].reset_index(drop=True)
    return df

def load_details(t, ld):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    p = OUT / 'details' / f'{safe}__{ld}.json'
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}

EDGAR = json.load(open(OUT / 'edgar_sic.json')) if (OUT / 'edgar_sic.json').exists() else {}

def ret(a, b):
    return b / a - 1 if (a and a > 0 and b is not None and not math.isnan(b)) else None

def main():
    uni = json.load(open(OUT / 'ipo_universe.json'))

    # SPY benchmark: repo daily csv (through 2025-10) stitched with API json (2024-07 onward)
    rep = pd.read_csv('/root/spy/data/candles_daily.csv.gz')
    rep['date'] = pd.to_datetime(rep.timestamp).dt.date
    api = pd.DataFrame(json.load(open(OUT / 'spy_daily.json')))
    api['date'] = pd.to_datetime(api['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.date
    api = api.rename(columns={'o': 'open', 'c': 'close'})
    cut = api.date.min()
    spy = pd.concat([rep[rep.date < cut][['date', 'open', 'close']],
                     api[['date', 'open', 'close']]], ignore_index=True)
    spy = spy[spy.date <= T_END].reset_index(drop=True)
    spy_close = dict(zip(spy.date, spy.close))
    spy_dates = sorted(spy_close)

    def spy_at(dt):
        # close on dt or most recent prior trading day
        i = np.searchsorted(spy_dates, dt, side='right') - 1
        return spy_close[spy_dates[i]] if i >= 0 else None

    events = []
    skipped_rows = []
    skipped = {'no_usable_bars': 0}
    for r in uni:
        t, ld = r['ticker'], r['listing_date']
        ldd = date.fromisoformat(ld)
        df = None
        source = None
        for src, loader in (('local', lambda: load_local_bars(t, ldd.year)),
                            ('api', lambda: load_api_bars(t, ld)),
                            ('yahoo', lambda: load_yahoo_bars(t, ld)),
                            ('stooq', lambda: load_stooq_bars(t, ld))):
            cand = loader()
            if cand is None or not len(cand):
                continue
            cand = cand[(cand.date >= ldd) & (cand.date <= T_END)].reset_index(drop=True)
            if not len(cand):
                continue
            cand = truncate_at_gap(cand)
            if (cand.date.iloc[0] - ldd).days > 7 or len(cand) < 2:
                continue  # truncated/incomplete series (e.g. 2y API cap) -> try next source
            df, source = cand, src
            break
        if df is None:
            skipped['no_usable_bars'] += 1
            skipped_rows.append({'ticker': t, 'listing_date': ld,
                                 'exchange': r.get('primary_exchange'),
                                 'issuer': r.get('issuer_name')})
            continue

        det = load_details(t, ld)
        eg = EDGAR.get(t) or {}
        sic = det.get('sic_code') or eg.get('sic') or ''
        if not det.get('sic_description') and eg.get('sic_desc'):
            det['sic_description'] = eg['sic_desc']
        last_i = len(df) - 1
        delisted = df.date.iloc[last_i] < (T_END - timedelta(days=10))

        ev = {
            'ticker': t, 'listing_date': ld, 'source': source,
            'exchange': r.get('primary_exchange'),
            'issuer': r.get('issuer_name'), 'security_type': r.get('security_type'),
            'issue_price': r.get('final_issue_price'),
            'offer_size': r.get('total_offer_size') or (
                (r.get('max_shares_offered') or 0) * (r.get('final_issue_price') or 0) or None),
            'sic_code': sic, 'sic_desc': det.get('sic_description') or '',
            'name_now': det.get('name') or '',
            'd1_open': df.open.iloc[0], 'd1_close': df.close.iloc[0],
            'last_date': str(df.date.iloc[last_i]), 'last_close': df.close.iloc[last_i],
            'n_bars': len(df), 'delisted': delisted,
            'pop_open': ret(r.get('final_issue_price'), df.open.iloc[0]),
            'pop_close': ret(r.get('final_issue_price'), df.close.iloc[0]),
        }

        # post-IPO path relative to day-1 close (drift curve)
        for h in [5, 21, 63, 126, 252]:
            if h <= last_i and ev['d1_close']:
                ev[f'path_{h}'] = ret(ev['d1_close'], df.close.iloc[h])

        for dly in ENTRY_DELAYS:
            tag = 'e0' if dly == 0 else f'e{dly}'
            if dly >= len(df):
                continue
            entry_px = df.open.iloc[0] if dly == 0 else df.close.iloc[dly]
            entry_dt = df.date.iloc[0] if dly == 0 else df.date.iloc[dly]
            if not entry_px or entry_px <= 0:
                continue
            ev[f'{tag}_date'] = str(entry_dt)
            spy0 = spy_at(entry_dt)
            # to-date (or delisting) return
            ev[f'{tag}_ret_end'] = ret(entry_px, df.close.iloc[last_i])
            se = spy_at(df.date.iloc[last_i])
            ev[f'{tag}_spy_end'] = ret(spy0, se)
            for h in HORIZONS:
                idx = dly + h
                if idx <= last_i:
                    exit_px, exit_dt, early = df.close.iloc[idx], df.date.iloc[idx], False
                elif delisted:
                    exit_px, exit_dt, early = df.close.iloc[last_i], df.date.iloc[last_i], True
                else:
                    continue  # horizon not yet elapsed (recent IPO) -> NaN
                ev[f'{tag}_ret_{h}'] = ret(entry_px, exit_px)
                ev[f'{tag}_spy_{h}'] = ret(spy0, spy_at(exit_dt))
                if early:
                    ev[f'{tag}_early_{h}'] = True
        events.append(ev)

    df = pd.DataFrame(events)
    pd.DataFrame(skipped_rows).to_csv(OUT / 'ipo_skipped.csv', index=False)

    # ---- aggregates ----
    name_spac = df.issuer.fillna('').str.contains(r'acquisition co|acquisition holdings|blank check', case=False, regex=True)
    is_spac = df.sic_code.astype(str).str.startswith('6770') | name_spac
    df['is_spac'] = is_spac
    df.to_csv(OUT / 'ipo_events.csv', index=False)
    core = df[~is_spac].copy()

    def agg(sub, tag, h):
        rc, sc = f'{tag}_ret_{h}', f'{tag}_spy_{h}'
        s = sub[[rc, sc]].dropna()
        if not len(s):
            return None
        ex = s[rc] - s[sc]
        return {
            'n': int(len(s)),
            'mean_ret': round(float(s[rc].mean()), 4),
            'median_ret': round(float(s[rc].median()), 4),
            'mean_excess': round(float(ex.mean()), 4),
            'median_excess': round(float(ex.median()), 4),
            'win_rate': round(float((s[rc] > 0).mean()), 4),
            'beat_spy': round(float((ex > 0).mean()), 4),
            'dollar_growth': round(float((1 + s[rc]).mean()), 4),
            'spy_growth': round(float((1 + s[sc]).mean()), 4),
        }

    summary = {'universe': len(uni), 'events': len(df), 'skipped': skipped,
               'spac_blankcheck': int(is_spac.sum()), 'core_n': len(core),
               'strategies': {}}
    for dly in ENTRY_DELAYS:
        tag = 'e0' if dly == 0 else f'e{dly}'
        summary['strategies'][tag] = {str(h): agg(core, tag, h) for h in HORIZONS}
        summary['strategies'][tag]['end'] = agg(core, tag, 'end')

    # IPO pop (issue price -> day-1 open/close): why "buy at IPO price" isn't implementable
    p = core[(core.issue_price >= 1)][['pop_open', 'pop_close']].dropna()
    p = p[p.pop_open.abs() < 10]  # drop data-error outliers (bad issue prices)
    summary['pop'] = {'n': int(len(p)),
                      'mean_pop_open': round(float(p.pop_open.mean()), 4),
                      'median_pop_open': round(float(p.pop_open.median()), 4),
                      'mean_pop_close': round(float(p.pop_close.mean()), 4)}

    # cohort by listing year (day-1 open entry, 1y horizon + to-date)
    core['year'] = core.listing_date.str[:4]
    summary['cohorts'] = {}
    for y, sub in core.groupby('year'):
        summary['cohorts'][y] = {'n': int(len(sub)),
                                 '1y': agg(sub, 'e0', 252), 'end': agg(sub, 'e0', 'end')}

    # SPAC segment for reference
    summary['spac_segment'] = {'1y': agg(df[is_spac], 'e0', 252), 'end': agg(df[is_spac], 'e0', 'end')}

    # money-weighted: $1 into each IPO at its entry date, valued at T_END/delisting; same cashflows into SPY
    from scipy.optimize import brentq
    def xirr(flows):  # flows: list of (date, amount)
        t0 = flows[0][0]
        def npv(r):
            return sum(a / (1 + r) ** ((d - t0).days / 365.25) for d, a in flows)
        try:
            return brentq(npv, -0.9999, 10.0)
        except ValueError:
            return None
    def strat_xirr(frame, tag):
        sub = frame.dropna(subset=[f'{tag}_ret_end', f'{tag}_date'])
        flows, sflows = [], []
        for _, r0 in sub.iterrows():
            ed = date.fromisoformat(r0[f'{tag}_date'])
            xd = date.fromisoformat(r0['last_date'])
            flows += [(ed, -1.0), (xd, 1.0 + r0[f'{tag}_ret_end'])]
            sflows += [(ed, -1.0), (xd, 1.0 + r0[f'{tag}_spy_end'])]
        flows.sort(); sflows.sort()
        if not flows:
            return None, None
        x, sx = xirr(flows), xirr(sflows)
        return (round(x, 4) if x is not None else None,
                round(sx, 4) if sx is not None else None)
    for tag in ['e0', 'e21', 'e126']:
        summary['strategies'][tag]['xirr'], summary['strategies'][tag]['xirr_spy'] = strat_xirr(core, tag)

    # median post-IPO drift path relative to day-1 close (the "chill out" curve)
    summary['drift_vs_d1close'] = {}
    for h in [5, 21, 63, 126, 252]:
        s = core[f'path_{h}'].dropna()
        if len(s):
            summary['drift_vs_d1close'][str(h)] = {
                'n': int(len(s)), 'median': round(float(s.median()), 4),
                'mean': round(float(s.mean()), 4),
                'pct_below_d1close': round(float((s < 0).mean()), 4)}

    # ---- offer-size segmentation ----
    def size_bucket(v):
        if v is None or not v == v: return 'unknown'
        if v < 25e6: return '<$25M'
        if v < 100e6: return '$25-100M'
        if v < 500e6: return '$100-500M'
        return '>=$500M'
    core['size_bucket'] = core.offer_size.apply(size_bucket)
    summary['size_buckets'] = {}
    for b, sub in core.groupby('size_bucket'):
        summary['size_buckets'][b] = {'n': int(len(sub)),
                                      'e0_1y': agg(sub, 'e0', 252),
                                      'e0_end': agg(sub, 'e0', 'end'),
                                      'e126_1y': agg(sub, 'e126', 252)}

    # >=100M sub-study: full entry-delay table + XIRR
    big = core[core.offer_size >= 1e8]
    summary['big100m'] = {'n': int(len(big)), 'strategies': {}}
    for dly in ENTRY_DELAYS:
        tag = 'e0' if dly == 0 else f'e{dly}'
        summary['big100m']['strategies'][tag] = {str(h): agg(big, tag, h) for h in HORIZONS}
        summary['big100m']['strategies'][tag]['end'] = agg(big, tag, 'end')
    for tag in ['e0', 'e21', 'e126']:
        summary['big100m']['strategies'][tag]['xirr'], summary['big100m']['strategies'][tag]['xirr_spy'] = strat_xirr(big, tag)

    # ---- industry segmentation (SIC) ----
    def sic_sector(code):
        try:
            c = int(str(code)[:4])
        except (ValueError, TypeError):
            return 'Unknown'
        if c == 6770: return 'Blank Check (SPAC)'
        if 2833 <= c <= 2836 or c == 8731: return 'Biotech & Pharma'
        if c == 3826 or 3840 <= c <= 3851 or c == 8000 or 8010 <= c <= 8099: return 'Medical Devices & Health Svcs'
        if 7370 <= c <= 7379: return 'Software & IT Services'
        if 3670 <= c <= 3679: return 'Semis & Electronics'
        if 3711 <= c <= 3716 or c == 3751: return 'Autos & EV'
        if 6020 <= c <= 6299 or 6300 <= c <= 6499: return 'Banks, Finance & Insurance'
        if 6500 <= c <= 6599 or 6798 <= c <= 6799: return 'Real Estate & REITs'
        if 1000 <= c <= 1499: return 'Mining, Oil & Gas'
        if 2000 <= c <= 2199: return 'Food & Beverage'
        if 5200 <= c <= 5999: return 'Retail'
        if 5000 <= c <= 5199: return 'Wholesale & Distribution'
        if 4000 <= c <= 4899: return 'Transport, Telecom & Utilities'
        if 4900 <= c <= 4999: return 'Energy Utilities'
        if 7000 <= c <= 8999: return 'Other Services'
        if 2200 <= c <= 3999: return 'Other Manufacturing'
        if 100 <= c <= 999: return 'Agriculture'
        if 1500 <= c <= 1799: return 'Construction'
        return 'Unknown'

    core['sector'] = core.sic_code.apply(sic_sector)
    summary['industry'] = {}
    for sec, sub in core.groupby('sector'):
        if len(sub) < 5:
            continue
        summary['industry'][sec] = {'n': int(len(sub)),
                                    'e0_1y': agg(sub, 'e0', 252),
                                    'e0_end': agg(sub, 'e0', 'end'),
                                    'e126_1y': agg(sub, 'e126', 252)}
    # predictiveness: Kruskal-Wallis on e0 1y excess across sectors with n>=15
    from scipy.stats import kruskal
    groups = []
    for sec, sub in core.groupby('sector'):
        ex = (sub['e0_ret_252'] - sub['e0_spy_252']).dropna()
        if len(ex) >= 15 and sec != 'Unknown':
            groups.append(ex.values)
    if len(groups) >= 3:
        H, pv = kruskal(*groups)
        summary['industry_kruskal'] = {'H': round(float(H), 3), 'p': round(float(pv), 5),
                                       'groups': len(groups)}

    json.dump(summary, open(OUT / 'ipo_summary.json', 'w'), indent=1)
    print(json.dumps(summary['skipped']), 'events:', len(df), 'core:', len(core), 'spac:', int(is_spac.sum()))
    for tag in ['e0', 'e21', 'e126']:
        s = summary['strategies'][tag]
        print(tag, '1y:', s.get('252'))
        print(tag, 'xirr:', s.get('xirr'), 'vs spy', s.get('xirr_spy'))

if __name__ == '__main__':
    main()
