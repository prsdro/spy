#!/usr/bin/env python3
"""Greeks pull for the surface's ridge cells (Pedro: gamma especially).

For each priced trade in cells {m2_09, a0_09, a0_28, p07_28}: pull hourly
first-order (delta/theta/vega + IV) and second-order (gamma/vanna/charm + IV)
greeks for the ENTRY day and the EXIT day of that trade's contract.
Deduped by (contract, day, order). Stored in theta/greeks.sqlite.
What it buys: real delta per cell (ridge in delta coordinates), gamma
exposure per sleeve, measured post-breakout IV crush (entry vs exit IV),
theta carry per tenor. Restartable; does not touch other DBs.
"""
import io
import sqlite3
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')
BASE = 'http://localhost:25503/v3'
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
DB = OUTDIR / 'greeks.sqlite'
CELLS = ['m2_09', 'a0_09', 'a0_28', 'p07_28']
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
    s = pd.read_parquet(OUTDIR / 'theta_surface.parquet')
    gl = pd.read_sql('SELECT * FROM grid_legs', sqlite3.connect(
        f"file:{OUTDIR/'quotes_grid.sqlite'}?mode=ro", uri=True))
    gl = gl[gl.cell.isin(CELLS)]
    tr = pd.read_parquet(OUTDIR / 'theta_stock_directional_strict.parquet')
    tr = tr[(tr['pop'] == 'hourly') & (tr.direction == 1)][
        ['ticker', 'entry_s', 'exit_s']]
    m = gl.merge(tr, on=['ticker', 'entry_s'], how='inner')
    m['ed'] = pd.to_datetime(m.entry_s, unit='s', utc=True).dt.tz_convert(ET).dt.date
    m['xd'] = pd.to_datetime(m.exit_s, unit='s', utc=True).dt.tz_convert(ET).dt.date
    jobs = {}
    for r in m.itertuples():
        for day in {r.ed, r.xd}:
            for order in ('first_order', 'second_order'):
                jobs[(r.contract, str(day), order)] = True
    print(f'contract-day-order jobs: {len(jobs)}', flush=True)

    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS jobs(
        contract TEXT, day TEXT, ord TEXT, status TEXT,
        PRIMARY KEY(contract, day, ord))""")
    con.execute("""CREATE TABLE IF NOT EXISTS greeks(
        contract TEXT, ord TEXT, t INTEGER, iv REAL, delta REAL, theta REAL,
        vega REAL, gamma REAL, vanna REAL, charm REAL, und REAL)""")
    con.execute("CREATE INDEX IF NOT EXISTS ig ON greeks(contract, ord, t)")
    con.commit()
    done = {tuple(r) for r in con.execute(
        "SELECT contract, day, ord FROM jobs WHERE status='ok'")}
    items = [j for j in jobs if j not in done]
    np.random.RandomState(7).shuffle(items)
    print(f'to pull: {len(items)} (done: {len(done)})', flush=True)
    cnt = [0]

    def pull(job):
        cid, day, order = job
        sym, exp, k, right = cid.split('|')
        txt = api(f'option/history/greeks/{order}', {
            'symbol': sym, 'expiration': exp, 'strike': f'{float(k):.2f}',
            'right': 'C', 'start_date': day, 'end_date': day, 'interval': '1h'})
        rows = []
        status = 'err' if txt is None else 'empty'
        if txt and 'timestamp' in txt.split('\n')[0]:
            df = pd.read_csv(io.StringIO(txt))
            ts = pd.to_datetime(df.timestamp).dt.tz_localize(ET)
            tt = (ts.astype('int64') // 10**9).tolist()
            g = lambda c: df[c].astype(float).tolist() if c in df else [None] * len(df)
            rows = list(zip([cid] * len(df), [order] * len(df), tt,
                            g('implied_vol'), g('delta'), g('theta'), g('vega'),
                            g('gamma'), g('vanna'), g('charm'),
                            g('underlying_price')))
            status = 'ok'
        with lock:
            if rows:
                con.executemany(
                    "INSERT INTO greeks VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            con.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)",
                        (cid, day, order, status))
            cnt[0] += 1
            if cnt[0] % 500 == 0:
                con.commit()
                print(f'{cnt[0]}/{len(items)}', flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(pull, items))
    con.commit()
    n = con.execute('SELECT COUNT(*) FROM greeks').fetchone()[0]
    print(f'greek rows: {n:,}')
    con.close()
    print('GREEKS PULL COMPLETE')


if __name__ == '__main__':
    main()
