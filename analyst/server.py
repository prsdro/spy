"""
Trading Analyst API Server

Fetches live SPY data from MASSIVE, computes indicators on-the-fly,
and uses Claude to generate concise trading analysis.
"""

import os
import json
import time
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone, date
from typing import Optional

import requests
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import uvicorn

# ── Config ──
from dotenv import load_dotenv
load_dotenv()

API_SECRET = os.environ["ANALYST_API_SECRET"]
MASSIVE_KEY = os.environ["MASSIVE_API_KEY"]
MASSIVE_BASE = "https://api.massive.com/v2/aggs/ticker/SPY/range/1/minute"
DB_PATH = os.environ.get("SPY_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "spy.db"))
KNOWLEDGE_PATH = os.environ.get("KNOWLEDGE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "KNOWLEDGE.md"))
STUDIES_PATH = os.environ.get("STUDIES_PATH", os.path.join(os.path.dirname(__file__), "studies_reference.md"))

OPENAI_KEY = os.environ["OPENAI_API_KEY"]

app = FastAPI(title="Milkman Trading Analyst")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Indicator Functions (lightweight, no pandas dependency on full DB) ──

def rma(series, period):
    """Wilder's RMA matching TradingView's ta.rma()."""
    result = np.empty_like(series)
    result[0] = series[0]
    alpha = 1.0 / period
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result

def ema(series, period):
    """EMA matching TradingView's ta.ema()."""
    result = np.empty_like(series)
    result[0] = series[0]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result

def compute_atr(highs, lows, closes, period=14):
    """Compute ATR using Wilder's RMA."""
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )
    tr = np.concatenate([[highs[0] - lows[0]], tr])
    return rma(tr, period)

def utc_ms_to_et(ts_ms):
    """Convert MASSIVE timestamp to ET datetime string."""
    utc_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    year = utc_dt.year
    mar_dst = datetime(year, 3, 8 + (6 - datetime(year, 3, 1).weekday()) % 7, 2, tzinfo=timezone.utc)
    nov_dst = datetime(year, 11, 1 + (6 - datetime(year, 11, 1).weekday()) % 7, 2, tzinfo=timezone.utc)
    offset = timedelta(hours=-4) if mar_dst <= utc_dt < nov_dst else timedelta(hours=-5)
    return utc_dt + offset


# ── Data Fetching ──

def fetch_today_yahoo():
    """Fetch today's 1-minute SPY bars from Yahoo Finance (free, same-day)."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
    resp = requests.get(url, params={"interval": "1m", "range": "1d"},
                        headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        return []

    data = resp.json()
    result = data.get("chart", {}).get("result", [{}])[0]
    timestamps = result.get("timestamp", [])
    quotes = result.get("indicators", {}).get("quote", [{}])[0]

    bars = []
    for i, ts in enumerate(timestamps):
        o = quotes.get("open", [])[i]
        h = quotes.get("high", [])[i]
        l = quotes.get("low", [])[i]
        c = quotes.get("close", [])[i]
        v = quotes.get("volume", [])[i]

        if o is None or c is None:
            continue

        # Yahoo timestamps are UTC
        utc_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        year = utc_dt.year
        mar_dst = datetime(year, 3, 8 + (6 - datetime(year, 3, 1).weekday()) % 7, 2, tzinfo=timezone.utc)
        nov_dst = datetime(year, 11, 1 + (6 - datetime(year, 11, 1).weekday()) % 7, 2, tzinfo=timezone.utc)
        offset = timedelta(hours=-4) if mar_dst <= utc_dt < nov_dst else timedelta(hours=-5)
        et = utc_dt + offset

        bars.append({
            "timestamp": et.strftime("%Y-%m-%d %H:%M:%S"),
            "dt": et,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": int(v or 0),
        })

    return bars


def fetch_recent_bars(days_back=5):
    """Fetch recent bars: MASSIVE for historical + Yahoo for today."""
    # Historical from MASSIVE (through yesterday)
    end = date.today()  # MASSIVE has up to yesterday
    start = end - timedelta(days=days_back + 4)

    url = f"{MASSIVE_BASE}/{start.isoformat()}/{end.isoformat()}"
    resp = requests.get(url, params={
        "apiKey": MASSIVE_KEY,
        "limit": 50000,
        "sort": "asc",
        "adjusted": "true",
    })

    bars = []
    if resp.status_code == 200:
        data = resp.json()
        results = data.get("results", [])
        for b in results:
            et = utc_ms_to_et(b["t"])
            bars.append({
                "timestamp": et.strftime("%Y-%m-%d %H:%M:%S"),
                "dt": et,
                "open": b["o"],
                "high": b["h"],
                "low": b["l"],
                "close": b["c"],
                "volume": int(b["v"]),
            })

    # Today's bars from Yahoo Finance (free, same-day)
    today_bars = fetch_today_yahoo()
    if today_bars:
        # Deduplicate: only add Yahoo bars that are newer than MASSIVE data
        last_massive_ts = bars[-1]["timestamp"] if bars else ""
        new_bars = [b for b in today_bars if b["timestamp"] > last_massive_ts]
        bars.extend(new_bars)

    return bars


def get_daily_bars_from_db(n_days=30):
    """Get recent daily bars from our database for context."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume, ema_21, ema_48, ema_200, atr_14, prev_close, "
        "atr_upper_trigger, atr_lower_trigger, atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, atr_upper_100, atr_lower_100, "
        "phase_oscillator, phase_zone, compression, atr_trend "
        f"FROM ind_1d ORDER BY timestamp DESC LIMIT {n_days}"
    ).fetchall()
    conn.close()
    return rows


# ── Live Indicator Computation ──

def compute_live_indicators(bars):
    """Compute indicators from recent 1-minute bars."""
    if len(bars) < 200:
        return None

    closes = np.array([b["close"] for b in bars])
    highs = np.array([b["high"] for b in bars])
    lows = np.array([b["low"] for b in bars])
    opens = np.array([b["open"] for b in bars])

    # EMAs on 10-minute resampled data
    # First, resample to 10m
    bars_10m = []
    chunk = []
    for b in bars:
        chunk.append(b)
        if len(chunk) == 10:
            bars_10m.append({
                "open": chunk[0]["open"],
                "high": max(c["high"] for c in chunk),
                "low": min(c["low"] for c in chunk),
                "close": chunk[-1]["close"],
                "timestamp": chunk[-1]["timestamp"],
            })
            chunk = []
    if chunk:
        bars_10m.append({
            "open": chunk[0]["open"],
            "high": max(c["high"] for c in chunk),
            "low": min(c["low"] for c in chunk),
            "close": chunk[-1]["close"],
            "timestamp": chunk[-1]["timestamp"],
        })

    c10 = np.array([b["close"] for b in bars_10m])

    # 10m EMAs
    ema_8 = ema(c10, 8)
    ema_13 = ema(c10, 13)
    ema_21 = ema(c10, 21)
    ema_48 = ema(c10, 48)
    ema_200 = ema(c10, 200) if len(c10) >= 200 else None

    # Daily data for ATR levels
    # Get today's and yesterday's data from the bars
    today_str = bars[-1]["dt"].strftime("%Y-%m-%d")
    today_bars = [b for b in bars if b["dt"].strftime("%Y-%m-%d") == today_str]
    rth_today = [b for b in today_bars
                 if (b["dt"].hour == 9 and b["dt"].minute >= 30) or (10 <= b["dt"].hour < 16)]

    # ── Derive prev_close and daily ATR from fetched bars (authoritative) ──
    # Group RTH bars (9:30-15:59) by date to build daily OHLC
    from collections import OrderedDict
    daily_map = OrderedDict()
    for b in bars:
        h, m = b["dt"].hour, b["dt"].minute
        is_rth = (h == 9 and m >= 30) or (10 <= h < 16)
        if not is_rth:
            continue
        d = b["dt"].strftime("%Y-%m-%d")
        if d not in daily_map:
            daily_map[d] = {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
        else:
            daily_map[d]["high"] = max(daily_map[d]["high"], b["high"])
            daily_map[d]["low"] = min(daily_map[d]["low"], b["low"])
            daily_map[d]["close"] = b["close"]

    day_keys = list(daily_map.keys())
    # prev_close = RTH close of the day before today
    if len(day_keys) >= 2 and day_keys[-1] == today_str:
        prev_close = daily_map[day_keys[-2]]["close"]
    elif len(day_keys) >= 1 and day_keys[-1] != today_str:
        prev_close = daily_map[day_keys[-1]]["close"]
    else:
        prev_close = bars[0]["close"]

    # Compute daily ATR from fetched daily bars (Wilder's RMA, 14-period)
    if len(day_keys) >= 3:
        d_highs = np.array([daily_map[k]["high"] for k in day_keys])
        d_lows = np.array([daily_map[k]["low"] for k in day_keys])
        d_closes = np.array([daily_map[k]["close"] for k in day_keys])
        daily_atr_arr = compute_atr(d_highs, d_lows, d_closes, min(14, len(day_keys)))
        # Use ATR as of yesterday (second-to-last day)
        daily_atr = float(daily_atr_arr[-2]) if day_keys[-1] == today_str else float(daily_atr_arr[-1])
    else:
        daily_atr = None

    # Get daily context from DB (for longer-term EMAs and phase oscillator only)
    daily_rows = get_daily_bars_from_db(5)

    if daily_rows:
        yesterday_db = daily_rows[0]
        daily_ema21 = yesterday_db[6]
        daily_ema48 = yesterday_db[7]
        daily_ema200 = yesterday_db[8]
        prev_phase_osc = yesterday_db[19]
        prev_phase_zone = yesterday_db[20]
        prev_compression = yesterday_db[21]
        prev_atr_trend = yesterday_db[22]
    else:
        daily_ema21 = daily_ema48 = daily_ema200 = None
        prev_phase_osc = prev_phase_zone = prev_compression = prev_atr_trend = None

    # Compute ATR levels from daily
    atr_levels = {}
    if daily_atr and prev_close:
        for name, fib in [("trigger", 0.236), ("0382", 0.382), ("050", 0.5),
                           ("0618", 0.618), ("0786", 0.786), ("100", 1.0)]:
            atr_levels[f"upper_{name}"] = round(prev_close + fib * daily_atr, 2)
            atr_levels[f"lower_{name}"] = round(prev_close - fib * daily_atr, 2)

    # Current price info
    current = bars[-1]
    today_open = rth_today[0]["open"] if rth_today else today_bars[0]["open"]
    today_high = max(b["high"] for b in (rth_today or today_bars))
    today_low = min(b["low"] for b in (rth_today or today_bars))
    today_range = today_high - today_low
    range_pct_atr = round(today_range / daily_atr * 100, 1) if daily_atr else None

    # Compute exact breach times for each level today (RTH bars only)
    level_breaches = {}
    rth_bars = rth_today if rth_today else today_bars
    if atr_levels and rth_bars:
        check_levels = [
            ("call_trigger", "upper_trigger", "high", ">="),
            ("put_trigger", "lower_trigger", "low", "<="),
            ("bull_gg_entry", "upper_0382", "high", ">="),
            ("bear_gg_entry", "lower_0382", "low", "<="),
            ("bull_gg_complete", "upper_0618", "high", ">="),
            ("bear_gg_complete", "lower_0618", "low", "<="),
            ("bull_full_atr", "upper_100", "high", ">="),
            ("bear_full_atr", "lower_100", "low", "<="),
        ]
        for name, level_key, bar_field, op in check_levels:
            level_val = atr_levels.get(level_key)
            if level_val is None:
                continue
            for b in rth_bars:
                if op == ">=" and b[bar_field] >= level_val:
                    level_breaches[name] = b["timestamp"]
                    break
                elif op == "<=" and b[bar_field] <= level_val:
                    level_breaches[name] = b["timestamp"]
                    break

    # Determine active setups
    active_setups = []
    if "bull_gg_entry" in level_breaches:
        if "bull_gg_complete" in level_breaches:
            active_setups.append(f"Bullish GG OPENED at {level_breaches['bull_gg_entry'][11:16]} and COMPLETED at {level_breaches['bull_gg_complete'][11:16]}")
        else:
            active_setups.append(f"Bullish GG OPENED at {level_breaches['bull_gg_entry'][11:16]} — NOT YET COMPLETED (target: {atr_levels['upper_0618']})")
    elif "call_trigger" in level_breaches:
        active_setups.append(f"Call trigger hit at {level_breaches['call_trigger'][11:16]} — GG entry ({atr_levels['upper_0382']}) NOT YET reached")

    if "bear_gg_entry" in level_breaches:
        if "bear_gg_complete" in level_breaches:
            active_setups.append(f"Bearish GG OPENED at {level_breaches['bear_gg_entry'][11:16]} and COMPLETED at {level_breaches['bear_gg_complete'][11:16]}")
        else:
            active_setups.append(f"Bearish GG OPENED at {level_breaches['bear_gg_entry'][11:16]} — NOT YET COMPLETED (target: {atr_levels['lower_0618']})")
    elif "put_trigger" in level_breaches:
        active_setups.append(f"Put trigger hit at {level_breaches['put_trigger'][11:16]} — GG entry ({atr_levels['lower_0382']}) NOT YET reached")

    # Trigger box status
    if prev_close and atr_levels:
        if today_open < prev_close and today_open > atr_levels.get("lower_trigger", -999):
            active_setups.append("Opened in BEARISH trigger box (below PDC, above put trigger)")
        elif today_open > prev_close and today_open < atr_levels.get("upper_trigger", 999):
            active_setups.append("Opened in BULLISH trigger box (above PDC, below call trigger)")

    # Phase Oscillator on 10m
    if len(c10) >= 21:
        pivot = ema(c10, 21)
        h10 = np.array([b["high"] for b in bars_10m])
        l10 = np.array([b["low"] for b in bars_10m])
        atr_10m = compute_atr(h10, l10, c10, 14)
        raw_po = ((c10 - pivot) / (3.0 * atr_10m)) * 100
        po = ema(raw_po, 3)
        current_po = round(float(po[-1]), 1)
    else:
        current_po = None

    # Determine where price is relative to ATR levels
    price = current["close"]
    level_position = "unknown"
    if atr_levels:
        if price > atr_levels.get("upper_100", 999999):
            level_position = "above +100% ATR"
        elif price > atr_levels.get("upper_0618", 999999):
            level_position = "between +61.8% and +100%"
        elif price > atr_levels.get("upper_0382", 999999):
            level_position = "in the bullish Golden Gate (+38.2% to +61.8%)"
        elif price > atr_levels.get("upper_trigger", 999999):
            level_position = "between call trigger and +38.2%"
        elif price > prev_close:
            level_position = "in the bullish trigger box (above PDC, below call trigger)"
        elif price > atr_levels.get("lower_trigger", -999999):
            level_position = "in the bearish trigger box (below PDC, above put trigger)"
        elif price > atr_levels.get("lower_0382", -999999):
            level_position = "between put trigger and -38.2%"
        elif price > atr_levels.get("lower_0618", -999999):
            level_position = "in the bearish Golden Gate (-38.2% to -61.8%)"
        elif price > atr_levels.get("lower_100", -999999):
            level_position = "between -61.8% and -100%"
        else:
            level_position = "below -100% ATR"

    # Ribbon state
    if len(c10) >= 48:
        fast_cloud = "bullish" if ema_8[-1] >= ema_21[-1] else "bearish"
        slow_cloud = "bullish" if ema_13[-1] >= ema_48[-1] else "bearish"
    else:
        fast_cloud = slow_cloud = "unknown"

    return {
        "timestamp": current["timestamp"],
        "latest_bar": bars[-1]["timestamp"],
        "total_bars_fetched": len(bars),
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": price,
        "today_open": today_open,
        "today_high": today_high,
        "today_low": today_low,
        "today_range": round(today_range, 2),
        "range_pct_atr": range_pct_atr,
        "prev_close": prev_close,
        "daily_atr": round(daily_atr, 2) if daily_atr else None,
        "atr_levels": atr_levels,
        "level_position": level_position,
        "gap_pct": round((today_open - prev_close) / prev_close * 100, 3) if prev_close else None,
        "ema_8_10m": round(float(ema_8[-1]), 2),
        "ema_21_10m": round(float(ema_21[-1]), 2),
        "ema_48_10m": round(float(ema_48[-1]), 2),
        "fast_cloud": fast_cloud,
        "slow_cloud": slow_cloud,
        "daily_ema21": round(daily_ema21, 2) if daily_ema21 else None,
        "daily_ema48": round(daily_ema48, 2) if daily_ema48 else None,
        "daily_ema200": round(daily_ema200, 2) if daily_ema200 else None,
        "phase_oscillator_10m": current_po,
        "prev_daily_po": round(prev_phase_osc, 1) if prev_phase_osc else None,
        "prev_daily_zone": prev_phase_zone,
        "prev_compression": prev_compression,
        "prev_atr_trend": prev_atr_trend,
        "level_breaches": level_breaches,
        "active_setups": active_setups,
    }


# ── Knowledge Base ──

def load_knowledge():
    """Load the study knowledge base."""
    try:
        with open(STUDIES_PATH, "r") as f:
            return f.read()
    except:
        try:
            with open(KNOWLEDGE_PATH, "r") as f:
                return f.read()
        except:
            return "Knowledge base not available."


# ── Claude Analysis ──

SYSTEM_PROMPT = """You are a concise trading analyst for SPY using Saty ATR Levels, Pivot Ribbon, and Phase Oscillator. Data may be ~15 min delayed.

CRITICAL TERMINOLOGY — GET THIS RIGHT:
- "Call trigger" = +23.6% ATR level. "Put trigger" = -23.6%. These are NOT Golden Gate levels.
- "Golden Gate ENTRY" = 38.2% ATR. "Golden Gate COMPLETION" = 61.8% ATR.
- The Golden Gate OPENS when 38.2% is breached. It COMPLETES when 61.8% is reached.
- Hitting the trigger (23.6%) does NOT mean the GG has opened. The GG opens at 38.2%.
- The "level_breaches" field tells you EXACTLY when each level was hit today. USE IT. Do not guess.
- The "active_setups" field tells you what setups are currently active. USE IT verbatim.

RULES:
- Use BULLET POINTS, not paragraphs. Be extremely concise.
- Start with a one-line bold summary: price, level position, bias direction.
- Then 4-8 bullet points covering: active setups, levels, ribbon, PO.
- ALWAYS cite specific study statistics for any setup you mention. This is the most important part.
- Flag HIGH CONVICTION signals prominently (e.g., trigger box held 30min = 90% spread win rate at 61.8%).
- Flag LOW CONVICTION / CAUTION signals (e.g., counter-trend PO, afternoon trigger).
- NEVER give trading advice. Present data and let the user decide.
- Note that backtests are historical and not independently verified.
- Use the computed level_breaches and active_setups fields. Do NOT make up breach times.

The full study reference with all statistics is provided in the user message context.
Look up the EXACT numbers from the reference — do not guess or approximate.
When a setup is active, cite the specific stat with sample size.

IMPORTANT — WHEN YOU DON'T HAVE THE ANSWER:
If the user asks a question whose answer is NOT in the study reference or the current indicators,
DO NOT guess or make up statistics. Instead, respond with EXACTLY this format:
**[QUERY_OFFER]** I don't have that specific stat. Want me to run the numbers against our 25-year database?
The frontend will detect [QUERY_OFFER] and show a "Run Analysis" button. When clicked, the system
will generate code, query the database, and return results. Only offer this for quantitative questions
that could be answered by querying the SPY indicator database.

FORMAT:
**SPY [price] | [level position] | [key signal or bias]**

- **[Setup/Level]:** [What happened, with exact time from level_breaches if available]
- **[Study stat]:** [Cite the exact number and sample size from the reference]
- **[Ribbon/PO]:** [State + what it means for current setup]
- **[Key levels]:** [Next target up/down with values]
- *Backtests historical, not verified. Data ~15 min delayed.*"""


def get_analysis(indicators: dict, user_message: str, conversation: list):
    """Call Claude to generate analysis."""
    knowledge = load_knowledge()

    indicator_context = json.dumps(indicators, indent=2)

    messages = []

    # Add conversation history
    for msg in conversation:
        messages.append(msg)

    # Add current message with indicator context and full study reference
    user_content = f"""Current SPY indicators (just fetched):
```json
{indicator_context}
```

FULL STUDY REFERENCE (cite exact numbers from here):
{knowledge}

User question: {user_message}"""

    messages.append({"role": "user", "content": user_content})

    client = OpenAI(api_key=OPENAI_KEY)

    response = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=4096,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
    )

    return response.choices[0].message.content


# ── API Endpoints ──

class AnalyzeRequest(BaseModel):
    message: str = "What's the current setup?"
    conversation: list = []

class AnalyzeResponse(BaseModel):
    analysis: str
    indicators: dict
    timestamp: str


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, authorization: str = Header(None)):
    # Simple auth
    if authorization != f"Bearer {API_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # 1. Fetch latest data from MASSIVE
        bars = fetch_recent_bars(days_back=7)
        if not bars:
            raise HTTPException(status_code=503, detail="No data from MASSIVE API")

        # 2. Compute live indicators
        indicators = compute_live_indicators(bars)
        if not indicators:
            raise HTTPException(status_code=503, detail="Insufficient data for indicators")

        # 3. Get Claude analysis
        analysis = get_analysis(indicators, req.message, req.conversation)

        return AnalyzeResponse(
            analysis=analysis,
            indicators=indicators,
            timestamp=indicators["timestamp"],
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Ad-hoc Database Query Endpoint ──

QUERY_SYSTEM = """You are a data analyst. Given a natural language question about SPY trading data,
write a Python script that queries the SQLite database and prints the answer.

DATABASE: /root/spy/spy.db

TABLES AND KEY POINTS:
- ind_10m: 10-minute bars (best for intraday studies). Has daily ATR levels broadcast to every bar.
  Filter to RTH: df.between_time("09:30", "15:59")
  Group by day: df["date"] = df.index.date; for date, group in df.groupby("date"): first = group.iloc[0]
  ATR levels are CONSTANT within a day (use first row): first["atr_upper_trigger"], first["atr_lower_trigger"],
    first["atr_upper_0382"], first["atr_lower_0382"], first["atr_upper_0618"], first["atr_lower_0618"],
    first["atr_upper_100"], first["atr_lower_100"], first["prev_close"]
- ind_1d: Daily bars. ATR levels here reference the PREVIOUS day (prev_close = yesterday's close).
  "Trigger box" = open between prev_close and trigger level.
  Bullish trigger box: open > prev_close AND open < atr_upper_trigger
  Bearish trigger box: open < prev_close AND open > atr_lower_trigger
- ind_1h: Hourly bars. phase_oscillator and compression are useful for 1h PO studies.
- ind_1w: Weekly bars. Own-timeframe ATR levels.

ALL TABLES have columns: timestamp, open, high, low, close, volume,
  ema_8, ema_13, ema_21, ema_48, ema_200,
  atr_14, prev_close, atr_upper_trigger, atr_lower_trigger,
  atr_upper_0382, atr_lower_0382, atr_upper_0618, atr_lower_0618,
  atr_upper_0786, atr_lower_0786, atr_upper_100, atr_lower_100,
  phase_oscillator, phase_zone, compression, atr_trend,
  fast_cloud_bullish, slow_cloud_bullish, candle_bias

TERMINOLOGY:
- Trigger = ±23.6% ATR. Golden Gate ENTRY = ±38.2%. Golden Gate COMPLETION = ±61.8%.
- The GG OPENS when 38.2% is hit, COMPLETES when 61.8% is hit.

RULES:
- Output ONLY Python code. No explanation. No markdown fences.
- Use sqlite3 and pandas. Import at top.
- Load with: pd.read_sql_query("SELECT ... FROM ind_10m ORDER BY timestamp", conn, parse_dates=["timestamp"])
- Print results clearly with labels. Keep output under 30 lines.
- Always print sample sizes (n=).
- If the question can't be answered, print "CANNOT_ANSWER: [reason]"
"""

class QueryRequest(BaseModel):
    question: str
    conversation: list = []

class QueryResponse(BaseModel):
    answer: str
    code: str
    raw_output: str


def generate_query_code(question: str) -> str:
    """Use OpenAI to generate Python code for the query."""
    client = OpenAI(api_key=OPENAI_KEY)
    response = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": QUERY_SYSTEM},
            {"role": "user", "content": question},
        ],
    )
    code = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    if code.startswith("```"):
        code = "\n".join(code.split("\n")[1:])
    if code.endswith("```"):
        code = "\n".join(code.split("\n")[:-1])
    return code


def execute_query_code(code: str) -> str:
    """Execute the generated Python code in a subprocess."""
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True, text=True, timeout=30,
            cwd="/root/spy"
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            output = f"ERROR: {result.stderr.strip()[:500]}"
        return output[:2000]  # cap output
    except subprocess.TimeoutExpired:
        return "ERROR: Query timed out (30s limit)"
    except Exception as e:
        return f"ERROR: {str(e)}"


def summarize_query_result(question: str, code: str, output: str) -> str:
    """Use OpenAI to summarize the raw output into a concise answer."""
    client = OpenAI(api_key=OPENAI_KEY)
    response = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": "Summarize this database query result in 2-4 concise bullet points. Include all key numbers. Note sample sizes. Add caveat that this is a draft analysis from historical data, not independently verified."},
            {"role": "user", "content": f"Question: {question}\n\nRaw output:\n{output}"},
        ],
    )
    return response.choices[0].message.content


@app.post("/api/query")
async def query(req: QueryRequest, authorization: str = Header(None)):
    if authorization != f"Bearer {API_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # 1. Generate code
        code = generate_query_code(req.question)

        # 2. Execute
        raw_output = execute_query_code(code)

        # 3. Summarize
        if raw_output.startswith("ERROR") or raw_output.startswith("CANNOT_ANSWER"):
            answer = f"Couldn't run that query: {raw_output}"
        else:
            answer = summarize_query_result(req.question, code, raw_output)

        return QueryResponse(answer=answer, code=code, raw_output=raw_output)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "milkman-analyst"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8899)
