#!/usr/bin/env python3
"""Indices run prep: build underlying_5m_topup_idx.parquet for PO_TICKERS=SPY,QQQ,SPX.

SPY/QQQ: real 5m ETH bars from Massive, 2024-01-01 -> 2026-07-06 (no local
parquet exists for ETFs; the whole history goes through the topup path).
SPX: synthetic 5m tape = SPY 5m x daily ratio, where
ratio(d) = I:SPX official daily close / SPY last RTH 5m-bar close on d.
By construction the synthetic RTH-resampled daily close equals the real SPX
close exactly -> SPXW cash settlement in the backtest is exact. Intraday box
geometry is SPY's (the tradable ETH proxy; SPX itself has no ETH tape).
Known wart: the ratio steps at day boundaries (~5bps, ~30bps on SPY ex-div
days 4x/yr) so multi-day box edges carry that noise.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = 'https://api.massive.com'
OUT = Path('/root/spy/analyst/po_comp_options/underlying_5m_topup_idx.parquet')
START, END = '2024-01-01', '2026-07-06'

KEY = None
for line in open('/root/spx-chart-app/.env'):
    if line.startswith('POLYGON_API_KEY='):
        KEY = line.strip().split('=', 1)[1]
assert KEY


def get(url, params=None):
    for attempt in range(20):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(65)
            continue
        if r.status_code >= 500:
            time.sleep(20)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f'giving up on {url}')


def fetch_aggs(ticker, mult, span, start, end):
    rows = []
    url = f'{BASE}/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{start}/{end}'
    params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': KEY}
    while url:
        d = get(url, params)
        rows.extend(d.get('results') or [])
        url = d.get('next_url')
        params = {'apiKey': KEY} if url else None
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    df['ts'] = pd.to_datetime(df['t'], unit='ms', utc=True)
    if 'v' not in df.columns:   # index aggs (I:SPX) carry no volume
        df['v'] = 0.0
    return df[['ts', 'o', 'h', 'l', 'c', 'v']].rename(
        columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})


def main():
    frames = []
    for tkr in ['SPY', 'QQQ']:
        df = fetch_aggs(tkr, 5, 'minute', START, END)
        df['ticker'] = tkr
        frames.append(df)
        print(f'{tkr}: {len(df)} 5m bars {df.ts.min()} -> {df.ts.max()}', flush=True)

    spy = frames[0]
    spx_d = fetch_aggs('I:SPX', 1, 'day', START, END)
    spx_close = spx_d.set_index(spx_d['ts'].dt.tz_convert('America/New_York').dt.date)['close']
    print(f'I:SPX daily: {len(spx_close)} rows', flush=True)

    et = spy['ts'].dt.tz_convert('America/New_York')
    spy_et = spy.assign(et_date=et.dt.date, et_time=et.dt.time)
    rth = spy_et[(spy_et.et_time >= pd.Timestamp('09:30').time())
                 & (spy_et.et_time <= pd.Timestamp('15:55').time())]
    spy_rth_close = rth.groupby('et_date')['close'].last()

    ratio = (spx_close / spy_rth_close).dropna()
    print(f'ratio: {len(ratio)} days, {ratio.min():.4f} .. {ratio.max():.4f}', flush=True)

    r = spy_et['et_date'].map(ratio)
    # SPY dates with no SPX print (should be ~none): forward-fill by date order
    if r.isna().any():
        rf = ratio.reindex(sorted(spy_et['et_date'].unique())).ffill()
        r = spy_et['et_date'].map(rf)
        print(f'ffilled ratio for {spy_et.loc[r.isna(), "et_date"].nunique()} residual days', flush=True)
    spx = spy[['ts']].copy()
    for col in ['open', 'high', 'low', 'close']:
        spx[col] = spy[col] * r.values
    spx['volume'] = 0.0
    spx['ticker'] = 'SPX'
    spx = spx.dropna(subset=['close'])
    print(f'SPX synthetic: {len(spx)} bars', flush=True)

    out = pd.concat(frames + [spx], ignore_index=True)[
        ['ticker', 'ts', 'open', 'high', 'low', 'close', 'volume']]
    out.to_parquet(OUT)
    print(f'wrote {OUT} ({len(out)} rows)', flush=True)


if __name__ == '__main__':
    main()
