import json, os, time, urllib.request, re
from pathlib import Path
from datetime import date, datetime, timedelta

OUT = Path('/root/spy/analyst/ipo_study')
YB = OUT / 'bars_yahoo'; YB.mkdir(exist_ok=True)
uni = json.load(open(OUT / 'ipo_universe.json'))
base = '/srv/ftp/ossicones/stock-data/bars_1d_adjusted'

targets = []
for r in uni:
    t, ld = r['ticker'], r['listing_date']
    y0 = int(ld[:4])
    if ld < '2024-07-02' and not os.path.exists(f'{base}/year={y0}/{t}.parquet'):
        targets.append(r)
print(len(targets), 'targets')

def yahoo(t, ld):
    p1 = int(datetime.fromisoformat(ld).timestamp()) - 86400*5
    p2 = int(time.time())
    # yahoo uses - instead of . for class shares
    sym = t.replace('.', '-')
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

ok, dead, err = 0, [], 0
for i, r in enumerate(targets):
    t, ld = r['ticker'], r['listing_date']
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    f = YB / f'{safe}__{ld}.json'
    if f.exists():
        ok += 1
        continue
    try:
        d = yahoo(t, ld)
        res = (d.get('chart') or {}).get('result')
        if res:
            f.write_text(json.dumps(res[0]))
            ok += 1
        else:
            dead.append(t)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            dead.append(t)
        elif e.code == 429:
            time.sleep(30)
            err += 1
        else:
            err += 1
    except Exception:
        err += 1
    time.sleep(0.6)
    if i % 40 == 0: print(i, 'ok', ok, 'dead', len(dead), 'err', err, flush=True)

json.dump(dead, open(OUT / 'yahoo_dead.json', 'w'))
print('DONE ok', ok, 'dead', len(dead), 'err', err)
