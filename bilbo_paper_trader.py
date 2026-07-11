#!/usr/bin/env python3
"""Bilbo box FORWARD PAPER-TRADING ledger — the final validated system,
recorded live so no backtest bias can operate.

System (frozen 2026-07-10, from the study):
  Universe: the 20 study names. Signal: hourly (ETH-grid, on-the-hour) candle
  that closes out of PO compression AND above the box high (box = first <=5
  grey candles), during RTH, bullish only.
  Gates (all logged, all live-knowable):
    G1 volume: signal-bar volume >= median same-clock-hour volume, prior 20
       sessions.  G2 options market: fresh two-sided quote, spread <= 5%.
    G3 trend (added 2026-07-10): spot >= daily 21 EMA (RTH daily closes
       through the prior completed day). Below-EMA breaks were noise in
       both eras; skipping them moved gated FULL +3.61%->+4.86% t=2.95.
  Position (single sleeve, per Pedro 2026-07-10 off surface v2):
    otm28: CALL strike ~ spot + 0.75*dATR (~1 strike OTM), DTE in [21,37]
    nearest 28. Size guidance: premium <= 3-5% of account.
  Exits (NEW rule, blind-validated at stock level; underlying-keyed,
  evaluated each run on 5m closes; premium never managed):
    invalidation = 5m close < box_lo; after excursion >= 1.0*dATR, exit on
    5m close <= entry + 0.25*best (tolerates 75% give-back of peak);
    time cap 10 trading days (14 calendar).
  Paper fills: option mid +/- half-spread from ThetaData snapshot at the run
  that detects entry/exit (timing lag logged).
Ledger: analyst/po_comp_options/theta/paper_ledger.sqlite
Telegram: entries/exits/skips via hermes. Cron-safe, idempotent per hour.
"""
import io
import json
import sqlite3
import subprocess
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/spy')
from indicators import compute_phase_oscillator, atr, ema

ET = 'America/New_York'
THETA = 'http://localhost:25503/v3'
MASSIVE = 'https://api.massive.com'
LEDGER = Path('/root/spy/analyst/po_comp_options/theta/paper_ledger.sqlite')
UNIV = ['AMZN', 'NVDA', 'MSFT', 'AAPL', 'META', 'GOOGL', 'TSLA', 'AMD',
        'PLTR', 'AVGO', 'NFLX', 'MU', 'COIN', 'SMCI', 'HOOD', 'INTC',
        'UBER', 'BAC', 'JPM', 'DIS']
HERMES = ['/root/.local/bin/hermes', 'send', '--to', 'telegram:7980528578', '-q']


def mkey():
    for line in open('/root/spy/analyst/po_comp_options/../../..'
                     '/spx-chart-app/.env'):
        if line.startswith('POLYGON_API_KEY='):
            return line.strip().split('=', 1)[1]


KEY = mkey()


def m5(sym, days=120):
    to = datetime.utcnow().date()
    frm = to - timedelta(days=days)
    url = (f'{MASSIVE}/v2/aggs/ticker/{sym}/range/5/minute/{frm}/{to}')
    params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': KEY}
    rows = []
    for _ in range(8):    # responses cap ~10-12k rows; follow pagination
        r = requests.get(url, params=params, timeout=60).json()
        rows += r.get('results', [])
        url = r.get('next_url')
        params = {'apiKey': KEY}
        if not url:
            break
    df = pd.DataFrame(rows)
    if not len(df):
        return None
    df['ts'] = pd.to_datetime(df.t, unit='ms', utc=True).dt.tz_convert(ET)
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low',
                            'c': 'close', 'v': 'volume'}).set_index('ts')
    return df[['open', 'high', 'low', 'close', 'volume']].sort_index()


def theta_get(path, params):
    try:
        r = requests.get(f'{THETA}/{path}', params=params, timeout=30)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def option_quote(sym, exp, strike):
    txt = theta_get('option/snapshot/quote',
                    {'symbol': sym, 'expiration': exp,
                     'strike': f'{strike:.2f}', 'right': 'C'})
    if not txt or 'bid' not in txt.split('\n')[0]:
        return None
    df = pd.read_csv(io.StringIO(txt))
    if not len(df) or df.bid.iloc[0] <= 0 or df.ask.iloc[0] <= 0:
        return None
    return float(df.bid.iloc[0]), float(df.ask.iloc[0])


def pick_contract(sym, spot, datr, itm_mult, dte_lo, dte_hi, dte_tgt):
    txt = theta_get('option/list/expirations', {'symbol': sym})
    if not txt:
        return None
    today = pd.Timestamp.now(tz=ET).date()
    exps = [pd.Timestamp(x).date() for x in
            pd.read_csv(io.StringIO(txt)).expiration]
    cands = [x for x in exps if dte_lo <= (x - today).days <= dte_hi]
    if not cands:
        return None
    exp = min(cands, key=lambda x: abs((x - today).days - dte_tgt))
    txt = theta_get('option/list/strikes',
                    {'symbol': sym, 'expiration': exp.isoformat()})
    if not txt:
        return None
    sl = sorted(pd.read_csv(io.StringIO(txt)).strike.astype(float))
    k = min(sl, key=lambda s: abs(s - (spot + itm_mult * datr)))
    return exp.isoformat(), k


MUTE_FLAG = Path('/root/spy/analyst/po_comp_options/theta/.telegram_muted')


def notify(msg):
    if MUTE_FLAG.exists():
        print(f'[muted] {msg}')
        return
    try:
        subprocess.run(HERMES + [msg], timeout=30, capture_output=True)
    except Exception:
        pass


def export_dashboard(con):
    """Dump ledger + live marks to site/data/bilbo-paper.json."""
    sig = pd.read_sql('SELECT * FROM signals ORDER BY bar_close_et DESC', con)
    pos = pd.read_sql('SELECT * FROM positions ORDER BY bar_close_et DESC', con)
    for p in pos.itertuples():
        if p.status != 'open':
            continue
        sym, exp, k, _ = p.contract.split('|')
        q = option_quote(sym, exp, float(k))
        if q:
            mid = (q[0] + q[1]) / 2
            mark = mid - 0.5 * (mid - q[0])
            pos.loc[p.Index, 'mark'] = mark
            pos.loc[p.Index, 'unreal_pct'] = 100 * (mark / p.entry_fill - 1)
    closed = pos[pos.status == 'closed']
    # account equity at ALLOC premium per trade: compound each realized
    # exit in exit order, then layer open positions' marked P&L on top
    ALLOC = 0.04
    eq, series = 1.0, []
    if len(pos):
        first = pos.bar_close_et.min()
        series.append({'t': first, 'eq': 1.0, 'label': 'start'})
    for p in closed.sort_values('exit_logged_et').itertuples():
        eq *= 1 + ALLOC * p.pnl_pct / 100
        series.append({'t': p.exit_logged_et, 'eq': round(eq, 4),
                       'label': f'{p.ticker} {p.pnl_pct:+.1f}%'})
    eq_marked = eq
    for p in pos[pos.status == 'open'].itertuples():
        u = getattr(p, 'unreal_pct', None)
        if u == u and u is not None:
            eq_marked *= 1 + ALLOC * u / 100
    series.append({'t': str(pd.Timestamp.utcnow()), 'eq': round(eq_marked, 4),
                   'label': 'marked (incl. open)'})
    eqs = pd.Series([s['eq'] for s in series])
    wins = closed[closed.pnl_pct > 0]
    loss = closed[closed.pnl_pct <= 0]
    stats = {
        'alloc_pct': 100 * ALLOC,
        'realized_ret': round(100 * (eq - 1), 2),
        'marked_ret': round(100 * (eq_marked - 1), 2),
        'max_dd': round(100 * float((eqs / eqs.cummax() - 1).min()), 2),
        'profit_factor': round(float(wins.pnl_pct.sum() /
                                     abs(loss.pnl_pct.sum())), 2)
        if len(loss) and loss.pnl_pct.sum() < 0 else None,
        'avg_win': round(float(wins.pnl_pct.mean()), 1) if len(wins) else None,
        'avg_loss': round(float(loss.pnl_pct.mean()), 1) if len(loss) else None,
        'open_exposure_pct': round(100 * ALLOC * int((pos.status == 'open').sum()), 1),
    }
    out = {
        'generated_utc': pd.Timestamp.utcnow().isoformat(),
        'muted': MUTE_FLAG.exists(),
        'summary': {
            'signals': len(sig), 'taken': int(sig.taken.sum()),
            'open': int((pos.status == 'open').sum()),
            'closed': len(closed),
            'closed_pnl_mean': round(float(closed.pnl_pct.mean()), 2)
            if len(closed) else None,
            'closed_win': round(100 * float((closed.pnl_pct > 0).mean()))
            if len(closed) else None,
        },
        'stats': stats,
        'equity': series,
        'positions': pos.astype(object).where(pos.notna(), None)
                        .to_dict('records'),
        'signals': sig.astype(object).where(sig.notna(), None)
                      .to_dict('records'),
    }
    Path('/root/spy/site/data/bilbo-paper.json').write_text(
        json.dumps(out, default=str))


def main():
    con = sqlite3.connect(LEDGER)
    con.execute("""CREATE TABLE IF NOT EXISTS signals(
        ticker TEXT, bar_close_et TEXT, spot REAL, box_hi REAL, box_lo REAL,
        grey INTEGER, datr REAL, f_hourrel REAL, taken INTEGER, reason TEXT,
        d21dist REAL, src TEXT DEFAULT 'live',
        PRIMARY KEY(ticker, bar_close_et))""")
    for ddl in ("ALTER TABLE signals ADD COLUMN d21dist REAL",
                "ALTER TABLE signals ADD COLUMN src TEXT DEFAULT 'live'",
                "ALTER TABLE positions ADD COLUMN src TEXT DEFAULT 'live'"):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass    # column already present
    con.execute("""CREATE TABLE IF NOT EXISTS positions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, sleeve TEXT,
        bar_close_et TEXT, contract TEXT, entry_bid REAL, entry_ask REAL,
        entry_fill REAL, entry_logged_et TEXT, spot REAL, box_lo REAL,
        datr REAL, cap_days INTEGER, status TEXT, best_exc REAL,
        exit_fill REAL, exit_reason TEXT, exit_logged_et TEXT, pnl_pct REAL)""")
    con.commit()
    now = pd.Timestamp.now(tz=ET)

    # ---- exits on open positions ----
    for p in con.execute("SELECT id,ticker,sleeve,bar_close_et,contract,"
                         "entry_fill,spot,box_lo,datr,cap_days,best_exc "
                         "FROM positions WHERE status='open'").fetchall():
        (pid, tkr, sleeve, bce, cid, efill, spot, box_lo, datr, cap, best) = p
        bars = m5(tkr, days=14)
        if bars is None:
            continue
        since = bars[bars.index > pd.Timestamp(bce, tz=ET)]
        since = since.between_time('09:30', '15:55')
        if not len(since):
            continue
        best = best or 0
        reason = None
        for ts, b in since.iterrows():
            best = max(best, float(b.high) - spot)
            if b.close < box_lo:
                reason = 'invalidation'
                break
            if best >= 1.0 * datr and b.close <= spot + 0.25 * best:
                reason = 'retrace'
                break
        if not reason and (now - pd.Timestamp(bce, tz=ET)).days >= cap:
            reason = 'timecap'
        con.execute("UPDATE positions SET best_exc=? WHERE id=?", (best, pid))
        if reason:
            sym, exp, k, _ = cid.split('|')
            q = option_quote(sym, exp, float(k))
            if q:
                mid = (q[0] + q[1]) / 2
                fill = mid - 0.5 * (mid - q[0])
                pnl = 100 * (fill / efill - 1)
                con.execute("UPDATE positions SET status='closed',exit_fill=?,"
                            "exit_reason=?,exit_logged_et=?,pnl_pct=? WHERE id=?",
                            (fill, reason, str(now), pnl, pid))
                notify(f'BILBO PAPER EXIT {tkr} {sleeve} {reason} '
                       f'pnl {pnl:+.1f}% (contract {cid})')
    con.commit()

    # ---- new signals: last fully closed on-the-hour bar in RTH ----
    last_close = now.floor('h')
    if now.minute < 1:
        last_close -= pd.Timedelta(hours=1)
    if not (10 <= last_close.hour <= 15) or now.weekday() >= 5:
        con.commit()
        export_dashboard(con)
        con.close()
        print(f'{now} no signal window (last close {last_close})')
        return
    for tkr in UNIV:
        try:
            bars = m5(tkr)
            if bars is None:
                continue
            x5 = bars.between_time('04:00', '19:55')
            h = x5.resample('60min').agg(
                open=('open', 'first'), high=('high', 'max'),
                low=('low', 'min'), close=('close', 'last'),
                volume=('volume', 'sum')).dropna(subset=['close'])
            h = compute_phase_oscillator(h)
            if h.index[-1] != last_close - pd.Timedelta(hours=1):
                continue          # bar for this hour not complete in data
            comp = h['po_compression'].to_numpy(int)
            ci = len(h) - 1
            if comp[ci] != 0:
                continue          # still grey: no confirm
            gb = 0
            while ci - 1 - gb >= 0 and comp[ci - 1 - gb] == 1:
                gb += 1
            if gb < 1:
                continue          # no compression run before this bar
            box = h.iloc[ci - gb: ci - gb + min(gb, 5)]
            box_hi, box_lo = float(box.high.max()), float(box.low.min())
            spot = float(h.close.iloc[ci])
            if spot <= box_hi:
                continue          # not a bull break
            key = str(h.index[ci] + pd.Timedelta(hours=1))
            if con.execute("SELECT 1 FROM signals WHERE ticker=? AND "
                           "bar_close_et=?", (tkr, key)).fetchone():
                continue          # already logged (idempotent)
            # dATR (Wilder 14) from RTH daily
            dly = bars.between_time('09:30', '15:55').resample('1D').agg(
                open=('open', 'first'), high=('high', 'max'),
                low=('low', 'min'), close=('close', 'last')).dropna()
            datr = float(atr(dly, 14).iloc[-2])   # prior completed day
            # G1 volume gate
            same = h[(h.index.hour == h.index[ci].hour) &
                     (h.index.date < h.index[ci].date())].volume[-20:]
            fh = float(h.volume.iloc[ci] / same.median()) if len(same) >= 5 \
                and same.median() > 0 else np.nan
            # G3 trend gate: daily 21 EMA through prior completed day
            e21 = float(ema(dly.close, 21).iloc[-2])
            d21 = (spot - e21) / datr
            taken, reason = 1, 'ok'
            if not np.isfinite(fh) or fh < 1.0:
                taken, reason = 0, f'G1 volume {fh:.2f}<1'
            elif spot < e21:
                taken, reason = 0, f'G3 below d21 EMA ({d21:+.2f} dATR)'
            con.execute("INSERT OR IGNORE INTO signals VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,'live')",
                        (tkr, key, spot, box_hi, box_lo, gb, datr, fh,
                         taken, reason, d21))
            if not taken:
                notify(f'BILBO PAPER SKIP {tkr} @{spot:.2f}: {reason}')
                continue
            for sleeve, mult, lo, hi, tgt, cap in [
                    ('otm28', +0.75, 21, 37, 28, 14)]:
                c = pick_contract(tkr, spot, datr, mult, lo, hi, tgt)
                if not c:
                    notify(f'BILBO PAPER {tkr} {sleeve}: no contract')
                    continue
                exp, k = c
                q = option_quote(tkr, exp, k)
                if not q:
                    notify(f'BILBO PAPER SKIP {tkr} {sleeve}: G2 no market')
                    continue
                bid, ask = q
                mid = (bid + ask) / 2
                spr = 100 * (ask - bid) / mid
                if spr > 5:
                    notify(f'BILBO PAPER SKIP {tkr} {sleeve}: '
                           f'G2 spread {spr:.1f}%>5')
                    continue
                fill = mid + 0.5 * (ask - mid)
                cid = f'{tkr}|{exp}|{k:.3f}|C'
                con.execute(
                    "INSERT INTO positions(ticker,sleeve,bar_close_et,"
                    "contract,entry_bid,entry_ask,entry_fill,entry_logged_et,"
                    "spot,box_lo,datr,cap_days,status,best_exc) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'open',0)",
                    (tkr, sleeve, key, cid, bid, ask, fill, str(now), spot,
                     box_lo, datr, cap))
                notify(f'BILBO PAPER ENTRY {tkr} {sleeve} {cid} fill '
                       f'{fill:.2f} (spread {spr:.1f}%, vol {fh:.2f}x, '
                       f'd21 {d21:+.2f}, spot {spot:.2f})')
        except Exception as e:
            print(f'{tkr}: {e}')
            notify(f'BILBO PAPER ERROR {tkr}: {e}')
        time.sleep(0.3)
    con.commit()
    export_dashboard(con)
    con.close()
    print(f'{now} run complete')


if __name__ == '__main__':
    main()
