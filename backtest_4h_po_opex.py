"""
4H PO Rollover + Monthly OpEx Study

Does the timing relative to monthly OpEx (3rd Friday) affect drop probability?

Hypotheses:
  H1: Pin risk suppresses drops during OpEx week
  H2: Post-OpEx week (Mon-Fri after) sees cleaner directional moves
  H3: Pre-OpEx (week before) has muted volatility too

Buckets:
  - OpEx week Mon-Thu
  - OpEx Friday itself
  - Week AFTER OpEx (Mon-Fri)
  - 2 weeks after OpEx
  - Week BEFORE OpEx
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def third_friday(year, month):
    """Return the date of the 3rd Friday of given year/month."""
    d = pd.Timestamp(year=year, month=month, day=1)
    # Day of week for 1st: 0=Mon, 4=Fri
    first_fri_offset = (4 - d.dayofweek) % 7
    first_friday = d + pd.Timedelta(days=first_fri_offset)
    third_fri = first_friday + pd.Timedelta(days=14)
    return third_fri.normalize()


def opex_context(date):
    """Classify a date relative to nearest monthly OpEx.
    Returns (bucket_name, days_to_opex).
    Negative days = before OpEx, 0 = OpEx, positive = after."""
    year, month = date.year, date.month
    this_opex = third_friday(year, month)
    # Also check prev and next month opex
    prev_opex = third_friday(year - (1 if month == 1 else 0),
                             12 if month == 1 else month - 1)
    next_opex = third_friday(year + (1 if month == 12 else 0),
                             1 if month == 12 else month + 1)

    # Find nearest OpEx
    candidates = [prev_opex, this_opex, next_opex]
    diffs = [(d - date).days for d in candidates]
    nearest_idx = min(range(3), key=lambda i: abs(diffs[i]))
    nearest_opex = candidates[nearest_idx]
    days_to = (nearest_opex - date).days  # negative = before, positive = after, 0 = opex day

    # Bucket
    if days_to == 0:
        bucket = "OpEx Friday"
    elif 1 <= days_to <= 4:
        bucket = "OpEx Week Mon-Thu"  # days 1-4 before = Mon-Thu of opex week
    elif 5 <= days_to <= 11:
        bucket = "Week Before OpEx"
    elif -4 <= days_to <= -1:
        bucket = "Post-OpEx Week (Mon-Thu after)"
    elif -7 <= days_to <= -5:
        bucket = "Post-OpEx Fri + Weekend"  # rarely hit by trading day
    elif -11 <= days_to <= -5:
        bucket = "Week After OpEx"
    elif -18 <= days_to <= -12:
        bucket = "2 Weeks After OpEx"
    else:
        bucket = "Far From OpEx"

    return bucket, days_to


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Loading data...")
    df4h = pd.read_sql_query(
        "SELECT timestamp, close, phase_oscillator FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp").dropna(subset=["phase_oscillator"])

    df1d = pd.read_sql_query(
        "SELECT timestamp, high, low, close FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")
    conn.close()

    # ─── Find V2 signals (peak ≥80, cross below 80) ───
    po = df4h["phase_oscillator"]
    was_above = False
    peak = 0
    signals = []
    for i in range(1, len(df4h)):
        cur = po.iloc[i]
        prev = po.iloc[i - 1]
        if prev >= 80:
            if not was_above:
                was_above = True
                peak = prev
            elif prev > peak:
                peak = prev
        if was_above and prev >= 80 and cur < 80:
            signals.append({
                "signal_time": df4h.index[i],
                "peak_po": peak,
                "signal_close": df4h.iloc[i]["close"],
            })
            was_above = False
            peak = 0

    print(f"V2 signals: {len(signals)}")

    # ─── Build results with OpEx context ───
    results = []
    df1d_sorted = df1d.sort_index()
    for sig in signals:
        sig_date = sig["signal_time"].normalize()
        sig_close = sig["signal_close"]

        dloc = df1d_sorted.index.searchsorted(sig_date)
        if dloc >= len(df1d_sorted):
            continue
        if df1d_sorted.index[dloc] < sig_date:
            dloc += 1
        if dloc >= len(df1d_sorted):
            continue

        # OpEx bucket
        bucket, days_to = opex_context(sig_date)

        # Forward drops
        row = {
            "signal_date": sig_date,
            "peak_po": sig["peak_po"],
            "opex_bucket": bucket,
            "days_to_opex": days_to,
            "day_of_week": sig_date.dayofweek,
        }
        for h in [3, 5, 10]:
            end = min(dloc + h + 1, len(df1d_sorted))
            fut = df1d_sorted.iloc[dloc + 1:end]
            if len(fut) == 0:
                continue
            min_low = fut["low"].min()
            row[f"max_drop_{h}d"] = (min_low - sig_close) / sig_close * 100
            for thr, key in [(0.5, "05"), (1.0, "10"), (1.5, "15"), (2.0, "20")]:
                row[f"hit_{key}_{h}d"] = (fut["low"] <= sig_close * (1 - thr/100)).any()

        results.append(row)

    rdf = pd.DataFrame(results).dropna(subset=["max_drop_5d"])
    n_total = len(rdf)
    baseline_10 = rdf["hit_10_5d"].mean() * 100
    baseline_15 = rdf["hit_15_5d"].mean() * 100
    print(f"\nValid events: {n_total}")
    print(f"Baseline ≥1.0% 5d: {baseline_10:.1f}%")
    print(f"Baseline ≥1.5% 5d: {baseline_15:.1f}%")

    # ─── Report by OpEx bucket ───
    print(f"\n{'═' * 75}")
    print(f"  OpEx BUCKET (5d window)")
    print(f"{'═' * 75}")
    print(f"  {'Bucket':<35s} {'N':>4s} {'≥0.5%':>7s} {'≥1.0%':>7s} {'≥1.5%':>7s} {'Med5d':>8s}")

    buckets_order = [
        "Week Before OpEx",
        "OpEx Week Mon-Thu",
        "OpEx Friday",
        "Post-OpEx Week (Mon-Thu after)",
        "Week After OpEx",
        "2 Weeks After OpEx",
    ]
    for b in buckets_order:
        s = rdf[rdf["opex_bucket"] == b]
        n = len(s)
        if n < 3:
            print(f"  {b:<35s} {n:>4d}   (too small)")
            continue
        h05 = s["hit_05_5d"].mean() * 100
        h10 = s["hit_10_5d"].mean() * 100
        h15 = s["hit_15_5d"].mean() * 100
        med = s["max_drop_5d"].median()
        tag = ""
        if abs(h10 - baseline_10) >= 10:
            tag = " ←"
        print(f"  {b:<35s} {n:>4d} {h05:>6.0f}% {h10:>6.0f}% {h15:>6.0f}% {med:>7.2f}%{tag}")

    # ─── Granular: by days to OpEx ───
    print(f"\n{'═' * 75}")
    print(f"  DAYS TO NEAREST OpEx (negative = after, positive = before)")
    print(f"{'═' * 75}")
    print(f"  {'Day':<15s} {'N':>4s} {'≥0.5%':>7s} {'≥1.0%':>7s} {'≥1.5%':>7s} {'Med5d':>8s}")

    for d in sorted(rdf["days_to_opex"].unique()):
        s = rdf[rdf["days_to_opex"] == d]
        n = len(s)
        if n < 3:
            continue
        h05 = s["hit_05_5d"].mean() * 100
        h10 = s["hit_10_5d"].mean() * 100
        h15 = s["hit_15_5d"].mean() * 100
        med = s["max_drop_5d"].median()
        tag = " ←" if abs(h10 - baseline_10) >= 15 else ""
        label = f"{int(d)}d {'before' if d > 0 else ('after' if d < 0 else 'OpEx')}"
        print(f"  {label:<15s} {n:>4d} {h05:>6.0f}% {h10:>6.0f}% {h15:>6.0f}% {med:>7.2f}%{tag}")

    # ─── 10d window (covers post-opex week) ───
    print(f"\n{'═' * 75}")
    print(f"  OpEx BUCKET (10d window — captures post-OpEx releases)")
    print(f"{'═' * 75}")
    print(f"  {'Bucket':<35s} {'N':>4s} {'≥1.0%':>7s} {'≥1.5%':>7s} {'≥2.0%':>7s} {'Med10d':>8s}")

    for b in buckets_order:
        s = rdf[rdf["opex_bucket"] == b]
        n = len(s)
        if n < 3:
            continue
        h10 = s["hit_10_10d"].mean() * 100
        h15 = s["hit_15_10d"].mean() * 100
        h20 = s["hit_20_10d"].mean() * 100
        med = s["max_drop_10d"].median()
        print(f"  {b:<35s} {n:>4d} {h10:>6.0f}% {h15:>6.0f}% {h20:>6.0f}% {med:>7.2f}%")

    # ─── Combined: OpEx Fri signal, forward 10d ───
    print(f"\n{'═' * 75}")
    print(f"  SIGNAL FIRES ON OpEx FRIDAY → FORWARD 10d")
    print(f"{'═' * 75}")
    opex_fri = rdf[rdf["opex_bucket"] == "OpEx Friday"]
    print(f"\n  N = {len(opex_fri)}")
    if len(opex_fri) >= 3:
        print(f"  ≥0.5% in 10d: {opex_fri['hit_05_10d'].mean()*100:.0f}%")
        print(f"  ≥1.0% in 10d: {opex_fri['hit_10_10d'].mean()*100:.0f}%")
        print(f"  ≥1.5% in 10d: {opex_fri['hit_15_10d'].mean()*100:.0f}%")
        print(f"  ≥2.0% in 10d: {opex_fri['hit_20_10d'].mean()*100:.0f}%")
        print(f"  Median 10d max drop: {opex_fri['max_drop_10d'].median():.2f}%")
        print(f"\n  Individual events:")
        print(f"  {'Date':<12s} {'PkPO':>6s} {'Drop5d':>8s} {'Drop10d':>8s}")
        for _, r in opex_fri.iterrows():
            d = str(r["signal_date"])[:10]
            pk = f"{r['peak_po']:.0f}"
            d5 = f"{r['max_drop_5d']:.2f}" if pd.notna(r["max_drop_5d"]) else "—"
            d10 = f"{r['max_drop_10d']:.2f}" if pd.notna(r["max_drop_10d"]) else "—"
            print(f"  {d:<12s} {pk:>6s} {d5:>8s} {d10:>8s}")


if __name__ == "__main__":
    main()
