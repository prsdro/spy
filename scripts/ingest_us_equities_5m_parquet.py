#!/usr/bin/env python3
from __future__ import annotations
import csv, gc, json, os, random, re, signal, sys, time, urllib.error, urllib.parse, urllib.request
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ENV_PATH = Path('/root/spx-chart-app/.env')
ROOT = Path('/srv/market-data/massive/us_equities')
UNIVERSE = ROOT / 'manifest' / 'universe.csv'
SOFT_BYTES = int(os.environ.get('SOFT_BYTES', str(140 * 1024**3)))
HARD_BYTES = int(os.environ.get('HARD_BYTES', str(160 * 1024**3)))
START_YEAR = int(os.environ.get('START_YEAR', '2003'))
END_YEAR = int(os.environ.get('END_YEAR', str(datetime.now(timezone.utc).year)))
MAX_SYMBOLS = int(os.environ.get('MAX_SYMBOLS','0') or '0')
RESUME_AFTER = os.environ.get('RESUME_AFTER','').strip()
START_AT_SYMBOL = os.environ.get('START_AT_SYMBOL','').strip()
WORKER_ID = (os.environ.get('WORKER_ID','single').strip() or 'single')
RANGE_START_INDEX = int(os.environ.get('RANGE_START_INDEX','0') or '0')
RANGE_END_INDEX = int(os.environ.get('RANGE_END_INDEX','0') or '0')  # exclusive; 0 means end of universe
SLEEP_BETWEEN_CALLS = float(os.environ.get('SLEEP_BETWEEN_CALLS','0.2'))
IS_PARALLEL = WORKER_ID not in ('', 'single')
STATUS = ROOT / 'manifest' / (f'status_{WORKER_ID}.json' if IS_PARALLEL else 'status.json')
COVERAGE = ROOT / 'manifest' / (f'coverage_{WORKER_ID}.csv' if IS_PARALLEL else 'coverage.csv')
RUNLOG = ROOT / 'manifest' / (f'ingestion_runs_{WORKER_ID}.jsonl' if IS_PARALLEL else 'ingestion_runs.jsonl')
LOCK = ROOT / (f'ingest_{WORKER_ID}.lock' if IS_PARALLEL else 'ingest.lock')
STOP = False

def on_signal(signum, frame):
    global STOP
    STOP = True
signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def load_key():
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith('POLYGON_API_KEY='):
            return line.split('=',1)[1].strip().strip('"')
    raise RuntimeError('POLYGON_API_KEY not found')

def retry_sleep(attempt: int, base: float = 2.0, cap: float = 180.0) -> float:
    return min(cap, base * (2 ** attempt)) + random.uniform(0.0, 3.0)

def get_json(url, retries=10):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'milkify-market-ingest/1.0'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            code = getattr(e, 'code', None)
            retryable = code == 429 or (code is not None and 500 <= code < 600)
            if not retryable:
                raise
            retry_after = None
            try:
                retry_after = e.headers.get('Retry-After')
            except Exception:
                pass
            try:
                sleep_for = float(retry_after) if retry_after else retry_sleep(attempt, base=10.0, cap=300.0)
            except Exception:
                sleep_for = retry_sleep(attempt, base=10.0, cap=300.0)
            print(json.dumps({'event':'api_retry','worker_id':WORKER_ID,'http_status':code,'attempt':attempt+1,'sleep_seconds':round(sleep_for,1),'ts_utc':utcnow()}), flush=True)
            time.sleep(sleep_for)
        except Exception as e:
            last = e
            sleep_for = retry_sleep(attempt, base=2.0, cap=120.0)
            print(json.dumps({'event':'api_retry','worker_id':WORKER_ID,'error_type':type(e).__name__,'attempt':attempt+1,'sleep_seconds':round(sleep_for,1),'ts_utc':utcnow()}), flush=True)
            time.sleep(sleep_for)
    raise last

def paged(url, key):
    while url:
        data = get_json(url)
        yield data
        url = data.get('next_url')
        if url and 'apiKey=' not in url:
            url += ('&' if '?' in url else '?') + 'apiKey=' + key
        time.sleep(SLEEP_BETWEEN_CALLS + random.uniform(0, 0.15))

def safe_symbol(s):
    return re.sub(r'[^A-Za-z0-9._-]+','_',s)

def dir_size(path):
    total=0
    if not path.exists(): return 0
    for p in path.rglob('*'):
        if p.is_file(): total += p.stat().st_size
    return total

def write_status(**kw):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    base = {}
    if STATUS.exists():
        try: base = json.loads(STATUS.read_text())
        except Exception: base = {}
    base.update(kw)
    base['worker_id'] = WORKER_ID
    base['updated_at_utc'] = utcnow()
    tmp = STATUS.with_suffix(f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(base, indent=2, default=str))
    tmp.replace(STATUS)

def append_run(event):
    RUNLOG.parent.mkdir(parents=True, exist_ok=True)
    event['worker_id'] = WORKER_ID
    event['ts_utc'] = utcnow()
    with RUNLOG.open('a') as f:
        f.write(json.dumps(event, default=str)+'\n')

def write_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    tmp = path.with_suffix(f'.{os.getpid()}.tmp.parquet')
    pq.write_table(table, tmp, compression='zstd', compression_level=9)
    tmp.replace(path)

def fetch_tickers(key, exchange='XNAS'):
    params=dict(market='stocks',active='true',type='CS',exchange=exchange,limit='1000',apiKey=key)
    url='https://api.massive.com/v3/reference/tickers?'+urllib.parse.urlencode(params)
    rows=[]
    for data in paged(url,key): rows.extend(data.get('results') or [])
    return rows

def fetch_sp500_wikipedia():
    # Wikipedia blocks pandas' default user-agent from this server; fetch HTML ourselves.
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 milkify-market-ingest/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode('utf-8', errors='ignore')
    tables = pd.read_html(StringIO(html))
    df = tables[0]
    return [{'ticker': str(x).replace('.','-'), 'name': ''} for x in df['Symbol'].tolist()]

def build_universe(key):
    if UNIVERSE.exists():
        with UNIVERSE.open() as f: return list(csv.DictReader(f))
    nas = fetch_tickers(key,'XNAS')
    sp = fetch_sp500_wikipedia()
    m = {}
    for r in nas:
        t = r['ticker']; m.setdefault(t, {'symbol':t,'name':r.get('name',''),'in_nasdaq':'0','in_sp500':'0'}); m[t]['in_nasdaq']='1'; m[t]['name']=r.get('name','') or m[t]['name']
    for r in sp:
        t = r['ticker']; m.setdefault(t, {'symbol':t,'name':r.get('name',''),'in_nasdaq':'0','in_sp500':'0'}); m[t]['in_sp500']='1'
    rows = sorted(m.values(), key=lambda x:x['symbol'])
    UNIVERSE.parent.mkdir(parents=True, exist_ok=True)
    with UNIVERSE.open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=['symbol','name','in_nasdaq','in_sp500']); w.writeheader(); w.writerows(rows)
    return rows

def fetch_aggs(key, symbol, mult, span, start, end):
    q=urllib.parse.urlencode({'adjusted':'true','sort':'asc','limit':'50000','apiKey':key})
    url=f'https://api.massive.com/v2/aggs/ticker/{urllib.parse.quote(symbol)}/range/{mult}/{span}/{start}/{end}?{q}'
    rows=[]
    for data in paged(url,key):
        status=data.get('status')
        if status not in ('OK','DELAYED'):
            raise RuntimeError(f'{symbol} bad status {status}: {data}')
        rows.extend(data.get('results') or [])
    if not rows: return pd.DataFrame()
    df=pd.DataFrame(rows)
    out=pd.DataFrame({
      'symbol': symbol,
      'metric_ts_utc': pd.to_datetime(df['t'], unit='ms', utc=True),
      'metric_ts_et': pd.to_datetime(df['t'], unit='ms', utc=True).dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d %H:%M:%S%z'),
      'open': df['o'].astype('float64'), 'high': df['h'].astype('float64'), 'low': df['l'].astype('float64'), 'close': df['c'].astype('float64'),
      'volume': df['v'].astype('float64'), 'vwap': df.get('vw', pd.Series([None]*len(df))).astype('float64'),
      'transactions': df.get('n', pd.Series([None]*len(df))).astype('Int64'),
      'source':'massive_rest', 'adjusted':True, 'multiplier':mult, 'span':span,
    })
    del df
    return out

def fetch_ref(key, symbol, kind):
    url=f'https://api.massive.com/v3/reference/{kind}?'+urllib.parse.urlencode({'ticker':symbol,'limit':'1000','apiKey':key})
    rows=[]
    for data in paged(url,key): rows.extend(data.get('results') or [])
    return pd.DataFrame(rows)

def coverage_append(row):
    exists=COVERAGE.exists()
    COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    with COVERAGE.open('a', newline='') as f:
        fields=['dataset','year','symbol','rows','first','last','bytes','status','error']
        w=csv.DictWriter(f, fieldnames=fields)
        if not exists: w.writeheader()
        w.writerow({k:row.get(k,'') for k in fields})

def already_done(path):
    return path.exists() and path.stat().st_size > 0

def clamp(v, lo, hi):
    return max(lo, min(v, hi))

def main():
    if LOCK.exists():
        try:
            oldpid = int(LOCK.read_text().strip())
        except Exception:
            oldpid = 0
        if oldpid and Path(f'/proc/{oldpid}').exists():
            raise SystemExit(f'Live lock exists for {WORKER_ID}: {LOCK} pid={oldpid}')
        LOCK.unlink(missing_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    key=load_key(); started=datetime.now(timezone.utc)
    try:
        all_universe=build_universe(key)
        total_symbols=len(all_universe)
        range_start=clamp(RANGE_START_INDEX, 0, total_symbols)
        range_end=RANGE_END_INDEX if RANGE_END_INDEX > 0 else total_symbols
        range_end=clamp(range_end, range_start, total_symbols)
        start_offset=range_start
        if START_AT_SYMBOL:
            positions=[i for i,r in enumerate(all_universe) if r['symbol']==START_AT_SYMBOL]
            if not positions: raise RuntimeError(f'START_AT_SYMBOL not found in universe: {START_AT_SYMBOL}')
            start_offset=clamp(positions[0], range_start, range_end)
        elif RESUME_AFTER:
            positions=[i for i,r in enumerate(all_universe) if r['symbol']==RESUME_AFTER]
            if not positions: raise RuntimeError(f'RESUME_AFTER not found in universe: {RESUME_AFTER}')
            start_offset=clamp(positions[0]+1, range_start, range_end)
        if MAX_SYMBOLS:
            range_end=min(range_end, start_offset + MAX_SYMBOLS)
        universe=all_universe[start_offset:range_end]
        completed=start_offset; failures=0
        range_total=max(0, range_end-range_start)
        if not universe and start_offset >= range_end:
            write_status(state='complete', pid=os.getpid(), total_symbols=total_symbols, range_start_index=range_start, range_end_index=range_end, range_total=range_total, remaining_symbols=0, completed_symbols=range_end, range_completed_symbols=range_total, current_symbol='', resume_after=RESUME_AFTER, start_at_symbol=START_AT_SYMBOL, started_at_utc=started.isoformat(), finished_at_utc=utcnow(), dataset_bytes=dir_size(ROOT), soft_limit_bytes=SOFT_BYTES, hard_limit_bytes=HARD_BYTES)
            append_run({'event':'complete_already','symbols':total_symbols,'range_start_index':range_start,'range_end_index':range_end})
            return
        write_status(state='running', pid=os.getpid(), total_symbols=total_symbols, range_start_index=range_start, range_end_index=range_end, range_total=range_total, remaining_symbols=len(universe), completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), current_symbol='', resume_after=RESUME_AFTER, start_at_symbol=START_AT_SYMBOL, started_at_utc=started.isoformat(), dataset_bytes=dir_size(ROOT), soft_limit_bytes=SOFT_BYTES, hard_limit_bytes=HARD_BYTES)
        append_run({'event':'start','symbols':total_symbols,'remaining_symbols':len(universe),'range_start_index':range_start,'range_end_index':range_end,'start_offset':start_offset,'resume_after':RESUME_AFTER,'start_at_symbol':START_AT_SYMBOL,'sleep_between_calls':SLEEP_BETWEEN_CALLS})
        for idx, rec in enumerate(universe, start=start_offset+1):
            if STOP: break
            symbol=rec['symbol']; ss=safe_symbol(symbol)
            write_status(current_symbol=symbol, symbol_index=idx, current_stage='symbol_start', current_year='', completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), failures=failures, dataset_bytes=dir_size(ROOT))
            if dir_size(ROOT) > HARD_BYTES:
                write_status(state='stopped_hard_disk_limit', current_symbol=symbol, dataset_bytes=dir_size(ROOT)); break
            try:
                for year in range(START_YEAR, END_YEAR+1):
                    if STOP: break
                    write_status(current_symbol=symbol, symbol_index=idx, current_stage='bars_5m_adjusted', current_year=year, completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), failures=failures, dataset_bytes=dir_size(ROOT))
                    p=ROOT/'bars_5m_adjusted'/f'year={year}'/f'{ss}.parquet'
                    if not already_done(p):
                        df=fetch_aggs(key,symbol,5,'minute',f'{year}-01-01',f'{year}-12-31')
                        try:
                            if not df.empty:
                                write_parquet(df,p)
                                coverage_append({'dataset':'bars_5m_adjusted','year':year,'symbol':symbol,'rows':len(df),'first':str(df.metric_ts_utc.min()),'last':str(df.metric_ts_utc.max()),'bytes':p.stat().st_size,'status':'ok'})
                        finally:
                            del df
                            gc.collect()
                    if dir_size(ROOT) > SOFT_BYTES:
                        write_status(state='stopped_soft_disk_limit', current_symbol=symbol, dataset_bytes=dir_size(ROOT)); append_run({'event':'soft_limit'}); return
                if STOP: break
                write_status(current_symbol=symbol, symbol_index=idx, current_stage='daily_and_corporate_actions', current_year='', completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), failures=failures, dataset_bytes=dir_size(ROOT))
                ddir=ROOT/'bars_1d_adjusted'
                ddir.mkdir(parents=True, exist_ok=True)
                if not (ddir/f'_DONE_{ss}').exists():
                    daily=fetch_aggs(key,symbol,1,'day',f'{START_YEAR}-01-01',f'{END_YEAR}-12-31')
                    try:
                        if not daily.empty:
                            for year,g in daily.groupby(daily.metric_ts_utc.dt.year):
                                p=ddir/f'year={int(year)}'/f'{ss}.parquet'; write_parquet(g,p)
                                coverage_append({'dataset':'bars_1d_adjusted','year':int(year),'symbol':symbol,'rows':len(g),'first':str(g.metric_ts_utc.min()),'last':str(g.metric_ts_utc.max()),'bytes':p.stat().st_size,'status':'ok'})
                        (ddir/f'_DONE_{ss}').write_text(utcnow())
                    finally:
                        del daily
                        gc.collect()
                for kind in ['splits','dividends']:
                    p=ROOT/'corporate_actions'/kind/f'{ss}.parquet'
                    if not already_done(p):
                        ref=fetch_ref(key,symbol,kind)
                        try:
                            if not ref.empty:
                                write_parquet(ref,p)
                                coverage_append({'dataset':kind,'year':'all','symbol':symbol,'rows':len(ref),'bytes':p.stat().st_size,'status':'ok'})
                        finally:
                            del ref
                            gc.collect()
                completed += 1
                write_status(completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), current_symbol=symbol, last_completed_symbol=symbol, last_processed_symbol=symbol, current_stage='symbol_complete', current_year='', failures=failures, dataset_bytes=dir_size(ROOT))
            except Exception as e:
                failures += 1
                completed += 1
                append_run({'event':'symbol_error','symbol':symbol,'error':repr(e)})
                coverage_append({'dataset':'symbol','year':'all','symbol':symbol,'rows':0,'status':'error','error':repr(e)[:500]})
                write_status(completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), current_symbol=symbol, last_processed_symbol=symbol, current_stage='symbol_error', current_year='', failures=failures, last_error_symbol=symbol, last_error=repr(e), dataset_bytes=dir_size(ROOT))
                gc.collect()
        state='stopped_signal' if STOP else 'complete'
        write_status(state=state, completed_symbols=completed, range_completed_symbols=max(0, completed-range_start), failures=failures, dataset_bytes=dir_size(ROOT), finished_at_utc=utcnow())
        append_run({'event':state,'completed':completed,'range_completed_symbols':max(0, completed-range_start),'failures':failures})
    finally:
        try: LOCK.unlink()
        except FileNotFoundError: pass

if __name__ == '__main__': main()
