"""
Import TradingView 1h CSV export into the spy.db ind_1h table.

The TV CSV contains:
- OHLC (cols 0-4)
- ATR Levels Day Mode (cols 5-35, first set)
- ATR Levels Multiday Mode (cols 43-72, second set)
- Pivot Ribbon 1h timeframe (cols 74-86, first set)
- Pivot Ribbon Daily timeframe overlay (cols 87-99, second set)
- Phase Oscillator 1h (cols 100-114)

We import the 1h Pivot Ribbon EMAs and the 1h Phase Oscillator,
plus the Day Mode ATR levels (daily reference for intraday).
"""

import os
import pandas as pd
import sqlite3
import sys
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
CSV_PATH = os.path.join(BASE_DIR, "AMEX_SPY, 60 (1).csv")


def main():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_csv(CSV_PATH)
    print(f"CSV rows: {len(df)}")

    # Parse timestamps — CST/CDT with offset, convert to naive ET for DB
    df['ts'] = pd.to_datetime(df['time'], utc=True)
    df['ts_et'] = df['ts'].dt.tz_convert('America/New_York').dt.tz_localize(None)

    print(f"Date range: {df['ts_et'].iloc[0]} to {df['ts_et'].iloc[-1]}")

    # Check what's already in the database
    cur = conn.execute("SELECT MAX(timestamp) FROM ind_1h")
    db_max = cur.fetchone()[0]
    print(f"Current DB max timestamp: {db_max}")

    # Only import rows after the DB's last timestamp
    if db_max:
        db_max_ts = pd.Timestamp(db_max)
        new_rows = df[df['ts_et'] > db_max_ts].copy()
    else:
        new_rows = df.copy()

    print(f"New rows to import: {len(new_rows)}")

    if len(new_rows) == 0:
        print("Nothing to import.")
        conn.close()
        return

    # Build the import DataFrame matching ind_1h schema
    # Column mapping from CSV to DB
    out = pd.DataFrame()
    out['timestamp'] = new_rows['ts_et'].dt.strftime('%Y-%m-%d %H:%M:%S')
    out['open'] = new_rows['open'].values
    out['high'] = new_rows['high'].values
    out['low'] = new_rows['low'].values
    out['close'] = new_rows['close'].values

    # Volume — TV CSV has volume in a column, let's find it
    # Check for volume column
    vol_cols = [c for c in df.columns if 'volume' in c.lower() or 'Volume' in c]
    if vol_cols:
        out['volume'] = new_rows[vol_cols[0]].values
    else:
        # Volume might be in one of the unnamed trailing columns
        # The last few columns in the CSV seem to have numeric values
        out['volume'] = 0

    # 1h Pivot Ribbon EMAs (first set — 1h timeframe)
    out['ema_8'] = pd.to_numeric(new_rows.iloc[:, 74], errors='coerce').values   # Fast EMA
    out['ema_13'] = pd.to_numeric(new_rows.iloc[:, 75], errors='coerce').values  # Pullback Overlap EMA
    out['ema_21'] = pd.to_numeric(new_rows.iloc[:, 76], errors='coerce').values  # Pivot EMA
    out['ema_48'] = pd.to_numeric(new_rows.iloc[:, 77], errors='coerce').values  # Slow EMA
    out['ema_200'] = pd.to_numeric(new_rows.iloc[:, 78], errors='coerce').values # Long-term EMA

    # Pivot Ribbon signals
    out['fast_cloud_bullish'] = (out['ema_8'] >= out['ema_21']).astype(int)
    out['slow_cloud_bullish'] = (out['ema_13'] >= out['ema_48']).astype(int)
    out['pivot_bias_bullish'] = (out['ema_8'] >= out['ema_21']).astype(int)
    out['longterm_bias_bullish'] = (out['ema_21'] >= out['ema_200']).astype(int)

    # Conviction signals from CSV
    conv_bull = pd.to_numeric(new_rows.iloc[:, 79], errors='coerce').fillna(0)
    conv_bear = pd.to_numeric(new_rows.iloc[:, 80], errors='coerce').fillna(0)
    out['conviction_bull'] = (conv_bull > 0).astype(int)
    out['conviction_bear'] = (conv_bear > 0).astype(int)

    # Compression — not directly in the CSV, set to 0
    out['compression'] = 0

    # Candle bias — derive from position relative to ema_48
    # 1=bull up, 2=bearish up (orange), 3=bullish down (blue), 4=bear down
    up = out['close'] >= out['open']
    above_48 = out['close'] > out['ema_48']
    out['candle_bias'] = 0
    out.loc[up & above_48, 'candle_bias'] = 1
    out.loc[up & ~above_48, 'candle_bias'] = 2
    out.loc[~up & above_48, 'candle_bias'] = 3
    out.loc[~up & ~above_48, 'candle_bias'] = 4

    # ATR Levels (Day Mode — first set, daily reference)
    out['atr_14'] = 0  # Not directly available per-bar; daily ATR is embedded in levels
    out['prev_close'] = pd.to_numeric(new_rows.iloc[:, 21], errors='coerce').values  # Previous Close

    # Compute atr_14 from the levels: atr_upper_100 - prev_close = ATR
    atr_upper_100 = pd.to_numeric(new_rows.iloc[:, 27], errors='coerce').values
    prev_close_vals = pd.to_numeric(new_rows.iloc[:, 21], errors='coerce').values
    out['atr_14'] = atr_upper_100 - prev_close_vals

    out['atr_upper_trigger'] = pd.to_numeric(new_rows.iloc[:, 22], errors='coerce').values
    out['atr_lower_trigger'] = pd.to_numeric(new_rows.iloc[:, 20], errors='coerce').values
    out['atr_upper_0382'] = pd.to_numeric(new_rows.iloc[:, 23], errors='coerce').values
    out['atr_lower_0382'] = pd.to_numeric(new_rows.iloc[:, 19], errors='coerce').values
    out['atr_upper_050'] = pd.to_numeric(new_rows.iloc[:, 24], errors='coerce').values
    out['atr_lower_050'] = pd.to_numeric(new_rows.iloc[:, 18], errors='coerce').values
    out['atr_upper_0618'] = pd.to_numeric(new_rows.iloc[:, 25], errors='coerce').values
    out['atr_lower_0618'] = pd.to_numeric(new_rows.iloc[:, 17], errors='coerce').values
    out['atr_upper_0786'] = pd.to_numeric(new_rows.iloc[:, 26], errors='coerce').values
    out['atr_lower_0786'] = pd.to_numeric(new_rows.iloc[:, 16], errors='coerce').values
    out['atr_upper_100'] = pd.to_numeric(new_rows.iloc[:, 27], errors='coerce').values
    out['atr_lower_100'] = pd.to_numeric(new_rows.iloc[:, 15], errors='coerce').values
    out['atr_upper_1236'] = pd.to_numeric(new_rows.iloc[:, 28], errors='coerce').values
    out['atr_lower_1236'] = pd.to_numeric(new_rows.iloc[:, 14], errors='coerce').values
    out['atr_upper_1382'] = pd.to_numeric(new_rows.iloc[:, 29], errors='coerce').values
    out['atr_lower_1382'] = pd.to_numeric(new_rows.iloc[:, 13], errors='coerce').values
    out['atr_upper_150'] = pd.to_numeric(new_rows.iloc[:, 30], errors='coerce').values
    out['atr_lower_150'] = pd.to_numeric(new_rows.iloc[:, 12], errors='coerce').values
    out['atr_upper_1618'] = pd.to_numeric(new_rows.iloc[:, 31], errors='coerce').values
    out['atr_lower_1618'] = pd.to_numeric(new_rows.iloc[:, 11], errors='coerce').values
    out['atr_upper_1786'] = pd.to_numeric(new_rows.iloc[:, 32], errors='coerce').values
    out['atr_lower_1786'] = pd.to_numeric(new_rows.iloc[:, 10], errors='coerce').values
    out['atr_upper_200'] = pd.to_numeric(new_rows.iloc[:, 33], errors='coerce').values
    out['atr_lower_200'] = pd.to_numeric(new_rows.iloc[:, 9], errors='coerce').values

    # ATR trend — derive from EMA stack
    ema34 = (out['ema_21'] + out['ema_48']) / 2  # Approximate EMA34
    bullish = (out['close'] >= out['ema_8']) & (out['ema_8'] >= out['ema_21']) & (out['ema_21'] >= ema34)
    bearish = (out['close'] <= out['ema_8']) & (out['ema_8'] <= out['ema_21']) & (out['ema_21'] <= ema34)
    out['atr_trend'] = 0
    out.loc[bullish, 'atr_trend'] = 1
    out.loc[bearish, 'atr_trend'] = -1

    out['range_pct_of_atr'] = 0  # Could compute but not critical
    out['period_high'] = out['high']
    out['period_low'] = out['low']

    # Phase Oscillator (1h timeframe)
    out['phase_oscillator'] = pd.to_numeric(new_rows.iloc[:, 107], errors='coerce').values

    # Phase zone from PO value
    po = out['phase_oscillator']
    out['phase_zone'] = 'neutral'
    out.loc[po > 100, 'phase_zone'] = 'extended_up'
    out.loc[(po > 61.8) & (po <= 100), 'phase_zone'] = 'distribution'
    out.loc[(po > 23.6) & (po <= 61.8), 'phase_zone'] = 'neutral_up'
    out.loc[(po >= -23.6) & (po <= 23.6), 'phase_zone'] = 'neutral'
    out.loc[(po >= -61.8) & (po < -23.6), 'phase_zone'] = 'neutral_down'
    out.loc[(po >= -100) & (po < -61.8), 'phase_zone'] = 'accumulation'
    out.loc[po < -100, 'phase_zone'] = 'extended_down'

    # Leaving signals from CSV
    out['leaving_accumulation'] = pd.to_numeric(new_rows.iloc[:, 108], errors='coerce').fillna(0).apply(lambda x: 1 if x > 0 else 0)
    out['leaving_extreme_down'] = pd.to_numeric(new_rows.iloc[:, 109], errors='coerce').fillna(0).apply(lambda x: 1 if x > 0 else 0)
    out['leaving_distribution'] = pd.to_numeric(new_rows.iloc[:, 110], errors='coerce').fillna(0).apply(lambda x: 1 if x > 0 else 0)
    out['leaving_extreme_up'] = pd.to_numeric(new_rows.iloc[:, 111], errors='coerce').fillna(0).apply(lambda x: 1 if x > 0 else 0)

    out['po_compression'] = 0

    # Insert into database
    print(f"\nInserting {len(out)} rows into ind_1h...")
    print(f"  First: {out.iloc[0]['timestamp']}")
    print(f"  Last:  {out.iloc[-1]['timestamp']}")

    # Verify columns match DB schema
    cur = conn.execute("SELECT * FROM ind_1h LIMIT 1")
    db_cols = [d[0] for d in cur.description]
    print(f"\n  DB columns ({len(db_cols)}): {db_cols[:10]}...")
    print(f"  Import columns ({len(out.columns)}): {list(out.columns)[:10]}...")

    # Reorder to match DB
    out = out[db_cols]

    out.to_sql('ind_1h', conn, if_exists='append', index=False)

    # Verify
    cur = conn.execute("SELECT MAX(timestamp), COUNT(*) FROM ind_1h")
    max_ts, total = cur.fetchone()
    print(f"\n  DB now has {total:,} rows in ind_1h")
    print(f"  Max timestamp: {max_ts}")

    # Show last 5 rows to verify PO values
    cur = conn.execute("SELECT timestamp, close, phase_oscillator, phase_zone, leaving_extreme_up FROM ind_1h ORDER BY timestamp DESC LIMIT 10")
    print(f"\n  Last 10 rows:")
    for row in cur:
        print(f"    {row}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
