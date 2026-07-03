import json, re, time, urllib.request
from pathlib import Path
OUT = Path('/root/spy/analyst/ipo_study')
ED = OUT / 'edgar'; ED.mkdir(exist_ok=True)
HDR = {'User-Agent': 'Milkify Research pedro@milkify.me'}

def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# ticker -> CIK map (includes many delisted registrants)
m = get('https://www.sec.gov/files/company_tickers.json')
t2cik = {v['ticker'].upper(): v['cik_str'] for v in m.values()}
print('map size', len(t2cik))

uni = json.load(open(OUT / 'ipo_universe.json'))
found, miss = 0, []
res = {}
for i, r in enumerate(uni):
    t = r['ticker']
    cik = t2cik.get(t.upper().replace('.', '-')) or t2cik.get(t.upper())
    if not cik:
        miss.append(t); continue
    f = ED / f'{cik}.json'
    try:
        if f.exists():
            d = json.loads(f.read_text())
        else:
            d = get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json')
            f.write_text(json.dumps({'sic': d.get('sic'), 'sicDescription': d.get('sicDescription'),
                                     'name': d.get('name'), 'tickers': d.get('tickers')}))
            time.sleep(0.13)
            d = json.loads(f.read_text())
        res[t] = {'sic': d.get('sic'), 'sic_desc': d.get('sicDescription'), 'name': d.get('name')}
        found += 1
    except Exception as e:
        miss.append(t)
    if i % 100 == 0: print(i, 'found', found, 'miss', len(miss), flush=True)
json.dump(res, open(OUT / 'edgar_sic.json', 'w'), indent=0)
json.dump(miss, open(OUT / 'edgar_miss.json', 'w'))
print('DONE found', found, 'miss', len(miss))
