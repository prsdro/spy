#!/usr/bin/env python3
"""Pull 1-min NBBO quotes from local Theta Terminal for every contract the
7-year entry set needs (W1 ATM straddle legs). Restartable: contract status
tracked in the sqlite; reruns skip completed contracts.
Output: analyst/po_comp_options/theta/quotes.sqlite
"""
import io
import sqlite3
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings('ignore')
BASE = 'http://localhost:25503/v3'
STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
DB = OUTDIR / 'quotes.sqlite'
MAX_DTE_PULL = 9          # window: entry date -> min(expiry, entry+9d)
import os
SHORT_LEG = os.environ.get('SHORT_LEG', '0') == '1'   # OTM leg for verticals:
# strike nearest spot + direction*0.75*dATR, same type as the directional leg
lock = threading.Lock()


def api(path, params, retries=6):
    for k in range(retries):
        try:
            r = requests.get(f'{BASE}/{path}', params=params, timeout=120)
            if r.status_code == 200:
                return r.text
            if r.status_code == 472:      # no data
                return ''
        except Exception:
            pass
        time.sleep(min(2 ** k, 30))
    return None


def next_friday(d):
    return d + timedelta(days=(4 - d.weekday()) % 7 or 7) \
        if d.weekday() == 4 else d + timedelta(days=(4 - d.weekday()) % 7)


def main():
    ent = pd.read_parquet(OUTDIR / 'theta_entries.parquet')
    ent = ent[ent.intraday]                      # tradeable class only
    print(f'intraday entries: {len(ent)}')

    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS contracts(
        contract TEXT PRIMARY KEY, symbol TEXT, expiration TEXT, strike REAL,
        right TEXT, start_date TEXT, end_date TEXT, status TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS quotes(
        contract TEXT, t INTEGER, bid REAL, ask REAL, bsz INTEGER, asz INTEGER)""")
    con.execute("CREATE INDEX IF NOT EXISTS iq ON quotes(contract, t)")
    con.execute("""CREATE TABLE IF NOT EXISTS entry_legs(
        ep_id TEXT, right TEXT, contract TEXT)""")
    con.commit()

    # resolve expirations + strikes per symbol (cached)
    exps, strikes = {}, {}
    def expirations(sym):
        if sym not in exps:
            txt = api('option/list/expirations', {'symbol': sym})
            e = pd.read_csv(io.StringIO(txt)).expiration if txt else []
            exps[sym] = sorted(pd.to_datetime(e).date if hasattr(
                pd.to_datetime(e), 'date') else [pd.Timestamp(x).date() for x in e])
        return exps[sym]

    def strike_list(sym, exp):
        key = (sym, exp)
        if key not in strikes:
            txt = api('option/list/strikes', {'symbol': sym, 'expiration': exp})
            strikes[key] = sorted(pd.read_csv(io.StringIO(txt)).strike.astype(float)) \
                if txt else []
        return strikes[key]

    have = {r[0] for r in con.execute("SELECT contract FROM contracts WHERE status='ok'")}
    if not SHORT_LEG:
        con.execute("DELETE FROM entry_legs")
    else:
        con.execute("DELETE FROM entry_legs WHERE right IN ('SC','SP')")
    todo = {}
    skip_noexp = 0
    for _, r in ent.iterrows():
        ets = pd.Timestamp(r.entry_ts)
        ed = ets.date()
        nf = next_friday(ed)
        cands = [x for x in expirations(r.ticker)
                 if 2 <= (x - ed).days <= 10]
        if not cands:
            skip_noexp += 1
            continue
        exp = min(cands, key=lambda x: abs((x - nf).days))
        sl = strike_list(r.ticker, exp.isoformat())
        if not sl:
            skip_noexp += 1
            continue
        if SHORT_LEG:
            tgt = r.spot + r.direction * 0.75 * r.datr14_prior
            k = min(sl, key=lambda s: abs(s - tgt))
            rights = (('SC' if r.direction == 1 else 'SP'),)
        else:
            k = min(sl, key=lambda s: abs(s - r.spot))
            rights = ('C', 'P')
        end = min(exp, ed + timedelta(days=MAX_DTE_PULL))
        for right in rights:
            cid = f'{r.ticker}|{exp.isoformat()}|{k:.3f}|{right[-1]}'
            con.execute("INSERT INTO entry_legs VALUES (?,?,?)", (r.ep_id, right, cid))
            if cid in have:
                continue
            if cid in todo:
                s0, e0 = todo[cid][3], todo[cid][4]
                todo[cid] = (r.ticker, exp.isoformat(), k, min(s0, ed), max(e0, end))
            else:
                todo[cid] = (r.ticker, exp.isoformat(), k, ed, end)
    con.commit()
    print(f'contracts to pull: {len(todo)} (done already: {len(have)}, '
          f'entries skipped no-exp/strikes: {skip_noexp})')

    items = list(todo.items())
    np.random.RandomState(7).shuffle(items)    # unbiased partial coverage
    done = [0]

    def pull(item):
        cid, (sym, exp, k, s, e) = item
        right = cid.split('|')[-1][-1]
        txt = api('option/history/quote', {
            'symbol': sym, 'expiration': exp, 'strike': f'{k:.2f}',
            'right': right, 'start_date': s.isoformat(),
            'end_date': e.isoformat(), 'interval': '1m'})
        if txt is None:
            status, rows = 'err', []
        elif not txt.strip() or txt.startswith('Invalid') or 'timestamp' not in txt.split('\n')[0]:
            status, rows = 'empty', []
        else:
            df = pd.read_csv(io.StringIO(txt))
            ts = pd.to_datetime(df.timestamp).dt.tz_localize('America/New_York')
            tms = (ts.astype('int64') // 10**6).tolist()
            rows = list(zip([cid] * len(df), tms,
                            df.bid.astype(float).tolist(),
                            df.ask.astype(float).tolist(),
                            df.bid_size.astype(int).tolist(),
                            df.ask_size.astype(int).tolist()))
            status = 'ok'
        with lock:
            if rows:
                con.executemany("INSERT INTO quotes VALUES (?,?,?,?,?,?)", rows)
            con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?)",
                        (cid, sym, exp, k, right, s.isoformat(), e.isoformat(), status))
            done[0] += 1
            if done[0] % 200 == 0:
                con.commit()
                print(f'{done[0]}/{len(items)} contracts, status={status}', flush=True)
        return status

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(pull, items))
    con.commit()
    st = pd.read_sql('SELECT status, COUNT(*) n FROM contracts GROUP BY status', con)
    nq = con.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]
    print(st.to_string(index=False))
    print(f'quote rows: {nq:,}')
    con.close()
    print('THETA PULL COMPLETE')


if __name__ == '__main__':
    main()
