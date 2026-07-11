#!/usr/bin/env python3
"""Entry-search pipeline: COPY of scratch_po_comp_flip_rerun.py extended with
re-poke entry modes (do not edit the original).

New env:
  REPOKE=same    box locked at BOX_LOCK_BARS grey bars (WAIT_FULL_BOX
                 semantics implied). If the episode's FIRST 5m poke of a box
                 edge closes back INSIDE the box (failed poke), enter at the
                 SECOND poke of the SAME edge (signal = that 5m bar close).
                 If the first poke closes outside the box (it "worked"), no
                 trade — that episode belongs to the first-poke strategy.
  REPOKE=either  same, but the second poke may be of EITHER edge; direction =
                 the edge poked (close vs box mid if both in one bar).

Original doc below.
--------------------------------------------------------------------------
Flip-rule rerun of the Bilbo-box options study (diagnostic — page NOT updated).

Entry semantics change vs backtest_po_comp_v3.py ('immediate' variant):
  - Walk each compression episode live, hourly bar by hourly bar (ETH grid).
  - Box = range of completed grey bars so far, frozen after 5 (same freeze rule).
  - At each 5m bar that pokes outside the current box, compute the PO
    compression flag on the FORMING hourly bar (partial OHLC up to that 5m
    close) with an exact incremental update of the indicator recursion.
  - Enter at that 5m close iff the forming bar computes OUT of compression.
    All completed bars so far are grey by construction (episode dies at the
    first hourly close out of compression with no entry).
  - First valid entry per episode only. No information from any later close.

Everything else (option contract pick, fills, exits, leg grid) reuses the
published study's own machinery (backtest_po_comp_bilbo.leg).

Usage: PO_EVENTS=events_v2_eth.csv PO_TOPUP=underlying_5m_topup_v2.parquet \
       PO_OUT=flip8 python3 scratch_po_comp_flip_rerun.py
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
from fetch_po_comp_options import load_5m, hourly_and_daily, next_friday
import backtest_po_comp_bilbo as B
from backtest_po_comp_bilbo import ms_of
from indicators import compute_phase_oscillator, atr, stdev, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
EVENTS = STUDY / os.environ.get('PO_EVENTS', 'events_v2_eth.csv')
OUT = os.environ.get('PO_OUT', 'flip8')
OFFSETS = [0.0, 0.5]
WATCH_DAYS = 10
# BOX_MODE=freeze5: box frozen after 5 grey bars (published rule)
# BOX_MODE=extend:  box keeps extending with every grey close (Pedro semantics)
BOX_MODE = os.environ.get('BOX_MODE', 'freeze5')
# FIRST_POKE_ONLY=1: decide at the episode's first 5m edge-cross; if the
# forming bar still computes grey there, the episode is dead (no re-arming).
FIRST_POKE_ONLY = os.environ.get('FIRST_POKE_ONLY', '0') == '1'
# CONFIRM_CLOSE=1: no intrabar entries at all — enter at the hourly close of
# the first bar that BOTH closes out of compression AND broke the box range.
# Zero false-fires by construction; pays the wait-for-close entry giveup.
CONFIRM_CLOSE = os.environ.get('CONFIRM_CLOSE', '0') == '1'
# NO_FLAG=1: pure price rule — enter at the first 5m poke outside the box of
# completed grey bars, no oscillator check. The strict live version of the
# published entry (which locked short boxes using the eventual bar close).
NO_FLAG = os.environ.get('NO_FLAG', '0') == '1'
# WAIT_FULL_BOX=1: only watch for breaks once the box has locked (BOX_LOCK_BARS
# grey bars completed, live-knowable). Episodes that flip earlier: no trade.
WAIT_FULL_BOX = os.environ.get('WAIT_FULL_BOX', '0') == '1'
# BOX_LOCK_BARS: grey bars that lock the box (canonical 5; try 3 for a faster
# live-knowable lock).
BOX_LOCK_BARS = int(os.environ.get('BOX_LOCK_BARS', '5'))
# MULTI_ENTRY=1: don't stop at the first fired entry. If the entry bar closes
# grey (false fire), keep walking and emit subsequent attempts — the analysis
# chains them with a bail-at-bar-close-if-red rule. Attempt order in
# 'attempt_seq'.
MULTI_ENTRY = os.environ.get('MULTI_ENTRY', '0') == '1'
MAX_ATTEMPTS = 6
# REPOKE: '', 'same', 'either' (see module doc). Implies NO_FLAG + locked box.
REPOKE = os.environ.get('REPOKE', '')
if REPOKE:
    NO_FLAG = True
    WAIT_FULL_BOX = True


def bar_close(label):  # ETH hourly grid
    return pd.Timestamp(label) + pd.Timedelta(minutes=60)


def roll_to_open(ts):
    t = ts
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


def prep_ticker(tkr):
    """Hourly indicator state + 5m arrays, mirroring the published run."""
    df5 = load_5m(tkr)
    h, dly = hourly_and_daily(df5, session='ETH')
    h = compute_phase_oscillator(h)
    h['close_ts'] = [bar_close(i) for i in h.index]
    # series needed for the exact incremental partial-bar flag
    closes = h['close'].to_numpy(float)
    atr14 = atr(h, 14).to_numpy(float)
    std21 = stdev(h['close'], 21).to_numpy(float)
    comp_val = 2.0 * (std21 - atr14)          # == both branches of the Pine where()
    r5 = df5.between_time('09:30', '15:55')
    x5 = df5.between_time('04:00', '19:55')
    U = {'h': h, 'daily_close': dly['close'],
         'm5_t': r5.index.as_unit('ns').asi8 // 10**6,
         'm5_hi': r5['high'].to_numpy(float),
         'm5_lo': r5['low'].to_numpy(float)}
    return {'h': h, 'closes': closes, 'atr14': atr14, 'comp_val': comp_val,
            'x5': x5, 'U': U,
            'hcomp': h['po_compression'].to_numpy(int)}


def provisional_flag(P, j, p_hi, p_lo, p_cl):
    """PO compression flag for a partial bar replacing hour j, exactly as
    compute_phase_oscillator would set it at that instant.
    Needs: last 20 completed closes, ATR14/comp_val at j-1."""
    closes, atr14, comp_val = P['closes'], P['atr14'], P['comp_val']
    prev_c = closes[j - 1]
    tr = max(p_hi - p_lo, abs(p_hi - prev_c), abs(p_lo - prev_c))
    atr_p = atr14[j - 1] + (tr - atr14[j - 1]) / 14.0        # Wilder RMA step
    w = np.append(closes[max(0, j - 20):j], p_cl)            # 21-window std
    std_p = w.std(ddof=1) if len(w) > 1 else np.nan
    cv = 2.0 * (std_p - atr_p)
    inexp = 2.0 * std_p - 1.854 * atr_p
    if (cv >= comp_val[j - 1]) and (inexp > 0):
        return 0
    return 1 if cv <= 0 else 0


def validate_flag(P):
    """Feed each completed bar as its own 'partial' — must reproduce
    po_compression exactly."""
    h = P['h']
    hi, lo, cl = h['high'].to_numpy(float), h['low'].to_numpy(float), P['closes']
    bad = 0
    for j in range(30, len(h)):
        if provisional_flag(P, j, hi[j], lo[j], cl[j]) != P['hcomp'][j]:
            bad += 1
    return bad, len(h) - 30


def main():
    ev = pd.read_csv(EVENTS)
    con = sqlite3.connect(f"file:{STUDY/'option_bars.sqlite'}?mode=ro", uri=True)
    meta = pd.read_sql("SELECT ticker,underlying,type,strike,expiry FROM contracts "
                       "WHERE status='ok'", con)
    con.close()
    opt = LazyBars(STUDY / 'option_bars.sqlite')

    P = {}
    for tkr in ev.ticker.unique():
        P[tkr] = prep_ticker(tkr)
        bad, tot = validate_flag(P[tkr])
        print(f"prepped {tkr}: incremental-flag validation {tot-bad}/{tot} match", flush=True)
        if bad:
            print(f"  !! {bad} mismatches — investigate before trusting results")

    rows = []
    funnel = {'events': 0, 'walked': 0, 'entries': 0, 'pokes_checked': 0,
              'died_no_break': 0, 'false_fire': 0, 'overnight_entries': 0,
              'drops_no_fill': 0, 'drops_after_expiry': 0}
    for _, e in ev.iterrows():
        funnel['events'] += 1
        tkr = e['ticker']
        pt = P[tkr]
        h, x5 = pt['h'], pt['x5']
        start = pd.Timestamp(e['start_ts_et'])
        try:
            i = h.index.get_loc(start)
        except KeyError:
            continue
        funnel['walked'] += 1
        box_hi = float(h['high'].iloc[i])
        box_lo = float(h['low'].iloc[i])
        grey = 1
        deadline = bar_close(start) + pd.Timedelta(days=WATCH_DAYS)
        attempts = []           # (sig_ts_raw, spot, direction, grey_at_entry, j, box_hi, box_lo)
        dead = False
        first_edge = None       # REPOKE state: edge of the episode's first poke
        j = i + 1
        while j < len(h) and not dead:
            h0 = h.index[j]
            if bar_close(h0) > deadline:
                break
            if CONFIRM_CLOSE:
                hj_hi, hj_lo = float(h['high'].iloc[j]), float(h['low'].iloc[j])
                hj_cl = float(h['close'].iloc[j])
                if pt['hcomp'][j] == 0:
                    up, dn = hj_hi > box_hi, hj_lo < box_lo
                    if up or dn:
                        dirn = (1 if hj_cl >= (box_hi + box_lo) / 2 else -1) \
                            if (up and dn) else (1 if up else -1)
                        attempts.append((bar_close(h0), hj_cl, dirn, grey, j,
                                         box_hi, box_lo))
                    else:
                        funnel['died_no_break'] += 1
                    break
                grey += 1
                if BOX_MODE == 'extend' or grey <= BOX_LOCK_BARS:
                    box_hi = max(box_hi, hj_hi)
                    box_lo = min(box_lo, hj_lo)
                j += 1
                continue
            seg = x5.loc[h0:h0 + pd.Timedelta(minutes=55)]
            p_hi = p_lo = None
            fired_this_bar = False
            for ts5, b in seg.iterrows():
                p_hi = b['high'] if p_hi is None else max(p_hi, b['high'])
                p_lo = b['low'] if p_lo is None else min(p_lo, b['low'])
                up, dn = b['high'] > box_hi, b['low'] < box_lo
                if not (up or dn):
                    continue
                if WAIT_FULL_BOX and grey < BOX_LOCK_BARS:
                    continue
                funnel['pokes_checked'] += 1
                if REPOKE:
                    edge = ('up' if b['close'] >= (box_hi + box_lo) / 2 else 'dn') \
                        if (up and dn) else ('up' if up else 'dn')
                    if first_edge is None:
                        first_edge = edge
                        if not (box_lo <= b['close'] <= box_hi):
                            # first poke closed OUTSIDE the box: it worked ->
                            # first-poke territory, no re-poke trade
                            funnel.setdefault('repoke_first_worked', 0)
                            funnel['repoke_first_worked'] += 1
                            dead = True
                            break
                        funnel.setdefault('repoke_armed', 0)
                        funnel['repoke_armed'] += 1
                        continue
                    if REPOKE == 'same' and edge != first_edge:
                        continue
                    dirn = 1 if edge == 'up' else -1
                    attempts.append((ts5 + pd.Timedelta(minutes=5),
                                     float(b['close']), dirn, grey, j,
                                     box_hi, box_lo))
                    fired_this_bar = True
                    break
                if not NO_FLAG and provisional_flag(pt, j, p_hi, p_lo, b['close']) == 1:
                    # still computes grey mid-bar -> not a breakout
                    if FIRST_POKE_ONLY:
                        dead = True
                        break
                    continue
                dirn = (1 if b['close'] >= (box_hi + box_lo) / 2 else -1) \
                    if (up and dn) else (1 if up else -1)
                attempts.append((ts5 + pd.Timedelta(minutes=5), float(b['close']),
                                 dirn, grey, j, box_hi, box_lo))
                if pt['hcomp'][j] == 1:      # bar later closed grey after all
                    funnel['false_fire'] += 1
                fired_this_bar = True
                break
            if dead:
                break
            if fired_this_bar:
                # stop unless MULTI_ENTRY and the entry bar closed grey
                # (false fire -> analysis bails at bar close and re-arms)
                if not (MULTI_ENTRY and pt['hcomp'][j] == 1) \
                        or len(attempts) >= MAX_ATTEMPTS:
                    break
            if pt['hcomp'][j] == 1:          # closed grey: extend and go on
                grey += 1
                if BOX_MODE == 'extend' or grey <= BOX_LOCK_BARS:
                    box_hi = max(box_hi, float(h['high'].iloc[j]))
                    box_lo = min(box_lo, float(h['low'].iloc[j]))
                j += 1
                continue
            funnel['died_no_break'] += 1     # closed expansion, no valid poke
            break

        if not attempts:
            continue
        funnel['entries'] += 1
        for seq, (sig_raw, spot, direction, grey_at, jbar,
                  a_box_hi, a_box_lo) in enumerate(attempts):
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
                        row = B.leg(e, 'flip', sig_ts, sig_ms, spot, direction,
                                    bname, exp, off, vehicle, typ, target, meta,
                                    opt, pt['U'], a_box_hi, a_box_lo, funnel)
                        if row:
                            row['n_box_bars'] = min(grey_at, BOX_LOCK_BARS)
                            row['grey_bars_at_entry'] = grey_at
                            row['attempt_seq'] = seq
                            row['sig_raw_ts'] = sig_raw.isoformat()
                            row['rolled_to_open'] = sig_ms != int(sig_raw.timestamp() * 1000)
                            row['flip_bar_closed_grey'] = bool(P[tkr]['hcomp'][jbar] == 1)
                            row['entry_bar_close_ts'] = bar_close(h.index[jbar]).isoformat()
                            rows.append(row)
        if funnel['events'] % 250 == 0:
            print(f"...{funnel['events']}/{len(ev)} events, {len(rows)} legs", flush=True)

    tr = pd.DataFrame(rows)
    tr.to_parquet(STUDY / f'{OUT}_trades.parquet')
    print("funnel:", funnel)
    print("legs:", len(tr), "->", STUDY / f'{OUT}_trades.parquet')


if __name__ == '__main__':
    main()
