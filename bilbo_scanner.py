"""
Bilbo Box Scanner
=================

Live scanner for hourly Bilbo Box compression across the S&P 500 and
Nasdaq-100. Reuses the exact compression logic from indicators.py
(Saty Pivot Ribbon BB/ATR squeeze) and the box mechanics from
backtest_bilbo_box.py:

  - Box = range of the first 5 contiguous compression bars
    (early-exit: fewer bars if compression ends sooner).
  - Box locks at min(5 bars, compression end); break-watch starts the
    NEXT bar and stays armed for BREAK_LOOKBACK bars.
  - Break = any trade outside the box range. A fresh compression start
    during the watch kills the pending box (stale rollover).

DATA
----
Extended-hours hourly bars, top-of-hour 04:00-19:00 ET starts (16/day)
— the same grid as the study's TradingView ETH export in spy.db
candles_1h. The in-progress bar IS included, so intrabar breaks are
caught while the bar forms.

Primary source: Massive 1h aggregates (paid plan, no rate limit,
SIP-filtered wicks that are clean even pre/post). Last prices come
from the bulk snapshot endpoint in one pass. Per-ticker fallback:
Yahoo 30m prepost aggregated to the same grid — Yahoo's own 60m
interval mixes 9:30-anchored RTH bars with top-of-hour ETH bars, and
its pre/post wicks carry phantom prints, so on the fallback path the
bar BODY is the extreme outside RTH. If the Massive key drops back to
the free 5/min tier (it has flip-flopped before), the sweep degrades
to Yahoo automatically instead of dying.

Universe: the TOP_N (25) most liquid names in the S&P500 ∪ Nasdaq-100,
ranked by 20-trading-day average dollar volume (Massive grouped
dailies). Full constituent list + ranking cached in
analyst/bilbo_scanner/universe.json; refresh with --refresh-universe
(re-scrapes Wikipedia AND re-ranks liquidity — run weekly-ish).

ALERTS (Telegram via Hermes)
----------------------------
Two kinds, both RTH-session only (the study shows ETH breaks carry no
edge), deduped per box in state.json, delivered to Pedro's Telegram DM
through `hermes send`.

The DASHBOARD keeps the raw study semantics (any trade outside a locked
box is a "breakout" — including wicks on the still-forming hour and
in-compression drift when a squeeze runs past 5 bars). TELEGRAM is
stricter — a quality gate on top of the raw status:
- BILBO BREAK alerts can fire intrabar, but only when the break bar is
  out of compression (expansion has actually started), is an RTH bar,
  and the box is not too wide (MAX_ALERT_BOX_WIDTH_ATR). We do NOT
  require the hourly bar to close; the quality filter is "not still in
  compression," not close-confirmation.
- NEAR BREAK alerts only for armed boxes that are already out of
  compression, under the same width cap, with live price within
  ALERT_PROXIMITY_ATR (tighter than the dashboard's 0.25 ⚡ marker).
Every breakout/near-break row carries alert_quality + alert_blockers in
the JSON and alerts.log so "why didn't this alert?" is answerable.
Run once with --quiet-alerts after any state reset to seed without
spamming.

OUTPUT
------
- site/data/bilbo-scanner.json      full scan snapshot for the HTML page
- analyst/bilbo_scanner/state.json  alert dedup state
- analyst/bilbo_scanner/alerts.log  one line per NEW break / pre-break
- stdout: summary (cron-friendly)

USAGE
-----
  python3 bilbo_scanner.py                 # one scan
  python3 bilbo_scanner.py --rth-only      # exit silently outside RTH (for cron)
  python3 bilbo_scanner.py --refresh-universe
  python3 bilbo_scanner.py --tickers AAPL,NVDA   # debug subset

Suggested crontab (server is UTC; guard handles DST via ET check):
  */5 13-21 * * 1-5 cd /root/spy && /usr/bin/python3 bilbo_scanner.py --rth-only >> analyst/bilbo_scanner/cron.log 2>&1
"""

import os
import io
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from indicators import compute_pivot_ribbon, atr as atr_fn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_DIR = os.path.join(BASE_DIR, "analyst", "bilbo_scanner")
UNIVERSE_PATH = os.path.join(SCAN_DIR, "universe.json")
STATE_PATH = os.path.join(SCAN_DIR, "state.json")
ALERTS_LOG = os.path.join(SCAN_DIR, "alerts.log")
OUT_JSON = os.path.join(BASE_DIR, "site", "data", "bilbo-scanner.json")

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")

# Box mechanics — same values as backtest_bilbo_box.py
BOX_MAX_BARS = 5
BREAK_LOOKBACK = 20

# How many bars after the break we keep showing it as a "fresh" breakout
BREAKOUT_DISPLAY_BARS = 7

# Scan only the N most liquid universe names (20d avg dollar volume)
TOP_N = 25
LIQUIDITY_DAYS = 20

# Pre-breakout ("move expected within ~1 bar"): armed box whose nearest
# boundary is within this many hourly ATRs of the live price. ATR-14 is
# the average 1h true range, so 0.25 ATR is ~a quarter of a typical bar.
# This raw threshold only drives the dashboard's ⚡ marker; the Telegram
# gate uses the tighter ALERT_PROXIMITY_ATR below.
PROXIMITY_ATR = 0.25

# ── Telegram alert quality gate ──
# Max box width for ANY Telegram alert, in the scanner's own hourly
# ATR-14 units (post wick-clip). Live top-25 boxes run ~0.8–3.9 ATR,
# median ~2.8; 3.0 trims the fattest quartile, where stop distance (the
# other side of the box) gets ugly. NOT comparable to the study CSV's
# box_width_atr scale (different ATR source) — tune from alerts.log,
# which records box_width_atr on every entry.
MAX_ALERT_BOX_WIDTH_ATR = 3.0

# NEAR BREAK Telegram proximity: price must be within this many hourly
# ATRs of the boundary (vs 0.25 for the dashboard marker) AND the box
# must pass near_break_alert_gate (out of compression, width cap).
ALERT_PROXIMITY_ATR = 0.15

# Telegram delivery via the Hermes agent's gateway credentials
HERMES_BIN = "/root/.local/bin/hermes"
TELEGRAM_TARGET = "telegram:7980528578"  # Pedro DM (channel_directory.json)

WORKERS = 12
YAHOO_RANGE = "60d"          # Yahoo's max for 30m bars; ~650 ETH hourly bars
REQUEST_TIMEOUT = 15
RETRIES = 2

# ETH session hourly bar starts (hour of day, ET)
ETH_HOURS = set(range(4, 20))  # 04:00 .. 19:00

HEADERS = {"User-Agent": "Mozilla/5.0 (bilbo-scanner; pedro@milkify.me)"}

MASSIVE_BASE = "https://api.massive.com"


def _massive_key():
    try:
        for line in open("/root/spx-chart-app/.env"):
            if line.startswith("POLYGON_API_KEY="):
                return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return None


MASSIVE_KEY = _massive_key()


# ── Universe ──

def refresh_universe():
    h = {"User-Agent": HEADERS["User-Agent"]}
    sp = pd.read_html(io.StringIO(requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=h, timeout=30).text))[0]
    nd_tables = pd.read_html(io.StringIO(requests.get(
        "https://en.wikipedia.org/wiki/Nasdaq-100", headers=h, timeout=30).text))
    nd = None
    for t in nd_tables:
        cols = [str(c).lower() for c in t.columns]
        if any("ticker" in c or "symbol" in c for c in cols) and len(t) > 80:
            nd = t
            break
    if nd is None or len(sp) < 400:
        raise RuntimeError("Wikipedia constituent scrape failed sanity check")
    sym_col = [c for c in nd.columns if "icker" in str(c) or "ymbol" in str(c)][0]
    name_col = [c for c in nd.columns if "ompany" in str(c)][0]
    uni = {}
    for _, row in sp.iterrows():
        s = str(row["Symbol"]).strip()
        uni[s] = {"name": str(row["Security"]).strip(), "sp500": True,
                  "ndx": False, "sector": str(row.get("GICS Sector", "")).strip()}
    for _, row in nd.iterrows():
        s = str(row[sym_col]).strip()
        if s in uni:
            uni[s]["ndx"] = True
        else:
            uni[s] = {"name": str(row[name_col]).strip(), "sp500": False,
                      "ndx": True, "sector": ""}
    ranked = rank_liquidity(uni)
    os.makedirs(SCAN_DIR, exist_ok=True)
    with open(UNIVERSE_PATH, "w") as f:
        json.dump({"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                   "tickers": uni, "ranked": ranked}, f, indent=1)
    print(f"universe refreshed: {len(uni)} tickers "
          f"({sum(1 for v in uni.values() if v['sp500'])} SP500, "
          f"{sum(1 for v in uni.values() if v['ndx'])} NDX); "
          f"top {TOP_N} by 20d $vol: {','.join(s for s, _ in ranked[:TOP_N])}")
    return {"tickers": uni, "ranked": ranked}


def rank_liquidity(uni):
    """Rank universe tickers by average daily dollar volume over the last
    LIQUIDITY_DAYS trading days (Massive grouped dailies, one call/day).
    Returns [(sym, avg_dollar_vol), ...] descending."""
    if not MASSIVE_KEY:
        raise RuntimeError("liquidity ranking needs the Massive key")
    sums, counts = {}, {}
    day = datetime.now(ET).date()
    got = 0
    while got < LIQUIDITY_DAYS:
        day -= timedelta(days=1)
        if day.weekday() >= 5:
            continue
        r = requests.get(
            f"{MASSIVE_BASE}/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}",
            params={"adjusted": "true", "apiKey": MASSIVE_KEY}, timeout=60)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            continue  # holiday
        for b in results:
            s = b["T"]
            if s in uni:
                sums[s] = sums.get(s, 0.0) + b["c"] * b["v"]
                counts[s] = counts.get(s, 0) + 1
        got += 1
    ranked = sorted(((s, sums[s] / counts[s]) for s in sums), key=lambda kv: -kv[1])
    return [(s, round(v)) for s, v in ranked]


def load_universe():
    if not os.path.exists(UNIVERSE_PATH):
        return refresh_universe()
    with open(UNIVERSE_PATH) as f:
        u = json.load(f)
    if not u.get("ranked"):
        return refresh_universe()
    return u


# ── Data fetch ──

def yahoo_symbol(sym):
    return sym.replace(".", "-")


def fetch_hourly_massive(sym):
    """Fetch ETH hourly bars from Massive 1h aggregates. Returns df."""
    frm = (datetime.now(ET) - timedelta(days=70)).strftime("%Y-%m-%d")
    to = datetime.now(ET).strftime("%Y-%m-%d")
    r = requests.get(
        f"{MASSIVE_BASE}/v2/aggs/ticker/{sym}/range/1/hour/{frm}/{to}",
        params={"adjusted": "true", "sort": "asc", "limit": 50000,
                "apiKey": MASSIVE_KEY},
        timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        raise RuntimeError("massive: no results")
    idx = pd.to_datetime([b["t"] for b in results], unit="ms", utc=True).tz_convert(ET)
    df = pd.DataFrame({"open": [b["o"] for b in results],
                       "high": [b["h"] for b in results],
                       "low": [b["l"] for b in results],
                       "close": [b["c"] for b in results],
                       "volume": [b["v"] for b in results]}, index=idx)
    df = df[df.index.hour.isin(list(ETH_HOURS))].sort_index()
    # Safety-net bad-tick clip, same rule as aggregate.py.
    body_high = np.maximum(df["open"], df["close"])
    body_low = np.minimum(df["open"], df["close"])
    df["high"] = np.minimum(df["high"], body_high * 1.02)
    df["low"] = np.maximum(df["low"], body_low * 0.98)
    return df


def fetch_snapshot_prices(syms):
    """One bulk-snapshot pass for live last prices. Returns {sym: price}."""
    out = {}
    if not MASSIVE_KEY:
        return out
    for i in range(0, len(syms), 100):
        chunk = syms[i:i + 100]
        try:
            r = requests.get(
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"tickers": ",".join(chunk), "apiKey": MASSIVE_KEY},
                timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            for t in r.json().get("tickers", []):
                px = (t.get("lastTrade") or {}).get("p") or (t.get("min") or {}).get("c")
                if px:
                    out[t["ticker"]] = float(px)
        except Exception:
            continue  # snapshot is a nicety; bar closes already cover last_price
    return out


def fetch_hourly_yahoo(sym):
    """Fallback: 30m pre/post bars from Yahoo aggregated to top-of-hour
    extended-hours hourly bars. Returns (df, last_quote)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol(sym)}"
    params = {"interval": "30m", "range": YAHOO_RANGE, "includePrePost": "true"}
    last_err = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS,
                             timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                last_err = "429"
                continue
            r.raise_for_status()
            d = r.json()["chart"]["result"][0]
            break
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(1 + attempt)
    else:
        raise RuntimeError(f"fetch failed: {last_err}")

    ts = d.get("timestamp")
    if not ts:
        raise RuntimeError("no timestamps returned")
    q = d["indicators"]["quote"][0]
    idx = pd.to_datetime(ts, unit="s", utc=True).tz_convert(ET)
    df = pd.DataFrame({"open": q["open"], "high": q["high"],
                       "low": q["low"], "close": q["close"],
                       "volume": q["volume"]}, index=idx)
    # Keep only bars on the :00/:30 grid (drops quote-stuffed artifacts
    # like 19:59:49) and inside the 04:00-20:00 ETH session.
    df = df[(df.index.minute.isin([0, 30])) & (df.index.second == 0)]
    df = df[df.index.hour.isin(list(ETH_HOURS))]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_index()
    # Yahoo's pre/post high/low carry phantom prints (e.g. AAPL AH low 296
    # while trading 311; ~half of all box "breaks" fired on AH bars before
    # this). AH wicks are unobservable in this feed: outside RTH use the
    # bar BODY as the extreme. Real AH moves still register through the
    # 30m opens/closes. RTH bars keep true wicks, clipped at 2% beyond the
    # body — the same bad-tick rule as aggregate.py.
    body_high = np.maximum(df["open"], df["close"])
    body_low = np.minimum(df["open"], df["close"])
    mins = df.index.hour * 60 + df.index.minute
    is_rth = pd.Series((mins >= 9 * 60 + 30) & (mins < 16 * 60), index=df.index)
    df["high"] = np.where(is_rth, np.minimum(df["high"], body_high * 1.02), body_high)
    df["low"] = np.where(is_rth, np.maximum(df["low"], body_low * 0.98), body_low)
    # Aggregate 30m -> top-of-hour ETH hourly (TV-style: 04:00..19:00 starts)
    hour = df.index.floor("h")
    df = df.groupby(hour).agg(open=("open", "first"), high=("high", "max"),
                              low=("low", "min"), close=("close", "last"),
                              volume=("volume", "sum"))
    meta = d.get("meta", {})
    live = meta.get("postMarketPrice") or meta.get("regularMarketPrice")
    return df, live


def fetch_hourly(sym):
    """Massive primary, Yahoo fallback. Returns (df, last_quote, source)."""
    if MASSIVE_KEY:
        try:
            return fetch_hourly_massive(sym), None, "massive"
        except Exception:
            pass
    df, live = fetch_hourly_yahoo(sym)
    return df, live, "yahoo"


# ── Box state machine (mirrors backtest_bilbo_box.py scan) ──

def current_box_state(df):
    """
    Walk compression runs exactly like the backtest scanner and return the
    state that is live at the FINAL bar.

    Returns dict with status in:
      forming    — inside a compression run, box still growing (<5 bars)
      locked     — box locked, break-watch armed (no break yet)
      breakout   — first trade outside the box happened within the last
                   BREAKOUT_DISPLAY_BARS bars
      none       — nothing live
    """
    comp = df["compression"].fillna(0).astype(int).values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    last = n - 1

    state = {"status": "none"}

    i = 0
    while i < n:
        if comp[i] != 1 or (i > 0 and comp[i - 1] == 1):
            i += 1
            continue

        box_start = i
        j = i + 1
        while j < n and (j - box_start) < BOX_MAX_BARS and comp[j] == 1:
            j += 1
        lock_bar = j - 1
        box_high = highs[box_start:j].max()
        box_low = lows[box_start:j].min()
        box_bars = j - box_start

        # Box still forming at the final bar?
        if lock_bar == last and comp[last] == 1 and box_bars < BOX_MAX_BARS:
            state = {"status": "forming", "box_start": box_start,
                     "lock_bar": None, "box_high": float(box_high),
                     "box_low": float(box_low), "box_bars": int(box_bars)}
            break

        break_end = min(j + BREAK_LOOKBACK, n)
        break_bar = None
        break_dir = None
        rolled = False
        for k in range(j, break_end):
            if comp[k] == 1 and comp[k - 1] == 0:
                rolled = True
                i = k
                break
            broke_up = highs[k] > box_high
            broke_dn = lows[k] < box_low
            if broke_up or broke_dn:
                break_bar = k
                if broke_up and broke_dn:
                    break_dir = "up" if closes[k] >= (box_high + box_low) / 2 else "down"
                else:
                    break_dir = "up" if broke_up else "down"
                break
        if rolled:
            continue

        if break_bar is not None:
            if last - break_bar <= BREAKOUT_DISPLAY_BARS:
                state = {"status": "breakout", "box_start": box_start,
                         "lock_bar": lock_bar, "box_high": float(box_high),
                         "box_low": float(box_low), "box_bars": int(box_bars),
                         "break_bar": break_bar, "break_dir": break_dir}
            i = break_bar + 1
            continue

        # No break yet — watch window still open at the final bar?
        if break_end == n and (n - j) < BREAK_LOOKBACK:
            state = {"status": "locked", "box_start": box_start,
                     "lock_bar": lock_bar, "box_high": float(box_high),
                     "box_low": float(box_low), "box_bars": int(box_bars)}
        i = break_end
    return state


def breakout_quality_fields(df, st, now=None):
    """Facts about the break bar that feed the Telegram gate. A raw break
    can fire on a wick of the still-forming hour, or while a >5-bar
    squeeze is still compressing (the box locks at 5 bars but the run
    continues). These fields let the gate require expansion/non-compression
    without requiring the live hourly bar to close."""
    bb = st["break_bar"]
    now = now if now is not None else datetime.now(ET)
    bar_closed = bb < len(df) - 1 or now >= df.index[bb] + pd.Timedelta(hours=1)
    in_comp = bool(df["compression"].fillna(0).iloc[bb] == 1)
    close_bb = float(df["close"].iloc[bb])
    if st["break_dir"] == "up":
        close_conf = close_bb > st["box_high"]
    else:
        close_conf = close_bb < st["box_low"]
    return {"break_bar_closed": bool(bar_closed),
            "break_expansion_confirmed": not in_comp,
            "break_close_confirmed": bool(close_conf)}


def scan_ticker(sym, info):
    df, live_px, source = fetch_hourly(sym)
    if len(df) < 150:
        raise RuntimeError(f"only {len(df)} bars")
    df = compute_pivot_ribbon(df)
    df["atr_14"] = atr_fn(df, 14)
    st = current_box_state(df)

    last_bar_ts = df.index[-1]
    last_close = float(df["close"].iloc[-1])
    atr14 = float(df["atr_14"].iloc[-1])
    row = {
        "sym": sym,
        "name": info.get("name", ""),
        "sp500": bool(info.get("sp500")),
        "ndx": bool(info.get("ndx")),
        "sector": info.get("sector", ""),
        "status": st["status"],
        "last_price": float(live_px) if live_px else last_close,
        "last_bar_ts": last_bar_ts.isoformat(),
        "atr14": round(atr14, 4),
        "in_compression": bool(df["compression"].iloc[-1] == 1),
        "src": source,
        "dollar_vol": info.get("dollar_vol"),
    }
    if st["status"] != "none":
        width = st["box_high"] - st["box_low"]
        row.update({
            "box_high": round(st["box_high"], 4),
            "box_low": round(st["box_low"], 4),
            "box_bars": st["box_bars"],
            "box_width_atr": round(width / atr14, 3) if atr14 > 0 else None,
            "box_width_pct": round(100 * width / last_close, 3),
            "box_start_ts": df.index[st["box_start"]].isoformat(),
        })
        if st.get("lock_bar") is not None:
            row["lock_ts"] = df.index[st["lock_bar"]].isoformat()
            row["bars_since_lock"] = int(len(df) - 1 - st["lock_bar"])
        if st["status"] == "breakout":
            bb = st["break_bar"]
            row.update({
                "break_dir": st["break_dir"],
                "break_ts": df.index[bb].isoformat(),
                "bars_since_break": int(len(df) - 1 - bb),
                "break_level": row["box_high"] if st["break_dir"] == "up" else row["box_low"],
                "break_session": bar_session(df.index[bb]),
            })
            row.update(breakout_quality_fields(df, st))
        if st["status"] == "locked":
            row["watch_bars_left"] = int(BREAK_LOOKBACK - (len(df) - 1 - st["lock_bar"]))
    return row


def flag_near_breaks(rows):
    """Mark armed boxes whose nearest boundary is within PROXIMITY_ATR
    hourly ATRs of the live price — a break is plausible within ~1 bar."""
    for r in rows:
        if r["status"] != "locked" or not r.get("atr14"):
            continue
        dist_up = r["box_high"] - r["last_price"]
        dist_dn = r["last_price"] - r["box_low"]
        side, dist = ("up", dist_up) if dist_up <= dist_dn else ("down", dist_dn)
        dist = max(dist, 0.0)  # snapshot price can drift past the bar data
        if dist <= PROXIMITY_ATR * r["atr14"]:
            r["near_break"] = side
            r["near_dist_atr"] = round(dist / r["atr14"], 3)


def breakout_alert_gate(r):
    """Telegram quality gate for a raw breakout row: returns the list of
    blockers (empty = alert-eligible). The dashboard shows the raw break
    either way. Intrabar breaks are allowed; the key quality filter is
    that the break bar is no longer in compression/has entered expansion."""
    blockers = []
    if r.get("break_session") != "rth":
        blockers.append("session_not_rth")
    if not r.get("break_expansion_confirmed"):
        blockers.append("break_bar_in_compression")
    w = r.get("box_width_atr")
    if w is None or w > MAX_ALERT_BOX_WIDTH_ATR:
        blockers.append("box_too_wide")
    return blockers


def near_break_alert_gate(r):
    """Telegram quality gate for a ⚡ near-break row: box must be armed
    for expansion (compression over), under the width cap, and the price
    genuinely close (ALERT_PROXIMITY_ATR, not the looser dashboard 0.25)."""
    blockers = []
    if r.get("in_compression"):
        blockers.append("still_in_compression")
    w = r.get("box_width_atr")
    if w is None or w > MAX_ALERT_BOX_WIDTH_ATR:
        blockers.append("box_too_wide")
    d = r.get("near_dist_atr")
    if d is None or d > ALERT_PROXIMITY_ATR:
        blockers.append("outside_alert_proximity")
    return blockers


def annotate_alert_quality(rows):
    """Attach alert_quality/alert_blockers to every row a gate applies to,
    so the JSON and alerts.log answer 'why did/didn't this alert?'."""
    for r in rows:
        if r["status"] == "breakout":
            blockers = breakout_alert_gate(r)
        elif r.get("near_break"):
            blockers = near_break_alert_gate(r)
        else:
            continue
        r["alert_blockers"] = blockers
        r["alert_quality"] = "pass" if not blockers else "blocked"


def bar_session(ts):
    """Session of a bar by its START time, using the study's convention
    (RTH = start >= 9:30 and < 16:00 ET). On the top-of-hour grid the
    9:00 bar counts as premarket, exactly as in the backtest events.

    Why it matters (computed from the study's own 1h events, immediate
    entry, Net-R at w10): RTH breaks median +0.12R (n=1,479) carry ALL
    of the 1h edge; premarket breaks +0.02R (n=1,471) are flat;
    after-hours breaks -0.17R (n=527) are negative. Only RTH breaks
    alert."""
    mins = ts.hour * 60 + ts.minute
    if 9 * 60 + 30 <= mins < 16 * 60:
        return "rth"
    return "premarket" if mins < 9 * 60 + 30 else "afterhours"


# ── Alert dedup ──

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def detect_new_breakouts(rows, state):
    """Returns (new_raw, new_alerts).

    new_raw: raw breakouts seen for the first time — logged and listed on
    the dashboard, dedup key sym|lock_ts|dir. new_alerts: breakouts that
    pass the Telegram quality gate, deduped on a separate '|alerted' key —
    a break first seen blocked (bar still forming, wick-only so far) can
    still alert once it confirms, but never twice."""
    now_iso = datetime.now(timezone.utc).isoformat()
    new_raw, new_alerts = [], []
    for r in rows:
        if r["status"] != "breakout":
            continue
        raw_key = f"{r['sym']}|{r.get('lock_ts')}|{r['break_dir']}"
        if raw_key not in state:
            state[raw_key] = now_iso
            new_raw.append(r)
        alert_key = raw_key + "|alerted"
        if r.get("alert_quality") == "pass" and alert_key not in state:
            state[alert_key] = now_iso
            new_alerts.append(r)
    # prune entries older than 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for k in [k for k, v in state.items()
              if datetime.fromisoformat(v) < cutoff]:
        del state[k]
    return new_raw, new_alerts


def detect_new_pre_breakouts(rows, state, now=None):
    """Pre-break alerts: quality-gated near-break rows, once per box+side.
    Only fires while RTH is open — the study says only RTH breaks are
    signals, so there is nothing to pre-alert outside the session. A row
    still blocked by the gate does NOT consume its dedup key, so it can
    alert later (e.g. once compression actually ends)."""
    now = now if now is not None else datetime.now(ET)
    mins = now.hour * 60 + now.minute
    if now.weekday() >= 5 or not (9 * 60 + 30 <= mins < 16 * 60):
        return []
    now_iso = datetime.now(timezone.utc).isoformat()
    new = []
    for r in rows:
        if not r.get("near_break") or r.get("alert_quality") != "pass":
            continue
        key = f"{r['sym']}|{r.get('lock_ts')}|{r['near_break']}|pre"
        if key not in state:
            state[key] = now_iso
            new.append(r)
    return new


def send_telegram(text):
    """Deliver via the Hermes agent (`hermes send` reuses its Telegram
    credentials; no agent loop). Returns True on success."""
    try:
        res = subprocess.run(
            [HERMES_BIN, "send", "--to", TELEGRAM_TARGET, "-q", text],
            capture_output=True, text=True, timeout=45)
        if res.returncode != 0:
            print(f"telegram send failed: {res.stderr.strip()[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"telegram send failed: {e}", file=sys.stderr)
        return False


def format_alerts(new_breakouts, new_pre):
    lines = []
    for r in new_breakouts:
        arrow = "🟢⬆️" if r["break_dir"] == "up" else "🔴⬇️"
        lines.append(
            f"{arrow} QUALIFIED BILBO BREAK {r['sym']} {r['break_dir'].upper()} — "
            f"intrabar expansion break through {'box high' if r['break_dir'] == 'up' else 'box low'} "
            f"{r['break_level']:.2f}; last {r['last_price']:.2f} "
            f"(box {r['box_bars']} bars, {r['box_width_atr']:.2f}×ATR, "
            f"stop = other side {r['box_low' if r['break_dir'] == 'up' else 'box_high']:.2f})")
    for r in new_pre:
        side = r["near_break"]
        lvl = r["box_high"] if side == "up" else r["box_low"]
        lines.append(
            f"⚡ QUALIFIED NEAR BREAK {r['sym']} — last {r['last_price']:.2f} is "
            f"{r['near_dist_atr']:.2f}×ATR from box {'high' if side == 'up' else 'low'} "
            f"{lvl:.2f} (box {r['box_bars']} bars, {r['box_width_atr']:.2f}×ATR wide); "
            f"watch only if it remains out of compression")
    return lines


# ── Main ──

def in_rth_window():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 25) <= mins <= (16 * 60 + 10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--rth-only", action="store_true",
                    help="exit silently outside 9:25-16:10 ET Mon-Fri")
    ap.add_argument("--tickers", help="comma-separated subset for debugging")
    ap.add_argument("--top", type=int, default=TOP_N,
                    help=f"scan the N most liquid names (default {TOP_N})")
    ap.add_argument("--quiet-alerts", action="store_true",
                    help="record alerts in state/log but do not send Telegram "
                         "(use once to seed state before enabling the cron)")
    args = ap.parse_args()

    if args.refresh_universe:
        refresh_universe()
        if not args.tickers:
            return

    if args.rth_only and not in_rth_window():
        return

    u = load_universe()
    all_tickers = u["tickers"]
    dollar_vol = dict(u["ranked"])
    if args.tickers:
        want = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        # Top N by liquidity, collapsing dual-class listings (GOOG/GOOGL,
        # FOX/FOXA, ...) to the more liquid class so slots aren't wasted.
        import re
        want, seen_co = [], set()
        for s, _ in u["ranked"]:
            name = all_tickers.get(s, {}).get("name", s)
            co = re.sub(r"\s*\(Class [A-C]\)\s*", "", name).strip() or s
            if co in seen_co:
                continue
            seen_co.add(co)
            want.append(s)
            if len(want) >= args.top:
                break
    uni = {s: all_tickers.get(s, {"name": s, "sp500": False, "ndx": False, "sector": ""})
           for s in want}
    for s in uni:
        uni[s] = {**uni[s], "dollar_vol": dollar_vol.get(s)}

    t0 = time.time()
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(scan_ticker, s, info): s for s, info in uni.items()}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                rows.append(fut.result())
            except Exception as e:
                errors.append({"sym": s, "error": str(e)[:160]})
    rows.sort(key=lambda r: r["sym"])

    # One bulk pass for live last prices (Massive snapshot); bar closes
    # already fill last_price for anything the snapshot misses.
    snap = fetch_snapshot_prices([r["sym"] for r in rows])
    for r in rows:
        if r["sym"] in snap:
            r["last_price"] = snap[r["sym"]]
    elapsed = time.time() - t0

    flag_near_breaks(rows)
    annotate_alert_quality(rows)
    state = load_state()
    new_raw_breaks, new_break_alerts = detect_new_breakouts(rows, state)
    new_pre = detect_new_pre_breakouts(rows, state)
    os.makedirs(SCAN_DIR, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=1)
    if new_raw_breaks or new_break_alerts or new_pre:
        # Log every raw first-sighting (with the gate's verdict) plus the
        # gate passes that actually went to Telegram.
        with open(ALERTS_LOG, "a") as f:
            for kind, group in (("break_raw", new_raw_breaks),
                                ("break_alert", new_break_alerts),
                                ("pre_break", new_pre)):
                for r in group:
                    f.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "type": kind,
                        "sym": r["sym"],
                        "dir": r.get("break_dir") or r.get("near_break"),
                        "level": r.get("break_level") or (
                            r["box_high"] if r.get("near_break") == "up" else r.get("box_low")),
                        "last_price": r["last_price"],
                        "box_bars": r.get("box_bars"),
                        "box_width_atr": r.get("box_width_atr"),
                        "session": r.get("break_session"),
                        "alert_quality": r.get("alert_quality"),
                        "alert_blockers": r.get("alert_blockers"),
                        "break_bar_closed": r.get("break_bar_closed"),
                        "break_expansion_confirmed": r.get("break_expansion_confirmed"),
                        "break_close_confirmed": r.get("break_close_confirmed"),
                    }) + "\n")
        if not args.quiet_alerts and (new_break_alerts or new_pre):
            lines = format_alerts(new_break_alerts, new_pre)
            sent = send_telegram("\n".join(lines))
            print(f"telegram: {'sent' if sent else 'FAILED'} {len(lines)} alert(s)")

    now_utc = datetime.now(timezone.utc)
    counts = {k: sum(1 for r in rows if r["status"] == k)
              for k in ("breakout", "locked", "forming", "none")}
    out = {
        "generated_utc": now_utc.isoformat(),
        "generated_ct": now_utc.astimezone(CT).strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "elapsed_sec": round(elapsed, 1),
        "universe_size": len(uni),
        "scanned": len(rows),
        "counts": counts,
        "params": {"box_max_bars": BOX_MAX_BARS, "break_lookback": BREAK_LOOKBACK,
                   "breakout_display_bars": BREAKOUT_DISPLAY_BARS,
                   "timeframe": "1h ETH",
                   "source": {"massive": sum(1 for r in rows if r["src"] == "massive"),
                              "yahoo": sum(1 for r in rows if r["src"] == "yahoo")}},
        "new_breakouts": [r["sym"] for r in new_raw_breaks],
        "new_break_alerts": [r["sym"] for r in new_break_alerts],
        "new_pre_breakouts": [r["sym"] for r in new_pre],
        "errors": errors,
        "tickers": rows,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace(tmp, OUT_JSON)

    print(f"{out['generated_ct']} | scanned {len(rows)}/{len(uni)} in {elapsed:.0f}s | "
          f"breakout {counts['breakout']}, locked {counts['locked']}, "
          f"forming {counts['forming']} | raw new: {','.join(out['new_breakouts']) or '-'} | "
          f"alerted: {','.join(out['new_break_alerts']) or '-'} | "
          f"errors {len(errors)}")


if __name__ == "__main__":
    main()
