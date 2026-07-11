"""
Pre-registered FORWARD consistency check (spec frozen in
analyst/es_ema_po_ribbon_forward_prereg.md before any post-2026-01-23 SPY
data was fetched or examined).

Fetches SPY 1-min from Massive (2025-10-01 -> today, adjusted, single source),
runs the frozen ribbon-riding spec, scores entries >= 2026-01-26 only.
"""

import os
import sys
import time
import requests
import numpy as np
import pandas as pd
from datetime import date, timedelta, datetime, timezone

sys.path.insert(0, "/root/spy")

CACHE = "/root/spy/analyst/spy_1m_massive_fwd.csv"
ATR_MIN = 0.20
COST = 0.03
SCORE_FROM = "2026-01-26"


def api_key():
    for line in open("/root/spx-chart-app/.env"):
        if line.startswith("POLYGON_API_KEY="):
            return line.strip().split("=", 1)[1]
    raise RuntimeError("no key")


def utc_ms_to_et(ts_ms):
    utc_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    y = utc_dt.year
    mar = datetime(y, 3, 8 + (6 - datetime(y, 3, 1).weekday()) % 7, 7, tzinfo=timezone.utc)
    nov = datetime(y, 11, 1 + (6 - datetime(y, 11, 1).weekday()) % 7, 6, tzinfo=timezone.utc)
    off = timedelta(hours=-4) if mar <= utc_dt < nov else timedelta(hours=-5)
    return (utc_dt + off).strftime("%Y-%m-%d %H:%M:%S")


def fetch():
    key = api_key()
    rows = []
    cur = date(2025, 10, 1)
    end = date.today()
    while cur <= end:
        chunk_end = min(cur + timedelta(days=13), end)
        url = (f"https://api.massive.com/v2/aggs/ticker/SPY/range/1/minute/"
               f"{cur}/{chunk_end}")
        params = {"apiKey": key, "limit": 50000, "sort": "asc", "adjusted": "true"}
        while url:
            for attempt in range(8):
                r = requests.get(url, params=params, timeout=60)
                if r.status_code == 429:
                    time.sleep(20); continue
                r.raise_for_status(); break
            js = r.json()
            for b in js.get("results", []):
                rows.append((utc_ms_to_et(b["t"]), b["o"], b["h"], b["l"], b["c"], b.get("v", 0)))
            url = js.get("next_url")
            params = {"apiKey": key}
            time.sleep(13)  # free tier 5/min
        print(f"  fetched through {chunk_end} ({len(rows)} bars)", flush=True)
        cur = chunk_end + timedelta(days=1)
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).drop_duplicates("ts")
    df.to_csv(CACHE, index=False, header=False)
    print(f"cached {len(df)} bars -> {CACHE}")


if not os.path.exists(CACHE):
    fetch()

import backtest_es_ema_po_pullback_round5b as r5b
from backtest_es_ema_po_pullback_round5 import prep5, win_arr

r5b.COST = COST
r5b.ATR_MIN = ATR_MIN

A = prep5(CACHE)
m = win_arr(A, "both")
t = r5b.simulate5b(A, m, "arm", "r10m21", 2, 2.5)
t["entry_ts"] = pd.to_datetime(t["entry_ts"])
t["exit_ts"] = pd.to_datetime(t["exit_ts"])
t = t[t["entry_ts"] >= SCORE_FROM].reset_index(drop=True)
t.to_csv("/root/spy/analyst/es_ema_po_ribbon_forward_spy_trades.csv", index=False)

pnl = t.pnl_pts
print(f"\nFORWARD WINDOW {SCORE_FROM} -> {t.exit_ts.max()}")
print(f"  n          : {len(t)}")
if len(t):
    daily = t.groupby(t.entry_ts.dt.date).pnl_pts.sum()
    tday = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
    print(f"  avg net    : {pnl.mean():+.4f} SPY pts/trade "
          f"(ES-scale ~{pnl.mean()*10:+.2f} pts, ~${pnl.mean()*10*50:+.0f}/ES)")
    print(f"  total      : {pnl.sum():+.3f} SPY pts")
    print(f"  win rate   : {(pnl>0).mean()*100:.1f}%")
    print(f"  t (day)    : {tday:.2f}")
    print(f"  exits      : {t.reason.value_counts().to_dict()}")
    for _, r in t.iterrows():
        print(f"    {r.entry_ts}  ->  {r.exit_ts}  {r.reason:7s} {r.pnl_pts:+.3f}")
