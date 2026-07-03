import json, time, re, urllib.parse, urllib.request, urllib.error
from pathlib import Path

key = [l.split('=',1)[1].strip().strip('"') for l in Path('/root/spx-chart-app/.env').read_text().splitlines() if l.startswith('POLYGON_API_KEY=')][0]
OUT = Path('/root/spy/analyst/ipo_study')
BARS, DETAILS = OUT/'bars', OUT/'details'
uni = json.load(open(OUT/'ipo_universe.json'))
dead = {t for t,_ in (json.load(open(OUT/'yahoo_dead2.json')))} | set(json.load(open(OUT/'yahoo_dead.json')))
edgar = json.load(open(OUT/'edgar_sic.json'))

def safe(t): return re.sub(r'[^A-Za-z0-9._-]+','_',t)
PACE = 12.5
last = [0.0]
def get_json(url):
    for a in range(8):
        w = PACE - (time.time()-last[0])
        if w > 0: time.sleep(w)
        last[0] = time.time()
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code == 429: time.sleep(65); continue
            time.sleep(10*(a+1))
        except Exception: time.sleep(10*(a+1))
    raise RuntimeError('fail '+url[:90])

todo = []
for r in uni:
    t, ld = r['ticker'], r['listing_date']
    bf = BARS/f'{safe(t)}__{ld}.json'
    # bars: only delisted post-2024-07 listings (Massive has their full series); pre-cap delisted need Stooq
    if t in dead and ld >= '2024-07-02' and not (bf.exists() and json.loads(bf.read_text() or '[]')):
        todo.append(('bars', t, ld, bf))
    df_ = DETAILS/f'{safe(t)}__{ld}.json'
    if t not in edgar and not df_.exists():
        todo.append(('det', t, ld, df_))
print(len(todo), 'calls', flush=True)
for i,(kind,t,ld,f) in enumerate(todo):
    try:
        if kind=='bars':
            q = urllib.parse.urlencode({'adjusted':'true','sort':'asc','limit':'50000','apiKey':key})
            d = get_json(f'https://api.massive.com/v2/aggs/ticker/{urllib.parse.quote(t)}/range/1/day/{ld}/2026-07-01?{q}')
            f.write_text(json.dumps((d or {}).get('results') or []))
        else:
            d = get_json(f'https://api.massive.com/v3/reference/tickers/{urllib.parse.quote(t)}?apiKey={key}')
            f.write_text(json.dumps((d or {}).get('results') or {}))
    except Exception as e:
        print('ERR', t, e, flush=True)
    if i % 10 == 0: print(f'{i}/{len(todo)} {kind} {t}', flush=True)
print('ALL DONE', flush=True)
