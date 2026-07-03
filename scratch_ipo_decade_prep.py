"""Decade-back cohort prep: from ipo_universe_2011_2021.json take deals with
offer size >= $250M, resolve SIC via EDGAR (with issuer-name sanity check to
catch recycled tickers), tag tech/SPAC, and write the Yahoo bar-fetch todo.

Outputs:
  analyst/ipo_study/decade_cohort.json   [{ticker, listing_date, issuer, size,
                                           sic, sic_src, tech, spac}]
  analyst/ipo_study/decade_yahoo_todo.json
"""
import json, re, time, urllib.request
from pathlib import Path

OUT = Path('/root/spy/analyst/ipo_study')
ED = OUT / 'edgar'; ED.mkdir(exist_ok=True)
HDR = {'User-Agent': 'Milkify Research pedro@milkify.me'}

def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def usize(r):
    return r.get('total_offer_size') or (
        (r.get('max_shares_offered') or 0) * (r.get('final_issue_price') or 0) or None)

STOP_TOKENS = {'inc', 'corp', 'corporation', 'company', 'co', 'ltd', 'plc', 'sa',
               'nv', 'lp', 'llc', 'holdings', 'holding', 'group', 'the', 'trust',
               'international', 'technologies', 'pharmaceuticals', 'therapeutics'}
def tokens(s):
    return {w for w in re.findall(r'[a-z0-9]+', (s or '').lower())
            if w not in STOP_TOKENS and len(w) > 2}

def name_match(a, b):
    ta, tb = tokens(a), tokens(b)
    return bool(ta & tb)

uni = json.load(open(OUT / 'ipo_universe_2011_2021.json'))
big = [r for r in uni if (usize(r) or 0) >= 250e6]
print('qualifying >=250M:', len(big))

m = get('https://www.sec.gov/files/company_tickers.json')
t2cik = {v['ticker'].upper(): v['cik_str'] for v in m.values()}

def is_tech(sic):
    try:
        c = int(str(sic)[:4])
    except (ValueError, TypeError):
        return False
    return 3570 <= c <= 3579 or 3660 <= c <= 3699 or 7370 <= c <= 7379

cohort = []
n_sic = n_namefail = 0
for i, r in enumerate(big):
    t, ld = r['ticker'], r['listing_date']
    issuer = r.get('issuer_name') or ''
    sic, sic_src = None, None
    cik = t2cik.get(t.upper().replace('.', '-')) or t2cik.get(t.upper())
    if cik:
        f = ED / f'{cik}.json'
        try:
            if f.exists():
                d = json.loads(f.read_text())
            else:
                d = get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json')
                d = {'sic': d.get('sic'), 'sicDescription': d.get('sicDescription'),
                     'name': d.get('name'), 'tickers': d.get('tickers')}
                f.write_text(json.dumps(d))
                time.sleep(0.13)
            if name_match(issuer, d.get('name')):
                sic, sic_src = d.get('sic'), 'edgar'
                n_sic += 1
            else:
                n_namefail += 1
        except Exception:
            pass
    name_spac = bool(re.search(r'acquisition co|acquisition holdings|blank check',
                               issuer, re.I))
    spac = str(sic).startswith('6770') if sic else name_spac
    cohort.append({'ticker': t, 'listing_date': ld, 'issuer': issuer,
                   'size': usize(r), 'issue_price': r.get('final_issue_price'),
                   'sic': sic, 'sic_src': sic_src,
                   'tech': is_tech(sic), 'spac': spac or name_spac})
    if i % 50 == 0:
        print(i, 'sic', n_sic, 'name-mismatch', n_namefail, flush=True)

json.dump(cohort, open(OUT / 'decade_cohort.json', 'w'))
todo = [[c['ticker'], c['listing_date']] for c in cohort if not c['spac']]
json.dump(todo, open(OUT / 'decade_yahoo_todo.json', 'w'))
per_yr = {}
for c in cohort:
    per_yr[c['listing_date'][:4]] = per_yr.get(c['listing_date'][:4], 0) + 1
print('cohort:', len(cohort), 'spac:', sum(c["spac"] for c in cohort),
      'tech:', sum(c["tech"] for c in cohort),
      'sic resolved:', n_sic, 'name-mismatch:', n_namefail)
print('per year:', dict(sorted(per_yr.items())))
print('yahoo todo:', len(todo))
