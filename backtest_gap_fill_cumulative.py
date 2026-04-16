"""
Cumulative Gap Midpoint Fill Study

For each gap (up and down), track whether the gap reaches its MIDPOINT
(halfway between previous close and open) over the next 1-7 trading days.
Condition on:
1. 1-hour Phase Oscillator compression state at the gap
2. Daily EMA 21 slope (bullish/bearish) at the gap

Gap size buckets: <0.25%, 0.25-0.5%, 0.5-1%, 1-2%, 2%+
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load daily data for gap detection and EMA21 slope
    print("Loading daily data...", flush=True)
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, prev_close, ema_21 "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()
    daily = daily.dropna(subset=["prev_close"])
    daily["date"] = daily.index.date
    daily["ema_21_prev"] = daily["ema_21"].shift(1)
    daily["ema_21_slope"] = np.where(daily["ema_21"] > daily["ema_21_prev"], "bullish", "bearish")

    # Load 1h compression state at market open each day
    # Use the 09:00 hourly bar (covers 9:00-9:59, includes market open at 9:30)
    print("Loading 1h compression...", flush=True)
    hourly = pd.read_sql_query(
        "SELECT timestamp, compression FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    hourly = hourly.set_index("timestamp").sort_index()

    # Build a date -> compression lookup from the 09:00 bar each day
    hourly_9am = hourly[hourly.index.hour == 9].copy()
    hourly_9am["date"] = hourly_9am.index.date
    compression_by_date = hourly_9am.set_index("date")["compression"]

    daily["compression_1h"] = daily["date"].map(compression_by_date)

    # Load weekly EMA 21 for above/below weekly pivot filter
    print("Loading weekly EMA 21...", flush=True)
    weekly = pd.read_sql_query(
        "SELECT timestamp, ema_21 FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    weekly = weekly.set_index("timestamp").sort_index()

    # Map each daily bar to the most recent weekly EMA 21
    daily_reset = daily.reset_index()
    weekly_reset = weekly.reset_index()
    merged_w = pd.merge_asof(
        daily_reset[["timestamp"]],
        weekly_reset.rename(columns={"ema_21": "weekly_ema_21"}),
        on="timestamp",
        direction="backward"
    )
    daily["weekly_ema_21"] = merged_w["weekly_ema_21"].values
    daily["above_weekly_21"] = daily["open"] > daily["weekly_ema_21"]

    # Gap through weekly 21: prev_close on one side, open on the other
    daily["gap_up_thru_w21"] = (daily["prev_close"] < daily["weekly_ema_21"]) & (daily["open"] > daily["weekly_ema_21"])
    daily["gap_dn_thru_w21"] = (daily["prev_close"] > daily["weekly_ema_21"]) & (daily["open"] < daily["weekly_ema_21"])

    # Compute gaps
    daily["gap_pct"] = (daily["open"] - daily["prev_close"]) / daily["prev_close"]
    daily["gap_abs"] = daily["gap_pct"].abs()

    # For each day, we need to know the high/low over the NEXT N days to check fill
    # Pre-compute rolling forward highs and lows
    print("Computing forward highs/lows...", flush=True)
    dates = daily.index.tolist()
    n_days = len(dates)

    # Build arrays of forward highs and lows for days 1-7
    fwd_highs = {}  # {horizon: array of max high over next N days}
    fwd_lows = {}
    for horizon in range(1, 8):
        fwd_h = np.full(n_days, np.nan)
        fwd_l = np.full(n_days, np.nan)
        for i in range(n_days):
            end = min(i + horizon + 1, n_days)  # +1 because includes current day
            if i + 1 < n_days:
                # Include current day (for same-day fill) through horizon days forward
                fwd_h[i] = daily["high"].iloc[i:end].max()
                fwd_l[i] = daily["low"].iloc[i:end].min()
        fwd_highs[horizon] = fwd_h
        fwd_lows[horizon] = fwd_l

    # Gap size buckets
    buckets = [
        (0.0, 0.0025, "<0.25%"),
        (0.0025, 0.005, "0.25-0.5%"),
        (0.005, 0.01, "0.5-1%"),
        (0.01, 0.02, "1-2%"),
        (0.02, 1.0, "2%+"),
    ]

    # Conditions
    conditions = [
        ("All", lambda row: True),
        ("Compression", lambda row: row["compression_1h"] == 1),
        ("No Compression", lambda row: row["compression_1h"] != 1),
        ("Daily EMA21 Bullish", lambda row: row["ema_21_slope"] == "bullish"),
        ("Daily EMA21 Bearish", lambda row: row["ema_21_slope"] == "bearish"),
        ("Compression + EMA21 Bull", lambda row: row["compression_1h"] == 1 and row["ema_21_slope"] == "bullish"),
        ("Compression + EMA21 Bear", lambda row: row["compression_1h"] == 1 and row["ema_21_slope"] == "bearish"),
        ("Above Weekly 21", lambda row: row["above_weekly_21"] == True),
        ("Below Weekly 21", lambda row: row["above_weekly_21"] == False),
        ("Gap Up Over W21", lambda row: row["gap_up_thru_w21"] == True),
        ("Gap Down Under W21", lambda row: row["gap_dn_thru_w21"] == True),
        ("Above Wkly 21 + EMA21 Bull", lambda row: row["above_weekly_21"] == True and row["ema_21_slope"] == "bullish"),
        ("Below Wkly 21 + EMA21 Bear", lambda row: row["above_weekly_21"] == False and row["ema_21_slope"] == "bearish"),
    ]

    horizons = [1, 2, 3, 4, 5, 6, 7]

    # Results
    results = {}

    for cond_name, cond_fn in conditions:
        results[cond_name] = {}

        for direction in ["gap_up", "gap_down"]:
            results[cond_name][direction] = {}

            for lo, hi, bucket_name in buckets:
                counts = {h: 0 for h in horizons}
                total = 0

                for i in range(n_days):
                    row = daily.iloc[i]
                    gap = row["gap_pct"]
                    gap_abs = row["gap_abs"]

                    # Filter direction
                    if direction == "gap_up" and gap <= 0:
                        continue
                    if direction == "gap_down" and gap >= 0:
                        continue

                    # Filter bucket
                    if not (lo <= gap_abs < hi):
                        continue

                    # Filter condition
                    try:
                        if not cond_fn(row):
                            continue
                    except:
                        continue

                    total += 1
                    prev_close = row["prev_close"]
                    day_open = row["open"]
                    # Midpoint fill: price reaches halfway back through the gap
                    midpoint = (prev_close + day_open) / 2

                    for h in horizons:
                        if direction == "gap_up":
                            # Gap up midpoint fill: price drops to midpoint between prev_close and open
                            if fwd_lows[h][i] <= midpoint:
                                counts[h] += 1
                        else:
                            # Gap down midpoint fill: price rises to midpoint
                            if fwd_highs[h][i] >= midpoint:
                                counts[h] += 1

                results[cond_name][direction][bucket_name] = {
                    "total": total,
                    "fills": {str(h): counts[h] for h in horizons},
                    "pcts": {str(h): round(counts[h] / total * 100, 1) if total > 0 else 0
                             for h in horizons},
                }

    # Print results
    print("\n" + "=" * 100)
    print("CUMULATIVE GAP MIDPOINT FILL PROBABILITIES (1-7 Trading Days)")
    print("=" * 100)

    for cond_name, cond_data in results.items():
        print(f"\n{'─' * 80}")
        print(f"  Condition: {cond_name}")
        print(f"{'─' * 80}")

        for direction in ["gap_up", "gap_down"]:
            dir_label = "Gap Up" if direction == "gap_up" else "Gap Down"
            print(f"\n  {dir_label}:")
            print(f"  {'Gap Size':<12s} {'N':>5s}", end="")
            for h in horizons:
                print(f"  {h}d", end="")
            print()

            for _, _, bucket_name in buckets:
                d = cond_data[direction][bucket_name]
                n = d["total"]
                if n == 0:
                    continue
                print(f"  {bucket_name:<12s} {n:5d}", end="")
                for h in horizons:
                    pct = d["pcts"][str(h)]
                    print(f" {pct:4.0f}%", end="")
                print()

    # Save JSON for visualization
    with open(os.path.join(BASE_DIR, "gap_fill_cumulative.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nJSON saved to {os.path.join(BASE_DIR, 'gap_fill_cumulative.json')}")

    conn.close()


if __name__ == "__main__":
    main()
