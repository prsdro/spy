#!/usr/bin/env python3
"""Random-entry control for the PO-compression options study.

Samples 186 random hourly bars (matched per-ticker counts, seed=42, dates
capped so W1/W2 are uncensored), prices the SAME grid cells (comp_start-style
entry, ATM, W1/W2, long+short) through the SAME leg engine, pulling any
missing contracts. Purpose: establish the baseline P&L of random-time entries
so compression cells are judged against baseline, not zero.
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F
from backtest_po_comp_options import (load_all, bar_close_ts, pick_contract,
                                      build_leg)
from indicators import compute_phase_oscillator, atr, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
COUNTS = {'AMZN': 63, 'NVDA': 63, 'MSFT': 60}
CAP = pd.Timestamp('2026-06-12', tz='America/New_York')
WSTART = pd.Timestamp('2025-07-07', tz='America/New_York')

for line in open('/root/spx-chart-app/.env'):
    if line.startswith('POLYGON_API_KEY='):
        F.KEY = line.strip().split('=', 1)[1]

rng = np.random.default_rng(42)
pseudo = []
for tkr, n in COUNTS.items():
    df5 = F.load_5m(tkr)
    h, dly = F.hourly_and_daily(df5)
    h = compute_phase_oscillator(h)
    h['ema9_h'] = ema(h['close'], 9)
    h['ema21_h'] = ema(h['close'], 21)
    dly['datr14'] = atr(dly, 14)
    dly['ema21_d'] = ema(dly['close'], 21)
    dprior = dly.shift(1)
    win = h[(h.index >= WSTART) & (h.index <= CAP)]
    po = h['phase_oscillator']
    picks = rng.choice(len(win), size=n, replace=False)
    for p in sorted(picks):
        ts = win.index[p]
        i = h.index.get_loc(ts)
        dkey = pd.Timestamp(ts.date(), tz='America/New_York')
        dsub = dprior.loc[dprior.index <= dkey]
        if not len(dsub) or pd.isna(dsub.iloc[-1]['datr14']):
            continue
        drow = dsub.iloc[-1]
        pseudo.append({
            'ticker': tkr, 'ep_id': f"RND-{tkr}-{len(pseudo):03d}",
            'start_ts_et': ts.isoformat(), 'end_ts_et': '',
            'spot_start': float(h['close'].iloc[i]),
            'datr14_prior': float(drow['datr14']),
            'ema9_h': float(h['ema9_h'].iloc[i]), 'ema21_h': float(h['ema21_h'].iloc[i]),
            'po': float(po.iloc[i]),
            'po_slope1': float(po.iloc[i] - po.iloc[i - 1]),
            'po_slope3': float(po.iloc[i] - po.iloc[i - 3]),
            'ema21_d_slope1': float(dly['ema21_d'].diff(1).shift(1).loc[:dkey].iloc[-1]),
            'ema21_d_slope3': float(dly['ema21_d'].diff(3).shift(1).loc[:dkey].iloc[-1]),
        })
pe = pd.DataFrame(pseudo)
pe.to_csv(STUDY / 'pseudo_events.csv', index=False)
print(f"pseudo events: {len(pe)}")

# --- figure out needed ATM contracts (W1/W2, call+put), pull missing ---------
con = sqlite3.connect(STUDY / 'option_bars.sqlite')
have = {r[0] for r in con.execute("SELECT ticker FROM contracts")}
need = {}
for _, e in pe.iterrows():
    d0 = pd.Timestamp(e['start_ts_et']).date()
    w1 = F.next_friday(d0)
    for exp in [w1, w1 + timedelta(days=7)]:
        chain = F.get_chain(e['ticker'], exp.isoformat())
        if chain is None:
            continue
        for typ in ['call', 'put']:
            s = min(chain[typ], key=lambda s: abs(s['strike'] - e['spot_start']))
            if s['ticker'] not in have:
                k = s['ticker']
                prev = need.get(k)
                need[k] = {'underlying': e['ticker'], 'type': typ,
                           'strike': s['strike'], 'expiry': chain['actual_expiry'],
                           'pull_from': min(d0.isoformat(),
                                            prev['pull_from'] if prev else '9999')}
print(f"missing contracts to pull: {len(need)}")
for i, (optk, m) in enumerate(sorted(need.items())):
    pull_to = min(date.fromisoformat(m['expiry']) + timedelta(days=1),
                  date.today()).isoformat()
    url = f"{F.BASE}/v2/aggs/ticker/{optk}/range/1/minute/{m['pull_from']}/{pull_to}"
    params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': F.KEY}
    nbars = 0
    while url:
        d = F.api_get(url, params)
        rows = [(optk, b['t'], b.get('o'), b.get('h'), b.get('l'), b.get('c'),
                 b.get('v'), b.get('vw'), b.get('n')) for b in d.get('results') or []]
        if rows:
            con.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
            nbars += len(rows)
        url = d.get('next_url')
        params = {'apiKey': F.KEY} if url else None
    con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?)",
                (optk, m['underlying'], m['type'], m['strike'], m['expiry'],
                 m['pull_from'], 'ok' if nbars else 'empty', nbars, 'baseline'))
    con.commit()
    if (i + 1) % 100 == 0:
        print(f"  pulled {i+1}/{len(need)}")
con.close()
print("pull done")

# --- evaluate the same legs through the same engine ---------------------------
ev, meta, opt, und = load_all()
rows, drops = [], {'no_end': 0, 'expired_before_confirm': 0, 'no_contract': 0,
                   'no_fill': 0}
for _, e in pe.iterrows():
    d0 = pd.Timestamp(e['start_ts_et']).date()
    w1 = F.next_friday(d0)
    sig_ts = bar_close_ts(e['start_ts_et'])
    sig_ms = int(sig_ts.timestamp() * 1000)
    for bname, exp in [('W1', w1), ('W2', w1 + timedelta(days=7))]:
        for direction in (1, -1):
            for vehicle in ('long', 'short'):
                typ = ('call' if direction == 1 else 'put') if vehicle == 'long' \
                    else ('put' if direction == 1 else 'call')
                row = build_leg(e, 'comp_start', sig_ts, sig_ms, e['spot_start'],
                                direction, bname, exp, 0.0, vehicle, typ,
                                e['spot_start'], meta, opt, und[e['ticker']],
                                e['datr14_prior'], 1, drops)
                if row:
                    rows.append(row)
rb = pd.DataFrame(rows)
rb.to_parquet(STUDY / 'random_baseline_trades.parquet')
print(f"baseline legs: {len(rb)}, drops: {drops}")


def cstats(df, col):
    g = df.groupby('ep_id')[col].mean()
    n = len(g)
    if n < 3:
        return "n/a"
    t = g.mean() / (g.std(ddof=1) / np.sqrt(n))
    return f"{g.mean():+.3f} (t={t:.2f}, n={n})"


tr = pd.read_parquet(STUDY / 'trades.parquet')
real = tr[(tr.entry == 'comp_start') & (tr.offset == 0.0) & (~tr.censored)
          & (tr.bucket.isin(['W1', 'W2']))]
rl = rb[~rb.censored]
print("\n=== RANDOM-ENTRY BASELINE vs COMPRESSION EVENTS (ATM, W1+W2) ===")
for veh in ['long', 'short']:
    print(f"-- {veh} --")
    for ex in (['pnl_hold', 'pnl_tp50', 'pnl_tp100', 'pnl_sc50_80',
                'pnl_tp100_stop50'] if veh == 'long' else
               ['pnl_hold', 'pnl_decay50', 'pnl_stop2x']):
        print(f"  {ex:18s} random: {cstats(rl[rl.vehicle==veh], ex):32s} "
              f"compression: {cstats(real[real.vehicle==veh], ex)}")
