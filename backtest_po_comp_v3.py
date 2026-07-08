#!/usr/bin/env python3
"""v3: Bilbo-box options backtest, 8 tickers x 24mo, RTH + ETH definitions.

Fixes/extensions vs v2: entry-anchored expiries (Codex), session-aware bars
(PO_SESSION), carry-to-open fills for overnight ETH signals, lazy bar loading,
comp_start legs included, missing-contract supplemental fetch.
Usage: PO_SESSION=RTH PO_EVENTS=events_v2.csv PO_OUT=v3_rth python3 backtest_po_comp_v3.py
"""
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
import fetch_po_comp_options as F
from fetch_po_comp_options import load_5m, hourly_and_daily, next_friday
from backtest_po_comp_options import entry_fill, first_cross_ms, opt_price_at, pick_contract
import backtest_po_comp_bilbo as B
from indicators import compute_phase_oscillator, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
SESSION = os.environ.get('PO_SESSION', 'RTH')
EVENTS = STUDY / os.environ.get('PO_EVENTS', 'events_v2.csv')
OUT = os.environ.get('PO_OUT', 'v3_rth')
DATA_END = pd.Timestamp('2026-07-06', tz='America/New_York')
OFFSETS = [0.0, 0.5]

for line in open('/root/spx-chart-app/.env'):
    if line.startswith('POLYGON_API_KEY='):
        F.KEY = line.strip().split('=', 1)[1]


def bar_close(label):
    ts = pd.Timestamp(label)
    if SESSION == 'ETH':
        return ts + pd.Timedelta(minutes=60)
    return ts + pd.Timedelta(minutes=30 if ts.hour == 15 and ts.minute == 30 else 60)


def roll_to_open(ts):
    """Overnight/weekend signal -> next RTH open + 5m (first tradeable print)."""
    t = ts.tz_convert('America/New_York') if ts.tzinfo else ts
    if t.hour >= 16:
        t = (t + pd.Timedelta(days=1)).replace(hour=9, minute=35, second=0)
    elif t.hour < 9 or (t.hour == 9 and t.minute < 35):
        t = t.replace(hour=9, minute=35, second=0)
    else:
        return ts
    while t.weekday() >= 5:
        t += pd.Timedelta(days=1)
    return t


class LazyBars(dict):
    def __init__(self, db):
        self.con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.con.execute("PRAGMA busy_timeout=30000")

    def __missing__(self, k):
        rows = self.con.execute(
            "SELECT t,o,h,l,c FROM bars WHERE ticker=? ORDER BY t", (k,)).fetchall()
        arr = np.array(rows, float) if rows else np.zeros((0, 5))
        self[k] = arr
        return arr


def main():
    ev = pd.read_csv(EVENTS)
    con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
    meta = pd.read_sql("SELECT ticker,underlying,type,strike,expiry FROM contracts "
                       "WHERE status='ok'", con)
    con.close()
    opt = LazyBars(STUDY / 'option_bars.sqlite')

    und, m5x = {}, {}
    for tkr in ev.ticker.unique():
        df5 = load_5m(tkr)
        h, dly = hourly_and_daily(df5, session=SESSION)
        h = compute_phase_oscillator(h)
        h['ema9'] = ema(h['close'], 9)
        h['ema21'] = ema(h['close'], 21)
        h['close_ts'] = [bar_close(i) for i in h.index]
        r5 = df5.between_time('09:30', '15:55')
        x5 = df5.between_time('04:00', '19:55') if SESSION == 'ETH' else r5
        und[tkr] = {'h': h, 'daily_close': dly['close'],
                    'm5_t': r5.index.as_unit('ns').asi8 // 10**6,
                    'm5_hi': r5['high'].to_numpy(float),
                    'm5_lo': r5['low'].to_numpy(float)}
        m5x[tkr] = {'t': x5.index.as_unit('ns').asi8 // 10**6,
                    'hi': x5['high'].to_numpy(float), 'lo': x5['low'].to_numpy(float),
                    'cl': x5['close'].to_numpy(float)}
        print(f"prepped {tkr}", flush=True)

    rows = []
    funnel = {'events': 0, 'boxes': 0, 'breakouts': 0, 'retests': 0, 'third_long': 0,
              'third_short': 0, 'drops_no_fill': 0, 'drops_after_expiry': 0,
              'overnight_breaks': 0}
    for _, e in ev.iterrows():
        funnel['events'] += 1
        tkr = e['ticker']
        H = und[tkr]['h']
        start = pd.Timestamp(e['start_ts_et'])
        try:
            i = H.index.get_loc(start)
        except KeyError:
            continue
        k = 0
        while i + k < len(H) and k < 5 and H['po_compression'].iloc[i + k] == 1:
            k += 1
        if k == 0 or i + k >= len(H):
            continue
        funnel['boxes'] += 1
        five = H.iloc[i:i + k]
        box_hi, box_lo = five['high'].max(), five['low'].min()
        box_h = box_hi - box_lo
        comp_ms = int(bar_close(five.index[-1]).timestamp() * 1000)
        M = m5x[tkr]
        watch_to = comp_ms + 10 * 86400_000
        sel = (M['t'] >= comp_ms) & (M['t'] <= watch_to)
        idxs = np.where(sel & ((M['hi'] > box_hi) | (M['lo'] < box_lo)))[0]
        entries = [('comp_start', int(bar_close(start).timestamp() * 1000),
                    e['spot_start'], 1), ('comp_start',
                    int(bar_close(start).timestamp() * 1000), e['spot_start'], -1)]
        br_i = None
        if len(idxs):
            br_i = idxs[0]
            up, dn = M['hi'][br_i] > box_hi, M['lo'][br_i] < box_lo
            dirn = (1 if M['cl'][br_i] >= (box_hi + box_lo) / 2 else -1) \
                if (up and dn) else (1 if up else -1)
            funnel['breakouts'] += 1
            br_ms = int(M['t'][br_i]) + 300_000
            br_ts = pd.Timestamp(br_ms, unit='ms', tz='America/New_York')
            if br_ts.hour < 9 or br_ts.hour >= 16 or (br_ts.hour == 9 and br_ts.minute < 35):
                funnel['overnight_breaks'] += 1
            entries.append(('immediate', br_ms, float(M['cl'][br_i]), dirn))
            edge = box_hi if dirn == 1 else box_lo
            rsel = (M['t'] > M['t'][br_i]) & (M['t'] <= br_ms + 7 * 86400_000)
            rid = np.where(rsel & ((M['lo'] <= edge) if dirn == 1
                                   else (M['hi'] >= edge)))[0]
            if len(rid):
                funnel['retests'] += 1
                entries.append(('retest', int(M['t'][rid[0]]) + 300_000,
                                float(M['cl'][rid[0]]), dirn))
        end_ms = M['t'][br_i] if br_i is not None else watch_to
        tsel = (M['t'] >= comp_ms) & (M['t'] < end_ms)
        for vname, cond, tdir in [('third_long', M['cl'] <= box_lo + box_h / 3, 1),
                                  ('third_short', M['cl'] >= box_hi - box_h / 3, -1)]:
            tid = np.where(tsel & cond)[0]
            if len(tid):
                funnel[vname] += 1
                entries.append((vname, int(M['t'][tid[0]]) + 300_000,
                                float(M['cl'][tid[0]]), tdir))

        for variant, sig_ms0, spot, direction in entries:
            sig_ts = roll_to_open(pd.Timestamp(sig_ms0, unit='ms', tz='America/New_York'))
            sig_ms = int(sig_ts.timestamp() * 1000)
            w1 = next_friday(sig_ts.date())          # ENTRY-anchored (Codex fix)
            for bname, exp in [('W1', w1), ('W2', w1 + timedelta(days=7))]:
                for off in OFFSETS:
                    for vehicle in ('long', 'short'):
                        if vehicle == 'long':
                            typ = 'call' if direction == 1 else 'put'
                            target = spot + direction * off * e['datr14_prior']
                        else:
                            typ = 'put' if direction == 1 else 'call'
                            target = spot - direction * off * e['datr14_prior']
                        row = B.leg(e, variant, sig_ts, sig_ms, spot, direction,
                                    bname, exp, off, vehicle, typ, target, meta,
                                    opt, und[tkr], box_hi, box_lo, funnel)
                        if row:
                            row['n_box_bars'] = k
                            row['sig_raw_ts'] = pd.Timestamp(
                                sig_ms0, unit='ms', tz='America/New_York').isoformat()
                            row['rolled_to_open'] = sig_ms != sig_ms0
                            rows.append(row)
        if funnel['events'] % 250 == 0:
            print(f"...{funnel['events']}/{len(ev)} events, {len(rows)} legs", flush=True)

    tr = pd.DataFrame(rows)
    feat = ev[['ep_id', 'po', 'po_slope1', 'po_slope3', 'phase_zone',
               'ema21_d_slope1', 'spot_start', 'ema21_h', 'ema9_h']]
    tr = tr.merge(feat, on='ep_id', how='left')
    tr.to_parquet(STUDY / f'{OUT}_trades.parquet')
    print("funnel:", funnel)
    print("legs:", len(tr), "->", STUDY / f'{OUT}_trades.parquet')


if __name__ == '__main__':
    main()
