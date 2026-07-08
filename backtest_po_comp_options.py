#!/usr/bin/env python3
"""
Analysis for the hourly PO-compression -> options study (AMZN/NVDA/MSFT).

Builds a per-leg trades table: one row per
(event x entry_variant x direction x expiry_bucket x strike_offset x vehicle)
with P&L columns for every exit rule. Saves:
  analyst/po_comp_options/trades.parquet
  analyst/po_comp_options/summary.json  (headline tables)

Entry timing is lookahead-safe: signals are known at hourly bar CLOSE
(events.csv timestamps are bar-open labels; +60min, or +30min for 15:30 bar).
Fills = actual trade prints (minute aggs); no bid/ask on our data.
"""
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from fetch_po_comp_options import load_5m, hourly_and_daily, next_friday, TICKERS  # noqa
from indicators import ema  # noqa

STUDY = Path('/root/spy/analyst/po_comp_options')
DATA_END = pd.Timestamp('2026-07-06', tz='America/New_York')
ENTRY_WINDOW_MIN = 20      # max staleness/forward wait for an option fill print
OFFSETS = [0.0, 0.5, 1.0]  # dATR multiples OTM in trade direction
TP_ALL = [0.25, 0.5, 0.8, 1.0, 2.0]
SCALES = [(0.5, 0.8), (0.25, 0.5), (0.5, 1.0), (1.0, 2.0)]
SHORT_TP = [0.5, 0.8]      # buy back when premium decays to (1-p)*entry
UND_TARGETS = [0.5, 1.0]   # underlying tags spot +/- k*dATR


def bar_close_ts(label):
    """Hourly bar-open label -> the moment the signal is known (bar close)."""
    ts = pd.Timestamp(label)
    return ts + pd.Timedelta(minutes=30 if ts.hour == 15 and ts.minute == 30 else 60)


def load_all():
    ev = pd.read_csv(STUDY / 'events.csv')
    con = sqlite3.connect(STUDY / 'option_bars.sqlite')
    meta = pd.read_sql("SELECT ticker, underlying, type, strike, expiry FROM contracts "
                       "WHERE status='ok'", con)
    bars = pd.read_sql("SELECT ticker, t, o, h, l, c FROM bars ORDER BY ticker, t", con)
    con.close()
    opt = {k: g[['t', 'o', 'h', 'l', 'c']].to_numpy(float)
           for k, g in bars.groupby('ticker')}
    und = {}
    for tkr in TICKERS:
        df5 = load_5m(tkr)
        h, dly = hourly_and_daily(df5)
        h['ema9'] = ema(h['close'], 9)
        h['ema21'] = ema(h['close'], 21)
        h['close_ts'] = [bar_close_ts(i) for i in h.index]
        rth5 = df5.between_time('09:30', '15:55')
        und[tkr] = {
            'h': h, 'daily_close': dly['close'],
            'm5_t': rth5.index.as_unit('ns').asi8 // 10**6,   # ms epoch (index may be us-resolution)
            'm5_hi': rth5['high'].to_numpy(float),
            'm5_lo': rth5['low'].to_numpy(float),
        }
    return ev, meta, opt, und


def pick_contract(meta, underlying, expiry, typ, target):
    m = meta[(meta.underlying == underlying) & (meta.expiry == expiry) &
             (meta.type == typ)]
    if m.empty:
        return None
    return m.iloc[(m.strike - target).abs().to_numpy().argmin()]


def entry_fill(arr, sig_ms):
    """Last print close <= sig_ms, else first open after; primary 20-min window,
    fallback 60-min (stale fills carry a large fill_lag_min for sensitivity checks).
    Returns (price, fill_ms) or None."""
    t = arr[:, 0]
    for win in (ENTRY_WINDOW_MIN, 60):
        before = np.where((t >= sig_ms - win * 60000) & (t <= sig_ms))[0]
        if len(before):
            i = before[-1]
            return arr[i, 4], t[i]
        after = np.where((t > sig_ms) & (t <= sig_ms + win * 60000))[0]
        if len(after):
            i = after[0]
            return arr[i, 1], t[i]
    return None


def first_cross_ms(t, vals, thresh, ms_from, ms_to, above):
    """First ms in (ms_from, ms_to] where vals crosses thresh."""
    sel = (t > ms_from) & (t <= ms_to)
    if not sel.any():
        return None
    idx = np.where(sel & ((vals >= thresh) if above else (vals <= thresh)))[0]
    return t[idx[0]] if len(idx) else None


def opt_price_at(arr, ms, forward_min=15):
    """Option print at/just after ms (for event-driven exits)."""
    t = arr[:, 0]
    idx = np.where((t >= ms) & (t <= ms + forward_min * 60000))[0]
    if len(idx):
        return arr[idx[0], 4]
    idx = np.where(t <= ms)[0]
    return arr[idx[-1], 4] if len(idx) else None


def run():
    ev, meta, opt, und = load_all()
    rows = []
    drops = {'no_end': 0, 'expired_before_confirm': 0, 'no_contract': 0, 'no_fill': 0}
    for _, e in ev.iterrows():
        tkr = e['ticker']
        datr = e['datr14_prior']
        d0 = pd.Timestamp(e['start_ts_et']).date()
        w1 = next_friday(d0)
        buckets = {'W1': w1, 'W2': w1 + timedelta(days=7), 'M1': w1 + timedelta(days=21)}
        H = und[tkr]['h']
        for entry_name, ts_col, spot_col in [('comp_start', 'start_ts_et', 'spot_start'),
                                             ('expansion_confirm', 'end_ts_et', 'spot_end')]:
            if not isinstance(e[ts_col], str) or e[ts_col] == '':
                drops['no_end'] += 1
                continue
            sig_ts = bar_close_ts(e[ts_col])
            spot = e[spot_col]
            sig_ms = int(sig_ts.timestamp() * 1000)
            # expansion direction (known at confirm bar close): close vs hourly ema21
            hrow = H.loc[H.index == pd.Timestamp(e[ts_col])]
            exp_dir = 1 if (len(hrow) and hrow['close'].iloc[0] >= hrow['ema21'].iloc[0]) else -1
            for direction in (1, -1):
                for bname, exp in buckets.items():
                    for off in OFFSETS:
                        for vehicle in ('long', 'short'):
                            # long: buy option in trade direction, OTM offset in direction
                            # short: sell the opposite-side option, OTM offset AGAINST direction
                            if vehicle == 'long':
                                typ = 'call' if direction == 1 else 'put'
                                target = spot + direction * off * datr
                            else:
                                typ = 'put' if direction == 1 else 'call'
                                target = spot - direction * off * datr
                            row = build_leg(e, entry_name, sig_ts, sig_ms, spot, direction,
                                            bname, exp, off, vehicle, typ, target,
                                            meta, opt, und[tkr], datr, exp_dir, drops)
                            if row:
                                rows.append(row)
    tr = pd.DataFrame(rows)
    tr.to_parquet(STUDY / 'trades.parquet')
    print(f"trades: {len(tr)} legs; drops: {drops}")
    return tr


def build_leg(e, entry_name, sig_ts, sig_ms, spot, direction, bname, exp, off,
              vehicle, typ, target, meta, opt, U, datr, exp_dir, drops):
    expiry_guess = exp.isoformat()
    c = pick_contract(meta, e['ticker'], expiry_guess, typ, target)
    if c is None:  # holiday Friday -> Thursday
        c = pick_contract(meta, e['ticker'],
                          (exp - timedelta(days=1)).isoformat(), typ, target)
    if c is None:
        drops['no_contract'] += 1
        return None
    expiry_ts = pd.Timestamp(c.expiry, tz='America/New_York') + pd.Timedelta(hours=16)
    if expiry_ts <= sig_ts:
        drops['expired_before_confirm'] += 1
        return None
    arr = opt[c.ticker]
    fill = entry_fill(arr, sig_ms)
    if fill is None:
        drops['no_fill'] += 1
        return None
    entry_px, fill_ms = fill
    if entry_px <= 0.01:
        drops['no_fill'] += 1
        return None
    expiry_ms = int(expiry_ts.timestamp() * 1000)
    censored = expiry_ts > DATA_END + pd.Timedelta(hours=20)

    # settlement (intrinsic at expiry close)
    dc = U['daily_close']
    dkey = dc.index[dc.index.date <= date.fromisoformat(c.expiry)]
    settle = None
    if not censored and len(dkey):
        S = dc.loc[dkey[-1]]
        settle = max(0.0, S - c.strike) if c.type == 'call' else max(0.0, c.strike - S)

    # path after entry to expiry
    t = arr[:, 0]
    path = arr[(t > fill_ms) & (t <= expiry_ms)]
    last_px = path[-1, 4] if len(path) else entry_px
    exit_mark = settle if settle is not None else last_px  # censored -> mark

    # stop-trigger times
    stop_prem_ms = first_cross_ms(path[:, 0], path[:, 3], 0.5 * entry_px,
                                  fill_ms, expiry_ms, above=False) if len(path) else None
    # underlying invalidation: hourly close through opposite side of 9-21 ribbon
    H = U['h']
    hh = H[(H['close_ts'] > sig_ts) & (H['close_ts'] <= min(expiry_ts, DATA_END))]
    if direction == 1:
        inv = hh[hh['close'] < hh[['ema9', 'ema21']].min(axis=1)]
    else:
        inv = hh[hh['close'] > hh[['ema9', 'ema21']].max(axis=1)]
    inval_ms = int(inv['close_ts'].iloc[0].timestamp() * 1000) if len(inv) else None

    def long_exit(tp=None, stop_ms=None):
        """P&L fraction of premium for a single full position."""
        tp_ms = first_cross_ms(path[:, 0], path[:, 2], entry_px * (1 + tp),
                               fill_ms, expiry_ms, above=True) if (tp and len(path)) else None
        events = [(m, px) for m, px in [
            (stop_ms, None), (tp_ms, entry_px * (1 + tp) if tp else None)] if m]
        if not events:
            return exit_mark / entry_px - 1
        m, px = min(events, key=lambda x: x[0])
        if px is None:  # stop hit first
            px = (0.5 * entry_px if stop_ms == stop_prem_ms and stop_ms == m
                  else opt_price_at(arr, m) or exit_mark)
        return px / entry_px - 1

    out = {
        'ep_id': e['ep_id'], 'ticker': e['ticker'], 'entry': entry_name,
        'direction': direction, 'bucket': bname, 'offset': off, 'vehicle': vehicle,
        'contract': c.ticker, 'strike': c.strike, 'expiry': c.expiry,
        'dte': (pd.Timestamp(c.expiry).date() - sig_ts.date()).days,
        'entry_ts': sig_ts.isoformat(), 'entry_px': entry_px,
        'fill_lag_min': (sig_ms - fill_ms) / 60000,
        'spot': spot, 'datr': datr, 'censored': censored,
        'exp_dir': exp_dir, 'settle': settle,
        'po_slope1': e['po_slope1'], 'po_slope3': e['po_slope3'],
        'ema21_d_slope1': e['ema21_d_slope1'], 'ema21_d_slope3': e['ema21_d_slope3'],
        'dist_ribbon_atr': (spot - e['ema21_h']) / datr,
    }
    if vehicle == 'long':
        out['pnl_hold'] = exit_mark / entry_px - 1
        for tp in TP_ALL:
            out[f'pnl_tp{int(tp*100)}'] = long_exit(tp=tp)
        for p1, p2 in SCALES:
            out[f'pnl_sc{int(p1*100)}_{int(p2*100)}'] = 0.5 * (
                long_exit(tp=p1) + long_exit(tp=p2))
        out['pnl_stop50'] = long_exit(stop_ms=stop_prem_ms)
        out['pnl_tp100_stop50'] = long_exit(tp=1.0, stop_ms=stop_prem_ms)
        out['pnl_inval'] = long_exit(stop_ms=inval_ms)
        out['pnl_tp100_inval'] = long_exit(tp=1.0, stop_ms=inval_ms)
        # underlying-target exits
        for k in UND_TARGETS:
            thr = spot + direction * k * datr
            um = first_cross_ms(U['m5_t'], U['m5_hi'] if direction == 1 else U['m5_lo'],
                                thr, fill_ms, min(expiry_ms,
                                int(DATA_END.timestamp() * 1000)), above=direction == 1)
            px = opt_price_at(arr, um) if um else None
            out[f'pnl_und{int(k*100)}'] = (px / entry_px - 1) if px else out['pnl_hold']
    else:
        # short premium: pnl fraction of premium received
        out['pnl_hold'] = 1 - exit_mark / entry_px
        for p in SHORT_TP:  # buy back at (1-p) * entry
            m = first_cross_ms(path[:, 0], path[:, 3], entry_px * (1 - p),
                               fill_ms, expiry_ms, above=False) if len(path) else None
            out[f'pnl_decay{int(p*100)}'] = p if m else out['pnl_hold']
        # stop: premium doubles
        m = first_cross_ms(path[:, 0], path[:, 2], entry_px * 2.0,
                           fill_ms, expiry_ms, above=True) if len(path) else None
        out['pnl_stop2x'] = -1.0 if m else out['pnl_hold']
        m2 = min([x for x in (m, inval_ms) if x], default=None)
        if m2:
            px = opt_price_at(arr, m2) or exit_mark
            out['pnl_stop2x_inval'] = 1 - px / entry_px if m2 == inval_ms else -1.0
        else:
            out['pnl_stop2x_inval'] = out['pnl_hold']
    return out


if __name__ == '__main__':
    tr = run()
