import json, time, re, urllib.parse, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

key = [l.split('=',1)[1].strip().strip('"') for l in Path('/root/spx-chart-app/.env').read_text().splitlines() if l.startswith('POLYGON_API_KEY=')][0]
OUT = Path('/root/spy/analyst/ipo_study')
BARS = OUT / 'bars'; BARS.mkdir(exist_ok=True)
DETAILS = OUT / 'details'; DETAILS.mkdir(exist_ok=True)

rows = json.load(open(OUT / 'ipo_calendar_raw.json'))
uni = [r for r in rows
       if r.get('security_type') in ('CS', 'ADRC')
       and r.get('primary_exchange') in ('XNAS', 'XNYS', 'XASE')
       and r.get('listing_date') and '2021-07-01' <= r['listing_date'] <= '2026-06-30']
# dedupe ticker+listing_date
seen = set(); uni2 = []
for r in uni:
    k = (r['ticker'], r['listing_date'])
    if k not in seen: seen.add(k); uni2.append(r)
uni = uni2
print('universe', len(uni))
json.dump(uni, open(OUT / 'ipo_universe.json', 'w'), indent=1)

def get_json(url):
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429: time.sleep(3 * (attempt + 1)); continue
            if e.code == 404: return None
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            last = e; time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'failed {url[:100]}: {last}')

def fetch_one(r):
    t, ld = r['ticker'], r['listing_date']
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    bar_f = BARS / f'{safe}__{ld}.json'
    det_f = DETAILS / f'{safe}__{ld}.json'
    try:
        if not bar_f.exists():
            q = urllib.parse.urlencode({'adjusted': 'true', 'sort': 'asc', 'limit': '50000', 'apiKey': key})
            url = f'https://api.massive.com/v2/aggs/ticker/{urllib.parse.quote(t)}/range/1/day/{ld}/2026-07-01?{q}'
            data = get_json(url)
            res = (data or {}).get('results') or []
            bar_f.write_text(json.dumps(res))
        if not det_f.exists():
            url = f'https://api.massive.com/v3/reference/tickers/{urllib.parse.quote(t)}?date={ld}&apiKey={key}'
            data = get_json(url)
            det = (data or {}).get('results') or {}
            if not det:  # retry without date (delisted lookups sometimes need it)
                data = get_json(f'https://api.massive.com/v3/reference/tickers/{urllib.parse.quote(t)}?apiKey={key}')
                det = (data or {}).get('results') or {}
            det_f.write_text(json.dumps(det))
        return 'ok'
    except Exception as e:
        return f'ERR {t} {e}'

with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(fetch_one, uni))
errs = [x for x in results if x != 'ok']
print('done, errors:', len(errs))
for e in errs[:20]: print(e)

# SPY benchmark
q = urllib.parse.urlencode({'adjusted': 'true', 'sort': 'asc', 'limit': '50000', 'apiKey': key})
spy = get_json(f'https://api.massive.com/v2/aggs/ticker/SPY/range/1/day/2021-06-01/2026-07-01?{q}')
(OUT / 'spy_daily.json').write_text(json.dumps(spy.get('results') or []))
print('spy bars', len(spy.get('results') or []))
