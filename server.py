"""
SPY Chart Visualizer — FastAPI backend
Serves candlestick data with Saty indicators for a TradingView-lite experience.
"""
import os
import calendar as cal
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
import pandas as pd
import numpy as np
from study_utils import compute_resampled_atr_ref, dedupe_signals_by_daily_cooldown

app = FastAPI(title="SPY Visualizer")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "spy.db")

# ═══════════════════════════════════════════════════════════════
# Mode configurations
# ═══════════════════════════════════════════════════════════════

MODES = {
    "big_picture": {
        "label": "Big Picture", "group": "Macro",
        "tf": "1M", "src": "1d", "atr_mode": None,
        "warp": None, "session": "ETH",
        "range_days": 3650, "warmup_days": 7300,
        "nav_delta": {"years": 5},
        "desc": "Monthly \u00b7 No ATR",
    },
    "long_term": {
        "label": "Long-term", "group": "Macro",
        "tf": "1w", "src": "1w", "atr_mode": "yearly",
        "warp": None, "session": "ETH",
        "range_days": 1825, "warmup_days": 1500,
        "nav_delta": {"years": 1},
        "desc": "Weekly \u00b7 Yearly ATR",
    },
    "position": {
        "label": "Position", "group": "Macro",
        "tf": "1d", "src": "1d", "atr_mode": "quarterly",
        "warp": None, "session": "ETH",
        "range_days": 365, "warmup_days": 400,
        "nav_delta": {"months": 3},
        "desc": "Daily \u00b7 Quarterly ATR",
    },
    "swing": {
        "label": "Swing", "group": "Swing",
        "tf": "1h", "src": "1h", "atr_mode": "monthly",
        "warp": None, "session": "RTH",
        "range_days": 56, "warmup_days": 120,
        "nav_delta": {"weeks": 2},
        "desc": "Hourly RTH \u00b7 Monthly ATR",
    },
    "swing_hd": {
        "label": "Swing H/D", "group": "Swing",
        "tf": "1h", "src": "1h", "atr_mode": "monthly",
        "warp": "1d", "session": "RTH",
        "range_days": 56, "warmup_days": 120,
        "nav_delta": {"weeks": 2},
        "desc": "Hourly RTH \u00b7 Monthly ATR \u00b7 Daily Warp",
    },
    "multiday": {
        "label": "Multiday", "group": "Intraday",
        "tf": "1h", "src": "1h", "atr_mode": "weekly",
        "warp": None, "session": "ETH",
        "range_days": 10, "warmup_days": 90,
        "nav_delta": {"days": 5},
        "desc": "Hourly ETH \u00b7 Weekly ATR",
    },
    "day": {
        "label": "Day", "group": "Intraday",
        "tf": "10m", "src": "10m", "atr_mode": "daily",
        "warp": None, "session": "ETH",
        "range_days": 1, "warmup_days": 14,
        "nav_delta": {"days": 1},
        "desc": "10min ETH \u00b7 Daily ATR",
    },
    "day_3_10": {
        "label": "Day 3/10", "group": "Intraday",
        "tf": "3m", "src": "3m", "atr_mode": "daily",
        "warp": "10m", "session": "ETH",
        "range_days": 1, "warmup_days": 14,
        "nav_delta": {"days": 1},
        "desc": "3min ETH \u00b7 Daily ATR \u00b7 10min Warp",
    },
    "day_rth": {
        "label": "Day RTH", "group": "Intraday",
        "tf": "3m", "src": "3m", "atr_mode": "daily",
        "warp": None, "session": "RTH",
        "range_days": 1, "warmup_days": 14,
        "nav_delta": {"days": 1},
        "desc": "3min RTH \u00b7 Daily ATR",
    },
}

# ═══════════════════════════════════════════════════════════════
# Indicator math
# ═══════════════════════════════════════════════════════════════

def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _atr(df, n=14):
    """ATR using Wilder's RMA (matches TradingView's ta.atr)."""
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def calc_ribbon(df):
    p = df["close"]
    for n in (8, 13, 21, 48, 200):
        df[f"ema_{n}"] = _ema(p, n)
    return df


def calc_phase(df):
    p = df["close"]
    a = _atr(df, 14)
    stdev = p.rolling(21, min_periods=1).std()
    pivot = _ema(p, 21)
    raw = ((p - pivot) / (3.0 * a)) * 100.0
    phase = _ema(raw, 3)
    df["phase"] = phase

    # Compression: BB width < 2*ATR
    above_pivot = p >= pivot
    bb_offset = 2.0 * stdev
    bb_up = pivot + bb_offset
    bb_down = pivot - bb_offset
    comp_thresh_up = pivot + (2.0 * a)
    comp_thresh_down = pivot - (2.0 * a)
    exp_thresh_up = pivot + (1.854 * a)
    exp_thresh_down = pivot - (1.854 * a)

    compression_val = np.where(above_pivot, bb_up - comp_thresh_up, comp_thresh_down - bb_down)
    in_exp_zone = np.where(above_pivot, bb_up - exp_thresh_up, exp_thresh_down - bb_down)
    comp_s = pd.Series(compression_val, index=df.index)
    inexp_s = pd.Series(in_exp_zone, index=df.index)
    exp_flag = comp_s.shift(1) <= comp_s

    po_comp = np.zeros(len(df), dtype=int)
    for i in range(1, len(df)):
        if exp_flag.iloc[i] and inexp_s.iloc[i] > 0:
            po_comp[i] = 0
        elif comp_s.iloc[i] <= 0:
            po_comp[i] = 1
        else:
            po_comp[i] = 0
    df["po_compression"] = po_comp

    # Leaving accumulation/distribution signals
    prev_phase = phase.shift(1)
    df["leaving_acc"] = ((prev_phase <= -61.8) & (phase > -61.8)).astype(int)
    df["leaving_dist"] = ((prev_phase >= 61.8) & (phase < 61.8)).astype(int)
    df["leaving_ext_down"] = ((prev_phase <= -100) & (phase > -100)).astype(int)
    df["leaving_ext_up"] = ((prev_phase >= 100) & (phase < 100)).astype(int)

    return df


def calc_atr_levels(ref_df):
    if ref_df is None or len(ref_df) < 15:
        return None
    a = _atr(ref_df, 14)
    pc = float(ref_df["close"].iloc[-1])
    av = float(a.iloc[-1])
    r2 = lambda v: round(v, 2)
    lvls = {"pc": r2(pc), "atr": r2(av)}
    for fib, tag in [(0.236, "trig"), (0.382, "382"), (0.5, "50"),
                     (0.618, "618"), (0.786, "786"), (1.0, "100")]:
        lvls[f"u{tag}"] = r2(pc + fib * av)
        lvls[f"l{tag}"] = r2(pc - fib * av)
    u1, l1 = pc + av, pc - av
    for ext, tag in [(0.236, "1236"), (0.382, "1382"), (0.5, "150"), (0.618, "1618")]:
        lvls[f"u{tag}"] = r2(u1 + ext * av)
        lvls[f"l{tag}"] = r2(l1 - ext * av)
    return lvls


def calc_atr_levels_multi(atr_mode, vis_start, end_date):
    """Compute ATR levels for each period in the visible range.
    Returns list of {date, levels} dicts."""
    c = _conn()
    try:
        if atr_mode == "daily":
            df = pd.read_sql(
                "SELECT timestamp,open,high,low,close,volume FROM candles_1d ORDER BY timestamp",
                c, parse_dates=["timestamp"])
            if not df.empty:
                df = df.set_index("timestamp").sort_index()
                df = _append_yahoo_daily(df, end_date)
                df = df.reset_index()
        elif atr_mode == "weekly":
            df = pd.read_sql(
                "SELECT timestamp,open,high,low,close,volume FROM candles_1w ORDER BY timestamp",
                c, parse_dates=["timestamp"])
        elif atr_mode in ("monthly", "quarterly", "yearly"):
            raw = pd.read_sql(
                "SELECT timestamp,open,high,low,close,volume FROM candles_1d ORDER BY timestamp",
                c, parse_dates=["timestamp"])
            raw = raw.set_index("timestamp").sort_index()
            freq = {"monthly": "MS", "quarterly": "QS", "yearly": "YS"}[atr_mode]
            df = raw.resample(freq).agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna().reset_index()
        else:
            return []
    finally:
        c.close()

    if df.empty:
        return []
    df = df.set_index("timestamp").sort_index()

    # Compute ATR for all periods
    atr_vals = _atr(df, 14)

    # Find periods that overlap with the visible range
    result = []
    vis_ts = pd.Timestamp(vis_start)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)

    for i in range(1, len(df)):
        period_start = df.index[i]
        if i + 1 < len(df):
            period_end = df.index[i + 1]
        else:
            period_end = end_ts + pd.Timedelta(days=30)

        # Check if this period overlaps with visible range
        # Use <= for start boundary: if a period ends exactly at vis_start,
        # it has no candles in the visible range (its candles are all before vis_start).
        # Use >= for end boundary: exclude periods starting on the day AFTER the chart date.
        if period_end <= vis_ts or period_start >= end_ts:
            continue

        pc = float(df["close"].iloc[i - 1])  # previous period close
        av = float(atr_vals.iloc[i - 1])
        if np.isnan(av) or av == 0:
            continue

        r2 = lambda v: round(v, 2)
        lvls = {"pc": r2(pc), "atr": r2(av)}
        for fib, tag in [(0.236, "trig"), (0.382, "382"), (0.5, "50"),
                         (0.618, "618"), (0.786, "786"), (1.0, "100")]:
            lvls[f"u{tag}"] = r2(pc + fib * av)
            lvls[f"l{tag}"] = r2(pc - fib * av)
        u1, l1 = pc + av, pc - av
        for ext, tag in [(0.236, "1236"), (0.382, "1382"), (0.5, "150"), (0.618, "1618")]:
            lvls[f"u{tag}"] = r2(u1 + ext * av)
            lvls[f"l{tag}"] = r2(l1 - ext * av)

        result.append({
            "date": period_start.strftime("%Y-%m-%d"),
            "levels": lvls,
        })

    return result


# ═══════════════════════════════════════════════════════════════
# Yahoo Finance — same-day data
# ═══════════════════════════════════════════════════════════════

import requests as _requests
from datetime import datetime as _dt, timezone as _tz, timedelta as _td

def _utc_to_et(utc_ts):
    """Convert UTC unix timestamp to ET datetime."""
    utc = _dt.fromtimestamp(utc_ts, tz=_tz.utc)
    yr = utc.year
    mar = _dt(yr, 3, 8 + (6 - _dt(yr, 3, 1).weekday()) % 7, 2, tzinfo=_tz.utc)
    nov = _dt(yr, 11, 1 + (6 - _dt(yr, 11, 1).weekday()) % 7, 2, tzinfo=_tz.utc)
    off = _td(hours=-4) if mar <= utc < nov else _td(hours=-5)
    return utc + off

def fetch_yahoo_today():
    """Fetch today's 1-minute SPY bars from Yahoo Finance."""
    try:
        resp = _requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
            params={"interval": "1m", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return pd.DataFrame()

        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]

        rows = []
        for i, ts in enumerate(timestamps):
            o = quotes.get("open", [])[i]
            h = quotes.get("high", [])[i]
            l = quotes.get("low", [])[i]
            c = quotes.get("close", [])[i]
            v = quotes.get("volume", [])[i]
            if o is None or c is None:
                continue
            et = _utc_to_et(ts)
            rows.append({
                "timestamp": et.replace(tzinfo=None),
                "open": float(o), "high": float(h), "low": float(l),
                "close": float(c), "volume": int(v or 0),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        return df
    except Exception as e:
        print(f"Yahoo fetch error: {e}")
        return pd.DataFrame()


def _fetch_yahoo_daily_history(days=10):
    """Fetch recent daily bars from Yahoo Finance to fill DB gaps."""
    try:
        resp = _requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
            params={"interval": "1d", "range": f"{days}d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return pd.DataFrame()
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        rows = []
        for i, ts in enumerate(timestamps):
            o = quotes.get("open", [])[i]
            h = quotes.get("high", [])[i]
            l = quotes.get("low", [])[i]
            c = quotes.get("close", [])[i]
            v = quotes.get("volume", [])[i]
            if o is None or c is None:
                continue
            et = _utc_to_et(ts)
            rows.append({
                "timestamp": pd.Timestamp(et.strftime("%Y-%m-%d")),
                "open": float(o), "high": float(h), "low": float(l),
                "close": float(c), "volume": int(v or 0),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).set_index("timestamp").sort_index()
        return df
    except Exception as e:
        print(f"Yahoo daily history fetch error: {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════
# Database helpers
# ═══════════════════════════════════════════════════════════════

def _conn():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _scrub_bad_ticks(df):
    """Remove bad ticks where high-low range exceeds 2% of close price.
    These are phantom prints common in after-hours data. Instead of dropping
    the candle, clamp high/low to open/close extremes."""
    if df.empty:
        return df
    oc_high = df[["open", "close"]].max(axis=1)
    oc_low = df[["open", "close"]].min(axis=1)
    range_pct = (df["high"] - df["low"]) / df["close"]
    bad = range_pct > 0.02
    if bad.any():
        df.loc[bad, "high"] = oc_high[bad]
        df.loc[bad, "low"] = oc_low[bad]
    return df


def fetch(table, start, end, session="ETH"):
    c = _conn()
    try:
        df = pd.read_sql(
            f"SELECT timestamp,open,high,low,close,volume FROM {table} "
            f"WHERE timestamp>=? AND timestamp<=? ORDER BY timestamp",
            c, params=[start, end], parse_dates=["timestamp"],
        )
    finally:
        c.close()
    if df.empty:
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    else:
        df = df.set_index("timestamp").sort_index()
        df = _scrub_bad_ticks(df)

    # Append today's Yahoo data for 1-minute-based tables
    if table in ("candles_10m", "candles_3m", "candles_1m", "candles_1h"):
        utc_now = pd.Timestamp.now(tz="UTC")
        et_now = utc_now.tz_convert("America/New_York")
        today_str = et_now.strftime("%Y-%m-%d")
        if end >= today_str:
            yahoo = fetch_yahoo_today()
            if not yahoo.empty:
                # Resample Yahoo 1m data to match table timeframe
                tf_map = {"candles_1m": "1min", "candles_3m": "3min",
                          "candles_10m": "10min", "candles_1h": "1h"}
                tf = tf_map.get(table, "10min")
                if tf != "1min":
                    yahoo = yahoo.resample(tf).agg({
                        "open": "first", "high": "max", "low": "min",
                        "close": "last", "volume": "sum",
                    }).dropna(subset=["open"])

                # Only add bars newer than what's in the database
                if not df.empty:
                    last_db = df.index.max()
                    yahoo = yahoo[yahoo.index > last_db]
                if not yahoo.empty:
                    df = pd.concat([df, yahoo])

    if session == "RTH":
        df = df[df.index.map(lambda t: 570 <= t.hour * 60 + t.minute < 960)]
    return df


def _synth_daily_from_intraday(c, after_date, before_date):
    """Build synthetic daily candles from RTH intraday data for missing days."""
    df = pd.read_sql(
        "SELECT timestamp,open,high,low,close,volume FROM candles_1h "
        "WHERE timestamp>=? AND timestamp<? ORDER BY timestamp",
        c, params=[after_date + " 00:00:00", before_date + " 23:59:59"],
        parse_dates=["timestamp"],
    )
    if df.empty:
        return pd.DataFrame()
    df = df.set_index("timestamp").sort_index()
    # RTH only: 9:30-16:00
    df = df[df.index.map(lambda t: 570 <= t.hour * 60 + t.minute < 960)]
    if df.empty:
        return pd.DataFrame()
    daily = df.resample("D").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()
    return daily


def _append_yahoo_daily(df, before_date):
    """If DB daily data is stale, try to fill gap with Yahoo + hourly data."""
    if df.empty:
        return df
    df = df[df.index.notna()].sort_index()
    if df.empty:
        return df
    last_date = df.index[-1].strftime("%Y-%m-%d")
    before_ts = pd.Timestamp(before_date)
    last_ts = df.index[-1]
    # If the gap is more than 1 calendar day, try to fill from intraday
    gap_days = (before_ts - last_ts).days
    if gap_days <= 1:
        return df

    # Try Yahoo daily history first (most reliable for multi-day gaps)
    synth = _fetch_yahoo_daily_history(max(gap_days + 5, 10))

    # Fallback: synthesize from DB intraday + Yahoo today
    if synth.empty:
        c = _conn()
        try:
            synth = _synth_daily_from_intraday(c, last_date, before_date)
        finally:
            c.close()
        yahoo = fetch_yahoo_today()
        if not yahoo.empty:
            yahoo_rth = yahoo[yahoo.index.map(lambda t: 570 <= t.hour * 60 + t.minute < 960)]
            if not yahoo_rth.empty:
                yd = yahoo_rth.resample("D").agg(
                    {"open": "first", "high": "max", "low": "min",
                     "close": "last", "volume": "sum"}
                ).dropna()
                if not yd.empty:
                    synth = pd.concat([synth, yd]) if not synth.empty else yd

    if synth.empty:
        return df
    # Only add days newer than what's in df and before the target date
    synth = synth[synth.index > df.index[-1]]
    synth = synth[synth.index < before_ts]
    if synth.empty:
        return df
    return pd.concat([df, synth])


def fetch_ref(atr_mode, before):
    c = _conn()
    try:
        if atr_mode == "daily":
            df = pd.read_sql(
                "SELECT timestamp,open,high,low,close,volume FROM candles_1d "
                "WHERE timestamp<? ORDER BY timestamp",
                c, params=[before], parse_dates=["timestamp"],
            )
            if df.empty:
                return None
            df = df.set_index("timestamp").sort_index().iloc[-200:]
            df = _append_yahoo_daily(df, before)
            return df
        elif atr_mode == "weekly":
            df = pd.read_sql(
                "SELECT timestamp,open,high,low,close,volume FROM candles_1w "
                "WHERE timestamp<? ORDER BY timestamp",
                c, params=[before], parse_dates=["timestamp"],
            )
            if df.empty:
                return None
            return df.set_index("timestamp").sort_index().iloc[-200:]
        elif atr_mode in ("monthly", "quarterly", "yearly"):
            df = pd.read_sql(
                "SELECT timestamp,open,high,low,close,volume FROM candles_1d "
                "ORDER BY timestamp",
                c, parse_dates=["timestamp"],
            )
            if df.empty:
                return None
            df = df.set_index("timestamp").sort_index()
            freq = {"monthly": "MS", "quarterly": "QS", "yearly": "YS"}[atr_mode]
            agg = df.resample(freq).agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}
            ).dropna()
            return agg[agg.index < pd.Timestamp(before)].iloc[-200:]
    finally:
        c.close()
    return None


# ═══════════════════════════════════════════════════════════════
# Timestamp helper — treat naive timestamps as UTC for chart display
# ═══════════════════════════════════════════════════════════════

def _ts(t, daily=False):
    if daily:
        return t.strftime("%Y-%m-%d")
    return int(cal.timegm(t.timetuple()))


# ═══════════════════════════════════════════════════════════════
# API endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/api/modes")
async def api_modes():
    return {
        k: {"label": v["label"], "group": v["group"], "desc": v["desc"],
             "tf": v["tf"], "warp": v["warp"], "session": v["session"],
             "atr_mode": v["atr_mode"]}
        for k, v in MODES.items()
    }


@app.get("/api/chart")
async def api_chart(mode: str = "day", date: Optional[str] = None,
                    range_days: Optional[int] = None,
                    atr_override: Optional[str] = None,
                    ribbon_tf: Optional[str] = None,
                    candle_tf: Optional[str] = None,
                    session: Optional[str] = None):
    cfg = MODES.get(mode)
    if not cfg:
        return JSONResponse({"error": "unknown mode"}, 400)

    # Allow overriding range_days, atr_mode, and candle timeframe
    effective_range = range_days if range_days is not None else cfg["range_days"]
    effective_atr = atr_override if atr_override and atr_override != "auto" else cfg["atr_mode"]
    if atr_override == "none":
        effective_atr = None

    # Candle timeframe override: map short names to table suffixes
    tf_map = {"3m": "3m", "10m": "10m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"}
    effective_src = tf_map.get(candle_tf, cfg["src"]) if candle_tf else cfg["src"]
    effective_tf = candle_tf or cfg["tf"]
    # Session override: allow forcing RTH on any intraday timeframe
    if session and session.upper() in ("RTH", "ETH"):
        effective_session = session.upper()
    elif effective_src in ("1d", "1w"):
        effective_session = "RTH"
    else:
        effective_session = cfg.get("session", "ETH")

    # Resolve date — use today ET if no date specified
    if not date:
        utc_now = pd.Timestamp.now(tz="UTC")
        et_now = utc_now.tz_convert("America/New_York")
        date = et_now.strftime("%Y-%m-%d")

    end_dt = pd.Timestamp(date) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    if effective_range <= 1:
        vis_start = pd.Timestamp(date)
    else:
        vis_start = pd.Timestamp(date) - pd.Timedelta(days=effective_range)
    warm_start = vis_start - pd.Timedelta(days=max(cfg["warmup_days"], 1))

    end_s = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    warm_s = warm_start.strftime("%Y-%m-%d %H:%M:%S")

    # Fetch candles
    if effective_tf == "1M":
        raw = fetch("candles_1d", warm_s, end_s)
        if raw.empty:
            return JSONResponse({"error": "no data"}, 404)
        df = raw.resample("MS").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna()
    else:
        df = fetch(f"candles_{effective_src}", warm_s, end_s, effective_session)

    if df.empty:
        return JSONResponse({"error": "no data for this range"}, 404)

    # Phase oscillator (always from chart timeframe)
    df = calc_phase(df)

    # Pivot ribbon — from ribbon_tf override, warp timeframe, or chart timeframe
    ribbon_source = ribbon_tf or cfg["warp"]
    if ribbon_source and ribbon_source != effective_src:
        wt = f"candles_{ribbon_source}"
        ws = "ETH" if ribbon_source in ("1d", "1w") else effective_session
        wdf = fetch(wt, warm_s, end_s, ws)
        if not wdf.empty:
            wdf = calc_ribbon(wdf)
            ecols = [f"ema_{n}" for n in (8, 13, 21, 48, 200)]
            merged = wdf[ecols].reindex(df.index, method="ffill")
            for col in ecols:
                df[col] = merged[col]
        else:
            df = calc_ribbon(df)
    else:
        df = calc_ribbon(df)

    # ATR levels from reference timeframe
    atr_lvls = None
    atr_multi = []
    if effective_atr:
        if effective_range > 1:
            atr_multi = calc_atr_levels_multi(effective_atr, vis_start.strftime("%Y-%m-%d"), date)
        # Always include the latest set as the primary
        ref = fetch_ref(effective_atr, date)
        atr_lvls = calc_atr_levels(ref)

        # Ensure today's ATR period is in multi when the last multi period
        # predates today (DB daily bar not yet complete for current day)
        if atr_multi and atr_lvls:
            last_multi_date = atr_multi[-1]["date"]
            if last_multi_date < date:
                atr_multi.append({"date": date, "levels": atr_lvls})

    # Trim to visible range
    vis = df[df.index >= vis_start]
    if vis.empty:
        return JSONResponse({"error": "no visible data"}, 404)

    # Build compact response
    is_daily = effective_tf in ("1d", "1w", "1M")
    candles, volume, phase = [], [], []
    emas = {str(n): [] for n in (8, 13, 21, 48, 200)}

    for t, row in vis.iterrows():
        s = _ts(t, daily=is_daily)
        candles.append([s, round(row.open, 2), round(row.high, 2),
                        round(row.low, 2), round(row.close, 2)])
        volume.append([s, int(row.volume), 1 if row.close >= row.open else 0])
        pv = row.get("phase")
        if pv is not None and not np.isnan(pv):
            comp = int(row.get("po_compression", 0))
            la = int(row.get("leaving_acc", 0))
            ld = int(row.get("leaving_dist", 0))
            led = int(row.get("leaving_ext_down", 0))
            leu = int(row.get("leaving_ext_up", 0))
            # [timestamp, value, compression, leaving_signals_bitmask]
            signals = la | (ld << 1) | (led << 2) | (leu << 3)
            phase.append([s, round(pv, 2), comp, signals])
        for n in (8, 13, 21, 48, 200):
            v = row.get(f"ema_{n}")
            if v is not None and not np.isnan(v):
                emas[str(n)].append([s, round(v, 2)])

    return {
        "candles": candles, "volume": volume, "phase": phase,
        "emas": emas, "atr": atr_lvls, "atr_multi": atr_multi,
        "meta": {
            "mode": mode, "label": cfg["label"], "tf": effective_tf,
            "session": effective_session, "atr_mode": effective_atr,
            "warp": ribbon_source or effective_src, "date": date, "bars": len(vis),
            "daily": is_daily,
        },
    }


@app.get("/api/nav")
async def api_nav(mode: str, date: str, dir: str = "next"):
    cfg = MODES.get(mode)
    if not cfg:
        return JSONResponse({"error": "unknown mode"}, 400)

    dt = pd.Timestamp(date)
    delta = cfg.get("nav_delta", {"days": 1})
    sign = 1 if dir == "next" else -1

    if "days" in delta and delta["days"] == 1:
        # Day modes — find actual next/prev trading day
        c = _conn()
        try:
            if dir == "next":
                r = c.execute(
                    "SELECT DISTINCT substr(timestamp,1,10) FROM candles_1d "
                    "WHERE substr(timestamp,1,10)>? ORDER BY timestamp LIMIT 1",
                    [date],
                ).fetchone()
            else:
                r = c.execute(
                    "SELECT DISTINCT substr(timestamp,1,10) FROM candles_1d "
                    "WHERE substr(timestamp,1,10)<? ORDER BY timestamp DESC LIMIT 1",
                    [date],
                ).fetchone()
        finally:
            c.close()
        return {"date": r[0] if r else date}

    if "years" in delta:
        nd = dt + pd.DateOffset(years=delta["years"] * sign)
    elif "months" in delta:
        nd = dt + pd.DateOffset(months=delta["months"] * sign)
    elif "weeks" in delta:
        nd = dt + pd.Timedelta(weeks=delta["weeks"] * sign)
    else:
        nd = dt + pd.Timedelta(days=delta["days"] * sign)

    return {"date": nd.strftime("%Y-%m-%d")}


@app.get("/api/dates")
async def api_dates():
    c = _conn()
    try:
        res = {}
        for tf in ["1m", "3m", "10m", "1h", "1d", "1w"]:
            r = c.execute(
                f"SELECT MIN(timestamp), MAX(timestamp) FROM candles_{tf}"
            ).fetchone()
            res[tf] = {"min": r[0][:10], "max": r[1][:10]}
    finally:
        c.close()
    return res


# ═══════════════════════════════════════════════════════════════
# Study engine — query individual dates for each study
# ═══════════════════════════════════════════════════════════════

def _load_study_frames():
    """Load and cache the dataframes needed for study queries."""
    if hasattr(_load_study_frames, "_cache"):
        return _load_study_frames._cache

    c = _conn()
    try:
        df10 = pd.read_sql(
            "SELECT timestamp, open, high, low, close, "
            "atr_upper_trigger, atr_lower_trigger, "
            "atr_upper_0382, atr_lower_0382, "
            "atr_upper_0618, atr_lower_0618, "
            "atr_upper_0786, atr_lower_0786, "
            "atr_upper_100, atr_lower_100, "
            "prev_close, atr_14 "
            "FROM ind_10m ORDER BY timestamp",
            c, parse_dates=["timestamp"],
        )
        df10 = df10.set_index("timestamp").sort_index()
        df10 = df10.between_time("09:30", "15:59")
        df10 = df10.dropna(subset=["prev_close", "atr_14"])

        df1h = pd.read_sql(
            "SELECT timestamp, phase_oscillator, compression "
            "FROM ind_1h ORDER BY timestamp",
            c, parse_dates=["timestamp"],
        )
        df1h = df1h.set_index("timestamp").sort_index()
        df1h["po_prev"] = df1h["phase_oscillator"].shift(1)

        # Merge 1h PO onto 10m bars
        df10r = df10.reset_index()
        df1hr = df1h.reset_index()
        merged = pd.merge_asof(
            df10r[["timestamp"]],
            df1hr[["timestamp", "phase_oscillator", "po_prev", "compression"]],
            on="timestamp", direction="backward",
        )
        df10["po_60m"] = merged["phase_oscillator"].values
        df10["po_prev_60m"] = merged["po_prev"].values
        df10["comp_60m"] = merged["compression"].values
        df10["date"] = df10.index.date
    finally:
        c.close()

    _load_study_frames._cache = df10
    return df10


def _classify_po(val, prev, comp):
    if val > 61.8:
        zone = "high"
    elif val < -61.8:
        zone = "low"
    else:
        zone = "mid"
    slope = "rising" if val > prev else "falling"
    return zone, slope


def _run_gg_study(direction, po_filter=None):
    """Run a Golden Gate study query.
    direction: 'bull' or 'bear'
    po_filter: None (baseline) or (zone, slope) tuple e.g. ('high','rising')
    Returns list of {date, result, trigger_hour, detail}
    """
    df10 = _load_study_frames()
    results = []

    for date, group in df10.groupby("date"):
        first = group.iloc[0]
        if direction == "bull":
            gate_entry = first["atr_upper_0382"]
            gate_exit = first["atr_upper_0618"]
            if pd.isna(gate_entry):
                continue
            if first["open"] >= gate_entry:
                trigger_idx = 0
                trigger_hour = "open"
            else:
                hit = group["high"] >= gate_entry
                if hit.any():
                    trigger_idx = hit.values.argmax()
                    trigger_hour = str(group.index[trigger_idx].hour)
                else:
                    continue
        else:
            gate_entry = first["atr_lower_0382"]
            gate_exit = first["atr_lower_0618"]
            if pd.isna(gate_entry):
                continue
            if first["open"] <= gate_entry:
                trigger_idx = 0
                trigger_hour = "open"
            else:
                hit = group["low"] <= gate_entry
                if hit.any():
                    trigger_idx = hit.values.argmax()
                    trigger_hour = str(group.index[trigger_idx].hour)
                else:
                    continue

        # PO filter
        if po_filter is not None:
            row = group.iloc[trigger_idx]
            pv = row.get("po_60m", np.nan)
            pp = row.get("po_prev_60m", np.nan)
            if pd.isna(pv) or pd.isna(pp):
                continue
            zone, slope = _classify_po(pv, pp, 0)
            if (zone, slope) != po_filter:
                continue

        # Check completion
        start_idx = trigger_idx if trigger_hour == "open" else trigger_idx + 1
        remaining = group.iloc[start_idx:]
        if direction == "bull":
            completed = (remaining["high"] >= gate_exit).any()
        else:
            completed = (remaining["low"] <= gate_exit).any()

        trigger_ts = group.index[trigger_idx]
        results.append({
            "date": str(date),
            "result": "for" if completed else "against",
            "trigger_time": trigger_ts.strftime("%H:%M"),
        })

    return results


def _run_trigger_box_study(direction):
    """Trigger box study: open inside the box, track GG open rate.
    Bull box: open > PDC but < call trigger (23.6%).
    Bear box: open < PDC but > put trigger (23.6%).
    """
    df10 = _load_study_frames()
    results = []

    for date, group in df10.groupby("date"):
        first = group.iloc[0]
        pdc = first["prev_close"]
        if pd.isna(pdc):
            continue

        if direction == "bull":
            call_trig = first["atr_upper_trigger"]
            gate_entry = first["atr_upper_0382"]
            if pd.isna(call_trig) or pd.isna(gate_entry):
                continue
            op = first["open"]
            if not (op > pdc and op < call_trig):
                continue
            # Did the GG open (38.2% reached)?
            completed = (group["high"] >= gate_entry).any()
        else:
            put_trig = first["atr_lower_trigger"]
            gate_entry = first["atr_lower_0382"]
            if pd.isna(put_trig) or pd.isna(gate_entry):
                continue
            op = first["open"]
            if not (op < pdc and op > put_trig):
                continue
            completed = (group["low"] <= gate_entry).any()

        results.append({
            "date": str(date),
            "result": "for" if completed else "against",
            "trigger_time": "open",
        })

    return results


def _third_friday(year, month):
    """Return date of the 3rd Friday of given year/month."""
    d = pd.Timestamp(year=year, month=month, day=1)
    first_fri_offset = (4 - d.dayofweek) % 7
    return (d + pd.Timedelta(days=first_fri_offset + 14)).normalize()


def _trading_days_to_opex(date, trading_days_index):
    """Return trading days to nearest monthly OpEx (negative=after, positive=before, 0=OpEx)."""
    y, m = date.year, date.month
    candidates = []
    for delta_m in [-1, 0, 1]:
        ny = y + (1 if m + delta_m > 12 else (-1 if m + delta_m < 1 else 0))
        nm = ((m + delta_m - 1) % 12) + 1
        candidates.append(_third_friday(ny, nm))
    diffs = []
    for opex in candidates:
        try:
            opex_idx = trading_days_index.searchsorted(opex)
            if opex_idx >= len(trading_days_index):
                continue
            date_idx = trading_days_index.searchsorted(date)
            if date_idx >= len(trading_days_index):
                continue
            diffs.append(opex_idx - date_idx)
        except Exception:
            continue
    if not diffs:
        return None
    return min(diffs, key=abs)


def _load_4h_po_opex_frames():
    """Load frames needed for the 4H PO OpEx study. Cached."""
    if hasattr(_load_4h_po_opex_frames, "_cache"):
        return _load_4h_po_opex_frames._cache

    c = _conn()
    try:
        df4h = pd.read_sql(
            "SELECT timestamp, close, phase_oscillator FROM ind_4h ORDER BY timestamp",
            c, parse_dates=["timestamp"]
        ).set_index("timestamp").dropna(subset=["phase_oscillator"])

        df1d = pd.read_sql(
            "SELECT timestamp, open, high, low, close FROM ind_1d ORDER BY timestamp",
            c, parse_dates=["timestamp"]
        ).set_index("timestamp")
    finally:
        c.close()

    wk_ref = compute_resampled_atr_ref(df1d, "W-FRI").rename(
        columns={"prev_close": "prev_wk_close", "atr": "wk_atr"}
    )
    df1d_enr = pd.merge_asof(
        df1d.reset_index().sort_values("timestamp"),
        wk_ref.reset_index().sort_values("timestamp"),
        on="timestamp", direction="backward"
    ).set_index("timestamp")

    mo_ref = compute_resampled_atr_ref(df1d, "ME").rename(
        columns={"prev_close": "prev_month_close", "atr": "monthly_atr"}
    ).reindex(df1d.index, method="ffill")
    df1d_enr = df1d_enr.join(mo_ref)

    _load_4h_po_opex_frames._cache = (df4h, df1d_enr)
    return _load_4h_po_opex_frames._cache


def _run_4h_po_opex_study(ext_min=0.618, drop_threshold=1.0, horizon_days=10):
    """4H PO rollover (peak ≥80, cross below 80) near monthly OpEx, under extended ATR.

    Event = ≥ drop_threshold% intraday drop within horizon_days trading days.
    OpEx window = signal fires on OpEx Friday or the following 1-5 trading days.
    Extended = weekly OR monthly ATR position ≥ ext_min.
    """
    df4h, df1d = _load_4h_po_opex_frames()
    trading_days = df1d.index

    # Find V2 signals
    po = df4h["phase_oscillator"]
    was_above = False
    peak = 0
    signals = []
    for i in range(1, len(df4h)):
        cur = po.iloc[i]
        prev = po.iloc[i - 1]
        if prev >= 80:
            if not was_above:
                was_above = True
                peak = prev
            elif prev > peak:
                peak = prev
        if was_above and prev >= 80 and cur < 80:
            signals.append({
                "signal_time": df4h.index[i],
                "peak_po": peak,
                "signal_close": df4h.iloc[i]["close"],
            })
            was_above = False
            peak = 0

    signals = dedupe_signals_by_daily_cooldown(signals, df1d.index, horizon_days)

    results = []
    for s in signals:
        sig_time = s["signal_time"]
        sig_date = sig_time.normalize()
        sig_close = s["signal_close"]

        dloc = df1d.index.searchsorted(sig_date)
        if dloc >= len(df1d):
            continue
        if df1d.index[dloc] < sig_date:
            dloc += 1
        if dloc >= len(df1d):
            continue
        drow = df1d.iloc[dloc]
        actual_date = df1d.index[dloc]

        opex_offset = _trading_days_to_opex(actual_date, trading_days)
        if opex_offset is None:
            continue
        # Window: OpEx Fri (0) or post-OpEx 1-5 trading days (offsets -1 to -5)
        if not (-5 <= opex_offset <= 0):
            continue

        # Extended filter
        wk_pos = None
        if pd.notna(drow.get("prev_wk_close")) and pd.notna(drow.get("wk_atr")) and drow["wk_atr"] > 0:
            wk_pos = (sig_close - drow["prev_wk_close"]) / drow["wk_atr"]
        mo_pos = None
        if pd.notna(drow.get("prev_month_close")) and pd.notna(drow.get("monthly_atr")) and drow["monthly_atr"] > 0:
            mo_pos = (sig_close - drow["prev_month_close"]) / drow["monthly_atr"]

        extended = ((wk_pos is not None and wk_pos >= ext_min) or
                    (mo_pos is not None and mo_pos >= ext_min))
        if not extended:
            continue

        # Forward drop
        end = min(dloc + horizon_days + 1, len(df1d))
        fut = df1d.iloc[dloc + 1:end]
        if len(fut) == 0:
            continue
        hit = (fut["low"] <= sig_close * (1 - drop_threshold / 100)).any()

        results.append({
            "date": str(actual_date.date()),
            "result": "for" if hit else "against",
            "trigger_time": sig_time.strftime("%H:%M"),
        })

    return results


# ═══════════════════════════════════════════════════════════════
# Gap Up Pre-Noon Study
# ═══════════════════════════════════════════════════════════════

def _load_gap_up_frames():
    """Load ind_10m frames for gap-up pre-noon study (includes extension levels)."""
    if hasattr(_load_gap_up_frames, "_cache"):
        return _load_gap_up_frames._cache

    c = _conn()
    try:
        df = pd.read_sql(
            """SELECT timestamp, open, high, low, close,
               prev_close, atr_14,
               atr_upper_trigger, atr_lower_trigger,
               atr_upper_0382, atr_lower_0382,
               atr_upper_0618, atr_lower_0618,
               atr_upper_100, atr_lower_100,
               atr_upper_1236
               FROM ind_10m ORDER BY timestamp""",
            c, parse_dates=["timestamp"],
        )
        df = df.set_index("timestamp").sort_index()
        df = df.between_time("09:30", "15:59")
        df = df.dropna(subset=["prev_close", "atr_14"])
        df["date"] = df.index.date
    finally:
        c.close()

    _load_gap_up_frames._cache = df
    return df


def _run_gap_up_pre_noon_study(opex_only=False, non_opex_friday=False, outcome="hold"):
    """Gap up + >1% gain before noon study.
    outcome:
      'hold'       – for = day closed > prev_close
      'cont_1atr'  – for = touched +1 ATR (100%) level rest of day
      'reversed'   – for = retraced all the way back to prev_close
    """
    df = _load_gap_up_frames()
    results = []

    for date_val, group in df.groupby("date"):
        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr_14 = first["atr_14"]
        if pd.isna(prev_close) or prev_close <= 0 or pd.isna(atr_14) or atr_14 <= 0:
            continue

        d = pd.Timestamp(date_val)
        is_opex = d.weekday() == 4 and 15 <= d.day <= 21
        is_friday = d.dayofweek == 4

        if opex_only and not is_opex:
            continue
        if non_opex_friday and not (is_friday and not is_opex):
            continue

        # Must gap up
        if first["open"] <= prev_close:
            continue

        # Pre-noon bars: hours 9, 10, 11
        pre_noon = group[group.index.hour < 12]
        if len(pre_noon) == 0:
            continue

        max_pre_noon = pre_noon["high"].max()
        if (max_pre_noon - prev_close) / prev_close < 0.01:
            continue

        # First bar where pre-noon crossed +1%
        trigger_bars = pre_noon[pre_noon["high"] >= prev_close * 1.01]
        trigger_time = trigger_bars.index[0]
        remaining = group[group.index > trigger_time]

        remaining_low = remaining["low"].min()
        remaining_high = remaining["high"].max()
        day_close = group.iloc[-1]["close"]

        if outcome == "hold":
            hit = day_close > prev_close
        elif outcome == "cont_1atr":
            upper_100 = first["atr_upper_100"]
            hit = (not pd.isna(upper_100)) and (remaining_high >= upper_100)
        elif outcome == "reversed":
            hit = remaining_low <= prev_close
        else:
            hit = day_close > prev_close

        results.append({
            "date": str(date_val),
            "result": "for" if hit else "against",
            "trigger_time": trigger_time.strftime("%H:%M"),
        })

    return results


# Study catalog definition
STUDY_CATALOG = [
    {
        "id": "bull_gg_baseline",
        "name": "Bull GG Baseline",
        "category": "Golden Gate",
        "desc": "Bull GG triggered → completed (61.8%)?",
        "runner": lambda: _run_gg_study("bull"),
    },
    {
        "id": "bear_gg_baseline",
        "name": "Bear GG Baseline",
        "category": "Golden Gate",
        "desc": "Bear GG triggered → completed (61.8%)?",
        "runner": lambda: _run_gg_study("bear"),
    },
    {
        "id": "bull_bilbo_high_rising",
        "name": "Bull Bilbo (PO High+Rising)",
        "category": "Bilbo",
        "desc": "Bull GG when 1h PO is high & rising — best bull signal",
        "runner": lambda: _run_gg_study("bull", ("high", "rising")),
    },
    {
        "id": "bear_bilbo_low_falling",
        "name": "Bear Bilbo (PO Low+Falling)",
        "category": "Bilbo",
        "desc": "Bear GG when 1h PO is low & falling — best bear signal",
        "runner": lambda: _run_gg_study("bear", ("low", "falling")),
    },
    {
        "id": "bull_counter_mid_falling",
        "name": "Bull Counter (PO Mid+Falling)",
        "category": "Bilbo",
        "desc": "Bull GG when 1h PO is mid & falling — worst bull signal",
        "runner": lambda: _run_gg_study("bull", ("mid", "falling")),
    },
    {
        "id": "bear_counter_mid_rising",
        "name": "Bear Counter (PO Mid+Rising)",
        "category": "Bilbo",
        "desc": "Bear GG when 1h PO is mid & rising — worst bear signal",
        "runner": lambda: _run_gg_study("bear", ("mid", "rising")),
    },
    {
        "id": "bull_mid_rising",
        "name": "Bull GG (PO Mid+Rising)",
        "category": "Bilbo",
        "desc": "Bull GG when 1h PO is mid & rising",
        "runner": lambda: _run_gg_study("bull", ("mid", "rising")),
    },
    {
        "id": "bear_mid_falling",
        "name": "Bear GG (PO Mid+Falling)",
        "category": "Bilbo",
        "desc": "Bear GG when 1h PO is mid & falling",
        "runner": lambda: _run_gg_study("bear", ("mid", "falling")),
    },
    {
        "id": "trigger_box_bull",
        "name": "Trigger Box Bull",
        "category": "Trigger Box",
        "desc": "Open in bull box (above PDC, below call trigger) → GG opens?",
        "runner": lambda: _run_trigger_box_study("bull"),
    },
    {
        "id": "trigger_box_bear",
        "name": "Trigger Box Bear",
        "category": "Trigger Box",
        "desc": "Open in bear box (below PDC, above put trigger) → GG opens?",
        "runner": lambda: _run_trigger_box_study("bear"),
    },
    {
        "id": "opex_4h_po_rollover_ext",
        "name": "4H PO OpEx (Extended)",
        "category": "OpEx",
        "desc": "4H PO peak ≥80 rolls under 80 in OpEx Fri + post 1-5d window, wk/mo ATR ≥0.618 → ≥1% drop in 10d?",
        "runner": lambda: _run_4h_po_opex_study(ext_min=0.618, drop_threshold=1.0, horizon_days=10),
    },
    {
        "id": "opex_4h_po_rollover_deep",
        "name": "4H PO OpEx (Deep Ext)",
        "category": "OpEx",
        "desc": "Same as above but wk/mo ATR ≥1.0 (deep extension) → ≥1% drop in 10d?",
        "runner": lambda: _run_4h_po_opex_study(ext_min=1.0, drop_threshold=1.0, horizon_days=10),
    },
    {
        "id": "opex_4h_po_rollover_ext_15pct",
        "name": "4H PO OpEx (Ext, ≥1.5%)",
        "category": "OpEx",
        "desc": "4H PO OpEx-window rollover under extension → ≥1.5% drop in 10d?",
        "runner": lambda: _run_4h_po_opex_study(ext_min=0.618, drop_threshold=1.5, horizon_days=10),
    },
    {
        "id": "gap_up_pre_noon_hold",
        "name": "Gap Up Pre-Noon: Holds",
        "category": "Gap Up",
        "desc": "Gap up + >1% gain before noon → day closes positive vs prev_close? (88% historical)",
        "runner": lambda: _run_gap_up_pre_noon_study(outcome="hold"),
    },
    {
        "id": "gap_up_pre_noon_cont",
        "name": "Gap Up Pre-Noon: +1ATR Ext",
        "category": "Gap Up",
        "desc": "Gap up + >1% before noon → price touches +1 ATR level rest of day? (52% historical)",
        "runner": lambda: _run_gap_up_pre_noon_study(outcome="cont_1atr"),
    },
    {
        "id": "gap_up_pre_noon_opex_pin",
        "name": "Gap Up Pre-Noon: OpEx Pin",
        "category": "Gap Up",
        "desc": "Same setup on OpEx Fridays only → price retraces to prev_close? (35% historical pin risk)",
        "runner": lambda: _run_gap_up_pre_noon_study(opex_only=True, outcome="reversed"),
    },
]

# Cache for computed study results
_study_cache = {}


@app.get("/api/studies")
async def api_studies():
    """Return study catalog with summary stats.
    Returns only studies that have been computed so far (preloading happens in background)."""
    catalog = []
    for s in STUDY_CATALOG:
        sid = s["id"]
        if sid not in _study_cache:
            continue  # Not yet computed — skip
        dates = _study_cache[sid]
        n = len(dates)
        n_for = sum(1 for d in dates if d["result"] == "for")
        pct = round(n_for / n * 100, 1) if n > 0 else 0
        catalog.append({
            "id": sid,
            "name": s["name"],
            "category": s["category"],
            "desc": s["desc"],
            "n": n,
            "n_for": n_for,
            "n_against": n - n_for,
            "pct": pct,
        })
    loading = len(catalog) < len(STUDY_CATALOG)
    return {"studies": catalog, "loading": loading}


@app.get("/api/study/{study_id}")
async def api_study(study_id: str, result: Optional[str] = None,
                    page: int = 1, per_page: int = 50):
    """Return individual dates for a study, with optional for/against filter.
    Most recent dates first. Paginated."""
    match = [s for s in STUDY_CATALOG if s["id"] == study_id]
    if not match:
        return JSONResponse({"error": "unknown study"}, 400)

    s = match[0]
    if study_id not in _study_cache:
        _study_cache[study_id] = s["runner"]()

    dates = _study_cache[study_id]
    if result in ("for", "against"):
        dates = [d for d in dates if d["result"] == result]

    # Sort most recent first
    dates_sorted = sorted(dates, key=lambda d: d["date"], reverse=True)
    total = len(dates_sorted)
    start = (page - 1) * per_page
    page_dates = dates_sorted[start:start + per_page]

    n_all = len(_study_cache[study_id])
    n_for = sum(1 for d in _study_cache[study_id] if d["result"] == "for")

    return {
        "study_id": study_id,
        "name": s["name"],
        "n": n_all,
        "n_for": n_for,
        "n_against": n_all - n_for,
        "pct": round(n_for / n_all * 100, 1) if n_all > 0 else 0,
        "filter": result,
        "page": page,
        "per_page": per_page,
        "total_filtered": total,
        "dates": page_dates,
    }


# ═══════════════════════════════════════════════════════════════
# Static files & startup
# ═══════════════════════════════════════════════════════════════

os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"),
                        headers={"Cache-Control": "no-cache, must-revalidate"})


import threading

def _preload_studies():
    """Precompute all study results in background on startup."""
    print("Preloading study data...", flush=True)
    for s in STUDY_CATALOG:
        sid = s["id"]
        if sid not in _study_cache:
            _study_cache[sid] = s["runner"]()
            n = len(_study_cache[sid])
            n_for = sum(1 for d in _study_cache[sid] if d["result"] == "for")
            pct = round(n_for / n * 100, 1) if n > 0 else 0
            print(f"  {s['name']}: n={n}, {pct}%", flush=True)
    print("Study preload complete.", flush=True)

@app.on_event("startup")
async def startup_preload():
    threading.Thread(target=_preload_studies, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
