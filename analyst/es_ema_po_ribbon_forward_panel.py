"""
Pre-registered forward replication panel: QQQ + IWM (spec and pass criteria
frozen in analyst/es_ema_po_ribbon_forward_panel_prereg.md BEFORE any fetch).
"""

import os
import sys
import time
import requests
import numpy as np
import pandas as pd
from datetime import date, timedelta

sys.path.insert(0, "/root/spy")
from analyst.es_ema_po_ribbon_forward_spy import api_key, utc_ms_to_et  # noqa
import backtest_es_ema_po_pullback_round5b as r5b
from backtest_es_ema_po_pullback_round5 import prep5, win_arr

SCORE_FROM = "2026-01-26"
PANEL = {
    "QQQ": {"cost": 0.03, "atr_min": 0.19},
    "IWM": {"cost": 0.02, "atr_min": 0.13},
}


def fetch(ticker, cache):
    key = api_key()
    rows = []
    cur = date(2025, 10, 1)
    end = date.today()
    while cur <= end:
        chunk_end = min(cur + timedelta(days=13), end)
        url = (f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/minute/"
               f"{cur}/{chunk_end}")
        params = {"apiKey": key, "limit": 50000, "sort": "asc", "adjusted": "true"}
        while url:
            for _ in range(8):
                r = requests.get(url, params=params, timeout=60)
                if r.status_code == 429:
                    time.sleep(20); continue
                r.raise_for_status(); break
            js = r.json()
            for b in js.get("results", []):
                rows.append((utc_ms_to_et(b["t"]), b["o"], b["h"], b["l"], b["c"], b.get("v", 0)))
            url = js.get("next_url")
            params = {"apiKey": key}
            time.sleep(13)
        print(f"  {ticker} through {chunk_end} ({len(rows)} bars)", flush=True)
        cur = chunk_end + timedelta(days=1)
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).drop_duplicates("ts")
    df.to_csv(cache, index=False, header=False)


all_t = []
for ticker, cfg in PANEL.items():
    cache = f"/root/spy/analyst/{ticker.lower()}_1m_massive_fwd.csv"
    if not os.path.exists(cache):
        fetch(ticker, cache)
    r5b.COST = cfg["cost"]
    r5b.ATR_MIN = cfg["atr_min"]
    A = prep5(cache)
    m = win_arr(A, "both")
    t = r5b.simulate5b(A, m, "arm", "r10m21", 2, 2.5)
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t = t[t["entry_ts"] >= SCORE_FROM].reset_index(drop=True)
    t["ticker"] = ticker
    t.to_csv(f"/root/spy/analyst/es_ema_po_ribbon_forward_{ticker.lower()}_trades.csv",
             index=False)
    pnl = t.pnl_pts
    daily = t.groupby(t.entry_ts.dt.date).pnl_pts.sum()
    td = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
    print(f"\n{ticker}: n={len(t)}  avg {pnl.mean():+.4f} pts  "
          f"win {(pnl>0).mean()*100:.1f}%  t_day {td:.2f}  "
          f"exits {t.reason.value_counts().to_dict()}")
    all_t.append(t)

pool = pd.concat(all_t, ignore_index=True)
# normalize per-instrument scale before pooling days: use pnl / instrument cost-multiple
# prereg says pooled day-clustered t on raw per-trade pnl summed per day per pnl in
# instrument points is scale-mixed; use pnl in units of each instrument's ATR_MIN
pool["pnl_u"] = pool.apply(
    lambda r: r.pnl_pts / PANEL[r.ticker]["atr_min"], axis=1)
daily = pool.groupby(pool.entry_ts.dt.date)["pnl_u"].sum()
t_pool = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))
m_q = all_t[0].pnl_pts.mean()
m_i = all_t[1].pnl_pts.mean()
print(f"\nPOOLED: {len(pool)} trades, {len(daily)} signal-days, "
      f"day-clustered t = {t_pool:.2f} (unit-normalized)")
ok = (m_q > 0) and (m_i > 0) and (t_pool >= 1.0)
print(f"\nREPLICATION {'PASS' if ok else 'FAIL'}  "
      f"(QQQ mean>0: {m_q > 0}; IWM mean>0: {m_i > 0}; pooled t>=1.0: {t_pool >= 1.0})")
