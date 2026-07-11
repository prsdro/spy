#!/usr/bin/env python3
"""20-year signal validation: ETH Bilbo-box intraday breaks, underlying
follow-through (no options). 8 study tickers, full local parquet history
(2003->2026). Per era-bucket: directional move to W1 Friday close (% and
dATR units), MFE/MAE, box-stop rate. Question: is 2024-26 typical?"""
import glob
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from fetch_po_comp_options import next_friday
from indicators import compute_phase_oscillator, atr

ROOT = Path('/srv/market-data/massive/us_equities/bars_5m_adjusted')
OUT = Path('/root/spy/analyst/po_comp_options')
TICKERS = ['AMZN', 'NVDA', 'MSFT', 'AAPL', 'META', 'GOOGL', 'TSLA', 'AMD']


def load_full_5m(tkr):
    frames = []
    for p in sorted(glob.glob(str(ROOT / 'year=*' / f'{tkr}.parquet'))):
        frames.append(pd.read_parquet(p, columns=['metric_ts_et', 'open', 'high',
                                                  'low', 'close']))
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(df['metric_ts_et'], utc=True).dt.tz_convert('America/New_York')
    return df.drop_duplicates('ts').sort_values('ts').set_index('ts')


rows = []
for tkr in TICKERS:
    df5 = load_full_5m(tkr)
    eth5 = df5.between_time('04:00', '19:55')
    h = eth5.resample('60min').agg(open=('open', 'first'), high=('high', 'max'),
                                   low=('low', 'min'), close=('close', 'last')).dropna()
    h = compute_phase_oscillator(h)
    rth = df5.between_time('09:30', '15:55')
    dly = rth.resample('1D').agg(open=('open', 'first'), high=('high', 'max'),
                                 low=('low', 'min'), close=('close', 'last')).dropna()
    dly['datr'] = atr(dly, 14)
    datr_prior = dly['datr'].shift(1)
    dclose = dly['close']
    m5t = eth5.index.as_unit('ns').asi8 // 10**6
    m5hi = eth5['high'].to_numpy(float)
    m5lo = eth5['low'].to_numpy(float)
    m5cl = eth5['close'].to_numpy(float)

    comp = h['po_compression'].to_numpy()
    starts = np.where((comp == 1) & (np.roll(comp, 1) != 1))[0]
    for i in starts[1:]:
        k = 0
        while i + k < len(h) and k < 5 and comp[i + k] == 1:
            k += 1
        if k == 0 or i + k >= len(h):
            continue
        five = h.iloc[i:i + k]
        box_hi, box_lo = five['high'].max(), five['low'].min()
        start_ts = h.index[i]
        dkey = pd.Timestamp(start_ts.date(), tz='America/New_York')
        dsub = datr_prior[datr_prior.index <= dkey]
        if not len(dsub) or pd.isna(dsub.iloc[-1]):
            continue
        datr = float(dsub.iloc[-1])
        comp_ms = int((h.index[i + k - 1] + pd.Timedelta(minutes=60)).timestamp() * 1000)
        sel = (m5t >= comp_ms) & (m5t <= comp_ms + 10 * 86400_000)
        idx = np.where(sel & ((m5hi > box_hi) | (m5lo < box_lo)))[0]
        if not len(idx):
            continue
        b = idx[0]
        up, dn = m5hi[b] > box_hi, m5lo[b] < box_lo
        mid = (box_hi + box_lo) / 2
        dirn = (1 if m5cl[b] >= mid else -1) if (up and dn) else (1 if up else -1)
        bts = pd.Timestamp(int(m5t[b]), unit='ms', tz='America/New_York')
        overnight = bts.hour < 9 or bts.hour >= 16 or (bts.hour == 9 and bts.minute < 30)
        if overnight:
            continue  # study rule: intraday breaks only
        entry = float(m5cl[b])
        w1 = next_friday(bts.date())
        fsub = dclose[dclose.index.date <= w1]
        if not len(fsub) or fsub.index[-1].date() < bts.date():
            continue
        fclose = float(fsub.iloc[-1])
        # MFE/MAE to W1 within 5m data
        wsel = (m5t > m5t[b]) & (m5t <= int(pd.Timestamp(
            f'{w1} 16:00', tz='America/New_York').timestamp() * 1000))
        if wsel.any():
            mfe = (m5hi[wsel].max() - entry) if dirn == 1 else (entry - m5lo[wsel].min())
            mae = (entry - m5lo[wsel].min()) if dirn == 1 else (m5hi[wsel].max() - entry)
        else:
            mfe = mae = np.nan
        rows.append({
            'ticker': tkr, 'ts': str(bts), 'year': bts.year, 'dir': dirn,
            'n_box_bars': k, 'box_h_atr': (box_hi - box_lo) / datr,
            'move_pct': dirn * (fclose - entry) / entry * 100,
            'move_atr': dirn * (fclose - entry) / datr,
            'mfe_atr': mfe / datr, 'mae_atr': mae / datr,
        })
    print(f"{tkr}: cumulative events {len(rows)}", flush=True)

ev = pd.DataFrame(rows)
ev.to_csv(OUT / 'validation_20yr_events.csv', index=False)
ev['era'] = pd.cut(ev.year, bins=[2003, 2007, 2010, 2013, 2016, 2019, 2022, 2024, 2027],
                   labels=['04-07', '08-10', '11-13', '14-16', '17-19', '20-22',
                           '23-24', '25-26'], right=True)
def stats(g):
    n = len(g)
    t = g.move_atr.mean() / (g.move_atr.std(ddof=1) / np.sqrt(n)) if n > 4 else np.nan
    return pd.Series({'n': n, 'move_atr': round(g.move_atr.mean(), 3),
                      't': round(t, 2), 'win': round((g.move_atr > 0).mean(), 3),
                      'mfe_atr': round(g.mfe_atr.median(), 2),
                      'mae_atr': round(g.mae_atr.median(), 2)})
by_era = ev.groupby('era', observed=True).apply(stats, include_groups=False)
print("\n=== directional follow-through to W1 Friday, by era ===")
print(by_era.to_string())
by_dir = ev.groupby(['era', 'dir'], observed=True).apply(stats, include_groups=False)
print("\n=== by era x direction ===")
print(by_dir.to_string())
res = {'by_era': by_era.reset_index().to_dict('records')}
(OUT / 'validation_20yr_summary.json').write_text(json.dumps(res, indent=1, default=str))
print("\nsaved validation_20yr_events.csv / validation_20yr_summary.json")
