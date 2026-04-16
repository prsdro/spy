"""
Aggregate 1-minute candles into higher timeframes: 3m, 10m, 1h, 4h, daily, weekly.
Uses pandas for proper OHLCV resampling, writes results back to SQLite.
Usage: python3 aggregate.py [--test]  (--test processes only 2024-10 data for validation)
"""

import sqlite3
import pandas as pd
import time
import sys

DB_PATH = "/root/spy/spy.db"

TIMEFRAMES = [
    ("candles_3m",  "3min"),
    ("candles_10m", "10min"),
    ("candles_1h",  "1h"),
    ("candles_4h",  "4h"),
    ("candles_1d",  "1D"),
    ("candles_1w",  "1W"),
]

# Regular Trading Hours: 9:30 AM - 4:00 PM ET
RTH_START = "09:30"
RTH_END = "16:00"

def load_1m(conn, test_mode=False, rth_only=False):
    where_parts = []
    if test_mode:
        where_parts.append("timestamp >= '2025-10-01' AND timestamp < '2025-11-01'")
    if rth_only:
        where_parts.append("TIME(timestamp) >= '09:30:00' AND TIME(timestamp) < '16:00:00'")
    else:
        # TradingView extended hours for NYSE/AMEX ends at 20:00 ET.
        # Exclude the 20:00 bar to match TV session boundaries.
        where_parts.append("TIME(timestamp) < '20:00:00'")
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    query = f"SELECT timestamp, open, high, low, close, volume FROM candles_1m {where} ORDER BY timestamp"
    df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()

    if rth_only:
        # Clip bad ticks: cap wicks at 2% beyond the candle body.
        # Catches phantom prints while preserving legitimate volatile bars.
        import numpy as np
        body_high = np.maximum(df["open"], df["close"])
        body_low = np.minimum(df["open"], df["close"])
        df["high"] = np.minimum(df["high"], body_high * 1.02)
        df["low"] = np.maximum(df["low"], body_low * 0.98)

    label = "RTH" if rth_only else "all-hours"
    print(f"Loaded {len(df):,} 1-minute candles ({label}) [{df.index.min()} -> {df.index.max()}]")
    return df

def resample_ohlcv(df, rule):
    """Resample OHLCV data to a coarser timeframe."""
    agg = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    return agg

def save_table(conn, table_name, df):
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    df_out = df.reset_index()
    df_out["timestamp"] = df_out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df_out["volume"] = df_out["volume"].astype(int)
    df_out.to_sql(table_name, conn, index=False, if_exists="replace")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_ts ON {table_name}(timestamp)")

def main():
    test_mode = "--test" in sys.argv
    if test_mode:
        print("TEST MODE: processing only 2025-10 data\n")

    conn = sqlite3.connect(DB_PATH)

    # Load all-hours data for intraday timeframes
    df_all = load_1m(conn, test_mode)

    # Load RTH-only data for daily and weekly candles
    df_rth = load_1m(conn, test_mode, rth_only=True)

    for table_name, rule in TIMEFRAMES:
        t0 = time.time()
        # Daily and weekly candles use RTH data only (matches TradingView behavior)
        use_rth = rule in ("1D", "1W")
        df = df_rth if use_rth else df_all
        label = "RTH" if use_rth else "all-hours"
        print(f"Aggregating {table_name} ({rule}, {label})...", end=" ", flush=True)
        agg = resample_ohlcv(df, rule)
        save_table(conn, table_name, agg)
        conn.commit()
        elapsed = time.time() - t0
        print(f"{len(agg):,} rows ({elapsed:.1f}s)")

    # Summary
    print("\n--- Summary ---")
    for table_name in ["candles_1m"] + [t[0] for t in TIMEFRAMES]:
        row = conn.execute(f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table_name}").fetchone()
        print(f"  {table_name:15s}: {row[0]:>10,} rows  [{row[1]} -> {row[2]}]")

    conn.close()

if __name__ == "__main__":
    main()
