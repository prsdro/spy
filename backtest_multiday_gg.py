"""
Multi-Day Golden Gate Study (Multiday Mode)

Uses WEEKLY ATR and previous week's close to define levels.
Tracks GG (38.2% → 61.8% of weekly ATR) completion over 1-5 trading days.
Conditions on DAILY Phase Oscillator state at GG entry.
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load weekly indicator data for ATR levels
    print("Loading weekly data...", flush=True)
    weekly = pd.read_sql_query(
        "SELECT timestamp, close, atr_14, prev_close, "
        "atr_upper_0382, atr_lower_0382, atr_upper_0618, atr_lower_0618, "
        "atr_upper_100, atr_lower_100, atr_upper_trigger, atr_lower_trigger "
        "FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    weekly = weekly.set_index("timestamp").sort_index()
    weekly = weekly.dropna(subset=["prev_close", "atr_14"])

    # Load daily data for price action and PO
    print("Loading daily data...", flush=True)
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "phase_oscillator, compression "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()
    # IMPORTANT: Use PREVIOUS day's PO to avoid look-ahead bias
    # The daily PO is computed at close, so same-day PO includes the move itself
    daily["po_yesterday"] = daily["phase_oscillator"].shift(1)
    daily["po_day_before"] = daily["phase_oscillator"].shift(2)

    # Map each daily bar to its week's ATR levels
    # Each week's levels apply Mon-Fri of that week
    print("Mapping weekly levels to daily bars...", flush=True)
    daily_reset = daily.reset_index()
    weekly_reset = weekly.reset_index()
    merged = pd.merge_asof(
        daily_reset[["timestamp"]],
        weekly_reset,
        on="timestamp",
        direction="backward",
        suffixes=("", "_wk")
    )
    for col in ["prev_close", "atr_14", "atr_upper_0382", "atr_lower_0382",
                "atr_upper_0618", "atr_lower_0618", "atr_upper_100", "atr_lower_100",
                "atr_upper_trigger", "atr_lower_trigger"]:
        daily[f"wk_{col}"] = merged[col].values

    dates = daily.index.tolist()
    n_days = len(dates)

    def classify_po(po, po_prev):
        """Classify PO. po = yesterday's PO, po_prev = day before yesterday."""
        if pd.isna(po) or pd.isna(po_prev):
            return None, None
        zone = "high" if po > 61.8 else ("low" if po < -61.8 else "mid")
        slope = "rising" if po > po_prev else "falling"
        return zone, slope

    print("Computing multi-day GG stats...\n")

    horizons = [1, 2, 3, 4, 5]

    for direction, label in [("bull", "BULLISH"), ("bear", "BEARISH")]:
        # Track: day GG entry occurs -> completion within N days
        # Also track by daily PO state
        results = {}  # po_key -> {total, completions_by_day, continuation}

        for i in range(n_days):
            row = daily.iloc[i]
            if direction == "bull":
                entry_level = row.get("wk_atr_upper_0382")
                exit_level = row.get("wk_atr_upper_0618")
                full_atr = row.get("wk_atr_upper_100")
            else:
                entry_level = row.get("wk_atr_lower_0382")
                exit_level = row.get("wk_atr_lower_0618")
                full_atr = row.get("wk_atr_lower_100")

            if pd.isna(entry_level) or pd.isna(exit_level):
                continue

            # Check if this day hits the weekly 38.2% level (GG entry)
            if direction == "bull":
                entry_hit = row["high"] >= entry_level
            else:
                entry_hit = row["low"] <= entry_level

            if not entry_hit:
                continue

            # Check if previous day already hit it (avoid double-counting)
            if i > 0:
                prev_row = daily.iloc[i - 1]
                if direction == "bull":
                    already_hit = prev_row["high"] >= entry_level
                else:
                    already_hit = prev_row["low"] <= entry_level
                # Only count first day the level is hit this week
                # Check if same week
                same_week = (dates[i].isocalendar()[1] == dates[i-1].isocalendar()[1] and
                             dates[i].year == dates[i-1].year)
                if same_week and already_hit:
                    continue

            # PO state BEFORE the entry day (yesterday's close PO)
            # Avoids look-ahead bias: can't use today's PO since it includes today's move
            zone, slope = classify_po(row["po_yesterday"], row["po_day_before"])
            if zone is None:
                continue

            po_key = f"{zone}|{slope}"

            if po_key not in results:
                results[po_key] = {"total": 0}
                for h in horizons:
                    results[po_key][f"complete_{h}d"] = 0
                    results[po_key][f"full_atr_{h}d"] = 0

            results[po_key]["total"] += 1

            # Check completion over next N days
            for h in horizons:
                end_idx = min(i + h, n_days - 1)
                future_slice = daily.iloc[i:end_idx + 1]

                if direction == "bull":
                    if (future_slice["high"] >= exit_level).any():
                        results[po_key][f"complete_{h}d"] += 1
                    if (future_slice["high"] >= full_atr).any():
                        results[po_key][f"full_atr_{h}d"] += 1
                else:
                    if (future_slice["low"] <= exit_level).any():
                        results[po_key][f"complete_{h}d"] += 1
                    if (future_slice["low"] <= full_atr).any():
                        results[po_key][f"full_atr_{h}d"] += 1

        # Print results
        pct = lambda n, d: f"{n/d*100:.1f}%" if d > 0 else "n/a"

        print(f"{'='*80}")
        print(f"  {label} MULTI-DAY GOLDEN GATE (Weekly ATR Levels)")
        print(f"{'='*80}")

        # Baseline (all PO states combined)
        total = sum(v["total"] for v in results.values())
        print(f"\n  Total GG entries: {total}")
        print(f"\n  --- Baseline (all daily PO states) ---")
        print(f"  {'':>25s}", end="")
        for h in horizons:
            print(f" {h}d", end="     ")
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

        # By PO state
        print(f"\n  --- By Daily PO State ---")
        print(f"  {'PO State':>25s} {'N':>5s}", end="")
        for h in horizons:
            print(f"  {h}d", end="   ")
        print()
        print(f"  {'-'*70}")

        # Sort by alignment: best first
        if direction == "bull":
            key_order = ["high|rising", "high|falling", "mid|rising", "mid|falling", "low|rising", "low|falling"]
        else:
            key_order = ["low|falling", "low|rising", "mid|falling", "mid|rising", "high|falling", "high|rising"]

        for pk in key_order:
            if pk not in results:
                continue
            v = results[pk]
            n = v["total"]
            if n < 20:
                continue
            z, s = pk.split("|")
            label_str = f"{z} + {s}"
            print(f"  {label_str:>25s} {n:5d}", end="")
            for h in horizons:
                print(f" {pct(v[f'complete_{h}d'], n):>6s}", end="")
            print()

        # Bilbo summary
        if direction == "bull":
            bilbo_key = "high|rising"
            counter_key = "mid|falling"
        else:
            bilbo_key = "low|falling"
            counter_key = "mid|rising"

        if bilbo_key in results and results[bilbo_key]["total"] >= 20:
            bv = results[bilbo_key]
            bn = bv["total"]
            print(f"\n  BILBO ({bilbo_key}): n={bn}")
            print(f"    GG completion by day: ", end="")
            for h in horizons:
                print(f"{h}d={pct(bv[f'complete_{h}d'], bn)} ", end="")
            print()
            print(f"    Full ATR by day:      ", end="")
            for h in horizons:
                print(f"{h}d={pct(bv[f'full_atr_{h}d'], bn)} ", end="")
            print()

        print()

    conn.close()


if __name__ == "__main__":
    main()
