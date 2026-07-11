#!/usr/bin/env python3
"""Deep-ITM call pull for the validated stock trades (Pedro: 'if the stock
edge is real, options must be able to juice it').

Pre-declared spec: for each hourly BULL close-confirmed trade (strict set),
contract = CALL, expiration nearest with 7-16 DTE (covers the 5-day cap),
strike = nearest listed to spot - 2.0 x dATR (delta ~0.8+, mostly intrinsic).
Quotes pulled entry date -> exit date +1d. Same terminal, restartable.
Legs map in table deepitm_legs(ticker, entry_s, contract).
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
DB = OUTDIR / 'quotes.sqlite'
ITM_DATR = 2.0
import os
MODE = os.environ.get('MODE', 'deep')  # 'monthly': ATM + OTM(+0.75dATR), 21-37 DTE
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
    tr = pd.read_parquet(OUTDIR / 'theta_stock_directional_strict.parquet')
    tr = tr[(tr['pop'] == 'hourly') & (tr.direction == 1)].copy()
    ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
    ent = ent[ent.intraday & (ent['pop'] == 'hourly') & (ent.direction == 1)].copy()
    ent['ts'] = pd.to_datetime(ent.entry_ts.map(pd.Timestamp), utc=True)
    ent['entry_s'] = ent.ts.map(lambda x: int(x.timestamp()))
    tr = tr.merge(ent[['ticker', 'entry_s', 'spot', 'datr14_prior']],
                  on=['ticker', 'entry_s'], how='inner')
    print(f'bull trades to price: {len(tr)}', flush=True)

    con = sqlite3.connect(DB, check_same_thread=False)
    table = 'monthly_legs' if MODE == 'monthly' else 'deepitm_legs'
    con.execute(f"""CREATE TABLE IF NOT EXISTS {table}(
        ticker TEXT, entry_s INTEGER, kind TEXT, contract TEXT)""")
    con.execute(f"DELETE FROM {table}")
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
    skipped = 0
    for r in tr.itertuples():
        ed = pd.Timestamp(r.entry_s, unit='s', tz='America/New_York').date()
        xd = pd.Timestamp(r.exit_s, unit='s', tz='America/New_York').date()
        lo_d, hi_d = (21, 37) if MODE == 'monthly' else (7, 16)
        cands = [x for x in expirations(r.ticker) if lo_d <= (x - ed).days <= hi_d]
        if not cands:
            skipped += 1
            continue
        exp = min(cands, key=lambda x: abs((x - ed).days - (28 if MODE == 'monthly' else 9)))
        sl = strike_list(r.ticker, exp.isoformat())
        if not sl:
            skipped += 1
            continue
        if MODE == 'monthly':
            targets = [('matm', r.spot), ('motm', r.spot + 0.75 * r.datr14_prior)]
        else:
            targets = [('deep', r.spot - ITM_DATR * r.datr14_prior)]
        end = min(exp, xd + timedelta(days=1))
        for kind, tgt in targets:
            k = min(sl, key=lambda s: abs(s - tgt))
            cid = f'{r.ticker}|{exp.isoformat()}|{k:.3f}|C'
            con.execute(f"INSERT INTO {table} VALUES (?,?,?,?)",
                        (r.ticker, int(r.entry_s), kind, cid))
            if cid in have:
                continue
            if cid in todo:
                s0, e0 = todo[cid][2], todo[cid][3]
                todo[cid] = (r.ticker, exp.isoformat(), min(s0, ed), max(e0, end), k)
            else:
                todo[cid] = (r.ticker, exp.isoformat(), ed, end, k)
    con.commit()
    print(f'contracts to pull: {len(todo)} (skipped {skipped})', flush=True)

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
                            df.ask.astype(float).tolist(),
                            df.bid_size.astype(int).tolist(),
                            df.ask_size.astype(int).tolist()))
            status = 'ok'
        with lock:
            if rows:
                con.executemany("INSERT INTO quotes VALUES (?,?,?,?,?,?)", rows)
            con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?)",
                        (cid, sym, exp, k, 'C', s.isoformat(), e.isoformat(), status))
            done[0] += 1
            if done[0] % 200 == 0:
                con.commit()
                print(f'{done[0]}/{len(items)}', flush=True)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(pull, items))
    con.commit()
    con.close()
    print('DEEPITM PULL COMPLETE')


if __name__ == '__main__':
    main()
