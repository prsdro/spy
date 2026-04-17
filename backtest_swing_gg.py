"""
Swing Golden Gate Study (Monthly ATR)

Uses MONTHLY ATR and previous month's close to define levels.
Tracks GG (38.2% → 61.8% of monthly ATR) completion over 1-20 trading days.
Conditions on WEEKLY Phase Oscillator state (previous week's close, to avoid look-ahead bias).

NOTE: We don't have ind_1m (monthly), so we compute monthly ATR from weekly data.
Instead, use ind_1d with a rolling 3-month window to approximate monthly levels.
Actually, Saty's Swing mode uses Monthly timeframe. We need monthly candles.
Let's compute monthly OHLC from daily, then compute ATR and levels, then track on daily.
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def rma(series, period):
    result = np.empty_like(series, dtype=float)
    result[0] = series.iloc[0]
    alpha = 1.0 / period
    for i in range(1, len(series)):
        result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=series.index)


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load daily data
    print("Loading daily data...", flush=True)
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, phase_oscillator "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()

    # Load weekly data for weekly PO
    print("Loading weekly data...", flush=True)
    weekly = pd.read_sql_query(
        "SELECT timestamp, phase_oscillator as weekly_po "
        "FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    weekly = weekly.set_index("timestamp").sort_index()

    # Map weekly PO to daily (use previous week's PO for no look-ahead)
    weekly["wk_po_prev"] = weekly["weekly_po"].shift(1)
    weekly["wk_po_prev2"] = weekly["weekly_po"].shift(2)
    dr = daily.reset_index()
    wr = weekly.reset_index()
    m = pd.merge_asof(dr[["timestamp"]], wr[["timestamp", "wk_po_prev", "wk_po_prev2"]],
                       on="timestamp", direction="backward")
    daily["wk_po"] = m["wk_po_prev"].values
    daily["wk_po_prev"] = m["wk_po_prev2"].values

    # Compute monthly candles from daily
    print("Computing monthly candles and ATR...", flush=True)
    daily["month"] = daily.index.to_period("M")
    monthly = daily.groupby("month").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )

    # Monthly ATR
    prev_close = monthly["close"].shift(1)
    tr = pd.concat([
        monthly["high"] - monthly["low"],
        (monthly["high"] - prev_close).abs(),
        (monthly["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    monthly["atr_14"] = rma(tr, 14)
    monthly["prev_close"] = prev_close

    monthly["level_prev_close"] = monthly["close"].shift(1)
    monthly["level_atr_14"] = monthly["atr_14"].shift(1)

    # Monthly ATR levels for the current trading month must come from the
    # previously completed monthly bar.
    for name, fib in [("trigger", 0.236), ("0382", 0.382), ("0618", 0.618), ("100", 1.0)]:
        monthly[f"upper_{name}"] = monthly["level_prev_close"] + fib * monthly["level_atr_14"]
        monthly[f"lower_{name}"] = monthly["level_prev_close"] - fib * monthly["level_atr_14"]

    monthly_lookup = monthly.rename(
        columns={
            "level_prev_close": "mo_prev_close",
            "level_atr_14": "mo_atr_14",
            "upper_trigger": "mo_upper_trigger",
            "lower_trigger": "mo_lower_trigger",
            "upper_0382": "mo_upper_0382",
            "lower_0382": "mo_lower_0382",
            "upper_0618": "mo_upper_0618",
            "lower_0618": "mo_lower_0618",
            "upper_100": "mo_upper_100",
            "lower_100": "mo_lower_100",
        }
    )
    daily = daily.join(
        monthly_lookup[
            [
                "mo_prev_close",
                "mo_atr_14",
                "mo_upper_trigger",
                "mo_lower_trigger",
                "mo_upper_0382",
                "mo_lower_0382",
                "mo_upper_0618",
                "mo_lower_0618",
                "mo_upper_100",
                "mo_lower_100",
            ]
        ],
        on="month",
    )

    dates = daily.index.tolist()
    n_days = len(dates)

    def classify_po(po, po_prev):
        if pd.isna(po) or pd.isna(po_prev):
            return None, None
        zone = "high" if po > 61.8 else ("low" if po < -61.8 else "mid")
        slope = "rising" if po > po_prev else "falling"
        return zone, slope

    print("Computing swing GG stats...\n")

    horizons = [1, 3, 5, 10, 15, 20]

    for direction, label in [("bull", "BULLISH"), ("bear", "BEARISH")]:
        results = {}

        for i in range(n_days):
            row = daily.iloc[i]
            if direction == "bull":
                entry_level = row.get("mo_upper_0382")
                exit_level = row.get("mo_upper_0618")
                full_atr = row.get("mo_upper_100")
            else:
                entry_level = row.get("mo_lower_0382")
                exit_level = row.get("mo_lower_0618")
                full_atr = row.get("mo_lower_100")

            if pd.isna(entry_level) or pd.isna(exit_level):
                continue

            # Check if this day hits the monthly 38.2%
            if direction == "bull":
                entry_hit = row["high"] >= entry_level
            else:
                entry_hit = row["low"] <= entry_level

            if not entry_hit:
                continue

            # Dedup within month
            if i > 0:
                prev_row = daily.iloc[i - 1]
                same_month = dates[i].month == dates[i - 1].month and dates[i].year == dates[i - 1].year
                if same_month:
                    if direction == "bull" and prev_row["high"] >= entry_level:
                        continue
                    if direction == "bear" and prev_row["low"] <= entry_level:
                        continue

            # Weekly PO state (previous week)
            zone, slope = classify_po(row["wk_po"], row["wk_po_prev"])
            if zone is None:
                continue

            po_key = f"{zone}|{slope}"
            if po_key not in results:
                results[po_key] = {"total": 0}
                for h in horizons:
                    results[po_key][f"complete_{h}d"] = 0
                    results[po_key][f"full_atr_{h}d"] = 0

            results[po_key]["total"] += 1

            for h in horizons:
                end_idx = min(i + h, n_days - 1)
                future = daily.iloc[i:end_idx + 1]
                if direction == "bull":
                    if (future["high"] >= exit_level).any():
                        results[po_key][f"complete_{h}d"] += 1
                    if (future["high"] >= full_atr).any():
                        results[po_key][f"full_atr_{h}d"] += 1
                else:
                    if (future["low"] <= exit_level).any():
                        results[po_key][f"complete_{h}d"] += 1
                    if (future["low"] <= full_atr).any():
                        results[po_key][f"full_atr_{h}d"] += 1

        # Print
        pct = lambda n, d: f"{n/d*100:.1f}%" if d > 0 else "n/a"

        print(f"{'='*90}")
        print(f"  {label} SWING GOLDEN GATE (Monthly ATR Levels)")
        print(f"{'='*90}")

        total = sum(v["total"] for v in results.values())
        print(f"\n  Total GG entries: {total}")

        print(f"\n  --- Baseline ---")
        print(f"  {'':>25s}", end="")
        for h in horizons:
            print(f" {h:>3d}d  ", end="")
        print()
        print(f"  {'GG completes (61.8%)':>25s}", end="")
        for h in horizons:
            n = sum(v[f"complete_{h}d"] for v in results.values())
            print(f" {pct(n, total):>6s}", end="")
        print()
        print(f"  {'Full ATR (100%)':>25s}", end="")
        for h in horizons:
            n = sum(v[f"full_atr_{h}d"] for v in results.values())
            print(f" {pct(n, total):>6s}", end="")
        print()

        print(f"\n  --- By Previous Week's PO ---")
        print(f"  {'PO State':>25s} {'N':>5s}", end="")
        for h in horizons:
            print(f" {h:>3d}d  ", end="")
        print()

        if direction == "bull":
            key_order = ["high|rising", "high|falling", "mid|rising", "mid|falling", "low|rising", "low|falling"]
        else:
            key_order = ["low|falling", "low|rising", "mid|falling", "mid|rising", "high|falling", "high|rising"]

        for pk in key_order:
            if pk not in results:
                continue
            v = results[pk]
            n = v["total"]
            if n < 15:
                continue
            z, s = pk.split("|")
            print(f"  {z} + {s:>25s} {n:5d}", end="")
            for h in horizons:
                print(f" {pct(v[f'complete_{h}d'], n):>6s}", end="")
            print()

        # Bilbo
        bilbo_key = "high|rising" if direction == "bull" else "low|falling"
        if bilbo_key in results and results[bilbo_key]["total"] >= 15:
            bv = results[bilbo_key]
            bn = bv["total"]
            print(f"\n  BILBO ({bilbo_key}): n={bn}")
            print(f"    GG:       ", end="")
            for h in horizons:
                print(f"{h}d={pct(bv[f'complete_{h}d'], bn)} ", end="")
            print()
            print(f"    Full ATR: ", end="")
            for h in horizons:
                print(f"{h}d={pct(bv[f'full_atr_{h}d'], bn)} ", end="")
            print()

        print()

    conn.close()


if __name__ == "__main__":
    main()
