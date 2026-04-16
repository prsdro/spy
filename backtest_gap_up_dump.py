"""
Quick study: Gap up >= 0.2%, price hits +1% from open, then retraces >= 0.5%
in the afternoon. When does the dump start?
"""

import sqlite3
import pandas as pd
import numpy as np
import datetime

DB_PATH = "/root/spy/spy.db"

def main():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query("SELECT * FROM ind_10m ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date
    df["time"] = df.index.time

    print(f"Loaded {len(df):,} bars, {df['date'].nunique():,} days\n")

    events = []

    for date, group in df.groupby("date"):
        if len(group) < 10:
            continue

        first = group.iloc[0]
        prev_close = first["prev_close"]
        day_open = first["open"]
        if pd.isna(prev_close) or prev_close == 0:
            continue

        gap_pct = (day_open - prev_close) / prev_close * 100
        if gap_pct < 0.2:
            continue

        # Did price hit +1% from open?
        target_1pct = day_open * 1.01
        hit_1pct = group[group["high"] >= target_1pct]
        if len(hit_1pct) == 0:
            continue

        hit_1pct_time = hit_1pct.index[0]
        hit_1pct_idx = group.index.get_loc(hit_1pct_time)

        # Track running high bar-by-bar after hitting 1%
        # Find the day high and its time
        day_high = group["high"].max()
        day_high_time = group["high"].idxmax()
        day_high_idx = group.index.get_loc(day_high_time)

        # After the day high, find the lowest point
        after_high = group.iloc[day_high_idx:]
        if len(after_high) < 2:
            continue

        post_high_low = after_high["low"].min()
        retracement = (day_high - post_high_low) / day_open * 100  # as % of open

        # Require at least 0.5% retracement from the high
        if retracement < 0.5:
            continue

        # Require the dump to happen in the afternoon (high after 11am or dump after 12pm)
        post_high_low_time = after_high["low"].idxmin()
        if post_high_low_time.hour < 12:
            continue

        # When does the dump START?
        # Walk forward from the day high — find the first bar where price starts declining
        # Define: first bar after the high where close < high's close, sustained for 2+ bars
        high_close = group.loc[day_high_time, "close"]

        # More precisely: find the bar where the running max stops growing
        # and price drops 0.1% from that running max
        dump_start = None
        dump_start_time = None
        running_max = -np.inf
        threshold = day_open * 0.001  # 0.1% of open = small move confirming direction

        for i in range(hit_1pct_idx, len(group)):
            bar = group.iloc[i]
            if bar["high"] > running_max:
                running_max = bar["high"]
                peak_idx = i
            elif running_max - bar["close"] >= day_open * 0.005:  # 0.5% below running max
                dump_start = peak_idx
                dump_start_time = group.index[peak_idx]
                break

        if dump_start is None:
            continue

        dump_bar = group.iloc[dump_start]
        dump_time = dump_start_time.time()
        dump_hour = dump_start_time.hour
        dump_half = f"{dump_hour:02d}:{0 if dump_start_time.minute < 30 else 30:02d}"

        # How far did price fall from the dump start?
        after_dump = group.iloc[dump_start:]
        dump_low = after_dump["low"].min()
        dump_magnitude = (dump_bar["high"] - dump_low) / day_open * 100
        close_price = group.iloc[-1]["close"]
        close_from_dump = (close_price - dump_bar["high"]) / day_open * 100

        # PO at dump start
        po_at_dump = dump_bar.get("phase_oscillator", np.nan)

        events.append({
            "date": date,
            "gap_pct": gap_pct,
            "day_high_pct": (day_high - day_open) / day_open * 100,
            "day_high_time": day_high_time.time(),
            "dump_start_time": dump_time,
            "dump_half": dump_half,
            "dump_hour": dump_hour,
            "retracement_pct": retracement,
            "dump_magnitude": dump_magnitude,
            "close_from_dump": close_from_dump,
            "close_from_open": (close_price - day_open) / day_open * 100,
            "po_at_dump": po_at_dump,
            "high_atr_pct": (day_high - prev_close) / first["atr_14"] * 100 if first["atr_14"] > 0 else np.nan,
        })

    edf = pd.DataFrame(events)
    n = len(edf)

    print("=" * 65)
    print(f"GAP UP >= 0.2%, HIT +1%, AFTERNOON RETRACEMENT >= 0.5%")
    print("=" * 65)
    print(f"\nQualifying days: {n}")
    print(f"Gap size: mean={edf['gap_pct'].mean():.2f}%, median={edf['gap_pct'].median():.2f}%")
    print(f"Day high from open: mean={edf['day_high_pct'].mean():.2f}%, median={edf['day_high_pct'].median():.2f}%")

    # ── CORE: When does the dump start? ──
    print(f"\n{'─' * 55}")
    print("WHEN DOES THE DUMP START?")
    print(f"{'─' * 55}")

    print(f"\n  By half-hour:")
    print(f"  {'Time':>7s} {'n':>5s} {'%':>7s} {'Avg Drop':>10s} {'Avg Close':>11s}")
    for half in sorted(edf["dump_half"].unique()):
        sub = edf[edf["dump_half"] == half]
        ns = len(sub)
        if ns < 3:
            continue
        avg_mag = sub["dump_magnitude"].mean()
        avg_close = sub["close_from_dump"].mean()
        bar = "█" * int(ns / n * 60)
        print(f"  {half:>7s} {ns:5d} {ns/n*100:6.1f}% {avg_mag:+9.2f}% {avg_close:+10.2f}%  {bar}")

    print(f"\n  By hour:")
    print(f"  {'Hour':>6s} {'n':>5s} {'%':>7s} {'Cum%':>7s} {'Avg Magnitude':>14s}")
    cum = 0
    for hour in range(9, 16):
        sub = edf[edf["dump_hour"] == hour]
        ns = len(sub)
        if ns == 0:
            continue
        cum += ns
        avg_mag = sub["dump_magnitude"].mean()
        print(f"  {hour:02d}:00 {ns:5d} {ns/n*100:6.1f}% {cum/n*100:6.1f}% {avg_mag:9.2f}%")

    # ── Stats on the dump itself ──
    print(f"\n{'─' * 55}")
    print("DUMP CHARACTERISTICS")
    print(f"{'─' * 55}")
    print(f"  Magnitude (high to post-dump low):")
    print(f"    Mean:   {edf['dump_magnitude'].mean():.2f}%")
    print(f"    Median: {edf['dump_magnitude'].median():.2f}%")
    print(f"    75th:   {edf['dump_magnitude'].quantile(0.75):.2f}%")
    print(f"    90th:   {edf['dump_magnitude'].quantile(0.90):.2f}%")

    print(f"\n  Close relative to dump high:")
    print(f"    Mean:   {edf['close_from_dump'].mean():+.2f}%")
    print(f"    Median: {edf['close_from_dump'].median():+.2f}%")

    print(f"\n  Full day return (open to close):")
    print(f"    Mean:   {edf['close_from_open'].mean():+.2f}%")
    print(f"    Median: {edf['close_from_open'].median():+.2f}%")
    pos = (edf["close_from_open"] > 0).sum()
    print(f"    Green:  {pos}/{n} ({pos/n*100:.1f}%)")

    # ── PO at dump start ──
    print(f"\n{'─' * 55}")
    print("PO AT DUMP START")
    print(f"{'─' * 55}")
    po_valid = edf.dropna(subset=["po_at_dump"])
    print(f"  Mean:   {po_valid['po_at_dump'].mean():.1f}")
    print(f"  Median: {po_valid['po_at_dump'].median():.1f}")

    po_bins = [(50, 999, "PO >= 50"), (0, 50, "PO 0-50"), (-50, 0, "PO -50 to 0"), (-999, -50, "PO < -50")]
    for lo, hi, label in po_bins:
        sub = po_valid[(po_valid["po_at_dump"] >= lo) & (po_valid["po_at_dump"] < hi)]
        if len(sub) >= 10:
            print(f"  {label:>14s}: n={len(sub):4d}, avg magnitude={sub['dump_magnitude'].mean():.2f}%, "
                  f"avg close from dump={sub['close_from_dump'].mean():+.2f}%")

    # ── By gap size ──
    print(f"\n{'─' * 55}")
    print("BY GAP SIZE")
    print(f"{'─' * 55}")
    gap_bins = [(0.2, 0.5, "0.2-0.5%"), (0.5, 1.0, "0.5-1.0%"), (1.0, 2.0, "1.0-2.0%"), (2.0, 99, "2.0%+")]
    for lo, hi, label in gap_bins:
        sub = edf[(edf["gap_pct"] >= lo) & (edf["gap_pct"] < hi)]
        if len(sub) < 10:
            continue
        median_dump_time = sub["dump_hour"].median()
        # Most common dump half
        mode_half = sub["dump_half"].mode().iloc[0] if len(sub) > 0 else "?"
        print(f"  Gap {label:>8s}: n={len(sub):4d}, most common dump={mode_half}, "
              f"avg magnitude={sub['dump_magnitude'].mean():.2f}%, "
              f"avg close={sub['close_from_open'].mean():+.2f}%")

    # ── By ATR position at high ──
    print(f"\n{'─' * 55}")
    print("BY ATR POSITION AT DAY HIGH")
    print(f"{'─' * 55}")
    atr_bins = [(0, 60, "< 60% ATR"), (60, 80, "60-80%"), (80, 100, "80-100%"),
                (100, 130, "100-130%"), (130, 999, "> 130%")]
    for lo, hi, label in atr_bins:
        sub = edf[(edf["high_atr_pct"] >= lo) & (edf["high_atr_pct"] < hi)]
        if len(sub) < 10:
            continue
        mode_half = sub["dump_half"].mode().iloc[0] if len(sub) > 0 else "?"
        print(f"  {label:>12s}: n={len(sub):4d}, most common dump={mode_half}, "
              f"avg dump magnitude={sub['dump_magnitude'].mean():.2f}%, "
              f"avg close={sub['close_from_open'].mean():+.2f}%")

    # ── Sample recent days ──
    print(f"\n{'─' * 55}")
    print("SAMPLE RECENT DAYS")
    print(f"{'─' * 55}")
    print(f"  {'Date':>12s} {'Gap':>6s} {'High':>6s} {'Dump@':>7s} {'Drop':>7s} {'Close':>7s} {'PO':>6s}")
    for _, row in edf.tail(20).iterrows():
        dt = f"{row['dump_start_time'].hour:02d}:{row['dump_start_time'].minute:02d}"
        print(f"  {str(row['date']):>12s} {row['gap_pct']:+5.1f}% {row['day_high_pct']:+5.1f}% "
              f"{dt:>7s} {row['dump_magnitude']:6.2f}% {row['close_from_open']:+6.2f}% "
              f"{row['po_at_dump']:5.0f}")

    conn.close()
    print(f"\n✓ Done. {n} qualifying days.")


if __name__ == "__main__":
    main()
