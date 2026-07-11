#!/usr/bin/env python3
"""Generate 7-year close-confirmed Bilbo box entries (30m + hourly) for the
20-name universe from the local 5m store, 2019-01-01 -> 2026-07-06.
Output: analyst/po_comp_options/theta/theta_entries.parquet
Entry rule = the validated live one: first bar that closes out of PO
compression AND broke the box of completed grey bars (freeze at 5).
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/spy')
from indicators import compute_phase_oscillator, atr, ema

STUDY = Path('/root/spy/analyst/po_comp_options')
OUTDIR = STUDY / 'theta'
OUTDIR.mkdir(exist_ok=True)
P5 = '/srv/ftp/ossicones/stock-data/bars_5m_adjusted/year={yr}/{tkr}.parquet'
TICKERS = ['AMZN', 'NVDA', 'MSFT', 'AAPL', 'META', 'GOOGL', 'TSLA', 'AMD',
           'PLTR', 'AVGO', 'NFLX', 'MU', 'COIN', 'SMCI', 'HOOD', 'INTC',
           'UBER', 'BAC', 'JPM', 'DIS']
W0 = pd.Timestamp('2019-01-01', tz='America/New_York')
W1 = pd.Timestamp('2026-07-06', tz='America/New_York')
WATCH_DAYS = 10


def load5(tkr):
    frames = []
    for yr in range(2019, 2027):
        p = Path(P5.format(yr=yr, tkr=tkr))
        if p.exists():
            frames.append(pd.read_parquet(
                p, columns=['metric_ts_et', 'open', 'high', 'low', 'close', 'volume']))
    for top in ['underlying_5m_topup_v2.parquet', 'underlying_5m_topup_new12.parquet']:
        t = pd.read_parquet(STUDY / top)
        t = t[t.ticker == tkr]
        if len(t):
            t = t.rename(columns={'ts': 'metric_ts_et'})
            frames.append(t[['metric_ts_et', 'open', 'high', 'low', 'close', 'volume']])
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(df.metric_ts_et, utc=True).dt.tz_convert('America/New_York')
    return (df.drop_duplicates(subset='ts').sort_values('ts')
            .set_index('ts')[['open', 'high', 'low', 'close']])


def walk(tkr, df5, minutes, tag):
    x5 = df5.between_time('04:00', '19:55')
    r5 = df5.between_time('09:30', '15:55')
    h = x5.resample(f'{minutes}min').agg(open=('open', 'first'), high=('high', 'max'),
                                         low=('low', 'min'), close=('close', 'last')).dropna()
    h = compute_phase_oscillator(h)
    comp = h['po_compression'].to_numpy(int)
    close_ts = h.index + pd.Timedelta(minutes=minutes)
    dly = r5.resample('1D').agg(open=('open', 'first'), high=('high', 'max'),
                                low=('low', 'min'), close=('close', 'last')).dropna()
    dly['datr14'] = atr(dly, 14)
    dprior = dly.shift(1)
    rows = []
    starts = np.where((comp == 1) & (np.roll(comp, 1) != 1))[0]
    ep = 0
    for i in starts:
        if i == 0:
            continue
        ts = h.index[i]
        if ts < W0 or ts > W1:
            continue
        dk = dprior.loc[:pd.Timestamp(ts.date(), tz='America/New_York')]
        if not len(dk) or pd.isna(dk['datr14'].iloc[-1]):
            continue
        ep += 1
        box_hi = float(h['high'].iloc[i])
        box_lo = float(h['low'].iloc[i])
        grey = 1
        deadline = close_ts[i] + pd.Timedelta(days=WATCH_DAYS)
        j = i + 1
        while j < len(h):
            if close_ts[j] > deadline:
                break
            if comp[j] == 1:
                grey += 1
                if grey <= 5:
                    box_hi = max(box_hi, float(h['high'].iloc[j]))
                    box_lo = min(box_lo, float(h['low'].iloc[j]))
                j += 1
                continue
            hj_hi, hj_lo = float(h['high'].iloc[j]), float(h['low'].iloc[j])
            hj_cl = float(h['close'].iloc[j])
            up, dn = hj_hi > box_hi, hj_lo < box_lo
            if up or dn:
                dirn = (1 if hj_cl >= (box_hi + box_lo) / 2 else -1) \
                    if (up and dn) else (1 if up else -1)
                et = close_ts[j]
                intraday = not (et.hour < 9 or et.hour >= 16
                                or (et.hour == 9 and et.minute < 35))
                rows.append({'pop': tag, 'ticker': tkr,
                             'ep_id': f'{tkr}-{tag}-{ep:05d}',
                             'entry_ts': et.isoformat(), 'spot': hj_cl,
                             'direction': dirn, 'box_hi': box_hi, 'box_lo': box_lo,
                             'grey_bars': grey, 'intraday': intraday,
                             'datr14_prior': float(dk['datr14'].iloc[-1])})
            break
    return rows


all_rows = []
for tkr in TICKERS:
    df5 = load5(tkr)
    if df5 is None or len(df5) < 1000:
        print(f"{tkr}: no data")
        continue
    a = walk(tkr, df5, 30, 'box30')
    b = walk(tkr, df5, 60, 'hourly')
    all_rows += a + b
    print(f"{tkr}: {df5.index[0].date()}..{df5.index[-1].date()} "
          f"box30={len(a)} hourly={len(b)}", flush=True)

d = pd.DataFrame(all_rows)
d.to_parquet(OUTDIR / 'theta_entries.parquet')
print(f"\ntotal entries: {len(d)} ({(d.pop=='box30').sum() if 'pop' in d else '?'})")
print(d.groupby(['pop', 'intraday']).size())
print(f"-> {OUTDIR/'theta_entries.parquet'}")
