#!/usr/bin/env python3
"""Backfill the paper ledger from study end (2026-07-06 10:00 ET, last
theta_entries hourly-bull entry) through now, per Pedro: "take trades
beginning with where the study ended in the paper account".

Same system as bilbo_paper_trader (single otm28 sleeve, G1/G3 gates, NEW
exit rule), but entries/exits are priced from ThetaData HISTORICAL 1m
quotes at the actual signal/exit timestamps (entry grace 300s, two-sided
only, half-spread fills) — the study's execution conventions, not stale
snapshots. Rows are tagged src='backfill'. Idempotent: skips signals
already in the ledger. Trades still open at run time are inserted as
status='open' with best_exc set, so the live trader manages them onward.
"""
import io
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')
import sys
sys.path.insert(0, '/root/spy')
import bilbo_paper_trader as bt
from indicators import compute_phase_oscillator, atr, ema

ET = 'America/New_York'
START = pd.Timestamp('2026-07-06 10:00', tz=ET)   # strictly-after boundary
GRACE_S = 300


def hist_quotes(sym, exp, strike, day):
    txt = bt.theta_get('option/history/quote', {
        'symbol': sym, 'expiration': exp, 'strike': f'{strike:.2f}',
        'right': 'C', 'start_date': day, 'end_date': day, 'interval': '1m'})
    if not txt or 'timestamp' not in txt.split('\n')[0]:
        return np.zeros((0, 3))
    df = pd.read_csv(io.StringIO(txt))
    ts = pd.to_datetime(df.timestamp).dt.tz_localize(ET)
    q = np.column_stack([(ts.astype('int64') // 10**6).to_numpy(),
                         df.bid.astype(float), df.ask.astype(float)])
    return q[(q[:, 1] > 0) & (q[:, 2] > 0)]


def pick_contract_hist(sym, sig_date, spot, datr):
    txt = bt.theta_get('option/list/expirations', {'symbol': sym})
    if not txt:
        return None
    exps = [pd.Timestamp(x).date() for x in
            pd.read_csv(io.StringIO(txt)).expiration]
    cands = [x for x in exps if 21 <= (x - sig_date).days <= 37]
    if not cands:
        return None
    exp = min(cands, key=lambda x: abs((x - sig_date).days - 28))
    txt = bt.theta_get('option/list/strikes',
                       {'symbol': sym, 'expiration': exp.isoformat()})
    if not txt:
        return None
    sl = sorted(pd.read_csv(io.StringIO(txt)).strike.astype(float))
    k = min(sl, key=lambda s: abs(s - (spot + 0.75 * datr)))
    return exp.isoformat(), k


def update_counterfactuals(con, now):
    """For every skipped signal (taken=0), compute what the trade WOULD have
    done under the exact system: same contract pick, same entry convention,
    same exits — priced from historical quotes. Open counterfactuals are
    marked at their latest quote and refreshed on every run."""
    for c in ("cf_contract TEXT", "cf_fill REAL", "cf_pnl REAL",
              "cf_status TEXT"):
        try:
            con.execute(f"ALTER TABLE signals ADD COLUMN {c}")
        except sqlite3.OperationalError:
            pass
    rows = con.execute(
        "SELECT ticker, bar_close_et, spot, box_lo, datr, cf_contract, "
        "cf_fill FROM signals WHERE taken=0 AND "
        "(cf_status IS NULL OR cf_status='open')").fetchall()
    for tkr, key, spot, box_lo, datr, cfc, cff in rows:
        bar_close = pd.Timestamp(key)
        sig_s = int(bar_close.timestamp())
        if cfc is None:
            c = pick_contract_hist(tkr, bar_close.date(), spot, datr)
            if not c:
                con.execute("UPDATE signals SET cf_status='no contract' "
                            "WHERE ticker=? AND bar_close_et=?", (tkr, key))
                continue
            exp, k = c
            q = hist_quotes(tkr, exp, k, str(bar_close.date()))
            i = np.searchsorted(q[:, 0], sig_s) if len(q) else 0
            if not len(q) or i >= len(q) or q[i, 0] > sig_s + GRACE_S:
                con.execute("UPDATE signals SET cf_status='no market' "
                            "WHERE ticker=? AND bar_close_et=?", (tkr, key))
                continue
            cff = (q[i, 1] + q[i, 2]) / 2 + 0.5 * (q[i, 2] - (q[i, 1] + q[i, 2]) / 2)
            cfc = f'{tkr}|{exp}|{k:.3f}|C'
        sym, exp, k, _ = cfc.split('|')
        bars = bt.m5(tkr)
        if bars is None:
            continue
        rth = bars.between_time('09:30', '15:55')
        since = rth[rth.index > bar_close]
        best, xts = 0.0, None
        for ts5, b in since.iterrows():
            best = max(best, float(b.high) - spot)
            if b.close < box_lo or (best >= 1.0 * datr and
                                    b.close <= spot + 0.25 * best):
                xts = ts5
                break
        if xts is None and (now - bar_close).days >= 14 and len(since):
            xts = since.index[-1]
        status = 'closed' if xts is not None else 'open'
        mday = xts.date() if xts is not None else now.date()
        qx = hist_quotes(sym, exp, float(k), str(mday))
        if not len(qx):
            continue
        ms = int(xts.timestamp()) if xts is not None else int(now.timestamp())
        j = min(np.searchsorted(qx[:, 0], ms), len(qx) - 1)
        xm = (qx[j, 1] + qx[j, 2]) / 2
        xfill = xm - 0.5 * (xm - qx[j, 1])
        pnl = 100 * (xfill / cff - 1)
        con.execute("UPDATE signals SET cf_contract=?, cf_fill=?, cf_pnl=?, "
                    "cf_status=? WHERE ticker=? AND bar_close_et=?",
                    (cfc, cff, pnl, status, tkr, key))
        print(f'CF {tkr} {key}: {status} {pnl:+.1f}% ({cfc})')
    con.commit()


def main():
    con = sqlite3.connect(bt.LEDGER)
    for tbl in ('signals', 'positions'):
        try:
            con.execute(f"ALTER TABLE {tbl} ADD COLUMN src TEXT DEFAULT 'live'")
        except sqlite3.OperationalError:
            pass
    con.commit()
    now = pd.Timestamp.now(tz=ET)
    taken = skipped = 0

    for tkr in bt.UNIV:
        bars = bt.m5(tkr)
        if bars is None:
            print(f'{tkr}: no bars')
            continue
        x5 = bars.between_time('04:00', '19:55')
        h = x5.resample('60min').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last'),
            volume=('volume', 'sum')).dropna(subset=['close'])
        h = compute_phase_oscillator(h)
        comp = h['po_compression'].to_numpy(int)
        dly = bars.between_time('09:30', '15:55').resample('1D').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last')).dropna()
        atr14 = atr(dly, 14)
        e21 = ema(dly.close, 21)
        ddates = np.array([d.date() for d in dly.index])

        for ci in range(1, len(h)):
            bar_close = h.index[ci] + pd.Timedelta(hours=1)
            if not (START < bar_close <= now):
                continue
            if not (10 <= bar_close.hour <= 15) or bar_close.weekday() >= 5:
                continue
            if comp[ci] != 0:
                continue
            gb = 0
            while ci - 1 - gb >= 0 and comp[ci - 1 - gb] == 1:
                gb += 1
            if gb < 1:
                continue
            box = h.iloc[ci - gb: ci - gb + min(gb, 5)]
            box_hi, box_lo = float(box.high.max()), float(box.low.min())
            spot = float(h.close.iloc[ci])
            if spot <= box_hi:
                continue
            key = str(bar_close)
            prior = con.execute("SELECT taken FROM signals WHERE ticker=? AND "
                                "bar_close_et=?", (tkr, key)).fetchone()
            orphan = False
            if prior:
                haspos = con.execute(
                    "SELECT 1 FROM positions WHERE ticker=? AND bar_close_et=?",
                    (tkr, key)).fetchone()
                if not prior[0] or haspos:
                    continue
                orphan = True   # taken=1 but entry crashed: take it now
            di = np.searchsorted(ddates, bar_close.date()) - 1
            if di < 1:
                continue
            datr = float(atr14.iloc[di])
            e21p = float(e21.iloc[di])
            d21 = (spot - e21p) / datr
            same = h[(h.index.hour == h.index[ci].hour) &
                     (h.index.date < h.index[ci].date())].volume[-20:]
            fh = float(h.volume.iloc[ci] / same.median()) if len(same) >= 5 \
                and same.median() > 0 else np.nan
            tk, reason = 1, 'ok'
            if not np.isfinite(fh) or fh < 1.0:
                tk, reason = 0, f'G1 volume {fh:.2f}<1'
            elif spot < e21p:
                tk, reason = 0, f'G3 below d21 EMA ({d21:+.2f} dATR)'
            if not orphan:
                con.execute("INSERT OR IGNORE INTO signals VALUES "
                            "(?,?,?,?,?,?,?,?,?,?,?,'backfill')",
                            (tkr, key, spot, box_hi, box_lo, gb, datr, fh,
                             tk, reason, d21))
            if not tk:
                skipped += 1
                print(f'SKIP {tkr} {key}: {reason}')
                continue
            sig_s = int(bar_close.timestamp())
            c = pick_contract_hist(tkr, bar_close.date(), spot, datr)
            if not c:
                print(f'SKIP {tkr} {key}: no contract')
                skipped += 1
                continue
            exp, k = c
            q = hist_quotes(tkr, exp, k, str(bar_close.date()))
            i = np.searchsorted(q[:, 0], sig_s) if len(q) else 0
            if not len(q) or i >= len(q) or q[i, 0] > sig_s + GRACE_S:
                con.execute("UPDATE signals SET taken=0, reason='G2 no market'"
                            " WHERE ticker=? AND bar_close_et=?", (tkr, key))
                print(f'SKIP {tkr} {key}: G2 no market at signal')
                skipped += 1
                continue
            bid, ask = q[i, 1], q[i, 2]
            mid = (bid + ask) / 2
            spr = 100 * (ask - bid) / mid
            if spr > 5:
                con.execute("UPDATE signals SET taken=0, reason=? WHERE "
                            "ticker=? AND bar_close_et=?",
                            (f'G2 spread {spr:.1f}%>5', tkr, key))
                print(f'SKIP {tkr} {key}: spread {spr:.1f}%')
                skipped += 1
                continue
            efill = mid + 0.5 * (ask - mid)
            cid = f'{tkr}|{exp}|{k:.3f}|C'
            # walk NEW-rule exits on RTH 5m closes after the signal
            rth = bars.between_time('09:30', '15:55')
            since = rth[rth.index > bar_close]
            best, xts, xreason = 0.0, None, None
            for ts5, b in since.iterrows():
                best = max(best, float(b.high) - spot)
                if b.close < box_lo:
                    xts, xreason = ts5, 'invalidation'
                    break
                if best >= 1.0 * datr and b.close <= spot + 0.25 * best:
                    xts, xreason = ts5, 'retrace'
                    break
            if xts is None and (now - bar_close).days >= 14:
                xts, xreason = since.index[-1], 'timecap'
            status, xfill, pnl, xlog = 'open', None, None, None
            if xts is not None:
                qx = hist_quotes(tkr, exp, k, str(xts.date()))
                xs = int(xts.timestamp())
                j = min(np.searchsorted(qx[:, 0], xs), len(qx) - 1) \
                    if len(qx) else -1
                if j >= 0:
                    xm = (qx[j, 1] + qx[j, 2]) / 2
                    xfill = xm - 0.5 * (xm - qx[j, 1])
                    pnl = 100 * (xfill / efill - 1)
                    status, xlog = 'closed', str(xts)
            con.execute(
                "INSERT INTO positions(ticker,sleeve,bar_close_et,contract,"
                "entry_bid,entry_ask,entry_fill,entry_logged_et,spot,box_lo,"
                "datr,cap_days,status,best_exc,exit_fill,exit_reason,"
                "exit_logged_et,pnl_pct,src) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'backfill')",
                (tkr, 'otm28', key, cid, bid, ask, efill, str(now), spot,
                 box_lo, datr, 14, status, best,
                 xfill, xreason if status == 'closed' else None, xlog, pnl))
            taken += 1
            px = f'{pnl:+.1f}%' if pnl is not None else 'open'
            print(f'TAKE {tkr} {key} {cid} fill {efill:.2f} -> {status} {px}')
    con.commit()
    update_counterfactuals(con, now)
    bt.export_dashboard(con)
    con.close()
    print(f'\nbackfill: {taken} taken, {skipped} skipped. DONE')


if __name__ == '__main__':
    main()
