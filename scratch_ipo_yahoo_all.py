import json, re, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
OUT = Path('/root/spy/analyst/ipo_study')
YB = OUT / 'bars_yahoo'
todo = json.load(open(OUT / 'yahoo_todo.json'))
ok, dead, err = 0, [], 0
for i, (t, ld) in enumerate(todo):
    f = YB / f"{re.sub(r'[^A-Za-z0-9._-]+','_',t)}__{ld}.json"
    if f.exists(): ok += 1; continue
    p1 = int(datetime.fromisoformat(ld).timestamp()) - 432000
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t.replace('.','-')}?period1={p1}&period2={int(time.time())}&interval=1d"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        res = (d.get('chart') or {}).get('result')
        if res: f.write_text(json.dumps(res[0])); ok += 1
        else: dead.append([t, ld])
    except urllib.error.HTTPError as e:
        if e.code == 404: dead.append([t, ld])
        elif e.code == 429: time.sleep(30); err += 1
        else: err += 1
    except Exception: err += 1
    time.sleep(0.5)
    if i % 50 == 0: print(i, 'ok', ok, 'dead', len(dead), 'err', err, flush=True)
json.dump(dead, open(OUT / 'yahoo_dead2.json', 'w'))
print('DONE ok', ok, 'dead', len(dead), 'err', err)
