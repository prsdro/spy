#!/usr/bin/env python3
"""
Hourly PO-compression -> options study: data pull for AMZN, NVDA, MSFT.

Phases (idempotent, checkpointed; safe to kill and rerun):
  1. Top up underlying 5m bars from Massive (local parquet ends 2026-05-07/08).
  2. Build hourly-compression episode list -> events.csv (deterministic, always rebuilt).
  3. Fetch option chains per (ticker, expiry), cache to chains/ dir; build contract todo list.
  4. Pull minute aggregates per unique contract into option_bars.sqlite (priority-ordered).

Progress: analyst/po_comp_options/state.json + pull.log.
Rate limit: free tier ~5 req/min -> 12.4s spacing, 429 backoff.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, '/root/spy')
from indicators import compute_phase_oscillator, atr, ema  # noqa: E402

# env-overridable so expansion runs (more tickers/years) can share the same
# DB + chain cache without clobbering the v1 study files
TICKERS = os.environ.get('PO_TICKERS', 'AMZN,NVDA,MSFT').split(',')
WINDOW_START = os.environ.get('PO_WINDOW_START', '2025-07-07')
DATA_END = '2026-07-06'              # last full session before today
BASE = 'https://api.massive.com'
STUDY = Path('/root/spy/analyst/po_comp_options')
CHAINS = STUDY / 'chains'
PARQUET_5M = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
TOPUP = STUDY / os.environ.get('PO_TOPUP', 'underlying_5m_topup.parquet')
EVENTS_CSV = STUDY / os.environ.get('PO_EVENTS', 'events.csv')
TODO_JSON = STUDY / os.environ.get('PO_TODO', 'contracts_todo.json')
BUCKET_NAMES = os.environ.get('PO_BUCKETS', 'W1,W2,M1').split(',')
DB = STUDY / 'option_bars.sqlite'
STATE = STUDY / 'state.json'
LOG = STUDY / 'pull.log'

KEY = None
_last_req = [0.0]
REQ_SPACING = 0.15  # paid plan (upgraded 2026-07-07): no per-minute cap; keep a polite gap


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def save_state(**kw):
    st = {}
    if STATE.exists():
        st = json.loads(STATE.read_text())
    st.update(kw)
    st['updated'] = datetime.now().isoformat(timespec='seconds')
    STATE.write_text(json.dumps(st, indent=1))


def api_get(url, params=None):
    """Rate-limited GET with 429 backoff. Returns parsed json or raises.
    Patient retry budget: free-tier contention can 429 for many minutes."""
    for attempt in range(30):
        wait = _last_req[0] + REQ_SPACING - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.time()
        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            log(f"  net error {e}; retry {attempt}")
            time.sleep(30)
            continue
        if r.status_code == 429:
            log("  429; sleeping 65s")
            time.sleep(65)
            continue
        if r.status_code >= 500:
            log(f"  {r.status_code}; sleeping 30s")
            time.sleep(30)
            continue
        return r.json()
    raise RuntimeError(f"giving up on {url}")


# ---------------------------------------------------------------- phase 1
def load_5m(tkr):
    frames = []
    for yr in [2024, 2025, 2026]:
        p = PARQUET_5M.format(yr=yr, tkr=tkr)
        if os.path.exists(p):
            frames.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'open', 'high', 'low', 'close', 'volume']))
    parts = []
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df['ts'] = pd.to_datetime(df['metric_ts_et'], utc=True).dt.tz_convert('America/New_York')
        parts.append(df[['ts', 'open', 'high', 'low', 'close', 'volume']])
    if TOPUP.exists():
        t = pd.read_parquet(TOPUP)
        t = t[t['ticker'] == tkr].copy()
        if len(t):
            t['ts'] = pd.to_datetime(t['ts'], utc=True).dt.tz_convert('America/New_York')
            parts.append(t[['ts', 'open', 'high', 'low', 'close', 'volume']])
    # topup-only tickers (SPY/QQQ/SPX indices run) have no local parquet store
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates(subset='ts').sort_values('ts').set_index('ts')
    return df


def phase1_topup():
    if TOPUP.exists():
        log("phase1: topup file exists, skipping")
        return
    rows = []
    for tkr in TICKERS:
        # local data ends 2026-05-07/08; overlap a few days, dedupe handles it
        url = f"{BASE}/v2/aggs/ticker/{tkr}/range/5/minute/2026-05-06/{DATA_END}"
        params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': KEY}
        while url:
            d = api_get(url, params)
            for b in d.get('results') or []:
                rows.append({'ticker': tkr, 'ts': pd.Timestamp(b['t'], unit='ms', tz='UTC'),
                             'open': b['o'], 'high': b['h'], 'low': b['l'],
                             'close': b['c'], 'volume': b['v']})
            url = d.get('next_url')
            params = {'apiKey': KEY} if url else None
        log(f"phase1: {tkr} topup rows so far {len(rows)}")
    pd.DataFrame(rows).to_parquet(TOPUP)
    log(f"phase1: wrote {TOPUP} ({len(rows)} rows)")


# ---------------------------------------------------------------- phase 2
def hourly_and_daily(df5, session=None):
    """session RTH (default): TV-style 9:30-anchored hourly. ETH: on-the-hour
    bars over 4:00-19:55 (matches TV extended-hours stock charts).
    Daily bars stay RTH-based either way (Saty daily ATR spec)."""
    session = session or os.environ.get('PO_SESSION', 'RTH')
    rth = df5.between_time('09:30', '15:55')
    if session == 'ETH':
        h = df5.between_time('04:00', '19:55').resample('60min').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last')).dropna()
    else:
        h = rth.resample('60min', offset='30min').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last')).dropna()
    dly = rth.resample('1D').agg(
        open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'), close=('close', 'last')).dropna()
    return h, dly


def phase2_events():
    all_events = []
    for tkr in TICKERS:
        df5 = load_5m(tkr)
        h, dly = hourly_and_daily(df5)
        h = compute_phase_oscillator(h)
        h['ema9_h'] = ema(h['close'], 9)
        h['ema21_h'] = ema(h['close'], 21)
        # daily features, Saty-spec ATR(14) Wilder; use prior completed day
        dly['datr14'] = atr(dly, 14)
        dly['ema21_d'] = ema(dly['close'], 21)
        dly['ema21_d_slope1'] = dly['ema21_d'].diff(1)
        dly['ema21_d_slope3'] = dly['ema21_d'].diff(3)
        dprior = dly.shift(1)  # as-of prior close

        comp = h['po_compression']
        start_mask = (comp == 1) & (comp.shift(1) != 1)
        po = h['phase_oscillator']
        ep_id = 0
        for ts in h.index[start_mask]:
            if ts < pd.Timestamp(WINDOW_START, tz='America/New_York'):
                continue
            ep_id += 1
            i = h.index.get_loc(ts)
            # episode end = first later bar with po_compression == 0
            end_ts, end_close = None, None
            for j in range(i + 1, len(h)):
                if h['po_compression'].iloc[j] == 0:
                    end_ts = h.index[j]
                    end_close = h['close'].iloc[j]
                    break
            dkey = pd.Timestamp(ts.date(), tz='America/New_York')
            drow = dprior.loc[dprior.index <= dkey].iloc[-1] if len(
                dprior.loc[dprior.index <= dkey]) else None
            if drow is None or pd.isna(drow['datr14']):
                continue
            all_events.append({
                'ticker': tkr, 'ep_id': f"{tkr}-{ep_id:03d}",
                'start_ts_et': ts.isoformat(),
                'end_ts_et': end_ts.isoformat() if end_ts is not None else '',
                'n_comp_bars': int((h['po_compression'].iloc[i:] == 1).values.argmin())
                               if end_ts is not None else -1,
                'spot_start': round(float(h['close'].iloc[i]), 4),
                'spot_end': round(float(end_close), 4) if end_close is not None else None,
                'datr14_prior': round(float(drow['datr14']), 4),
                'ema9_h': round(float(h['ema9_h'].iloc[i]), 4),
                'ema21_h': round(float(h['ema21_h'].iloc[i]), 4),
                'po': round(float(po.iloc[i]), 3),
                'po_slope1': round(float(po.iloc[i] - po.iloc[i - 1]), 3),
                'po_slope3': round(float(po.iloc[i] - po.iloc[i - 3]), 3),
                'phase_zone': h['phase_zone'].iloc[i],
                'ema21_d': round(float(drow['ema21_d']), 4),
                'ema21_d_slope1': round(float(drow['ema21_d_slope1']), 4),
                'ema21_d_slope3': round(float(drow['ema21_d_slope3']), 4),
            })
        log(f"phase2: {tkr} episodes={ep_id}")
    ev = pd.DataFrame(all_events)
    ev.to_csv(EVENTS_CSV, index=False)
    log(f"phase2: wrote {EVENTS_CSV} ({len(ev)} events)")
    return ev


# ---------------------------------------------------------------- phase 3
def next_friday(d, min_dte=4):
    x = d + timedelta(days=min_dte)
    while x.weekday() != 4:
        x += timedelta(days=1)
    return x


def get_chain(tkr, expiry):
    """Cached strikes for (ticker, expiry). Returns dict or None if no contracts.
    Falls back expiry-1d (holiday Friday) once; result cached under requested date."""
    CHAINS.mkdir(exist_ok=True, parents=True)
    cache = CHAINS / f"{tkr}_{expiry}.json"
    if cache.exists():
        d = json.loads(cache.read_text())
        return d if d.get('call') or d.get('put') else None
    out = {'call': [], 'put': [], 'actual_expiry': expiry}
    for exp_try in [expiry, (date.fromisoformat(expiry) - timedelta(days=1)).isoformat()]:
        params = {'underlying_ticker': tkr, 'expiration_date': exp_try,
                  'limit': 1000, 'apiKey': KEY}
        if exp_try < date.today().isoformat():
            params['expired'] = 'true'
        url = f"{BASE}/v3/reference/options/contracts"
        while url:
            d = api_get(url, params)
            for r in d.get('results') or []:
                # SPX chains mix PM-settled weeklies (O:SPXW) with AM-settled
                # monthlies (O:SPX) that stop trading Thursday; keep SPXW only
                if tkr == 'SPX' and not r['ticker'].startswith('O:SPXW'):
                    continue
                out[r['contract_type']].append(
                    {'strike': r['strike_price'], 'ticker': r['ticker']})
            url = d.get('next_url')
            params = {'apiKey': KEY} if url else None
        if out['call'] or out['put']:
            out['actual_expiry'] = exp_try
            break
    cache.write_text(json.dumps(out))
    log(f"phase3: chain {tkr} {expiry} -> {len(out['call'])}C/{len(out['put'])}P"
        f" (actual {out['actual_expiry']})")
    return out if (out['call'] or out['put']) else None


def snap(chain_side, target):
    if not chain_side:
        return None
    return min(chain_side, key=lambda s: abs(s['strike'] - target))


def phase3_todo(ev):
    if TODO_JSON.exists():
        log("phase3: todo exists, skipping rebuild")
        return json.loads(TODO_JSON.read_text())
    todo = {}   # opt_ticker -> meta
    OFFS = [float(x) for x in os.environ.get(
        'PO_OFFSETS', '0,0.5,-0.5,1.0,-1.0').split(',')]
    for _, e in ev.iterrows():
        d0 = datetime.fromisoformat(e['start_ts_et']).date()
        w1 = next_friday(d0)
        buckets = [b for b in [('W1', w1, 0), ('W2', w1 + timedelta(days=7), 1),
                               ('M1', w1 + timedelta(days=21), 2)]
                   if b[0] in BUCKET_NAMES]
        for bname, exp, bprio in buckets:
            chain = get_chain(e['ticker'], exp.isoformat())
            if chain is None:
                log(f"phase3: NO CHAIN {e['ticker']} {exp} (event {e['ep_id']})")
                continue
            for off in OFFS:
                target = e['spot_start'] + off * e['datr14_prior']
                for typ in ['call', 'put']:
                    s = snap(chain[typ], target)
                    if s is None:
                        continue
                    t = s['ticker']
                    prio = (bprio, abs(off))
                    if t not in todo or prio < tuple(todo[t]['prio']):
                        prev_start = todo[t]['pull_from'] if t in todo else '9999'
                        todo[t] = {
                            'underlying': e['ticker'], 'type': typ,
                            'strike': s['strike'], 'expiry': chain['actual_expiry'],
                            'pull_from': min(d0.isoformat(), prev_start),
                            'prio': list(prio)}
                    else:
                        todo[t]['pull_from'] = min(todo[t]['pull_from'], d0.isoformat())
    TODO_JSON.write_text(json.dumps(todo, indent=0))
    log(f"phase3: todo built, {len(todo)} unique contracts")
    return todo


# ---------------------------------------------------------------- phase 4
def phase4_pull(todo):
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS contracts(
        ticker TEXT PRIMARY KEY, underlying TEXT, type TEXT, strike REAL,
        expiry TEXT, pull_from TEXT, status TEXT, nbars INT, pulled_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS bars(
        ticker TEXT, t INTEGER, o REAL, h REAL, l REAL, c REAL,
        v REAL, vw REAL, n INT, PRIMARY KEY(ticker, t))""")
    done = {r[0] for r in con.execute("SELECT ticker FROM contracts WHERE status IS NOT NULL")}
    items = sorted(todo.items(), key=lambda kv: (tuple(kv[1]['prio']), kv[1]['expiry'], kv[0]))
    total = len(items)
    log(f"phase4: {total} contracts, {len(done)} already done")
    n_done = len(done)
    for opt, m in items:
        if opt in done:
            continue
        pull_to = min(date.fromisoformat(m['expiry']) + timedelta(days=1),
                      date.today()).isoformat()
        url = f"{BASE}/v2/aggs/ticker/{opt}/range/1/minute/{m['pull_from']}/{pull_to}"
        params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': KEY}
        status, nbars = 'ok', 0
        try:
            while url:
                d = api_get(url, params)
                if d.get('status') == 'NOT_AUTHORIZED':
                    status = 'not_authorized'
                    break
                rows = [(opt, b['t'], b.get('o'), b.get('h'), b.get('l'), b.get('c'),
                         b.get('v'), b.get('vw'), b.get('n'))
                        for b in d.get('results') or []]
                if rows:
                    con.executemany(
                        "INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
                    nbars += len(rows)
                url = d.get('next_url')
                params = {'apiKey': KEY} if url else None
        except RuntimeError as ex:
            status = f'error:{ex}'
        if nbars == 0 and status == 'ok':
            status = 'empty'
        con.execute("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?)",
                    (opt, m['underlying'], m['type'], m['strike'], m['expiry'],
                     m['pull_from'], status, nbars,
                     datetime.now().isoformat(timespec='seconds')))
        con.commit()
        n_done += 1
        if n_done % 10 == 0 or n_done == total:
            log(f"phase4: {n_done}/{total} contracts ({opt}: {status} {nbars} bars)")
            save_state(phase=4, contracts_done=n_done, contracts_total=total)
    con.close()
    log("phase4: COMPLETE")
    save_state(phase='done', contracts_done=n_done, contracts_total=total)


def main():
    global KEY
    STUDY.mkdir(exist_ok=True, parents=True)
    for line in open('/root/spx-chart-app/.env'):
        if line.startswith('POLYGON_API_KEY='):
            KEY = line.strip().split('=', 1)[1]
    assert KEY, 'no api key'
    log("=== run start ===")
    save_state(phase=1)
    phase1_topup()
    save_state(phase=2)
    ev = phase2_events()
    save_state(phase=3, events=len(ev))
    todo = phase3_todo(ev)
    save_state(phase=4, contracts_total=len(todo))
    phase4_pull(todo)


if __name__ == '__main__':
    main()
