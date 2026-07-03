"""Fetch IPO universe 2011-01-01..2021-06-30 from Massive vX/reference/ipos
(one query per listing year, ipo_status=history, 5 req/min budget) and save to
analyst/ipo_study/ipo_universe_2011_2021.json with the same qualifying filter
as the 5-yr study: CS/ADRC on XNAS/XNYS/XASE.
"""
import json, time, urllib.request, urllib.parse
from pathlib import Path

OUT = Path('/root/spy/analyst/ipo_study')
key = [l.split('=', 1)[1].strip().strip('"')
       for l in Path('/root/spx-chart-app/.env').read_text().splitlines()
       if l.startswith('POLYGON_API_KEY=')][0]

def get(url):
    if 'apiKey=' not in url:
        url += ('&' if '?' in url else '?') + 'apiKey=' + key
    return json.load(urllib.request.urlopen(url, timeout=60))

rows = []
for y in range(2011, 2022):
    gte = f'{y}-01-01'
    lte = f'{y}-06-30' if y == 2021 else f'{y}-12-31'
    params = dict(ipo_status='history', limit=1000, order='asc', sort='listing_date')
    params['listing_date.gte'] = gte
    params['listing_date.lte'] = lte
    url = 'https://api.massive.com/vX/reference/ipos?' + urllib.parse.urlencode(params)
    n_y = 0
    while url:
        d = get(url)
        rs = d.get('results') or []
        rows += rs
        n_y += len(rs)
        url = d.get('next_url')
        time.sleep(13)          # 5/min budget
    print(y, n_y, flush=True)

qual = [r for r in rows
        if r.get('security_type') in ('CS', 'ADRC')
        and r.get('primary_exchange') in ('XNAS', 'XNYS', 'XASE')]
(OUT / 'ipo_universe_2011_2021.json').write_text(json.dumps(qual))
print('total raw:', len(rows), 'qualifying:', len(qual))
big = [r for r in qual if (r.get('total_offer_size') or
        ((r.get('max_shares_offered') or 0) * (r.get('final_issue_price') or 0))) >= 250e6]
print('>=250M:', len(big))
