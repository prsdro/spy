#!/usr/bin/env python3
"""Moneyness x tenor surface pull: 12 cells on the same 3,833 validated
hourly-bull entries. Strike offset in dATR (negative = ITM call), tenor as
DTE band. Windows entry -> min(expiry, entry+11d) to support 5d AND 10d
management variants. Separate DB (quotes_grid.sqlite), restartable.
"""
import io
import sqlite3
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')
BASE = 'http://localhost:25503/v3'
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
DB = OUTDIR / 'quotes_grid.sqlite'
lock = threading.Lock()
CELLS = [  # (name, moneyness_datr, dte_lo, dte_hi, dte_target)
    ('m2_09', -2.0, 7, 16, 9), ('m1_09', -1.0, 7, 16, 9),
    ('a0_09', 0.0, 7, 16, 9), ('p07_09', 0.75, 7, 16, 9),
    ('m2_28', -2.0, 21, 37, 28), ('m1_28', -1.0, 21, 37, 28),
    ('a0_28', 0.0, 21, 37, 28), ('p07_28', 0.75, 21, 37, 28),
    ('p15_28', 1.5, 21, 37, 28),
    ('m1_45', -1.0, 38, 56, 45), ('a0_45', 0.0, 38, 56, 45),
    ('p07_45', 0.75, 38, 56, 45),
]


def api(path, params, retries=6):
    for k in range(retries):
        try:
            r = requests.get(f'{BASE}/{path}', params=params, timeout=120)
            if r.status_code == 200:
                return r.text
            if r.status_code == 472:
                return ''
        except Exception:
            pass
        time.sleep(min(2 ** k, 30))
    return None


def main():
    ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
    ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
    ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
    ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
    print(f'entries: {len(ent)}', flush=True)

    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS contracts(
        contract TEXT PRIMARY KEY, status TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS quotes(
        contract TEXT, t INTEGER, bid REAL, ask REAL)""")
    con.execute("CREATE INDEX IF NOT EXISTS iq ON quotes(contract, t)")
    con.execute("""CREATE TABLE IF NOT EXISTS grid_legs(
        ticker TEXT, entry_s INTEGER, cell TEXT, contract TEXT)""")
    con.execute("DELETE FROM grid_legs")
    con.commit()
    have = {r[0] for r in con.execute(
        "SELECT contract FROM contracts WHERE status='ok'")}

    exps, strikes = {}, {}
    def expirations(sym):
        if sym not in exps:
            txt = api('option/list/expirations', {'symbol': sym})
            e = pd.read_csv(io.StringIO(txt)).expiration if txt else []
            exps[sym] = sorted(pd.Timestamp(x).date() for x in e)
        return exps[sym]

    def strike_list(sym, exp):
        key = (sym, exp)
        if key not in strikes:
            txt = api('option/list/strikes', {'symbol': sym, 'expiration': exp})
            strikes[key] = sorted(pd.read_csv(io.StringIO(txt)).strike.astype(float)) \
                if txt else []
        return strikes[key]

    todo = {}
    for r in ent.itertuples():
        ed = pd.Timestamp(r.entry_s, unit='s', tz='America/New_York').date()
        wend = ed + timedelta(days=11)
        elist = expirations(r.ticker)
        for cname, mny, lo, hi, tgt_dte in CELLS:
            cands = [x for x in elist if lo <= (x - ed).days <= hi]
            if not cands:
                continue
            exp = min(cands, key=lambda x: abs((x - ed).days - tgt_dte))
            sl = strike_list(r.ticker, exp.isoformat())
            if not sl:
                continue
            tgt = r.spot + mny * r.datr14_prior
            k = min(sl, key=lambda s: abs(s - tgt))
            cid = f'{r.ticker}|{exp.isoformat()}|{k:.3f}|C'
            con.execute("INSERT INTO grid_legs VALUES (?,?,?,?)",
                        (r.ticker, int(r.entry_s), cname, cid))
            end = min(exp, wend)
            if cid in have:
                continue
            if cid in todo:
                s0, e0 = todo[cid][2], todo[cid][3]
                todo[cid] = (r.ticker, exp.isoformat(), min(s0, ed), max(e0, end), k)
            else:
                todo[cid] = (r.ticker, exp.isoformat(), ed, end, k)
    con.commit()
    print(f'contracts to pull: {len(todo)}', flush=True)

    items = list(todo.items())
    np.random.RandomState(7).shuffle(items)
    done = [0]

    def pull(item):
        cid, (sym, exp, s, e, k) = item
        txt = api('option/history/quote', {
            'symbol': sym, 'expiration': exp, 'strike': f'{k:.2f}',
            'right': 'C', 'start_date': s.isoformat(),
            'end_date': e.isoformat(), 'interval': '1m'})
        if txt is None:
            status, rows = 'err', []
        elif not txt.strip() or 'timestamp' not in txt.split('\n')[0]:
            status, rows = 'empty', []
        else:
            df = pd.read_csv(io.StringIO(txt))
            ts = pd.to_datetime(df.timestamp).dt.tz_localize('America/New_York')
            tms = (ts.astype('int64') // 10**6).tolist()
            rows = list(zip([cid]*len(df), tms, df.bid.astype(float).tolist(),
                            df.ask.astype(float).tolist()))
            status = 'ok'
        with lock:
            if rows:
                con.executemany("INSERT INTO quotes VALUES (?,?,?,?)", rows)
            con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?)", (cid, status))
            done[0] += 1
            if done[0] % 500 == 0:
                con.commit()
                print(f'{done[0]}/{len(items)}', flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(pull, items))
    con.commit()
    nq = con.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]
    print(f'quote rows: {nq:,}')
    con.close()
    print('GRID PULL COMPLETE')


if __name__ == '__main__':
    main()
