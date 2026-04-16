"""
Golden Gate Invalidation Study

Question: Once a Golden Gate enters (price hits 38.2%), what pullback levels
predict failure to complete to 61.8%?

Tests candle CLOSES below ATR levels and Pivot Ribbon EMAs on multiple
timeframes (3m, 10m, 1h). Only checks pullbacks after the 38.2% entry
within the same RTH session.
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/root/spy/spy.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    # ── Load 10m data (primary timeframe for entry/exit detection) ──
    print("Loading 10m data...", flush=True)
    df10 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "prev_close, atr_14, "
        "ema_8, ema_21, ema_48 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df10 = df10.set_index("timestamp").sort_index()
    df10 = df10.between_time("09:30", "15:59")
    df10 = df10.dropna(subset=["prev_close", "atr_14"])
    df10["date"] = df10.index.date

    # ── Load 1h EMAs for cross-timeframe checks ──
    print("Loading 1h EMAs...", flush=True)
    df1h = pd.read_sql_query(
        "SELECT timestamp, ema_21 as ema_21_1h, ema_48 as ema_48_1h "
        "FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df1h = df1h.set_index("timestamp").sort_index()

    # ── Load 3m EMA8 for scalp-level check ──
    print("Loading 3m EMA8...", flush=True)
    df3m = pd.read_sql_query(
        "SELECT timestamp, ema_8 as ema_8_3m "
        "FROM ind_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df3m = df3m.set_index("timestamp").sort_index()

    # ── Merge cross-timeframe EMAs onto 10m bars ──
    print("Merging cross-timeframe EMAs...", flush=True)
    df10_reset = df10.reset_index()

    merged_1h = pd.merge_asof(
        df10_reset[["timestamp"]],
        df1h.reset_index(),
        on="timestamp", direction="backward"
    )
    df10["ema_21_1h"] = merged_1h["ema_21_1h"].values
    df10["ema_48_1h"] = merged_1h["ema_48_1h"].values

    merged_3m = pd.merge_asof(
        df10_reset[["timestamp"]],
        df3m.reset_index(),
        on="timestamp", direction="backward"
    )
    df10["ema_8_3m"] = merged_3m["ema_8_3m"].values

    # ── Define invalidation levels ──
    # For bullish: "close below X" after GG entry
    # For bearish: "close above X" after GG entry (mirrored)

    bull_levels = [
        ("10m close < EMA 8 (10m)",    lambda row: row["close"] < row["ema_8"]),
        ("10m close < EMA 21 (10m)",   lambda row: row["close"] < row["ema_21"]),
        ("10m close < EMA 48 (10m)",   lambda row: row["close"] < row["ema_48"]),
        ("10m close < EMA 8 (3m)",     lambda row: row["close"] < row["ema_8_3m"]),
        ("10m close < EMA 21 (1h)",    lambda row: row["close"] < row["ema_21_1h"]),
        ("10m close < EMA 48 (1h)",    lambda row: row["close"] < row["ema_48_1h"]),
        ("10m close < Upper Trigger",  lambda row: row["close"] < row["atr_upper_trigger"]),
        ("10m close < Prev Close",     lambda row: row["close"] < row["prev_close"]),
        ("10m close < Lower Trigger",  lambda row: row["close"] < row["atr_lower_trigger"]),
    ]

    bear_levels = [
        ("10m close > EMA 8 (10m)",    lambda row: row["close"] > row["ema_8"]),
        ("10m close > EMA 21 (10m)",   lambda row: row["close"] > row["ema_21"]),
        ("10m close > EMA 48 (10m)",   lambda row: row["close"] > row["ema_48"]),
        ("10m close > EMA 8 (3m)",     lambda row: row["close"] > row["ema_8_3m"]),
        ("10m close > EMA 21 (1h)",    lambda row: row["close"] > row["ema_21_1h"]),
        ("10m close > EMA 48 (1h)",    lambda row: row["close"] > row["ema_48_1h"]),
        ("10m close > Lower Trigger",  lambda row: row["close"] > row["atr_lower_trigger"]),
        ("10m close > Prev Close",     lambda row: row["close"] > row["prev_close"]),
        ("10m close > Upper Trigger",  lambda row: row["close"] > row["atr_upper_trigger"]),
    ]

    # ── Run analysis ──
    print("Computing invalidation stats...\n", flush=True)

    for direction, entry_col, target_col, levels, label in [
        ("bull", "atr_upper_0382", "atr_upper_0618", bull_levels, "BULLISH"),
        ("bear", "atr_lower_0382", "atr_lower_0618", bear_levels, "BEARISH"),
    ]:
        results = []

        # Track per-level: {level_name: {"hit_and_completed", "hit_and_failed", "miss_and_completed", "miss_and_failed"}}
        stats = {name: {"hit_complete": 0, "hit_fail": 0, "miss_complete": 0, "miss_fail": 0}
                 for name, _ in levels}
        total_gg = 0

        for date, group in df10.groupby("date"):
            first = group.iloc[0]
            entry_level = first[entry_col]
            target_level = first[target_col]
            if pd.isna(entry_level):
                continue

            # Find GG entry
            if direction == "bull":
                if first["open"] >= entry_level:
                    tidx = 0
                else:
                    hit = group["high"] >= entry_level
                    if hit.any():
                        tidx = hit.values.argmax()
                    else:
                        continue
            else:
                if first["open"] <= entry_level:
                    tidx = 0
                else:
                    hit = group["low"] <= entry_level
                    if hit.any():
                        tidx = hit.values.argmax()
                    else:
                        continue

            total_gg += 1

            # Bars after entry (inclusive)
            remaining = group.iloc[tidx:]

            # Did GG complete?
            if direction == "bull":
                completed = (remaining["high"] >= target_level).any()
            else:
                completed = (remaining["low"] <= target_level).any()

            # Check each invalidation level across all bars after entry
            for name, check_fn in levels:
                # Check if ANY bar after entry has a close violating the level
                invalidated = False
                for _, bar in remaining.iterrows():
                    try:
                        if check_fn(bar):
                            invalidated = True
                            break
                    except:
                        continue

                if invalidated:
                    if completed:
                        stats[name]["hit_complete"] += 1
                    else:
                        stats[name]["hit_fail"] += 1
                else:
                    if completed:
                        stats[name]["miss_complete"] += 1
                    else:
                        stats[name]["miss_fail"] += 1

        # Print results
        print(f"{'=' * 90}")
        print(f"{label} GOLDEN GATE INVALIDATION (n={total_gg} entries)")
        print(f"{'=' * 90}")
        baseline_rate = (sum(s["hit_complete"] + s["miss_complete"] for s in stats.values()) // len(stats)) / total_gg * 100

        print(f"\n{'Invalidation Level':<30s} {'Occurs':>7s} {'GG% Hit':>8s} {'GG% No Hit':>10s} {'Delta':>7s} {'Edge':>6s}")
        print("-" * 75)

        for name, _ in levels:
            s = stats[name]
            hit_total = s["hit_complete"] + s["hit_fail"]
            miss_total = s["miss_complete"] + s["miss_fail"]
            hit_rate = s["hit_complete"] / hit_total * 100 if hit_total > 0 else 0
            miss_rate = s["miss_complete"] / miss_total * 100 if miss_total > 0 else 0
            occurs_pct = hit_total / total_gg * 100
            delta = hit_rate - miss_rate
            edge = "AVOID" if delta < -10 else ("weak" if delta < -5 else "---")

            print(f"  {name:<28s} {occurs_pct:6.1f}% {hit_rate:7.1f}% {miss_rate:9.1f}% {delta:+6.1f}% {edge:>6s}")

        print()

    conn.close()


if __name__ == "__main__":
    main()
