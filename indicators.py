"""
Compute Saty indicator values (ATR Levels, Pivot Ribbon, Phase Oscillator)
for all timeframes and store in SQLite.

Usage: python3 indicators.py [--test]  (--test processes only 2025-10 1m data)
"""

import sqlite3
import pandas as pd
import numpy as np
import time
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")

TABLES = [
    "candles_1m",
    "candles_3m",
    "candles_10m",
    "candles_1h",
    "candles_4h",
    "candles_1d",
    "candles_1w",
]


# ──────────────────────────────────────────────
# Technical indicator helpers
# ──────────────────────────────────────────────

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rma(series, period):
    """Wilder's Moving Average (RMA), same as TradingView's ta.rma().
    Equivalent to EWM with alpha=1/period."""
    return series.ewm(alpha=1/period, adjust=False).mean()

def atr(df, period=14):
    """Average True Range using RMA (Wilder's smoothing), matching TradingView's ta.atr()."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return rma(tr, period)

def stdev(series, period=21):
    return series.rolling(window=period, min_periods=1).std()


# ──────────────────────────────────────────────
# Saty Pivot Ribbon Pro
# ──────────────────────────────────────────────

def compute_pivot_ribbon(df):
    """Compute Pivot Ribbon EMAs, cloud states, conviction arrows, compression, and candle bias."""
    price = df["close"]

    # Core EMAs
    df["ema_8"]   = ema(price, 8)
    df["ema_13"]  = ema(price, 13)
    df["ema_21"]  = ema(price, 21)
    df["ema_48"]  = ema(price, 48)
    df["ema_200"] = ema(price, 200)

    # Fast cloud: bullish when ema_8 >= ema_21
    df["fast_cloud_bullish"] = (df["ema_8"] >= df["ema_21"]).astype(int)

    # Slow cloud: bullish when ema_13 >= ema_48
    df["slow_cloud_bullish"] = (df["ema_13"] >= df["ema_48"]).astype(int)

    # Pivot bias: bullish when ema_8 >= ema_21
    df["pivot_bias_bullish"] = (df["ema_8"] >= df["ema_21"]).astype(int)

    # Long-term bias: bullish when ema_21 >= ema_200
    df["longterm_bias_bullish"] = (df["ema_21"] >= df["ema_200"]).astype(int)

    # Conviction arrows (13/48 EMA crossover)
    bullish_conv = (df["ema_13"] >= df["ema_48"])
    bearish_conv = (df["ema_13"] < df["ema_48"])
    df["conviction_bull"] = (bullish_conv & ~bullish_conv.shift(1).fillna(False)).astype(int)
    df["conviction_bear"] = (bearish_conv & ~bearish_conv.shift(1).fillna(False)).astype(int)

    # Bollinger Band Compression (same logic as Pine Script)
    compression_pivot = ema(price, 21)
    above_compression_pivot = price >= compression_pivot
    atr_14 = atr(df, 14)
    std_21 = stdev(price, 21)

    bband_offset = 2.0 * std_21
    bband_up = compression_pivot + bband_offset
    bband_down = compression_pivot - bband_offset
    compression_threshold_up = compression_pivot + (2.0 * atr_14)
    compression_threshold_down = compression_pivot - (2.0 * atr_14)
    expansion_threshold_up = compression_pivot + (1.854 * atr_14)
    expansion_threshold_down = compression_pivot - (1.854 * atr_14)

    compression = np.where(above_compression_pivot,
                           bband_up - compression_threshold_up,
                           compression_threshold_down - bband_down)
    in_expansion_zone = np.where(above_compression_pivot,
                                  bband_up - expansion_threshold_up,
                                  expansion_threshold_down - bband_down)

    compression_s = pd.Series(compression, index=df.index)
    in_expansion_s = pd.Series(in_expansion_zone, index=df.index)
    expansion = compression_s.shift(1) <= compression_s

    # compression_tracker logic from Pine Script
    df["compression"] = 0
    comp_vals = np.zeros(len(df), dtype=int)
    exp_arr = expansion.values
    inexp_arr = in_expansion_s.values
    comp_arr = compression_s.values
    for i in range(1, len(df)):
        if exp_arr[i] and inexp_arr[i] > 0:
            comp_vals[i] = 0
        elif comp_arr[i] <= 0:
            comp_vals[i] = 1
        else:
            comp_vals[i] = 0
    df["compression"] = comp_vals

    # Candle bias (relative to ema_48)
    # 1=bullish_up, 2=bearish_up(orange), 3=bullish_down(blue), 4=bearish_down
    # 5=compression_up, 6=compression_down
    above_bias = price >= df["ema_48"]
    up = df["open"] < df["close"]
    down = df["open"] > df["close"]
    comp_mask = df["compression"] == 1

    candle_bias = np.zeros(len(df), dtype=int)
    candle_bias = np.where(comp_mask & up, 5,
                  np.where(comp_mask & down, 6,
                  np.where(above_bias & up, 1,
                  np.where(~above_bias & up, 2,
                  np.where(above_bias & down, 3,
                  np.where(~above_bias & down, 4, 0))))))
    df["candle_bias"] = candle_bias

    return df


# ──────────────────────────────────────────────
# Saty ATR Levels (Day trading mode = Daily reference)
# For each candle, compute levels based on its own timeframe's ATR.
# The "previous close" concept maps to shifted close.
# ──────────────────────────────────────────────

def compute_atr_levels(df, daily_ref=None):
    """Compute ATR-based Fibonacci levels.

    If daily_ref is provided (a DataFrame with daily candles), ATR levels are derived
    from daily ATR and previous daily close, then broadcast to each bar by date.
    This matches TradingView's request.security(ticker, 'D', ...) behavior.

    If daily_ref is None, computes from the df's own timeframe (used for daily/weekly tables).
    """
    if daily_ref is not None:
        # Compute daily ATR and prev close from the daily reference
        daily_atr = atr(daily_ref, 14)
        daily_prev_close = daily_ref["close"].shift(1)

        # Build a daily lookup: date -> (prev_close, atr_14)
        daily_lookup = pd.DataFrame({
            "date": daily_ref.index.date,
            "d_prev_close": daily_prev_close.values,
            "d_atr_14": daily_atr.values,
        }).set_index("date")

        # Map each intraday bar to its date's daily values
        bar_dates = df.index.date
        # Use reindex to handle dates not in daily data (fills with NaN)
        mapped = daily_lookup.reindex(bar_dates)
        df["atr_14"] = mapped["d_atr_14"].values
        df["prev_close"] = mapped["d_prev_close"].values
    else:
        df["atr_14"] = atr(df, 14)
        df["prev_close"] = df["close"].shift(1)

    atr_14 = df["atr_14"]
    prev_close = df["prev_close"]
    trigger_pct = 0.236

    # Trigger levels
    df["atr_upper_trigger"] = prev_close + trigger_pct * atr_14
    df["atr_lower_trigger"] = prev_close - trigger_pct * atr_14

    # Key Fibonacci levels
    fib_labels = {0.382: "0382", 0.5: "050", 0.618: "0618", 0.786: "0786", 1.0: "100"}
    for fib, label in fib_labels.items():
        df[f"atr_upper_{label}"] = prev_close + fib * atr_14
        df[f"atr_lower_{label}"] = prev_close - fib * atr_14

    # Extension levels
    upper_1 = prev_close + atr_14
    lower_1 = prev_close - atr_14
    ext_labels = {0.236: "1236", 0.382: "1382", 0.5: "150", 0.618: "1618", 0.786: "1786", 1.0: "200"}
    for ext, label in ext_labels.items():
        df[f"atr_upper_{label}"] = upper_1 + ext * atr_14
        df[f"atr_lower_{label}"] = lower_1 - ext * atr_14

    # Range vs ATR
    df["period_high"] = df["high"]
    df["period_low"] = df["low"]
    df["range_pct_of_atr"] = ((df["high"] - df["low"]) / atr_14 * 100)

    # Trend from 8/21/34 pivot ribbon
    price = df["close"]
    e8 = ema(price, 8)
    e21 = ema(price, 21)
    e34 = ema(price, 34)
    df["atr_trend"] = np.where(
        (price >= e8) & (e8 >= e21) & (e21 >= e34), 1,   # bullish
        np.where(
            (price <= e8) & (e8 <= e21) & (e21 <= e34), -1,  # bearish
            0  # neutral
        )
    )

    return df


# ──────────────────────────────────────────────
# Saty Phase Oscillator
# ──────────────────────────────────────────────

def compute_phase_oscillator(df):
    """Compute the Phase Oscillator and zone signals."""
    price = df["close"]
    atr_14 = atr(df, 14)
    pivot = ema(price, 21)
    std_21 = stdev(price, 21)

    # Raw signal: ((price - pivot) / (3 * ATR)) * 100
    raw_signal = ((price - pivot) / (3.0 * atr_14)) * 100
    oscillator = ema(raw_signal, 3)
    df["phase_oscillator"] = oscillator

    # Phase zone classification
    # >100: extended_up, 61.8-100: distribution, 23.6-61.8: neutral_up
    # -23.6 to 23.6: neutral, -61.8 to -23.6: neutral_down
    # -100 to -61.8: accumulation, <-100: extended_down
    df["phase_zone"] = np.select(
        [
            oscillator > 100,
            oscillator > 61.8,
            oscillator > 23.6,
            oscillator > -23.6,
            oscillator > -61.8,
            oscillator > -100,
        ],
        ["extended_up", "distribution", "neutral_up", "neutral", "neutral_down", "accumulation"],
        default="extended_down"
    )

    # Mean reversion signals
    osc_prev = oscillator.shift(1)
    df["leaving_accumulation"] = ((osc_prev <= -61.8) & (oscillator > -61.8)).astype(int)
    df["leaving_distribution"] = ((osc_prev >= 61.8) & (oscillator < 61.8)).astype(int)
    df["leaving_extreme_down"] = ((osc_prev <= -100) & (oscillator > -100)).astype(int)
    df["leaving_extreme_up"]   = ((osc_prev >= 100) & (oscillator < 100)).astype(int)

    # Compression (same BB compression logic)
    above_pivot = price >= pivot
    bband_offset = 2.0 * std_21
    bband_up = pivot + bband_offset
    bband_down = pivot - bband_offset
    comp_thresh_up = pivot + (2.0 * atr_14)
    comp_thresh_down = pivot - (2.0 * atr_14)
    exp_thresh_up = pivot + (1.854 * atr_14)
    exp_thresh_down = pivot - (1.854 * atr_14)

    compression_val = np.where(above_pivot,
                               bband_up - comp_thresh_up,
                               comp_thresh_down - bband_down)
    in_exp_zone = np.where(above_pivot,
                            bband_up - exp_thresh_up,
                            exp_thresh_down - bband_down)

    comp_s = pd.Series(compression_val, index=df.index)
    inexp_s = pd.Series(in_exp_zone, index=df.index)
    exp_flag = comp_s.shift(1) <= comp_s

    po_comp = np.zeros(len(df), dtype=int)
    exp_arr = exp_flag.values
    inexp_arr = inexp_s.values
    comp_arr = comp_s.values
    for i in range(1, len(df)):
        if exp_arr[i] and inexp_arr[i] > 0:
            po_comp[i] = 0
        elif comp_arr[i] <= 0:
            po_comp[i] = 1
        else:
            po_comp[i] = 0
    df["po_compression"] = po_comp

    return df


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def save_df_to_table(conn, out_table, df, mode="replace"):
    """Save a DataFrame to SQLite, handling type conversion."""
    df_out = df.reset_index()
    df_out["timestamp"] = df_out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    for col in df_out.columns:
        if df_out[col].dtype == bool:
            df_out[col] = df_out[col].astype(int)
    df_out.to_sql(out_table, conn, index=False, if_exists=mode)


def load_daily_ref(conn):
    """Load daily candles for use as ATR level reference."""
    query = "SELECT timestamp, open, high, low, close, volume FROM candles_1d ORDER BY timestamp"
    df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df


# Intraday tables that need daily ATR reference
INTRADAY_TABLES = {"candles_1m", "candles_3m", "candles_10m", "candles_1h", "candles_4h"}


def process_table_chunked(conn, table_name, daily_ref, chunk_months=3):
    """Process large tables in time-based chunks to avoid OOM.
    Uses overlapping windows so EMA warmup is handled correctly."""
    out_table = f"ind_{table_name.replace('candles_', '')}"
    is_intraday = table_name in INTRADAY_TABLES

    # Get date range
    min_ts, max_ts = conn.execute(
        f"SELECT MIN(timestamp), MAX(timestamp) FROM {table_name}"
    ).fetchone()
    min_date = pd.Timestamp(min_ts)
    max_date = pd.Timestamp(max_ts)

    # EMA warmup: need ~200 bars of lead-in for EMA-200
    overlap = pd.Timedelta(days=14)

    conn.execute(f"DROP TABLE IF EXISTS {out_table}")
    total_rows = 0
    chunk_start = min_date

    while chunk_start <= max_date:
        chunk_end = chunk_start + pd.DateOffset(months=chunk_months)
        warmup_start = chunk_start - overlap

        query = f"""SELECT timestamp, open, high, low, close, volume
                    FROM {table_name}
                    WHERE timestamp >= '{warmup_start.strftime('%Y-%m-%d %H:%M:%S')}'
                      AND timestamp < '{chunk_end.strftime('%Y-%m-%d %H:%M:%S')}'
                    ORDER BY timestamp"""
        df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
        df = df.set_index("timestamp").sort_index()

        if len(df) == 0:
            chunk_start = chunk_end
            continue

        df = compute_pivot_ribbon(df)
        df = compute_atr_levels(df, daily_ref=daily_ref if is_intraday else None)
        df = compute_phase_oscillator(df)

        # Trim off warmup period
        df = df[df.index >= chunk_start]

        if len(df) > 0:
            mode = "replace" if total_rows == 0 else "append"
            save_df_to_table(conn, out_table, df, mode=mode)
            total_rows += len(df)
            conn.commit()
            print(f"  chunk {chunk_start.strftime('%Y-%m')} -> {chunk_end.strftime('%Y-%m')}: {len(df):,} rows", flush=True)

        chunk_start = chunk_end
        del df

    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{out_table}_ts ON {out_table}(timestamp)")
    conn.commit()
    return total_rows


def process_table(conn, table_name, daily_ref, test_mode=False):
    """Process a table — use chunking for large tables, direct for small ones."""
    out_table = f"ind_{table_name.replace('candles_', '')}"
    is_intraday = table_name in INTRADAY_TABLES

    if test_mode:
        where = "WHERE timestamp >= '2025-10-01' AND timestamp < '2025-11-01'"
        query = f"SELECT timestamp, open, high, low, close, volume FROM {table_name} {where} ORDER BY timestamp"
        df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
        df = df.set_index("timestamp").sort_index()
        if len(df) == 0:
            return 0
        df = compute_pivot_ribbon(df)
        df = compute_atr_levels(df, daily_ref=daily_ref if is_intraday else None)
        df = compute_phase_oscillator(df)
        conn.execute(f"DROP TABLE IF EXISTS {out_table}")
        save_df_to_table(conn, out_table, df, "replace")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{out_table}_ts ON {out_table}(timestamp)")
        conn.commit()
        return len(df)

    # Check row count to decide strategy
    row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    if row_count > 500_000:
        return process_table_chunked(conn, table_name, daily_ref, chunk_months=6)
    else:
        query = f"SELECT timestamp, open, high, low, close, volume FROM {table_name} ORDER BY timestamp"
        df = pd.read_sql_query(query, conn, parse_dates=["timestamp"])
        df = df.set_index("timestamp").sort_index()
        if len(df) == 0:
            return 0
        df = compute_pivot_ribbon(df)
        df = compute_atr_levels(df, daily_ref=daily_ref if is_intraday else None)
        df = compute_phase_oscillator(df)
        conn.execute(f"DROP TABLE IF EXISTS {out_table}")
        save_df_to_table(conn, out_table, df, "replace")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{out_table}_ts ON {out_table}(timestamp)")
        conn.commit()
        return len(df)


def main():
    test_mode = "--test" in sys.argv
    if test_mode:
        print("TEST MODE: processing only 2025-10 data\n")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Load daily reference data for ATR levels on intraday tables
    print("Loading daily reference for ATR levels...", flush=True)
    daily_ref = load_daily_ref(conn)
    print(f"  {len(daily_ref):,} daily bars loaded\n")

    tables = TABLES
    if test_mode:
        tables = ["candles_1m"]  # just validate on 1m

    for table_name in tables:
        t0 = time.time()
        out_name = f"ind_{table_name.replace('candles_', '')}"
        print(f"Computing indicators for {table_name} -> {out_name}...", end=" ", flush=True)
        count = process_table(conn, table_name, daily_ref, test_mode)
        elapsed = time.time() - t0
        print(f"{count:,} rows ({elapsed:.1f}s)")

    # Summary
    print("\n--- Indicator Tables ---")
    tables_check = [f"ind_{t.replace('candles_', '')}" for t in tables]
    for t in tables_check:
        row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        cols = [desc[0] for desc in conn.execute(f"SELECT * FROM {t} LIMIT 0").description]
        print(f"  {t:15s}: {row[0]:>10,} rows, {len(cols)} columns")

    conn.close()

if __name__ == "__main__":
    main()
