#!/usr/bin/env python3
"""Carry timer test: sell ATM W1 premium (call+put separately) at random
NON-compression times vs AT compression starts, 8 tickers ETH definition.
Pulls missing contracts (paced 0.15s). Writes carry_timer_results.json."""
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F
from fetch_po_comp_options import load_5m, hourly_and_daily, next_friday
from backtest_po_comp_options import entry_fill
from indicators import compute_phase_oscillator

STUDY = Path('/root/spy/analyst/po_comp_options')
TICKERS = ['AMZN', 'NVDA', 'MSFT', 'AAPL', 'META', 'GOOGL', 'TSLA', 'AMD']
N_PER = 70
CAP = pd.Timestamp('2026-06-19', tz='America/New_York')
W0 = pd.Timestamp('2024-07-14', tz='America/New_York')
for line in open('/root/spx-chart-app/.env'):
    if line.startswith('POLYGON_API_KEY='):
        F.KEY = line.strip().split('=', 1)[1]

rng = np.random.default_rng(11)
samples = []
for tkr in TICKERS:
    df5 = load_5m(tkr)
    h, dly = hourly_and_daily(df5, session='ETH')
    h = compute_phase_oscillator(h)
    win = h[(h.index >= W0) & (h.index <= CAP)]
    rth = win[(win.index.hour >= 10) & (win.index.hour <= 14)]
    pool = rth[rth['po_compression'] == 0]
    for i in rng.choice(len(pool), size=N_PER, replace=False):
        samples.append({'ticker': tkr, 'ts': pool.index[i], 'spot': pool['close'].iloc[i]})
print(f"non-compression samples: {len(samples)}", flush=True)

con = sqlite3.connect(STUDY / 'option_bars.sqlite')
con.execute("PRAGMA busy_timeout=60000")
have = {r[0] for r in con.execute("SELECT ticker FROM contracts")}
need, legs = {}, []
for s in samples:
    d0 = s['ts'].date()
    exp = next_friday(d0)
    chain = F.get_chain(s['ticker'], exp.isoformat())
    if chain is None:
        continue
    for typ in ['call', 'put']:
        k = min(chain[typ], key=lambda x: abs(x['strike'] - s['spot']))
        legs.append({**s, 'type': typ, 'contract': k['ticker'], 'strike': k['strike'],
                     'expiry': chain['actual_expiry']})
        if k['ticker'] not in have:
            prev = need.get(k['ticker'])
            need[k['ticker']] = {'expiry': chain['actual_expiry'],
                                 'pull_from': min(d0.isoformat(),
                                                  prev['pull_from'] if prev else '9999')}
print(f"legs: {len(legs)}, missing contracts: {len(need)}", flush=True)
for i, (opt, m) in enumerate(sorted(need.items())):
    pull_to = min(date.fromisoformat(m['expiry']) + timedelta(days=1), date.today()).isoformat()
    url = f"{F.BASE}/v2/aggs/ticker/{opt}/range/1/minute/{m['pull_from']}/{pull_to}"
    params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': F.KEY}
    nb = 0
    while url:
        d = F.api_get(url, params)
        rows = [(opt, b['t'], b.get('o'), b.get('h'), b.get('l'), b.get('c'),
                 b.get('v'), b.get('vw'), b.get('n')) for b in d.get('results') or []]
        if rows:
            con.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
            nb += len(rows)
        url = d.get('next_url')
        params = {'apiKey': F.KEY} if url else None
    con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?)",
                (opt, opt.split(':')[1][:4].rstrip('0123456789'), 'x', 0, m['expiry'],
                 m['pull_from'], 'ok' if nb else 'empty', nb, 'carry'))
    con.commit()
    if (i + 1) % 100 == 0:
        print(f"pulled {i+1}/{len(need)}", flush=True)

# evaluate short legs: hold to expiry (settle from 5m-derived daily), stop 2x
daily = {}
for tkr in TICKERS:
    _, dly = hourly_and_daily(load_5m(tkr))
    daily[tkr] = dly['close']
recs = []
for L in legs:
    arr = np.array(con.execute("SELECT t,o,h,l,c FROM bars WHERE ticker=? ORDER BY t",
                               (L['contract'],)).fetchall(), float)
    if not len(arr):
        continue
    sig_ms = int((L['ts'] + pd.Timedelta(minutes=60)).timestamp() * 1000)
    f = entry_fill(arr, sig_ms)
    if f is None or f[0] <= 0.01:
        continue
    entry_px, fill_ms = f
    dc = daily[L['ticker']]
    dkey = dc.index[dc.index.date <= date.fromisoformat(L['expiry'])]
    if not len(dkey):
        continue
    S = dc.loc[dkey[-1]]
    settle = max(0.0, S - L['strike']) if L['type'] == 'call' else max(0.0, L['strike'] - S)
    expiry_ms = int((pd.Timestamp(L['expiry'], tz='America/New_York')
                     + pd.Timedelta(hours=16)).timestamp() * 1000)
    p = arr[(arr[:, 0] > fill_ms) & (arr[:, 0] <= expiry_ms)]
    hold = 1 - settle / entry_px
    m2 = p[:, 2] >= 2 * entry_px if len(p) else np.array([False])
    recs.append({'ticker': L['ticker'], 'ts': str(L['ts']), 'type': L['type'],
                 'pnl_hold': hold, 'pnl_stop2x': -1.0 if m2.any() else hold})
con.close()
g = pd.DataFrame(recs)
g.to_parquet(STUDY / 'carry_noncomp_legs.parquet')

def cs(df, col):
    e = df.groupby('ts')[col].mean()
    n = len(e)
    return {'mean': round(float(e.mean()), 4),
            't': round(float(e.mean() / (e.std(ddof=1) / np.sqrt(n))), 2), 'n': n}

# compression-time shorts from v3 for comparison
v3 = pd.read_parquet(STUDY / 'v3_eth_trades.parquet')
v3 = v3.drop_duplicates(subset=['ep_id', 'variant', 'direction', 'bucket', 'vehicle', 'contract'])
cshort = v3[(v3.variant == 'comp_start') & (v3.vehicle == 'short') & (v3.offset == 0.0) &
            (v3.bucket == 'W1') & (~v3.censored)].rename(columns={'ep_id': 'ts'})
out = {
    'noncomp_short_hold': cs(g, 'pnl_hold'),
    'noncomp_short_stop2x': cs(g, 'pnl_stop2x'),
    'comp_short_hold': cs(cshort, 'pnl_hold'),
    'comp_short_stop2x': cs(cshort, 'pnl_stop2x'),
    'noncomp_by_ticker_hold': {k: cs(d, 'pnl_hold') for k, d in g.groupby('ticker')},
}
(STUDY / 'carry_timer_results.json').write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
