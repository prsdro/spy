#!/usr/bin/env python3
"""30-minute Bilbo Box variant, under the two validated live entries.

Box timeframe moves from 1h to 30m: episodes = 30m PO-compression runs on ETH
bars, box = completed grey 30m bars (freeze after 5). Two entry variants:
  confirm  - first 30m bar that closes out of compression AND broke the box;
             enter at that 30m close (analog of hourly D). All box sizes.
  ltf10po  - box must lock (5 grey 30m bars = 2.5h); enter at first 10m bar
             CLOSE beyond the edge whose own 10m PO computes out of
             compression with slope in the break direction (analog of ltf10po).
Episodes/window/tickers derived from the reference hourly events file.

env: PO_EVENTS (for tickers+window), PO_TOPUP, PO_OUT, VARIANT=confirm|ltf10po
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
from fetch_po_comp_options import load_5m, next_friday
from scratch_po_comp_flip_rerun import roll_to_open, LazyBars
import backtest_po_comp_bilbo as B
from indicators import compute_phase_oscillator, atr, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
EVENTS = STUDY / os.environ.get('PO_EVENTS', 'events_v2_eth.csv')
OUT = os.environ.get('PO_OUT', 'box30')
VARIANT = os.environ.get('VARIANT', 'confirm')
OFFSETS = [0.0, 0.5]
WATCH_DAYS = 10


def prep(tkr):
    df5 = load_5m(tkr)
    x5 = df5.between_time('04:00', '19:55')
    r5 = df5.between_time('09:30', '15:55')

    def frame(minutes):
        f = x5.resample(f'{minutes}min').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last')).dropna()
        f = compute_phase_oscillator(f)
        f['po_slope1'] = f['phase_oscillator'].diff(1)
        f['close_ts'] = f.index + pd.Timedelta(minutes=minutes)
        return f
    h30, f10 = frame(30), frame(10)
    dly = r5.resample('1D').agg(open=('open', 'first'), high=('high', 'max'),
                                low=('low', 'min'), close=('close', 'last')).dropna()
    dly['datr14'] = atr(dly, 14)
    dly['ema21_d'] = ema(dly['close'], 21)
    dly['ema21_d_slope3'] = dly['ema21_d'].diff(3)
    dprior = dly.shift(1)
    U = {'h': h30, 'daily_close': dly['close'],
         'm5_t': r5.index.as_unit('ns').asi8 // 10**6,
         'm5_hi': r5['high'].to_numpy(float),
         'm5_lo': r5['low'].to_numpy(float)}
    return {'h30': h30, 'f10': f10, 'dprior': dprior, 'U': U,
            'comp': h30['po_compression'].to_numpy(int)}


def main():
    ref = pd.read_csv(EVENTS)
    tickers = sorted(ref.ticker.unique())
    st = pd.to_datetime(ref.start_ts_et, utc=True)
    w0 = st.min().tz_convert('America/New_York')
    w1_ = st.max().tz_convert('America/New_York')
    con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
    meta = pd.read_sql("SELECT ticker,underlying,type,strike,expiry FROM contracts "
                       "WHERE status='ok'", con)
    con.close()
    opt = LazyBars(STUDY / 'option_bars.sqlite')

    P = {}
    for tkr in tickers:
        P[tkr] = prep(tkr)
        print(f"prepped {tkr}", flush=True)

    rows = []
    funnel = {'episodes': 0, 'locked_boxes': 0, 'entries': 0, 'no_signal': 0,
              'overnight_entries': 0, 'drops_no_fill': 0, 'drops_after_expiry': 0,
              'no_datr': 0}
    for tkr in tickers:
        pt = P[tkr]
        h, comp, f10 = pt['h30'], pt['comp'], pt['f10']
        starts = np.where((comp == 1) & (np.roll(comp, 1) != 1))[0]
        ep_n = 0
        for i in starts:
            if i == 0:
                continue
            ts = h.index[i]
            if ts < w0 or ts > w1_:
                continue
            funnel['episodes'] += 1
            ep_n += 1
            dk = pt['dprior'].loc[:pd.Timestamp(ts.date(), tz='America/New_York')]
            if not len(dk) or pd.isna(dk['datr14'].iloc[-1]):
                funnel['no_datr'] += 1
                continue
            drow = dk.iloc[-1]
            e = {'ep_id': f"{tkr}-30m-{ep_n:04d}", 'ticker': tkr,
                 'datr14_prior': float(drow['datr14']),
                 'ema21_d_slope3': float(drow['ema21_d_slope3'])
                 if np.isfinite(drow['ema21_d_slope3']) else 0.0}
            box_hi = float(h['high'].iloc[i])
            box_lo = float(h['low'].iloc[i])
            grey = 1
            deadline = h['close_ts'].iloc[i] + pd.Timedelta(days=WATCH_DAYS)
            entry = None
            j = i + 1
            while j < len(h):
                if h['close_ts'].iloc[j] > deadline:
                    break
                if comp[j] == 1:
                    grey += 1
                    if grey <= 5:
                        box_hi = max(box_hi, float(h['high'].iloc[j]))
                        box_lo = min(box_lo, float(h['low'].iloc[j]))
                    j += 1
                    continue
                # bar j closes out of compression -> episode resolution bar
                break
            if VARIANT == 'confirm':
                if j < len(h) and comp[j] == 0 and h['close_ts'].iloc[j] <= deadline:
                    hj_hi, hj_lo = float(h['high'].iloc[j]), float(h['low'].iloc[j])
                    hj_cl = float(h['close'].iloc[j])
                    up, dn = hj_hi > box_hi, hj_lo < box_lo
                    if up or dn:
                        dirn = (1 if hj_cl >= (box_hi + box_lo) / 2 else -1) \
                            if (up and dn) else (1 if up else -1)
                        entry = (h['close_ts'].iloc[j], hj_cl, dirn)
            else:  # ltf10po on locked 30m box
                if grey >= 5:
                    funnel['locked_boxes'] += 1
                    lock_ts = h['close_ts'].iloc[i + 4]
                    death_ts = h['close_ts'].iloc[j] if (j < len(h) and comp[j] == 0) \
                        else deadline
                    death_ts = min(death_ts, deadline)
                    seg = f10[(f10['close_ts'] > lock_ts) & (f10['close_ts'] <= death_ts)]
                    for _, b in seg.iterrows():
                        up, dn = b['close'] > box_hi, b['close'] < box_lo
                        if not (up or dn):
                            continue
                        dirn = 1 if up else -1
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
            wf = next_friday(sig_ts.date())
            for bname, exp in [('W1', wf), ('W2', wf + timedelta(days=7))]:
                for off in OFFSETS:
                    for vehicle in ('long', 'short'):
                        if vehicle == 'long':
                            typ = 'call' if direction == 1 else 'put'
                            target = spot + direction * off * e['datr14_prior']
                        else:
                            typ = 'put' if direction == 1 else 'call'
                            target = spot - direction * off * e['datr14_prior']
                        row = B.leg(e, f'box30_{VARIANT}', sig_ts, sig_ms, spot,
                                    direction, bname, exp, off, vehicle, typ,
                                    target, meta, opt, pt['U'], box_hi, box_lo,
                                    funnel)
                        if row:
                            row['sig_raw_ts'] = sig_raw.isoformat()
                            row['rolled_to_open'] = sig_ms != int(sig_raw.timestamp() * 1000)
                            row['flip_bar_closed_grey'] = False
                            row['entry_bar_close_ts'] = sig_raw.isoformat()
                            row['grey_bars_at_entry'] = grey
                            rows.append(row)
        print(f"{tkr}: episodes so far {funnel['episodes']}, entries {funnel['entries']}",
              flush=True)

    tr = pd.DataFrame(rows)
    tr.to_parquet(STUDY / f'{OUT}_trades.parquet')
    print("funnel:", funnel)
    print("legs:", len(tr), "->", STUDY / f'{OUT}_trades.parquet')


if __name__ == '__main__':
    main()
