import hashlib, json, re, time, urllib.request, urllib.parse
import http.cookiejar
from pathlib import Path

OUT = Path('/root/spy/analyst/ipo_study')
SB = OUT / 'bars_stooq'; SB.mkdir(exist_ok=True)

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')]

def solve_challenge(html):
    m = re.search(r'const c="([^"]+)",d=(\d+)', html)
    c, d = m.group(1), int(m.group(2))
    target = '0' * d
    n = 0
    while True:
        if hashlib.sha256((c + str(n)).encode()).hexdigest().startswith(target):
            return c, n
        n += 1

def get(url):
    for attempt in range(4):
        r = opener.open(url, timeout=30)
        body = r.read()
        text = body.decode('utf-8', 'ignore')
        if '__verify' in text and 'crypto.subtle' in text:
            c, n = solve_challenge(text)
            data = urllib.parse.urlencode({'c': c, 'n': n}).encode()
            req = urllib.request.Request('https://stooq.com/__verify', data=data,
                                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
            opener.open(req, timeout=30)
            continue
        return text
    return None

dead = json.load(open(OUT / 'yahoo_dead.json'))
uni = json.load(open(OUT / 'ipo_universe.json'))
ld_map = {}
for r in uni:
    ld_map.setdefault(r['ticker'], r['listing_date'])

ok, miss = 0, []
for i, t in enumerate(dead):
    ld = ld_map[t]
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', t)
    f = SB / f'{safe}__{ld}.csv'
    if f.exists():
        ok += 1
        continue
    sym = t.lower().replace('.', '-') + '.us'
    text = get(f'https://stooq.com/q/d/l/?s={sym}&i=d')
    if text and text.startswith('Date,'):
        f.write_text(text)
        ok += 1
    else:
        miss.append(t)
    time.sleep(1.5)
    if i % 20 == 0: print(i, 'ok', ok, 'miss', len(miss), flush=True)

json.dump(miss, open(OUT / 'stooq_missing.json', 'w'))
print('DONE ok', ok, 'missing', len(miss), miss[:20])
