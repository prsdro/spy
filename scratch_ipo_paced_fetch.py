import json, time, re, urllib.parse, urllib.request, urllib.error, os
from pathlib import Path

key = [l.split('=',1)[1].strip().strip('"') for l in Path('/root/spx-chart-app/.env').read_text().splitlines() if l.startswith('POLYGON_API_KEY=')][0]
OUT = Path('/root/spy/analyst/ipo_study')
BARS = OUT / 'bars'; DETAILS = OUT / 'details'
BARS.mkdir(exist_ok=True); DETAILS.mkdir(exist_ok=True)
uni = json.load(open(OUT / 'ipo_universe.json'))
local = set(json.load(open(OUT / 'local_covered.json')))

PACE = 12.5
last_call = [0.0]
def get_json(url):
    for attempt in range(8):
        wait = PACE - (time.time() - last_call[0])
        if wait > 0: time.sleep(wait)
        last_call[0] = time.time()
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code == 429: time.sleep(65); continue
            time.sleep(10 * (attempt + 1))
        except Exception:
            time.sleep(10 * (attempt + 1))
    raise RuntimeError('failed ' + url[:100])

def safe(t): return re.sub(r'[^A-Za-z0-9._-]+', '_', t)

todo = []
for r in uni:
    t, ld = r['ticker'], r['listing_date']
    bar_f = BARS / f'{safe(t)}__{ld}.json'
    det_f = DETAILS / f'{safe(t)}__{ld}.json'
    if t not in local and not bar_f.exists(): todo.append(('bars', t, ld, bar_f))
    if not det_f.exists(): todo.append(('det', t, ld, det_f))
todo.sort(key=lambda x: 0 if x[0]=='bars' else 1)
print(f'{len(todo)} calls to make, est {len(todo)*PACE/3600:.1f}h', flush=True)

for i, (kind, t, ld, f) in enumerate(todo):
    try:
        if kind == 'bars':
            q = urllib.parse.urlencode({'adjusted':'true','sort':'asc','limit':'50000','apiKey':key})
            data = get_json(f'https://api.massive.com/v2/aggs/ticker/{urllib.parse.quote(t)}/range/1/day/{ld}/2026-07-01?{q}')
            f.write_text(json.dumps((data or {}).get('results') or []))
        else:
            data = get_json(f'https://api.massive.com/v3/reference/tickers/{urllib.parse.quote(t)}?date={ld}&apiKey={key}')
            det = (data or {}).get('results') or {}
            if not det:
                data = get_json(f'https://api.massive.com/v3/reference/tickers/{urllib.parse.quote(t)}?apiKey={key}')
                det = (data or {}).get('results') or {}
            f.write_text(json.dumps(det))
    except Exception as e:
        print(f'ERR {kind} {t}: {e}', flush=True)
    if i % 20 == 0:
        print(f'{i}/{len(todo)} {kind} {t}', flush=True)

# SPY benchmark through 2026-07-01
spy_f = OUT / 'spy_daily.json'
if not spy_f.exists():
    q = urllib.parse.urlencode({'adjusted':'true','sort':'asc','limit':'50000','apiKey':key})
    spy = get_json(f'https://api.massive.com/v2/aggs/ticker/SPY/range/1/day/2021-06-01/2026-07-01?{q}')
    spy_f.write_text(json.dumps((spy or {}).get('results') or []))
print('ALL DONE', flush=True)
