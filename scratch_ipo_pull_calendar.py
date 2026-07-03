import json, time, urllib.parse, urllib.request
from pathlib import Path

key = [l.split('=',1)[1].strip().strip('"') for l in Path('/root/spx-chart-app/.env').read_text().splitlines() if l.startswith('POLYGON_API_KEY=')][0]

def get_json(url):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            print('retry', attempt, e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError('failed: ' + url[:80])

rows = []
params = dict(ipo_status='history', order='asc', sort='listing_date', limit='1000',
              **{'listing_date.gte': '2021-07-01'}, apiKey=key)
url = 'https://api.massive.com/vX/reference/ipos?' + urllib.parse.urlencode(params)
while url:
    data = get_json(url)
    batch = data.get('results') or []
    rows.extend(batch)
    url = data.get('next_url')
    if url and 'apiKey=' not in url:
        url += '&apiKey=' + key
    print(len(rows), batch[-1].get('listing_date') if batch else '')
    time.sleep(0.2)

Path('/root/spy/analyst/ipo_study/ipo_calendar_raw.json').write_text(json.dumps(rows, indent=1))
print('TOTAL', len(rows))
