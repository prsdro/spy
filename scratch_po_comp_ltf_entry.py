#!/usr/bin/env python3
"""Lower-timeframe (10m/30m) confirmation entries for the locked Bilbo box.

Setup: hourly box locks after 5 completed grey bars (live-knowable, same as
WAIT_FULL_BOX). Watch from the lock until the first hourly close out of
compression (inclusive) or lock+10d. Entry = first LTF bar CLOSE beyond the
box edge; optional gate: that LTF bar's own PO computes out of compression
at its close AND its oscillator slope agrees with the break direction.
All conditions use completed LTF bars only — live-valid.

env: PO_EVENTS, PO_TOPUP, PO_OUT, LTF (minutes, e.g. 10/30), LTF_PO (0/1)
"""
import os
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
os.environ.setdefault('PO_SESSION', 'ETH')
from fetch_po_comp_options import next_friday
from scratch_po_comp_flip_rerun import prep_ticker, roll_to_open, bar_close, LazyBars
import backtest_po_comp_bilbo as B
from indicators import compute_phase_oscillator

STUDY = Path('/root/spy/analyst/po_comp_options')
EVENTS = STUDY / os.environ.get('PO_EVENTS', 'events_v2_eth.csv')
OUT = os.environ.get('PO_OUT', 'ltf10')
LTF = int(os.environ.get('LTF', '10'))
LTF_PO = os.environ.get('LTF_PO', '0') == '1'
OFFSETS = [0.0, 0.5]


def ltf_frame(x5):
    f = x5.resample(f'{LTF}min').agg(open=('open', 'first'), high=('high', 'max'),
                                     low=('low', 'min'), close=('close', 'last')).dropna()
    f = compute_phase_oscillator(f)
    f['po_slope1'] = f['phase_oscillator'].diff(1)
    f['close_ts'] = f.index + pd.Timedelta(minutes=LTF)
    return f


def main():
    ev = pd.read_csv(EVENTS)
    con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
    meta = pd.read_sql("SELECT ticker,underlying,type,strike,expiry FROM contracts "
                       "WHERE status='ok'", con)
    con.close()
    opt = LazyBars(STUDY / 'option_bars.sqlite')

    P, L = {}, {}
    for tkr in ev.ticker.unique():
        P[tkr] = prep_ticker(tkr)
        L[tkr] = ltf_frame(P[tkr]['x5'])
        print(f"prepped {tkr}", flush=True)

    rows = []
    funnel = {'events': 0, 'locked_boxes': 0, 'entries': 0, 'no_signal': 0,
              'overnight_entries': 0, 'drops_no_fill': 0, 'drops_after_expiry': 0}
    for _, e in ev.iterrows():
        funnel['events'] += 1
        tkr = e['ticker']
        pt, lf = P[tkr], L[tkr]
        h, hcomp = pt['h'], pt['hcomp']
        start = pd.Timestamp(e['start_ts_et'])
        try:
            i = h.index.get_loc(start)
        except KeyError:
            continue
        # need 5 completed grey bars to lock the box
        k = 0
        while i + k < len(h) and k < 5 and hcomp[i + k] == 1:
            k += 1
        if k < 5:
            continue
        funnel['locked_boxes'] += 1
        five = h.iloc[i:i + 5]
        box_hi, box_lo = float(five['high'].max()), float(five['low'].min())
        lock_ts = bar_close(five.index[-1])
        # death: first hourly close out of compression after the lock
        death_ts = lock_ts + pd.Timedelta(days=10)
        for j in range(i + 5, len(h)):
            if hcomp[j] == 0:
                death_ts = min(death_ts, bar_close(h.index[j]))
                break
        seg = lf[(lf['close_ts'] > lock_ts) & (lf['close_ts'] <= death_ts)]
        entry = None
        for _, b in seg.iterrows():
            up, dn = b['close'] > box_hi, b['close'] < box_lo
            if not (up or dn):
                continue
            dirn = 1 if up else -1
            if LTF_PO:
                if b['po_compression'] == 1:
                    continue
                if not np.isfinite(b['po_slope1']) or b['po_slope1'] * dirn <= 0:
                    continue
            entry = (b['close_ts'], float(b['close']), dirn)
            break
        if entry is None:
            funnel['no_signal'] += 1
            continue
        funnel['entries'] += 1
        sig_raw, spot, direction = entry
        if sig_raw.hour < 9 or sig_raw.hour >= 16 or \
                (sig_raw.hour == 9 and sig_raw.minute < 35):
            funnel['overnight_entries'] += 1
        sig_ts = roll_to_open(sig_raw)
        sig_ms = int(sig_ts.timestamp() * 1000)
        w1 = next_friday(sig_ts.date())
        for bname, exp in [('W1', w1), ('W2', w1 + timedelta(days=7))]:
            for off in OFFSETS:
                for vehicle in ('long', 'short'):
                    if vehicle == 'long':
                        typ = 'call' if direction == 1 else 'put'
                        target = spot + direction * off * e['datr14_prior']
                    else:
                        typ = 'put' if direction == 1 else 'call'
                        target = spot - direction * off * e['datr14_prior']
                    row = B.leg(e, f'ltf{LTF}', sig_ts, sig_ms, spot, direction,
                                bname, exp, off, vehicle, typ, target, meta,
                                opt, pt['U'], box_hi, box_lo, funnel)
                    if row:
                        row['sig_raw_ts'] = sig_raw.isoformat()
                        row['rolled_to_open'] = sig_ms != int(sig_raw.timestamp() * 1000)
                        # entry-bar-close semantics for mgmt code reuse:
                        # LTF close IS the confirmation -> confirmed at entry
                        row['flip_bar_closed_grey'] = False
                        row['entry_bar_close_ts'] = sig_raw.isoformat()
                        rows.append(row)
        if funnel['events'] % 500 == 0:
            print(f"...{funnel['events']}/{len(ev)}, {len(rows)} legs", flush=True)

    tr = pd.DataFrame(rows)
    tr.to_parquet(STUDY / f'{OUT}_trades.parquet')
    print("funnel:", funnel)
    print("legs:", len(tr), "->", STUDY / f'{OUT}_trades.parquet')


if __name__ == '__main__':
    main()
