#!/usr/bin/env python3
"""Top up /srv/ftp/ossicones/stock-data through today (store ended 2026-05-07).

Strategy: refetch the FULL year=2026 partition per ticker per feed (5m + 1d),
atomic replace — idempotent, no merge edge cases. Tickers that SPLIT since
2026-05-01 get their entire history refetched (adjusted basis changed).
Resumable via done-list json. Rate: ~0.15s spacing, 429-backoff.
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

# NB: /srv/ftp/ossicones/stock-data is a READ-ONLY bind mount of this path
ROOT = Path('/srv/market-data/massive/us_equities')
STATE = ROOT / 'logs' / 'topup_2026_done.json'
LOG = ROOT / 'logs' / 'topup_2026.log'
TODAY = date.today().isoformat()
KEY = None
for line in open('/root/spx-chart-app/.env'):
    if line.startswith('POLYGON_API_KEY='):
        KEY = line.strip().split('=', 1)[1]
_last = [0.0]


def log(m):
    line = f"{pd.Timestamp.utcnow().isoformat(timespec='seconds')} {m}"
    print(line, flush=True)
    with LOG.open('a') as f:
        f.write(line + '\n')


def get(url):
    for attempt in range(8):
        w = _last[0] + 0.15 - time.time()
        if w > 0:
            time.sleep(w)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(30)
                continue
            if e.code >= 500:
                time.sleep(15)
                continue
            raise
        except Exception:
            time.sleep(10)
    raise RuntimeError(f'giving up: {url}')


def fetch_aggs(symbol, mult, span, start, end):
    q = urllib.parse.urlencode({'adjusted': 'true', 'sort': 'asc',
                                'limit': '50000', 'apiKey': KEY})
    url = (f'https://api.massive.com/v2/aggs/ticker/{urllib.parse.quote(symbol)}'
           f'/range/{mult}/{span}/{start}/{end}?{q}')
    rows = []
    while url:
        d = get(url)
        if d.get('status') not in ('OK', 'DELAYED'):
            raise RuntimeError(f'{symbol} status {d.get("status")}')
        rows.extend(d.get('results') or [])
        url = d.get('next_url')
        if url:
            url += f'&apiKey={KEY}'
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        'symbol': symbol,
        'metric_ts_utc': pd.to_datetime(df['t'], unit='ms', utc=True),
        'metric_ts_et': pd.to_datetime(df['t'], unit='ms', utc=True)
            .dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d %H:%M:%S%z'),
        'open': df['o'].astype('float64'), 'high': df['h'].astype('float64'),
        'low': df['l'].astype('float64'), 'close': df['c'].astype('float64'),
        'volume': df['v'].astype('float64'),
        'vwap': df.get('vw', pd.Series([None] * len(df))).astype('float64'),
        'transactions': df.get('n', pd.Series([None] * len(df))).astype('Int64'),
        'source': 'massive_rest', 'adjusted': True, 'multiplier': mult, 'span': span,
    })


def write_year(feed, mult, span, symbol, year):
    out = ROOT / feed / f'year={year}' / f'{symbol}.parquet'
    df = fetch_aggs(symbol, mult, span, f'{year}-01-01',
                    min(f'{year}-12-31', TODAY))
    if df.empty:
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.tmp.parquet')
    df.to_parquet(tmp, index=False)
    tmp.replace(out)
    return len(df)


def main():
    done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    tickers = sorted(p.stem for p in (ROOT / 'bars_5m_adjusted' / 'year=2026').glob('*.parquet'))
    log(f'=== topup start: {len(tickers)} tickers, {len(done)} already done ===')

    # splits since May: vendor-refetch recent years; MANUALLY re-adjust old
    # years (API 403s history beyond ~2yr even on the paid plan)
    url = ('https://api.massive.com/v3/reference/splits?' + urllib.parse.urlencode(
        {'execution_date.gte': '2026-05-01', 'limit': '1000', 'apiKey': KEY}))
    ratios = {}
    while url:
        d = get(url)
        for r in d.get('results') or []:
            ratios[r['ticker']] = ratios.get(r['ticker'], 1.0) * (
                float(r['split_to']) / float(r['split_from']))
        url = d.get('next_url')
        if url:
            url += f'&apiKey={KEY}'
    split_tickers = set(ratios) & set(tickers)
    log(f'tickers with splits since 2026-05-01: {sorted(split_tickers)}')

    ADJ = ROOT / 'logs' / 'topup_2026_adjusted.json'
    adjusted = set(json.loads(ADJ.read_text())) if ADJ.exists() else set()

    def manual_adjust(sym, ratio):
        """Apply new split ratio to pre-2025 parquet files (all rows predate
        the split). Vendor would divide prices by ratio, multiply volume."""
        nfiles = 0
        for feed in ['bars_5m_adjusted', 'bars_1d_adjusted']:
            for yr in range(2003, 2025):
                p = ROOT / feed / f'year={yr}' / f'{sym}.parquet'
                if not p.exists():
                    continue
                df = pd.read_parquet(p)
                for col in ['open', 'high', 'low', 'close', 'vwap']:
                    df[col] = df[col] / ratio
                df['volume'] = df['volume'] * ratio
                tmp = p.with_suffix('.tmp.parquet')
                df.to_parquet(tmp, index=False)
                tmp.replace(p)
                nfiles += 1
        return nfiles

    for i, sym in enumerate(tickers):
        if sym in done:
            continue
        try:
            n5 = nd = 0
            if sym in split_tickers:
                if sym not in adjusted:
                    nf = manual_adjust(sym, ratios[sym])
                    adjusted.add(sym)
                    ADJ.write_text(json.dumps(sorted(adjusted)))
                    log(f'{sym}: manually re-adjusted {nf} pre-2025 files '
                        f'(ratio {ratios[sym]})')
                years = [2025, 2026]
            else:
                years = [2026]
            for yr in years:
                n5 += write_year('bars_5m_adjusted', 5, 'minute', sym, yr)
                nd += write_year('bars_1d_adjusted', 1, 'day', sym, yr)
            done.add(sym)
            if len(done) % 25 == 0 or sym in split_tickers:
                STATE.write_text(json.dumps(sorted(done)))
                log(f'{len(done)}/{len(tickers)} done ({sym}: {n5} 5m rows, {nd} d rows'
                    f'{" FULL-REFETCH" if sym in split_tickers else ""})')
        except Exception as e:
            log(f'ERROR {sym}: {e}')
    STATE.write_text(json.dumps(sorted(done)))
    log('=== topup COMPLETE ===')


if __name__ == '__main__':
    main()
