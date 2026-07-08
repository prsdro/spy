#!/usr/bin/env python3
"""
Bilbo-box variant of the PO-compression options study.

Box = high/low of the FIRST 5 hourly bars of each compression episode
(episodes <5 bars have no box). Entries (all lookahead-safe, 5m-close signals):
  immediate    - first 5m bar crossing box edge after box completes; direction = break side
  retest       - after a break, first 5m touch back to the broken edge (<=7 cal days)
  third_long   - while still inside box: first 5m close in bottom third -> long
  third_short  - while still inside box: first 5m close in top third -> short

Legs: expiry buckets W1/W2/M1 (same Friday anchors as pulled), strike offsets
{0,0.5,1.0}xdATR from ENTRY spot in trade direction, long + short premium.
Box exits: box_stop (hourly close through box midpoint against trade; for third
entries: through the opposite box edge) and box-height measured-move target.
Outputs: bilbo_trades.parquet, bilbo_summary.json.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/root/spy')
from backtest_po_comp_options import (load_all, bar_close_ts, pick_contract,   # noqa
    entry_fill, first_cross_ms, opt_price_at, DATA_END, TP_ALL, SCALES)
from fetch_po_comp_options import load_5m, next_friday  # noqa
from indicators import compute_phase_oscillator  # noqa

STUDY = Path('/root/spy/analyst/po_comp_options')
OFFSETS = [0.0, 0.5, 1.0]
BREAKOUT_WATCH_DAYS = 10
RETEST_DAYS = 7


def ms_of(ts):
    return int(pd.Timestamp(ts).timestamp() * 1000)


def run():
    ev, meta, opt, und = load_all()
    # attach 5m closes + hourly po_compression flags
    m5 = {}
    for tkr in und:
        df5 = load_5m(tkr).between_time('09:30', '15:55')
        m5[tkr] = {'t': df5.index.as_unit('ns').asi8 // 10**6,
                   'hi': df5['high'].to_numpy(float), 'lo': df5['low'].to_numpy(float),
                   'cl': df5['close'].to_numpy(float)}
        h = und[tkr]['h']
        und[tkr]['h_po'] = compute_phase_oscillator(h.copy())

    rows, funnel = [], {'events': 0, 'boxes': 0, 'breakouts': 0, 'retests': 0,
                        'third_long': 0, 'third_short': 0, 'drops_no_fill': 0,
                        'drops_after_expiry': 0}
    for _, e in ev.iterrows():
        funnel['events'] += 1
        tkr = e['ticker']
        H = und[tkr]['h_po']
        start = pd.Timestamp(e['start_ts_et'])
        i = H.index.get_loc(start)
        # box = first min(5, episode_length) compression bars; freezes early if
        # expansion arrives before bar 5
        k = 0
        while i + k < len(H) and k < 5 and H['po_compression'].iloc[i + k] == 1:
            k += 1
        if k == 0 or i + k >= len(H):
            continue
        five = H.iloc[i:i + k]
        funnel['boxes'] += 1
        box_hi, box_lo = five['high'].max(), five['low'].min()
        box_h = box_hi - box_lo
        comp_ms = ms_of(bar_close_ts(five.index[-1]))
        M = m5[tkr]
        watch_to = comp_ms + BREAKOUT_WATCH_DAYS * 86400_000

        sel = (M['t'] >= comp_ms) & (M['t'] <= watch_to)
        idxs = np.where(sel & ((M['hi'] > box_hi) | (M['lo'] < box_lo)))[0]
        entries = []  # (variant, sig_ms, spot, direction)
        br_i = None
        if len(idxs):
            br_i = idxs[0]
            up = M['hi'][br_i] > box_hi
            dn = M['lo'][br_i] < box_lo
            direction = (1 if M['cl'][br_i] >= (box_hi + box_lo) / 2 else -1) \
                if (up and dn) else (1 if up else -1)
            funnel['breakouts'] += 1
            br_ms = M['t'][br_i] + 300_000  # signal at 5m bar close
            entries.append(('immediate', br_ms, M['cl'][br_i], direction))
            # retest of the broken edge
            edge = box_hi if direction == 1 else box_lo
            rsel = (M['t'] > M['t'][br_i]) & (M['t'] <= br_ms + RETEST_DAYS * 86400_000)
            rid = np.where(rsel & ((M['lo'] <= edge) if direction == 1
                                   else (M['hi'] >= edge)))[0]
            if len(rid):
                funnel['retests'] += 1
                entries.append(('retest', M['t'][rid[0]] + 300_000,
                                M['cl'][rid[0]], direction))
        # thirds: only while inside box, before the breakout bar
        end_ms = M['t'][br_i] if br_i is not None else watch_to
        tsel = (M['t'] >= comp_ms) & (M['t'] < end_ms)
        for vname, cond, tdir in [
                ('third_long', M['cl'] <= box_lo + box_h / 3, 1),
                ('third_short', M['cl'] >= box_hi - box_h / 3, -1)]:
            tid = np.where(tsel & cond)[0]
            if len(tid):
                funnel[vname] += 1
                entries.append((vname, M['t'][tid[0]] + 300_000, M['cl'][tid[0]], tdir))

        d0 = start.date()
        w1 = next_friday(d0)
        buckets = {'W1': w1, 'W2': w1 + timedelta(days=7), 'M1': w1 + timedelta(days=21)}
        for variant, sig_ms, spot, direction in entries:
            sig_ts = pd.Timestamp(sig_ms, unit='ms', tz='America/New_York')
            for bname, exp in buckets.items():
                for off in OFFSETS:
                    for vehicle in ('long', 'short'):
                        if vehicle == 'long':
                            typ = 'call' if direction == 1 else 'put'
                            target = spot + direction * off * e['datr14_prior']
                        else:
                            typ = 'put' if direction == 1 else 'call'
                            target = spot - direction * off * e['datr14_prior']
                        row = leg(e, variant, sig_ts, sig_ms, spot, direction, bname,
                                  exp, off, vehicle, typ, target, meta, opt, und[tkr],
                                  box_hi, box_lo, funnel)
                        if row:
                            row['n_box_bars'] = k
                            rows.append(row)
    tr = pd.DataFrame(rows)
    tr.to_parquet(STUDY / 'bilbo_trades.parquet')
    print("funnel:", funnel)
    print("legs:", len(tr))
    return tr


def leg(e, variant, sig_ts, sig_ms, spot, direction, bname, exp, off, vehicle,
        typ, target, meta, opt, U, box_hi, box_lo, funnel):
    c = pick_contract(meta, e['ticker'], exp.isoformat(), typ, target)
    if c is None:
        c = pick_contract(meta, e['ticker'], (exp - timedelta(days=1)).isoformat(),
                          typ, target)
    if c is None:
        return None
    expiry_ts = pd.Timestamp(c.expiry, tz='America/New_York') + pd.Timedelta(hours=16)
    if expiry_ts <= sig_ts:
        funnel['drops_after_expiry'] += 1
        return None
    arr = opt[c.ticker]
    fill = entry_fill(arr, sig_ms)
    if fill is None or fill[0] <= 0.01:
        funnel['drops_no_fill'] += 1
        return None
    entry_px, fill_ms = fill
    expiry_ms = ms_of(expiry_ts)
    censored = expiry_ts > DATA_END + pd.Timedelta(hours=20)

    dc = U['daily_close']
    dkey = dc.index[dc.index.date <= date.fromisoformat(c.expiry)]
    settle = None
    if not censored and len(dkey):
        S = dc.loc[dkey[-1]]
        settle = max(0.0, S - c.strike) if c.type == 'call' else max(0.0, c.strike - S)
    t = arr[:, 0]
    path = arr[(t > fill_ms) & (t <= expiry_ms)]
    exit_mark = settle if settle is not None else (path[-1, 4] if len(path) else entry_px)

    # box stop: hourly close against trade through stop level
    mid = (box_hi + box_lo) / 2
    if variant.startswith('third'):
        stop_lvl = box_lo if direction == 1 else box_hi
    else:
        stop_lvl = mid
    H = U['h']
    hh = H[(H['close_ts'] > sig_ts) & (H['close_ts'] <= min(expiry_ts, DATA_END))]
    inv = hh[hh['close'] < stop_lvl] if direction == 1 else hh[hh['close'] > stop_lvl]
    box_stop_ms = ms_of(inv['close_ts'].iloc[0]) if len(inv) else None

    # box-height measured-move target on underlying (5m extremes)
    box_h = box_hi - box_lo
    tgt = (box_hi + box_h) if direction == 1 else (box_lo - box_h)
    um = first_cross_ms(U['m5_t'], U['m5_hi'] if direction == 1 else U['m5_lo'], tgt,
                        fill_ms, min(expiry_ms, ms_of(DATA_END)), above=direction == 1)

    stop_prem_ms = first_cross_ms(path[:, 0], path[:, 3], 0.5 * entry_px,
                                  fill_ms, expiry_ms, above=False) if len(path) else None

    def long_exit(tp=None, stop_ms=None, und_ms=None):
        tp_ms = first_cross_ms(path[:, 0], path[:, 2], entry_px * (1 + tp),
                               fill_ms, expiry_ms, above=True) if (tp and len(path)) else None
        cand = [(m, 'tp') for m in [tp_ms] if m] + \
               [(m, 'stop') for m in [stop_ms] if m] + \
               [(m, 'und') for m in [und_ms] if m]
        if not cand:
            return exit_mark / entry_px - 1
        m, kind = min(cand, key=lambda x: x[0])
        if kind == 'tp':
            return tp
        if kind == 'stop' and stop_ms == stop_prem_ms:
            return -0.5
        px = opt_price_at(arr, m)
        return (px / entry_px - 1) if px else exit_mark / entry_px - 1

    out = {'ep_id': e['ep_id'], 'ticker': e['ticker'], 'variant': variant,
           'direction': direction, 'bucket': bname, 'offset': off, 'vehicle': vehicle,
           'contract': c.ticker, 'strike': c.strike, 'expiry': c.expiry,
           'entry_ts': sig_ts.isoformat(), 'entry_px': entry_px, 'spot': spot,
           'box_hi': box_hi, 'box_lo': box_lo, 'box_h_atr': box_h / e['datr14_prior'],
           'censored': censored, 'ema21_d_slope3': e['ema21_d_slope3'],
           'dte': (pd.Timestamp(c.expiry).date() - sig_ts.date()).days}
    if vehicle == 'long':
        out['pnl_hold'] = exit_mark / entry_px - 1
        for tp in TP_ALL:
            out[f'pnl_tp{int(tp*100)}'] = long_exit(tp=tp)
        for p1, p2 in SCALES:
            out[f'pnl_sc{int(p1*100)}_{int(p2*100)}'] = 0.5 * (
                long_exit(tp=p1) + long_exit(tp=p2))
        out['pnl_stop50'] = long_exit(stop_ms=stop_prem_ms)
        out['pnl_tp100_stop50'] = long_exit(tp=1.0, stop_ms=stop_prem_ms)
        out['pnl_boxstop'] = long_exit(stop_ms=box_stop_ms)
        out['pnl_tp100_boxstop'] = long_exit(tp=1.0, stop_ms=box_stop_ms)
        out['pnl_boxtgt'] = long_exit(und_ms=um)
        out['pnl_boxtgt_boxstop'] = long_exit(stop_ms=box_stop_ms, und_ms=um)
    else:
        out['pnl_hold'] = 1 - exit_mark / entry_px
        m = first_cross_ms(path[:, 0], path[:, 3], entry_px * 0.5,
                           fill_ms, expiry_ms, above=False) if len(path) else None
        out['pnl_decay50'] = 0.5 if m else out['pnl_hold']
        m2 = first_cross_ms(path[:, 0], path[:, 2], entry_px * 2.0,
                            fill_ms, expiry_ms, above=True) if len(path) else None
        out['pnl_stop2x'] = -1.0 if m2 else out['pnl_hold']
        cand = [x for x in (m2, box_stop_ms) if x]
        if cand:
            mm = min(cand)
            px = opt_price_at(arr, mm) or exit_mark
            out['pnl_stop2x_boxstop'] = -1.0 if mm == m2 else 1 - px / entry_px
        else:
            out['pnl_stop2x_boxstop'] = out['pnl_hold']
    return out


def cstats(df, col):
    g = df.groupby('ep_id')[col].mean()
    n = len(g)
    if n < 3 or g.std(ddof=1) == 0:
        return None
    return {'mean': round(float(g.mean()), 4),
            't': round(float(g.mean() / (g.std(ddof=1) / np.sqrt(n))), 2),
            'n_ev': n, 'win': round(float((df[col] > 0).mean()), 3)}


if __name__ == '__main__':
    tr = run()
    out = {}
    longs = tr[(tr.vehicle == 'long')]
    unc = longs[~longs.censored]
    LEX = ['pnl_hold', 'pnl_tp50', 'pnl_tp100', 'pnl_sc50_80', 'pnl_tp100_stop50',
           'pnl_boxstop', 'pnl_tp100_boxstop', 'pnl_boxtgt', 'pnl_boxtgt_boxstop']
    for v, g in unc.groupby('variant'):
        out[f'long|{v}'] = {ex: cstats(g, ex) for ex in LEX}
        out[f'long|{v}|by_bucket_tp100boxstop'] = {
            str(k): cstats(gg, 'pnl_tp100_boxstop') for k, gg in g.groupby('bucket')}
        out[f'long|{v}|by_offset_tp100boxstop'] = {
            str(k): cstats(gg, 'pnl_tp100_boxstop') for k, gg in g.groupby('offset')}
    shorts = tr[(tr.vehicle == 'short') & (~tr.censored)]
    for v, g in shorts.groupby('variant'):
        out[f'short|{v}'] = {ex: cstats(g, ex) for ex in
                             ['pnl_hold', 'pnl_decay50', 'pnl_stop2x', 'pnl_stop2x_boxstop']}
    best = unc[(unc.variant == 'immediate')]
    out['per_ticker_immediate_long_tp100boxstop'] = {
        str(k): cstats(g, 'pnl_tp100_boxstop') for k, g in best.groupby('ticker')}
    out['direction_split_immediate'] = {
        str(k): cstats(g, 'pnl_tp100_boxstop')
        for k, g in best.groupby('direction')}
    # box-size split (equity-level bilbo study: edge lived in 1-4 bar boxes)
    unc2 = unc.assign(box_sz=np.where(unc.n_box_bars >= 5, '5', '1-4'))
    for v in ['immediate', 'retest']:
        out[f'box_size_split|{v}'] = {
            ex: {str(k): cstats(g, ex) for k, g in unc2[unc2.variant == v].groupby('box_sz')}
            for ex in ['pnl_tp100_stop50', 'pnl_tp100_boxstop', 'pnl_sc50_80', 'pnl_hold']}
    out['box_size_split|direction'] = {
        f"{k[0]}|dir{k[1]}": cstats(g, 'pnl_tp100_stop50')
        for k, g in unc2[unc2.variant == 'retest'].groupby(['box_sz', 'direction'])}
    (STUDY / 'bilbo_summary.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1)[:400], "... (saved)")
