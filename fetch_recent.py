"""
Fetch recent SPY data from Yahoo Finance, verify ATR levels, and print intraday context.
Usage: python3 fetch_recent.py
"""

import os, sqlite3, sys
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, date, timedelta
import pytz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")

ET = pytz.timezone("America/New_York")

def rma(series, period):
    """Wilder's RMA (same as ta.atr in TradingView)."""
    alpha = 1.0 / period
    result = np.full(len(series), np.nan)
    # Find first valid index
    first = series.first_valid_index()
    if first is None:
        return pd.Series(result, index=series.index)
    idx = series.index.get_loc(first)
    result[idx] = series.iloc[idx]
    for i in range(idx + 1, len(series)):
        if np.isnan(result[i-1]):
            result[i] = series.iloc[i]
        else:
            result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i-1]
    return pd.Series(result, index=series.index)


def compute_daily_atr(daily_df, period=14):
    """Compute ATR(14) using Wilder's RMA on daily candles."""
    df = daily_df.copy()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["prev_close"]).abs(),
            (df["low"] - df["prev_close"]).abs()
        )
    )
    df["atr_14"] = rma(df["tr"], period)
    return df


def update_db_daily(conn, daily_df):
    """Insert new daily candles that aren't already in the DB."""
    existing = pd.read_sql(
        "SELECT timestamp FROM candles_1d ORDER BY timestamp", conn
    )
    existing_dates = set(existing["timestamp"].str[:10].tolist())

    new_rows = []
    for ts, row in daily_df.iterrows():
        d_str = str(ts.date())
        if d_str not in existing_dates:
            new_rows.append((
                str(ts.date()),
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"])
            ))

    if new_rows:
        conn.executemany(
            "INSERT INTO candles_1d (timestamp, open, high, low, close, volume) VALUES (?,?,?,?,?,?)",
            new_rows
        )
        conn.commit()
        print(f"  Inserted {len(new_rows)} new daily candle(s): {[r[0] for r in new_rows]}")
    else:
        print("  Daily candles: already up to date")
    return new_rows


def main():
    conn = sqlite3.connect(DB_PATH)

    # ── 1. Fetch last 30 daily bars from Yahoo Finance ───────────────────────
    print("\nFetching SPY daily data from Yahoo Finance...")
    raw_daily = yf.download("SPY", period="30d", interval="1d",
                            auto_adjust=True, progress=False)
    raw_daily.columns = raw_daily.columns.get_level_values(0).str.lower()
    # Keep only RTH-relevant columns
    daily = raw_daily[["open", "high", "low", "close", "volume"]].copy()
    daily.index = daily.index.tz_localize(None)
    # Drop today if market is still open (incomplete candle)
    today = date.today()
    # We'll keep today's partial bar for intraday reference but use yesterday for ATR
    daily_complete = daily[daily.index.date < today].copy()

    print(f"  Daily bars fetched: {len(daily)} (through {daily.index[-1].date()})")

    # ── 2. Load full history from DB to compute accurate ATR ─────────────────
    print("\nLoading daily history from DB for ATR calculation...")
    df_db = pd.read_sql(
        "SELECT timestamp, open, high, low, close, volume FROM candles_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df_db = df_db.set_index("timestamp")

    # Merge: DB history + new Yahoo bars
    all_daily = pd.concat([df_db, daily_complete[~daily_complete.index.isin(df_db.index)]])
    all_daily = all_daily.sort_index()
    all_daily_with_atr = compute_daily_atr(all_daily)

    # ── 3. Update database with new rows ────────────────────────────────────
    print("\nUpdating database...")
    update_db_daily(conn, daily_complete)

    # ── 4. Compute today's ATR levels ────────────────────────────────────────
    # Today = April 17, 2026. prev_close = yesterday's close.
    yesterday = all_daily_with_atr.iloc[-1]  # last complete day
    prev_close = yesterday["close"]
    atr_14 = yesterday["atr_14"]

    fib = {
        "trigger":    0.236,
        "0382":       0.382,
        "050":        0.500,
        "0618":       0.618,
        "0786":       0.786,
        "100":        1.000,
        "1236":       1.236,
        "1618":       1.618,
        "200":        2.000,
    }

    print(f"\n{'='*60}")
    print(f"  TODAY'S ATR LEVELS  ({today})")
    print(f"{'='*60}")
    print(f"  Previous close:   {prev_close:.4f}  ({yesterday.name.date()})")
    print(f"  ATR(14):          {atr_14:.4f}  ({atr_14/prev_close*100:.2f}% of price)")
    print()
    print(f"  {'Level':<20s} {'Upper':>10s}  {'Lower':>10s}")
    print(f"  {'-'*44}")
    for name, mult in fib.items():
        upper = prev_close + mult * atr_14
        lower = prev_close - mult * atr_14
        print(f"  {name:<20s} {upper:10.2f}  {lower:10.2f}")

    # ── 5. Verify against user-supplied levels ───────────────────────────────
    expected = {
        "trigger_upper": 703.82,
        "100_upper": 710.83,
        "trigger_lower": 699.50,
        "100_lower": 692.49,
    }
    our = {
        "trigger_upper": prev_close + 0.236 * atr_14,
        "100_upper":     prev_close + 1.000 * atr_14,
        "trigger_lower": prev_close - 0.236 * atr_14,
        "100_lower":     prev_close - 1.000 * atr_14,
    }
    print(f"\n  {'VERIFICATION vs user-supplied levels'}")
    print(f"  {'Level':<20s} {'Expected':>10s}  {'Computed':>10s}  {'Delta':>8s}")
    print(f"  {'-'*52}")
    all_ok = True
    for key in expected:
        delta = our[key] - expected[key]
        ok = "✓" if abs(delta) < 0.20 else "✗"
        if abs(delta) >= 0.20:
            all_ok = False
        print(f"  {key:<20s} {expected[key]:10.2f}  {our[key]:10.2f}  {delta:+8.2f} {ok}")

    if all_ok:
        print(f"\n  ATR levels verified ✓ (within rounding)")
    else:
        print(f"\n  WARNING: ATR mismatch — possible prev_close or ATR difference")

    # ── 6. Fetch today's 1-minute intraday data ───────────────────────────────
    print(f"\n{'='*60}")
    print(f"  TODAY'S INTRADAY DATA (SPY, 1-min, ET)")
    print(f"{'='*60}")
    intraday = yf.download("SPY", period="1d", interval="1m",
                           auto_adjust=True, progress=False)
    intraday.columns = intraday.columns.get_level_values(0).str.lower()

    # Convert UTC → ET
    if intraday.index.tz is None:
        intraday.index = intraday.index.tz_localize("UTC")
    intraday.index = intraday.index.tz_convert("America/New_York")

    # RTH only
    rth = intraday.between_time("09:30", "15:59")
    if len(rth) == 0:
        print("  No RTH data yet")
        conn.close()
        return

    open_bar = rth.iloc[0]
    open_price = open_bar["open"]
    gap_pct = (open_price - prev_close) / prev_close * 100

    print(f"\n  Open:         {open_price:.2f}  (gap {gap_pct:+.2f}% vs prev_close {prev_close:.2f})")
    print(f"  Gapped up:    {'YES' if open_price > prev_close else 'NO'}")

    # 9:45am bar
    bar_945 = rth[rth.index.time == pd.Timestamp("09:45").time()]
    latest = rth.iloc[-1]

    print()
    print(f"  {'Time (ET)':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8}  Position vs ATR")
    print(f"  {'-'*72}")

    def atr_position(price):
        upper_100 = prev_close + atr_14
        lower_100 = prev_close - atr_14
        upper_trig = prev_close + 0.236 * atr_14
        lower_trig = prev_close - 0.236 * atr_14
        upper_0382 = prev_close + 0.382 * atr_14
        upper_0618 = prev_close + 0.618 * atr_14
        upper_1236 = prev_close + 1.236 * atr_14
        gain_pct = (price - prev_close) / prev_close * 100
        if price >= upper_1236:
            zone = f"+1.236 ATR ext  ({gain_pct:+.2f}%)"
        elif price >= upper_100:
            zone = f"AT/ABOVE +1 ATR ({gain_pct:+.2f}%)"
        elif price >= upper_0618:
            zone = f"+0.618–1.0 ATR  ({gain_pct:+.2f}%)"
        elif price >= upper_0382:
            zone = f"+0.382–0.618 ATR({gain_pct:+.2f}%)"
        elif price >= upper_trig:
            zone = f"above trigger   ({gain_pct:+.2f}%)"
        elif price >= prev_close:
            zone = f"above PDC       ({gain_pct:+.2f}%)"
        elif price >= lower_trig:
            zone = f"below PDC       ({gain_pct:+.2f}%)"
        else:
            zone = f"below trigger   ({gain_pct:+.2f}%)"
        return zone

    # Print first 8 RTH bars
    for ts, row in rth.head(8).iterrows():
        print(f"  {ts.strftime('%H:%M'):12} {row['open']:8.2f} {row['high']:8.2f} {row['low']:8.2f} {row['close']:8.2f}  {atr_position(row['close'])}")

    # Print 9:45 specifically if beyond the first 8
    if len(rth) > 8:
        print(f"  {'...':12}")
        # Find 9:45 bar
        for ts, row in rth.iterrows():
            if ts.hour == 9 and ts.minute == 45:
                print(f"  {ts.strftime('%H:%M'):12} {row['open']:8.2f} {row['high']:8.2f} {row['low']:8.2f} {row['close']:8.2f}  {atr_position(row['close'])} ← 9:45 bar")
                break
        print(f"  {'...':12}")
        ts = latest.name
        row = latest
        print(f"  {ts.strftime('%H:%M'):12} {row['open']:8.2f} {row['high']:8.2f} {row['low']:8.2f} {row['close']:8.2f}  {atr_position(row['close'])} ← latest")

    # Summary stats so far today
    print(f"\n  Intraday (RTH so far):")
    print(f"    High:         {rth['high'].max():.2f}  ({(rth['high'].max() - prev_close)/prev_close*100:+.2f}%)")
    print(f"    Low:          {rth['low'].min():.2f}  ({(rth['low'].min() - prev_close)/prev_close*100:+.2f}%)")
    print(f"    Latest:       {latest['close']:.2f}  ({(latest['close'] - prev_close)/prev_close*100:+.2f}%)")
    print(f"    Bars so far:  {len(rth)}")

    # Key ATR context
    upper_100 = prev_close + atr_14
    upper_1236 = prev_close + 1.236 * atr_14

    print(f"\n  Key ATR context:")
    print(f"    +1 ATR (710.83):   {'HIT' if rth['high'].max() >= upper_100 else 'not yet reached'}")
    print(f"    +1.236 ATR ({upper_1236:.2f}):  {'HIT' if rth['high'].max() >= upper_1236 else 'not yet reached'}")
    print(f"    Max pre-noon gain: {(rth[rth.index.hour < 12]['high'].max() - prev_close)/prev_close*100:+.2f}%"
          if len(rth[rth.index.hour < 12]) > 0 else "")

    conn.close()


if __name__ == "__main__":
    main()
