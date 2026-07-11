#!/usr/bin/env python3
"""Quote-window top-up for the new exit rule (arm 1.0 / retrace 0.25 /
cap 10 TRADING days ~ 14cd). Original grid windows end at entry+11cd;
~25% of new-rule exits land beyond that. For every grid leg whose new
exit exceeds its contract's last pulled quote, pull the missing tail
(last-covered day -> min(expiry, exit day + 1)). Same request shape and
timestamp math as scratch_theta_grid_pull.py (t in epoch seconds via the
datetime64[us] // 10**6 path). Separate DB: quotes_grid_topup.sqlite.
Restartable; read-only on quotes_grid.sqlite.
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
DB = OUTDIR / 'quotes_grid_topup.sqlite'
ET = 'America/New_York'
lock = threading.Lock()


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
    x = pd.read_parquet(OUTDIR / 'theta_newrule_exits.parquet')
    src = sqlite3.connect(f"file:{OUTDIR/'quotes_grid.sqlite'}?mode=ro", uri=True)
    legs = pd.read_sql('SELECT * FROM grid_legs', src)
    last = pd.read_sql('SELECT contract, MAX(t) mx FROM quotes GROUP BY contract',
                       src)
    src.close()
    m = legs.merge(x, on=['ticker', 'entry_s']).merge(last, on='contract',
                                                      how='left')
    m = m[m.exit_new_s > m.mx.fillna(0)]
    print(f'legs needing tail quotes: {len(m)}', flush=True)

    # one window per contract: [day after last covered, min(expiry, exit+1d)]
    todo = {}
    for r in m.itertuples():
        sym, exp, k, _ = r.contract.split('|')
        expd = pd.Timestamp(exp).date()
        s = (pd.Timestamp(int(r.mx), unit='s', tz=ET).date()
             if r.mx == r.mx and r.mx else
             pd.Timestamp(r.entry_s, unit='s', tz=ET).date())
        e = min(expd, pd.Timestamp(r.exit_new_s, unit='s', tz=ET).date()
                + timedelta(days=1))
        if s >= e:
            continue          # contract expired before the tail: nothing exists
        if r.contract in todo:
            s0, e0 = todo[r.contract][2:4]
            todo[r.contract] = (sym, exp, min(s0, s), max(e0, e), float(k))
        else:
            todo[r.contract] = (sym, exp, s, e, float(k))
    print(f'contracts to pull: {len(todo)}', flush=True)

    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS contracts(
        contract TEXT PRIMARY KEY, status TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS quotes(
        contract TEXT, t INTEGER, bid REAL, ask REAL)""")
    con.execute("CREATE INDEX IF NOT EXISTS iq ON quotes(contract, t)")
    con.commit()
    have = {r[0] for r in con.execute(
        "SELECT contract FROM contracts WHERE status='ok'")}
    items = [(c, v) for c, v in todo.items() if c not in have]
    np.random.RandomState(7).shuffle(items)
    print(f'to pull now: {len(items)} (done: {len(have)})', flush=True)
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
            ts = pd.to_datetime(df.timestamp).dt.tz_localize(ET)
            tms = (ts.astype('int64') // 10**6).tolist()
            rows = list(zip([cid] * len(df), tms, df.bid.astype(float).tolist(),
                            df.ask.astype(float).tolist()))
            status = 'ok'
        with lock:
            if rows:
                con.executemany("INSERT INTO quotes VALUES (?,?,?,?)", rows)
            con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?)",
                        (cid, status))
            done[0] += 1
            if done[0] % 250 == 0:
                con.commit()
                print(f'{done[0]}/{len(items)}', flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(pull, items))
    con.commit()
    nq = con.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]
    print(f'topup quote rows: {nq:,}')
    con.close()
    print('TOPUP COMPLETE')


if __name__ == '__main__':
    main()
