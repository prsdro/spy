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
from zoneinfo import ZoneInfo

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
# Live SPX ATR cascade dashboard helpers
# ═══════════════════════════════════════════════════════════════

_SPX_ET = ZoneInfo("America/New_York")
_SPX_CT = ZoneInfo("America/Chicago")
_SPX_TICKER = "I:SPX"

# Measurement ladder includes hidden outside rails; public ladder matches the
# ATR cascade and open-band studies published in site/data.
_SPX_LEVELS = [
    ("-2.236", -2.236, "Outer Put Extension"),
    ("-2.00", -2.000, "-2 ATR"),
    ("-1.786", -1.786, "Momo Put 78.6"),
    ("-1.618", -1.618, "Momo Put GG Closed"),
    ("-1.50", -1.500, "Momo Put Midrange"),
    ("-1.382", -1.382, "Momo Put GG Open"),
    ("-1.236", -1.236, "Momo Put Trigger"),
    ("-1.00", -1.000, "-1 ATR"),
    ("-0.786", -0.786, "Put 78.6"),
    ("-0.618", -0.618, "Put GG Closed"),
    ("-0.50", -0.500, "Put Midrange"),
    ("-0.382", -0.382, "Put GG Open"),
    ("-0.236", -0.236, "Put Trigger"),
    ("PDC", 0.000, "Previous Close / Central Pivot"),
    ("+0.236", 0.236, "Call Trigger"),
    ("+0.382", 0.382, "Call GG Open"),
    ("+0.50", 0.500, "Call Midrange"),
    ("+0.618", 0.618, "Call GG Closed"),
    ("+0.786", 0.786, "Call 78.6"),
    ("+1.00", 1.000, "+1 ATR"),
    ("+1.236", 1.236, "Momo Call Trigger"),
    ("+1.382", 1.382, "Momo Call GG Open"),
    ("+1.50", 1.500, "Momo Call Midrange"),
    ("+1.618", 1.618, "Momo Call GG Closed"),
    ("+1.786", 1.786, "Momo Call 78.6"),
    ("+2.00", 2.000, "+2 ATR"),
    ("+2.236", 2.236, "Outer Call Extension"),
]
_SPX_HIDDEN_LABELS = {"-2.236", "+2.236"}
_SPX_PUBLIC_LEVELS = [r for r in _SPX_LEVELS if r[0] not in _SPX_HIDDEN_LABELS]
_SPX_PUBLIC_PDC_INDEX = next(i for i, row in enumerate(_SPX_PUBLIC_LEVELS) if row[0] == "PDC")


def _safe_float(value, ndigits=2):
    try:
        if value is None or pd.isna(value):
            return None
        return round(float(value), ndigits)
    except Exception:
        return None


def _load_massive_api_key():
    for env_name in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
        value = os.environ.get(env_name)
        if value:
            return value.strip().strip('"').strip("'")

    candidates = [
        os.path.join(BASE_DIR, ".env"),
        "/root/spx-chart-app/.env",
        "/root/medical/.env",
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
                        value = value.strip().strip('"').strip("'")
                        if value:
                            return value
        except OSError:
            continue
    return None


def _massive_aggs(ticker, multiplier, timespan, start_date, end_date, limit=50000):
    api_key = _load_massive_api_key()
    if not api_key:
        raise RuntimeError("Massive API key not configured on server")
    url = f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start_date}/{end_date}"
    resp = _requests.get(
        url,
        params={"adjusted": "true", "sort": "asc", "limit": limit, "apiKey": api_key},
        timeout=15,
    )
    if resp.status_code != 200:
        try:
            payload = resp.json()
        except Exception:
            payload = {"error": resp.text[:240]}
        raise RuntimeError(f"Massive returned HTTP {resp.status_code}: {payload.get('error') or payload.get('message') or 'unknown error'}")
    data = resp.json()
    return data.get("results") or []


def _massive_daily_df(days_back=220, end_date=None):
    end = end_date or _dt.now(_SPX_ET).date()
    if isinstance(end, str):
        end = _dt.fromisoformat(end).date()
    start = end - _td(days=days_back)
    rows = _massive_aggs(_SPX_TICKER, 1, "day", start.isoformat(), end.isoformat(), limit=5000)
    records = []
    for row in rows:
        ts = _dt.fromtimestamp(row["t"] / 1000, tz=_tz.utc).astimezone(_SPX_ET)
        records.append({
            "timestamp": pd.Timestamp(ts.date()),
            "open": float(row.get("o")),
            "high": float(row.get("h")),
            "low": float(row.get("l")),
            "close": float(row.get("c")),
            "volume": float(row.get("v", 0) or 0),
        })
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()


def _massive_intraday_df(days_back=21, end_date=None, start_date=None):
    end = end_date or _dt.now(_SPX_ET).date()
    if isinstance(end, str):
        end = _dt.fromisoformat(end).date()
    start = start_date or (end - _td(days=days_back))
    if isinstance(start, str):
        start = _dt.fromisoformat(start).date()
    rows = _massive_aggs(_SPX_TICKER, 1, "minute", start.isoformat(), end.isoformat(), limit=50000)
    records = []
    for row in rows:
        ts = _dt.fromtimestamp(row["t"] / 1000, tz=_tz.utc).astimezone(_SPX_ET)
        records.append({
            "timestamp": pd.Timestamp(ts),
            "open": float(row.get("o")),
            "high": float(row.get("h")),
            "low": float(row.get("l")),
            "close": float(row.get("c")),
            "volume": float(row.get("v", 0) or 0),
        })
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()


def _atr_series(df, period=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _ema(series, period):
    return series.ewm(span=period, adjust=False, min_periods=1).mean()


def _rma(series, period):
    return series.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()


def _aggregate_rth(df, rule):
    if df.empty:
        return pd.DataFrame()
    chunks = []
    for _, grp in df.groupby(df.index.date):
        agg = grp.resample(rule, origin="start_day", offset="9h30min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open", "high", "low", "close"])
        agg = agg.between_time("09:30", "15:59")
        if not agg.empty:
            chunks.append(agg)
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks).sort_index()


def _phase_zone(value):
    if value is None:
        return "na"
    if value > 100:
        return "extended_up"
    if value > 61.8:
        return "distribution"
    if value > 23.6:
        return "neutral_up"
    if value > -23.6:
        return "neutral"
    if value > -61.8:
        return "neutral_down"
    if value > -100:
        return "accumulation"
    return "extended_down"


def _indicator_snapshot(df):
    if df.empty:
        return None
    work = df.copy()
    price = work["close"]
    work["ema_8"] = _ema(price, 8)
    work["ema_13"] = _ema(price, 13)
    work["ema_21"] = _ema(price, 21)
    work["ema_48"] = _ema(price, 48)
    work["ema_200"] = _ema(price, 200)
    atr14 = _atr_series(work, 14)
    pivot = work["ema_21"]
    raw_signal = ((price - pivot) / (3.0 * atr14.replace(0, np.nan))) * 100
    work["phase_oscillator"] = _ema(raw_signal, 3)
    std21 = price.rolling(window=21, min_periods=1).std()
    bband_offset = 2.0 * std21
    above_pivot = price >= pivot
    compression_val = np.where(
        above_pivot,
        pivot + bband_offset - (pivot + 2.0 * atr14),
        (pivot - 2.0 * atr14) - (pivot - bband_offset),
    )
    work["po_compression"] = pd.Series(compression_val, index=work.index).le(0).astype(int)
    last = work.iloc[-1]
    po_value = _safe_float(last.get("phase_oscillator"), 1)
    ts = work.index[-1]
    return {
        "timestamp_et": ts.isoformat(),
        "phase_oscillator": po_value,
        "phase_zone": _phase_zone(po_value),
        "po_compression": bool(int(last.get("po_compression", 0)) == 1),
        "pivot_ribbon": {
            "ema_8": _safe_float(last.get("ema_8")),
            "ema_13": _safe_float(last.get("ema_13")),
            "ema_21": _safe_float(last.get("ema_21")),
            "ema_48": _safe_float(last.get("ema_48")),
            "ema_200": _safe_float(last.get("ema_200")),
            "fast_cloud": "bullish" if last.get("ema_8") >= last.get("ema_21") else "bearish",
            "slow_cloud": "bullish" if last.get("ema_13") >= last.get("ema_48") else "bearish",
            "longterm": "bullish" if last.get("ema_21") >= last.get("ema_200") else "bearish",
        },
    }


def _build_spx_levels(prev_close, atr_value):
    levels = []
    for label, multiple, name in _SPX_LEVELS:
        value = prev_close + multiple * atr_value
        levels.append({
            "label": label,
            "atr": multiple,
            "name": name,
            "value": _safe_float(value),
            "public": label not in _SPX_HIDDEN_LABELS,
        })
    return levels


def _find_public_band(atr_multiple):
    if atr_multiple is None:
        return None
    public = list(_SPX_PUBLIC_LEVELS)
    for idx in range(len(public) - 1):
        lo_label, lo_atr, lo_name = public[idx]
        hi_label, hi_atr, hi_name = public[idx + 1]
        if idx == len(public) - 2:
            in_band = lo_atr <= atr_multiple <= hi_atr
        else:
            in_band = lo_atr <= atr_multiple < hi_atr
        if in_band:
            side = "up" if idx >= _SPX_PUBLIC_PDC_INDEX else "down"
            return {
                "index": idx,
                "lower_label": lo_label,
                "upper_label": hi_label,
                "lower_atr": lo_atr,
                "upper_atr": hi_atr,
                "lower_name": lo_name,
                "upper_name": hi_name,
                "side": side,
            }
    return None


def _level_dict(levels):
    return {row["label"]: row["value"] for row in levels if row.get("public")}


def _session_level_hits(session_3m, levels, session_open):
    if session_3m.empty:
        return []
    level_values = _level_dict(levels)
    events = []
    for label, multiple, name in _SPX_PUBLIC_LEVELS:
        if label == "PDC":
            continue
        price = level_values.get(label)
        if price is None:
            continue
        direction = "up" if multiple > 0 else "down"
        if direction == "up" and session_open >= price:
            continue
        if direction == "down" and session_open <= price:
            continue
        if direction == "up":
            mask = session_3m["high"] >= price
        else:
            mask = session_3m["low"] <= price
        if not bool(mask.any()):
            continue
        ts = session_3m.index[mask.to_numpy().argmax()]
        minute = (ts.hour * 60 + ts.minute) - (9 * 60 + 30)
        hour_bucket = "09:30-10:00" if ts.hour == 9 else f"{ts.hour:02d}:00-{ts.hour + 1:02d}:00"
        events.append({
            "label": label,
            "atr": multiple,
            "name": name,
            "value": _safe_float(price),
            "direction": direction,
            "timestamp_et": ts.isoformat(),
            "time_et": ts.strftime("%H:%M"),
            "minutes_from_open": int(minute),
            "hour_bucket": hour_bucket,
        })
    events.sort(key=lambda row: (row["timestamp_et"], abs(row["atr"])))
    return events


def _open_band_walk(session_3m, levels, open_band):
    if session_3m.empty or open_band is None:
        return {"path_prefix": [], "completed_events": [], "active_band": open_band, "terminal": False}

    rung_prices = [levels[row[0]] for row in _SPX_PUBLIC_LEVELS]
    public = list(_SPX_PUBLIC_LEVELS)
    pdc_idx = _SPX_PUBLIC_PDC_INDEX
    open_idx = int(open_band["index"])
    bars = session_3m.reset_index()
    time_col = bars.columns[0]
    session_open = float(bars.iloc[0]["open"])
    lower_idx = open_idx
    upper_idx = open_idx + 1
    is_first_band = True
    start_bar = 0
    completed = []

    def band_payload(idx):
        if idx is None or idx < 0 or idx >= len(public) - 1:
            return None
        side = "up" if idx >= pdc_idx else "down"
        lo = public[idx]
        hi = public[idx + 1]
        return {
            "band_index": int(idx),
            "lower_label": lo[0],
            "upper_label": hi[0],
            "lower_atr": lo[1],
            "upper_atr": hi[1],
            "side": side,
        }

    terminal = False
    while start_bar < len(bars):
        hit = None
        hit_bar = None
        lower_price = rung_prices[lower_idx]
        upper_price = rung_prices[upper_idx]
        if is_first_band and abs(session_open - lower_price) < 1e-9:
            lower_hit_from = 1
        else:
            lower_hit_from = 0
        for i in range(start_bar, len(bars)):
            row = bars.iloc[i]
            hi_hit = float(row["high"]) >= upper_price
            lo_hit = (i >= lower_hit_from) and float(row["low"]) <= lower_price
            if hi_hit and lo_hit:
                hit = "amb"
                hit_bar = i
                break
            if hi_hit:
                hit = "upper"
                hit_bar = i
                break
            if lo_hit:
                hit = "lower"
                hit_bar = i
                break
        band_idx = lower_idx
        side = "up" if band_idx >= pdc_idx else "down"
        if hit is None:
            final_bar = bars.iloc[-1]
            final_ts = final_bar[time_col]
            full_session = final_ts.strftime("%H:%M") >= "15:57"
            if full_session:
                completed.append({**band_payload(band_idx), "outcome": "none", "minutes_from_open": 390})
                terminal = True
                return {"path_prefix": completed, "completed_events": completed, "active_band": None, "terminal": terminal}
            active = band_payload(band_idx)
            prefix = completed + [{**active, "outcome": None}]
            return {"path_prefix": prefix, "completed_events": completed, "active_band": active, "terminal": terminal}

        ts = bars.iloc[hit_bar][time_col]
        minute = int((ts.hour * 60 + ts.minute) - (9 * 60 + 30))
        if hit == "amb":
            outcome = "amb"
        else:
            continued = (side == "up" and hit == "upper") or (side == "down" and hit == "lower")
            outcome = "cont" if continued else "retr"
        event = {**band_payload(band_idx), "outcome": outcome, "minutes_from_open": minute, "time_et": ts.strftime("%H:%M"), "timestamp_et": ts.isoformat()}
        completed.append(event)
        if outcome == "amb":
            terminal = True
            return {"path_prefix": completed, "completed_events": completed, "active_band": None, "terminal": terminal}
        if hit == "upper":
            lower_idx += 1
            upper_idx += 1
        else:
            lower_idx -= 1
            upper_idx -= 1
        if lower_idx < 0 or upper_idx >= len(public):
            terminal = True
            return {"path_prefix": completed, "completed_events": completed, "active_band": None, "terminal": terminal}
        start_bar = hit_bar + 1
        is_first_band = False

    active = band_payload(lower_idx)
    if active:
        final_ts = bars.iloc[-1][time_col]
        full_session = final_ts.strftime("%H:%M") >= "15:57"
        if full_session:
            completed.append({**active, "outcome": "none", "minutes_from_open": 390})
            return {"path_prefix": completed, "completed_events": completed, "active_band": None, "terminal": True}
    prefix = completed + ([{**active, "outcome": None}] if active else [])
    return {"path_prefix": prefix, "completed_events": completed, "active_band": active, "terminal": terminal}


def _parse_spx_asof(date_value=None, time_value=None, tz_value="CT"):
    """Parse optional historical as-of inputs. Default user-facing time zone is Central."""
    if not date_value and not time_value:
        return None
    if not date_value:
        raise ValueError("Historical mode requires a date in YYYY-MM-DD format")

    raw_time = (time_value or "15:00").strip()
    if len(raw_time) == 4 and raw_time[1] == ":":
        raw_time = "0" + raw_time
    if len(raw_time) == 5:
        raw_time = raw_time + ":00"
    try:
        naive = _dt.fromisoformat(f"{str(date_value).strip()}T{raw_time}")
    except ValueError:
        raise ValueError("Use date YYYY-MM-DD and time HH:MM")

    tz_key = (tz_value or "CT").strip().upper()
    if tz_key in ("ET", "EST", "EDT", "EASTERN", "AMERICA/NEW_YORK"):
        zone = _SPX_ET
        label = "ET"
    else:
        zone = _SPX_CT
        label = "CT"
    local_dt = naive.replace(tzinfo=zone)
    et_dt = local_dt.astimezone(_SPX_ET)
    ct_dt = et_dt.astimezone(_SPX_CT)
    return {
        "mode": "historical",
        "input_date": str(date_value).strip(),
        "input_time": raw_time[:5],
        "input_timezone": label,
        "as_of_time_et": et_dt,
        "as_of_time_ct": ct_dt,
    }


@app.get("/api/spx-live-cascade")
def api_spx_live_cascade(date: Optional[str] = None, time: Optional[str] = None, tz: Optional[str] = "CT"):
    try:
        asof = _parse_spx_asof(date, time, tz)
        historical_mode = asof is not None
        end_date = asof["as_of_time_et"].date() if historical_mode else None

        daily = _massive_daily_df(end_date=end_date)
        intraday_raw = _massive_intraday_df(end_date=end_date)
        if daily.empty:
            return JSONResponse({"ok": False, "error": "No SPX daily bars returned from Massive"}, status_code=502)
        if intraday_raw.empty:
            return JSONResponse({"ok": False, "error": "No SPX intraday bars returned from Massive"}, status_code=502)

        if historical_mode:
            asof_ts = pd.Timestamp(asof["as_of_time_et"])
            session_date = asof_ts.date()
            intraday_asof = intraday_raw[intraday_raw.index <= asof_ts].copy()
            rth_intraday = intraday_asof.between_time("09:30", "15:59")
            session_all = intraday_asof[intraday_asof.index.date == session_date].copy()
            session_1m = rth_intraday[rth_intraday.index.date == session_date].copy()
            full_session_all = intraday_raw[intraday_raw.index.date == session_date].copy()
            full_session_1m = full_session_all.between_time("09:30", "15:59")
            if session_1m.empty:
                return JSONResponse({
                    "ok": False,
                    "error": f"No SPX RTH bars found for {session_date.isoformat()} through {asof['as_of_time_ct'].strftime('%H:%M %Z')}. Use a market day/time after 08:30 CT."
                }, status_code=404)
        else:
            rth_intraday = intraday_raw.between_time("09:30", "15:59")
            if rth_intraday.empty:
                return JSONResponse({"ok": False, "error": "No SPX RTH bars returned from Massive"}, status_code=502)
            session_date = max(rth_intraday.index.date)
            session_all = intraday_raw[intraday_raw.index.date == session_date].copy()
            session_1m = rth_intraday[rth_intraday.index.date == session_date].copy()
            full_session_all = session_all
            full_session_1m = session_1m
            intraday_asof = intraday_raw
            asof_ts = session_all.index[-1] if not session_all.empty else None

        session_3m = _aggregate_rth(session_1m, "3min")
        warm_3m = _aggregate_rth(intraday_asof, "3min")
        warm_10m = _aggregate_rth(intraday_asof, "10min")
        if session_all.empty or session_1m.empty or session_3m.empty:
            return JSONResponse({"ok": False, "error": "SPX session bars were empty after RTH filter"}, status_code=502)

        prior_daily = daily[daily.index.date < session_date].copy()
        if len(prior_daily) < 20:
            return JSONResponse({"ok": False, "error": "Not enough daily history to compute ATR"}, status_code=502)
        prior_atr = _atr_series(prior_daily, 14).dropna()
        if prior_atr.empty:
            return JSONResponse({"ok": False, "error": "ATR calculation returned no values"}, status_code=502)
        prev_close = float(prior_daily["close"].iloc[-1])
        atr_value = float(prior_atr.iloc[-1])
        atr_date = prior_daily.index[-1].strftime("%Y-%m-%d")
        levels = _build_spx_levels(prev_close, atr_value)

        latest = session_all.iloc[-1]
        latest_ts = session_all.index[-1]
        latest_price = float(latest["close"])
        latest_atr_multiple = (latest_price - prev_close) / atr_value if atr_value else None
        session_open = float(session_1m.iloc[0]["open"])
        open_atr_multiple = (session_open - prev_close) / atr_value if atr_value else None
        session_high = float(session_1m["high"].max())
        session_low = float(session_1m["low"].min())
        open_band = _find_public_band(open_atr_multiple)
        current_band = _find_public_band(latest_atr_multiple)
        hits = _session_level_hits(session_3m, levels, session_open)
        public_levels = _level_dict(levels)
        walk = _open_band_walk(session_3m, public_levels, open_band)

        historical_actual = None
        if historical_mode and not full_session_1m.empty:
            full_session_3m = _aggregate_rth(full_session_1m, "3min")
            if not full_session_3m.empty:
                full_hits = _session_level_hits(full_session_3m, levels, session_open)
                future_hits = [h for h in full_hits if pd.Timestamp(h["timestamp_et"]) > latest_ts]
                full_walk = _open_band_walk(full_session_3m, public_levels, open_band)
                final_bar = full_session_all.iloc[-1] if not full_session_all.empty else full_session_1m.iloc[-1]
                final_ts = full_session_all.index[-1] if not full_session_all.empty else full_session_1m.index[-1]
                final_ct = final_ts.tz_convert(_SPX_CT)
                full_high = float(full_session_1m["high"].max())
                full_low = float(full_session_1m["low"].min())
                historical_actual = {
                    "complete_session_available": final_ts.strftime("%H:%M") >= "15:57",
                    "final_time_et": final_ts.strftime("%Y-%m-%d %H:%M %Z"),
                    "final_time_ct": final_ct.strftime("%Y-%m-%d %H:%M %Z"),
                    "final_price": _safe_float(float(final_bar["close"])),
                    "full_day_high": _safe_float(full_high),
                    "full_day_low": _safe_float(full_low),
                    "full_day_range_atr": _safe_float((full_high - full_low) / atr_value, 3),
                    "next_first_hit_after_asof": future_hits[0] if future_hits else None,
                    "full_level_hits": full_hits,
                    "full_open_band_walk": full_walk,
                }

        ct_ts = latest_ts.tz_convert(_SPX_CT)
        request_payload = {
            "mode": "historical" if historical_mode else "live",
            "input_date": asof["input_date"] if historical_mode else None,
            "input_time": asof["input_time"] if historical_mode else None,
            "input_timezone": asof["input_timezone"] if historical_mode else None,
            "as_of_time_et": asof["as_of_time_et"].isoformat() if historical_mode else None,
            "as_of_time_ct": asof["as_of_time_ct"].isoformat() if historical_mode else None,
        }
        response = {
            "ok": True,
            "source": "Massive / Polygon",
            "ticker": _SPX_TICKER,
            "generated_at_et": _dt.now(_SPX_ET).isoformat(),
            "request": request_payload,
            "session": {
                "date": session_date.isoformat(),
                "latest_time_et": latest_ts.strftime("%Y-%m-%d %H:%M %Z"),
                "latest_time_ct": ct_ts.strftime("%Y-%m-%d %H:%M %Z"),
                "latest_price": _safe_float(latest_price),
                "open": _safe_float(session_open),
                "high": _safe_float(session_high),
                "low": _safe_float(session_low),
                "range_atr": _safe_float((session_high - session_low) / atr_value, 3),
                "bar_count_1m": int(len(session_1m)),
                "bar_count_3m": int(len(session_3m)),
                "latest_atr_multiple": _safe_float(latest_atr_multiple, 4),
                "open_atr_multiple": _safe_float(open_atr_multiple, 4),
                "open_band": open_band,
                "current_band": current_band,
            },
            "atr_reference": {
                "date": atr_date,
                "previous_close": _safe_float(prev_close),
                "atr_14": _safe_float(atr_value),
            },
            "levels": levels,
            "level_hits": hits,
            "latest_level_hit": hits[-1] if hits else None,
            "open_band_walk": walk,
            "historical_actual": historical_actual,
            "indicators": {
                "3m": _indicator_snapshot(warm_3m),
                "10m": _indicator_snapshot(warm_10m),
            },
        }
        return JSONResponse(response)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


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
