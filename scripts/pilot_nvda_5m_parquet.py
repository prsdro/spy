#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ENV_PATH = Path('/root/spx-chart-app/.env')
OUT = Path('/srv/market-data/massive/us_equities_pilot')
SYMBOL = 'NVDA'
START_YEAR = 1999
END_YEAR = datetime.now(timezone.utc).year


def load_key() -> str:
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith('POLYGON_API_KEY='):
            return line.split('=',1)[1].strip().strip('"')
    raise RuntimeError('POLYGON_API_KEY not found')


def get_json(url: str, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError('unreachable')


def aggs_url(key: str, multiplier: int, span: str, start: str, end: str, limit: int = 50000) -> str:
    q = urllib.parse.urlencode({
        'adjusted': 'true',
        'sort': 'asc',
        'limit': str(limit),
        'apiKey': key,
    })
    return f'https://api.massive.com/v2/aggs/ticker/{SYMBOL}/range/{multiplier}/{span}/{start}/{end}?{q}'


def fetch_aggs(key: str, multiplier: int, span: str, start: str, end: str) -> pd.DataFrame:
    rows = []
    url = aggs_url(key, multiplier, span, start, end)
    while url:
        data = get_json(url)
        if data.get('status') not in ('OK', 'DELAYED'):
            raise RuntimeError(f'Bad status {data.get("status")}: {data}')
        rows.extend(data.get('results') or [])
        url = data.get('next_url')
        if url and 'apiKey=' not in url:
            url += ('&' if '?' in url else '?') + 'apiKey=' + key
    if not rows:
        return pd.DataFrame(columns=['symbol','metric_ts_utc','metric_ts_et','open','high','low','close','volume','vwap','transactions','source','adjusted','multiplier','span'])
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        'symbol': SYMBOL,
        'metric_ts_utc': pd.to_datetime(df['t'], unit='ms', utc=True),
        'open': df['o'].astype('float64'),
        'high': df['h'].astype('float64'),
        'low': df['l'].astype('float64'),
        'close': df['c'].astype('float64'),
        'volume': df['v'].astype('float64'),
        'vwap': df.get('vw', pd.Series([None]*len(df))).astype('float64'),
        'transactions': df.get('n', pd.Series([None]*len(df))).astype('Int64'),
        'source': 'massive_rest',
        'adjusted': True,
        'multiplier': multiplier,
        'span': span,
    })
    out['metric_ts_et'] = out['metric_ts_utc'].dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d %H:%M:%S%z')
    return out


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression='zstd', compression_level=9)


def fetch_reference(key: str, kind: str) -> pd.DataFrame:
    url = f'https://api.massive.com/v3/reference/{kind}?' + urllib.parse.urlencode({'ticker': SYMBOL, 'limit': '1000', 'apiKey': key})
    rows=[]
    while url:
        data=get_json(url)
        rows.extend(data.get('results') or [])
        url=data.get('next_url')
        if url and 'apiKey=' not in url:
            url += ('&' if '?' in url else '?') + 'apiKey=' + key
    return pd.DataFrame(rows)


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def main():
    key=load_key()
    OUT.mkdir(parents=True, exist_ok=True)
    coverage=[]
    for year in range(START_YEAR, END_YEAR+1):
        start=f'{year}-01-01'; end=f'{year}-12-31'
        df=fetch_aggs(key,5,'minute',start,end)
        if not df.empty:
            path=OUT/'bars_5m_adjusted'/f'year={year}'/f'{SYMBOL}.parquet'
            write_parquet(df,path)
            coverage.append({'dataset':'bars_5m_adjusted','year':year,'symbol':SYMBOL,'rows':len(df),'first':str(df.metric_ts_utc.min()),'last':str(df.metric_ts_utc.max()),'bytes':path.stat().st_size})
            print('5m',year,len(df),path.stat().st_size)
    daily=fetch_aggs(key,1,'day',f'{START_YEAR}-01-01',f'{END_YEAR}-12-31')
    if not daily.empty:
        for year, g in daily.groupby(daily.metric_ts_utc.dt.year):
            path=OUT/'bars_1d_adjusted'/f'year={int(year)}'/f'{SYMBOL}.parquet'
            write_parquet(g,path)
            coverage.append({'dataset':'bars_1d_adjusted','year':int(year),'symbol':SYMBOL,'rows':len(g),'first':str(g.metric_ts_utc.min()),'last':str(g.metric_ts_utc.max()),'bytes':path.stat().st_size})
    (OUT/'corporate_actions').mkdir(exist_ok=True)
    for kind in ['splits','dividends']:
        ref=fetch_reference(key,kind)
        if not ref.empty:
            path=OUT/'corporate_actions'/f'{kind}.parquet'
            write_parquet(ref,path)
            coverage.append({'dataset':kind,'year':'all','symbol':SYMBOL,'rows':len(ref),'first':'','last':'','bytes':path.stat().st_size})
    cov=pd.DataFrame(coverage)
    (OUT/'manifest').mkdir(exist_ok=True)
    cov.to_csv(OUT/'manifest'/'coverage.csv', index=False)
    con=duckdb.connect(str(OUT/'duckdb_market_pilot.duckdb'))
    con.execute(f"CREATE OR REPLACE VIEW bars_5m_adjusted AS SELECT * FROM read_parquet('{OUT}/bars_5m_adjusted/year=*/*.parquet', hive_partitioning=true)")
    con.execute(f"CREATE OR REPLACE VIEW bars_1d_adjusted AS SELECT * FROM read_parquet('{OUT}/bars_1d_adjusted/year=*/*.parquet', hive_partitioning=true)")
    summary={
        'symbol': SYMBOL,
        'total_bytes': dir_size(OUT),
        'coverage_rows': coverage,
        'duckdb_5m': con.execute("select count(*) as row_count, min(metric_ts_utc) as first_ts, max(metric_ts_utc) as last_ts from bars_5m_adjusted").fetchdf().to_dict('records')[0],
        'duckdb_1d': con.execute("select count(*) as row_count, min(metric_ts_utc) as first_ts, max(metric_ts_utc) as last_ts from bars_1d_adjusted").fetchdf().to_dict('records')[0],
        'atr_sample': con.execute("""
            WITH d AS (
              SELECT metric_ts_utc::DATE d, high, low, close,
                     lag(close) OVER (ORDER BY metric_ts_utc) prev_close
              FROM bars_1d_adjusted
            ), tr AS (
              SELECT d, high, low, close, greatest(high-low, abs(high-prev_close), abs(low-prev_close)) true_range
              FROM d
            )
            SELECT * FROM tr ORDER BY d DESC LIMIT 5
        """).fetchdf().astype(str).to_dict('records')
    }
    (OUT/'manifest'/'pilot_summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))

if __name__ == '__main__':
    main()
