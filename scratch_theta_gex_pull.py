#!/usr/bin/env python3
"""GEX (dealer gamma exposure) pull for the hourly-bull signal days.

For each unique (ticker, entry_date) of the 3,833 hourly-bull signals, and
each expiration with 0 < DTE <= 45 on that day:
  - full-chain open interest (one request; OI stamped ~06:30, i.e. prior-day
    OI reported pre-open -> live-knowable before any intraday entry)
  - full-chain 2nd-order greeks at 1h intervals (one request)
Aggregated AT PULL TIME into hourly GEX components per (ticker, day, exp):
  gex_call = sum(gamma * OI * 100 * S^2), gex_put likewise (standard
  convention applies call:+ put:- at analysis; both stored unsigned).
Stored slim in theta/gex.sqlite. Restartable. ~59k requests, overnight-safe.
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

warnings.filterwarnings('ignore')
BASE = 'http://localhost:25503/v3'
OUTDIR = Path('/root/spy/analyst/po_comp_options/theta')
DB = OUTDIR / 'gex.sqlite'
ET = 'America/New_York'
MAX_DTE = 45
lock = threading.Lock()


def api(path, params, retries=6):
    for k in range(retries):
        try:
            import requests
            r = requests.get(f'{BASE}/{path}', params=params, timeout=180)
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
    ent['day'] = ent.ts.dt.tz_convert(ET).dt.date
    ent['hr'] = ent.ts.dt.tz_convert(ET).dt.hour
    days = ent.groupby(['ticker', 'day']).hr.agg(['min', 'max']).reset_index()
    print(f'signal ticker-days: {len(days)}', flush=True)

    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS jobs(
        ticker TEXT, day TEXT, expiration TEXT, status TEXT,
        PRIMARY KEY(ticker, day, expiration))""")
    con.execute("""CREATE TABLE IF NOT EXISTS gex(
        ticker TEXT, day TEXT, expiration TEXT, hour_ts INTEGER,
        gex_call REAL, gex_put REAL, oi_call REAL, oi_put REAL, spot REAL)""")
    con.commit()
    done = {tuple(r) for r in con.execute(
        "SELECT ticker, day, expiration FROM jobs WHERE status='ok'")}

    exps_cache = {}
    def expirations(sym):
        if sym not in exps_cache:
            txt = api('option/list/expirations', {'symbol': sym})
            e = pd.read_csv(io.StringIO(txt)).expiration if txt else []
            exps_cache[sym] = sorted(pd.Timestamp(x).date() for x in e)
        return exps_cache[sym]

    jobs = []
    for r in days.itertuples():
        t0 = f'{max(9, r.min - 1):02d}:30'
        t1 = f'{r.max:02d}:05'
        for exp in expirations(r.ticker):
            dte = (exp - r.day).days
            if 0 < dte <= MAX_DTE:
                j = (r.ticker, str(r.day), exp.isoformat())
                if j not in done:
                    jobs.append((j, t0, t1))
    np.random.RandomState(7).shuffle(jobs)
    print(f'jobs: {len(jobs)} (done: {len(done)})', flush=True)
    cnt = [0]

    def pull(item):
        (sym, day, exp), t0, t1 = item
        oi_txt = api('option/history/open_interest', {
            'symbol': sym, 'expiration': exp,
            'start_date': day, 'end_date': day})
        gk_txt = api('option/history/greeks/second_order', {
            'symbol': sym, 'expiration': exp, 'start_date': day,
            'end_date': day, 'interval': '1h',
            'start_time': t0, 'end_time': t1})
        rows, status = [], 'empty'
        if oi_txt and gk_txt and 'strike' in (oi_txt.split('\n')[0] or '') \
                and 'gamma' in (gk_txt.split('\n')[0] or ''):
            try:
                oi = pd.read_csv(io.StringIO(oi_txt))[
                    ['strike', 'right', 'open_interest']]
                gk = pd.read_csv(io.StringIO(gk_txt))
                gk = gk[(gk.implied_vol > 0.005) & (gk.gamma >= 0)]
                m = gk.merge(oi, on=['strike', 'right'], how='inner')
                m['gexd'] = m.gamma * m.open_interest * 100 \
                    * m.underlying_price ** 2 * 0.0001
                ts = pd.to_datetime(m.timestamp).dt.tz_localize(ET)
                m['hts'] = ts.astype('int64') // 10**9
                for hts, g in m.groupby('hts'):
                    c = g[g.right == 'CALL']
                    p = g[g.right == 'PUT']
                    rows.append((sym, day, exp, int(hts),
                                 float(c.gexd.sum()), float(p.gexd.sum()),
                                 float(c.open_interest.sum()),
                                 float(p.open_interest.sum()),
                                 float(g.underlying_price.iloc[0])))
                status = 'ok'
            except Exception:
                status = 'err'
        elif oi_txt is None or gk_txt is None:
            status = 'err'
        with lock:
            if rows:
                con.executemany(
                    "INSERT INTO gex VALUES (?,?,?,?,?,?,?,?,?)", rows)
            con.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)",
                        (sym, day, exp, status))
            cnt[0] += 1
            if cnt[0] % 500 == 0:
                con.commit()
                print(f'{cnt[0]}/{len(jobs)}', flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(pull, jobs))
    con.commit()
    n = con.execute('SELECT COUNT(*) FROM gex').fetchone()[0]
    st = pd.read_sql('SELECT status, COUNT(*) n FROM jobs GROUP BY status', con)
    print(st.to_string(index=False))
    print(f'gex rows: {n:,}')
    con.close()
    print('GEX PULL COMPLETE')


if __name__ == '__main__':
    main()
