"""
Price vs Daily 21 EMA: Maximum Historical Deviation

How far can SPY stretch from its daily 21 EMA? What are the extremes,
the distribution, and what happens after extreme deviations?

The 21 EMA is the pivot EMA in the Saty system — the core trend reference.
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_21, ema_8, ema_48, ema_200, "
        "atr_14, phase_oscillator, phase_zone, compression, atr_trend, candle_bias "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.dropna(subset=["ema_21"])
    df["date"] = df.index.date

    # Core metric: % deviation of close from 21 EMA
    df["dev_pct"] = (df["close"] - df["ema_21"]) / df["ema_21"] * 100

    # Also compute intraday extremes vs ema_21
    df["high_dev_pct"] = (df["high"] - df["ema_21"]) / df["ema_21"] * 100
    df["low_dev_pct"] = (df["low"] - df["ema_21"]) / df["ema_21"] * 100

    # Max intraday deviation (absolute furthest point from EMA21)
    df["max_intraday_dev"] = np.where(
        df["high_dev_pct"].abs() > df["low_dev_pct"].abs(),
        df["high_dev_pct"],
        df["low_dev_pct"]
    )

    n = len(df)
    print(f"Total daily bars with EMA21: {n:,}")
    print(f"Date range: {df.index[0].date()} to {df.index[-1].date()}\n")

    # ─────────────────────────────────────────────
    # SECTION 1: Absolute Extremes
    # ─────────────────────────────────────────────
    print("=" * 70)
    print("SECTION 1: ALL-TIME EXTREMES (Close vs Daily 21 EMA)")
    print("=" * 70)

    max_above = df["dev_pct"].max()
    max_below = df["dev_pct"].min()
    max_above_row = df.loc[df["dev_pct"].idxmax()]
    max_below_row = df.loc[df["dev_pct"].idxmin()]

    print(f"\n  Maximum ABOVE EMA21:  {max_above:+.2f}%")
    print(f"    Date:  {max_above_row.name.date()}")
    print(f"    Close: ${max_above_row['close']:.2f}  EMA21: ${max_above_row['ema_21']:.2f}")

    print(f"\n  Maximum BELOW EMA21:  {max_below:+.2f}%")
    print(f"    Date:  {max_below_row.name.date()}")
    print(f"    Close: ${max_below_row['close']:.2f}  EMA21: ${max_below_row['ema_21']:.2f}")

    # Intraday extremes (using high/low vs EMA21)
    max_high_dev = df["high_dev_pct"].max()
    max_low_dev = df["low_dev_pct"].min()
    max_high_row = df.loc[df["high_dev_pct"].idxmax()]
    max_low_row = df.loc[df["low_dev_pct"].idxmin()]

    print(f"\n  Max intraday HIGH above EMA21: {max_high_dev:+.2f}%")
    print(f"    Date: {max_high_row.name.date()}  High: ${max_high_row['high']:.2f}  EMA21: ${max_high_row['ema_21']:.2f}")

    print(f"\n  Max intraday LOW below EMA21:  {max_low_dev:+.2f}%")
    print(f"    Date: {max_low_row.name.date()}  Low: ${max_low_row['low']:.2f}  EMA21: ${max_low_row['ema_21']:.2f}")

    # ─────────────────────────────────────────────
    # SECTION 2: Distribution
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 2: DISTRIBUTION OF CLOSE vs EMA21 DEVIATION")
    print("=" * 70)

    dev = df["dev_pct"]
    print(f"\n  Mean:     {dev.mean():+.3f}%")
    print(f"  Median:   {dev.median():+.3f}%")
    print(f"  Std Dev:  {dev.std():.3f}%")
    print(f"  Skew:     {dev.skew():.3f}")
    print(f"  Kurtosis: {dev.kurtosis():.3f}")

    print(f"\n  Percentiles:")
    print(f"  {'Pctile':<10s} {'Value':>10s}")
    print("  " + "-" * 22)
    for p in [1, 2.5, 5, 10, 25, 50, 75, 90, 95, 97.5, 99]:
        v = np.percentile(dev, p)
        print(f"  {p:>5.1f}th    {v:+9.3f}%")

    # Bucket distribution
    print(f"\n  Distribution by bucket:")
    print(f"  {'Range':<20s} {'Count':>7s} {'%':>8s} {'Cum%':>8s}")
    print("  " + "-" * 45)
    buckets = [
        (-100, -15, "< -15%"),
        (-15, -10, "-15% to -10%"),
        (-10, -7, "-10% to -7%"),
        (-7, -5, "-7% to -5%"),
        (-5, -3, "-5% to -3%"),
        (-3, -2, "-3% to -2%"),
        (-2, -1, "-2% to -1%"),
        (-1, 0, "-1% to 0%"),
        (0, 1, "0% to +1%"),
        (1, 2, "+1% to +2%"),
        (2, 3, "+2% to +3%"),
        (3, 5, "+3% to +5%"),
        (5, 7, "+5% to +7%"),
        (7, 10, "+7% to +10%"),
        (10, 15, "+10% to +15%"),
        (15, 100, "> +15%"),
    ]
    cum = 0
    for lo, hi, label in buckets:
        count = ((dev >= lo) & (dev < hi)).sum()
        pct = count / n * 100
        cum += pct
        print(f"  {label:<20s} {count:7d} {pct:7.2f}% {cum:7.1f}%")

    # ─────────────────────────────────────────────
    # SECTION 3: Top 20 Extremes (each direction)
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 3: TOP 20 MOST EXTREME DEVIATIONS")
    print("=" * 70)

    print(f"\n  --- Most ABOVE EMA21 (close) ---")
    print(f"  {'#':>3s} {'Date':<12s} {'Dev%':>8s} {'Close':>8s} {'EMA21':>8s} {'PO':>8s} {'Zone':<14s}")
    print("  " + "-" * 66)
    top_above = df.nlargest(20, "dev_pct")
    for i, (ts, row) in enumerate(top_above.iterrows(), 1):
        print(f"  {i:3d} {ts.date()!s:<12s} {row['dev_pct']:+7.2f}% {row['close']:8.2f} {row['ema_21']:8.2f} "
              f"{row['phase_oscillator']:7.1f} {str(row['phase_zone']):<14s}")

    print(f"\n  --- Most BELOW EMA21 (close) ---")
    print(f"  {'#':>3s} {'Date':<12s} {'Dev%':>8s} {'Close':>8s} {'EMA21':>8s} {'PO':>8s} {'Zone':<14s}")
    print("  " + "-" * 66)
    top_below = df.nsmallest(20, "dev_pct")
    for i, (ts, row) in enumerate(top_below.iterrows(), 1):
        print(f"  {i:3d} {ts.date()!s:<12s} {row['dev_pct']:+7.2f}% {row['close']:8.2f} {row['ema_21']:8.2f} "
              f"{row['phase_oscillator']:7.1f} {str(row['phase_zone']):<14s}")

    # ─────────────────────────────────────────────
    # SECTION 4: Mean Reversion After Extreme Deviations
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 4: MEAN REVERSION — FORWARD RETURNS AFTER EXTREME DEVIATIONS")
    print("=" * 70)

    df["fwd_1d"] = df["close"].pct_change(1).shift(-1) * 100
    df["fwd_3d"] = df["close"].pct_change(3).shift(-3) * 100
    df["fwd_5d"] = df["close"].pct_change(5).shift(-5) * 100
    df["fwd_10d"] = df["close"].pct_change(10).shift(-10) * 100
    df["fwd_20d"] = df["close"].pct_change(20).shift(-20) * 100

    # How many days until deviation returns to within ±1%?
    dev_series = df["dev_pct"].values
    days_to_mean = []
    for i in range(len(df)):
        if abs(dev_series[i]) > 5:
            found = False
            for j in range(i + 1, min(i + 60, len(df))):
                if abs(dev_series[j]) <= 1:
                    days_to_mean.append((i, j - i))
                    found = True
                    break
            if not found:
                days_to_mean.append((i, np.nan))

    thresholds = [
        ("Dev > +7%", df["dev_pct"] > 7),
        ("Dev > +5%", df["dev_pct"] > 5),
        ("Dev > +3%", df["dev_pct"] > 3),
        ("Dev +1% to +3%", (df["dev_pct"] >= 1) & (df["dev_pct"] < 3)),
        ("Dev -1% to +1%", (df["dev_pct"] >= -1) & (df["dev_pct"] < 1)),
        ("Dev -3% to -1%", (df["dev_pct"] >= -3) & (df["dev_pct"] < -1)),
        ("Dev < -3%", df["dev_pct"] < -3),
        ("Dev < -5%", df["dev_pct"] < -5),
        ("Dev < -7%", df["dev_pct"] < -7),
    ]

    print(f"\n  {'Condition':<20s} {'n':>5s} {'1d':>8s} {'3d':>8s} {'5d':>8s} {'10d':>8s} {'20d':>8s}")
    print("  " + "-" * 60)
    for label, mask in thresholds:
        subset = df[mask]
        sn = len(subset)
        if sn < 10:
            flag = " *"
        else:
            flag = ""
        f1 = subset["fwd_1d"].dropna().mean()
        f3 = subset["fwd_3d"].dropna().mean()
        f5 = subset["fwd_5d"].dropna().mean()
        f10 = subset["fwd_10d"].dropna().mean()
        f20 = subset["fwd_20d"].dropna().mean()
        print(f"  {label:<20s} {sn:5d} {f1:+7.3f}% {f3:+7.3f}% {f5:+7.3f}% {f10:+7.3f}% {f20:+7.3f}%{flag}")

    # Green candle % after extremes
    df["next_green"] = (df["close"].shift(-1) > df["open"].shift(-1)).astype(float)
    print(f"\n  Next-day green candle %:")
    for label, mask in thresholds:
        subset = df[mask]
        if len(subset) < 10:
            continue
        g = subset["next_green"].dropna().mean() * 100
        print(f"    {label:<20s} {g:.1f}% green  (n={len(subset)})")

    # ─────────────────────────────────────────────
    # SECTION 5: By Era / Decade
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 5: DEVIATION STATS BY ERA")
    print("=" * 70)

    df["year"] = df.index.year
    eras = [
        ("2000-2002 (Dot-com bust)", (2000, 2002)),
        ("2003-2007 (Bull run)", (2003, 2007)),
        ("2008-2009 (GFC)", (2008, 2009)),
        ("2010-2019 (Long bull)", (2010, 2019)),
        ("2020 (COVID)", (2020, 2020)),
        ("2021-2022 (Post-COVID)", (2021, 2022)),
        ("2023-2025 (AI bull)", (2023, 2025)),
    ]

    print(f"\n  {'Era':<30s} {'n':>6s} {'Mean':>8s} {'Std':>8s} {'Min':>9s} {'Max':>9s} {'P5':>8s} {'P95':>8s}")
    print("  " + "-" * 90)
    for label, (y1, y2) in eras:
        era = df[(df["year"] >= y1) & (df["year"] <= y2)]["dev_pct"]
        if len(era) == 0:
            continue
        print(f"  {label:<30s} {len(era):6d} {era.mean():+7.3f}% {era.std():7.3f}% "
              f"{era.min():+8.2f}% {era.max():+8.2f}% {era.quantile(0.05):+7.2f}% {era.quantile(0.95):+7.2f}%")

    # ─────────────────────────────────────────────
    # SECTION 6: Relationship to Phase Oscillator
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 6: DEVIATION vs PHASE OSCILLATOR CORRELATION")
    print("=" * 70)

    valid = df.dropna(subset=["phase_oscillator", "dev_pct"])
    corr = valid["dev_pct"].corr(valid["phase_oscillator"])
    print(f"\n  Pearson correlation (dev% vs PO): {corr:.4f}")

    # PO zone vs deviation stats
    print(f"\n  {'PO Zone':<18s} {'n':>6s} {'Mean Dev%':>10s} {'Median':>10s} {'Min':>10s} {'Max':>10s}")
    print("  " + "-" * 66)
    for zone in ["extended_up", "distribution", "neutral_up", "neutral",
                  "neutral_down", "accumulation", "extended_down"]:
        z = valid[valid["phase_zone"] == zone]["dev_pct"]
        if len(z) == 0:
            continue
        print(f"  {zone:<18s} {len(z):6d} {z.mean():+9.3f}% {z.median():+9.3f}% "
              f"{z.min():+9.2f}% {z.max():+9.2f}%")

    # ─────────────────────────────────────────────
    # SECTION 7: Consecutive Days Beyond Thresholds
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 7: LONGEST STREAKS BEYOND THRESHOLDS")
    print("=" * 70)

    for threshold_label, condition in [
        ("> +3% above EMA21", df["dev_pct"] > 3),
        ("> +5% above EMA21", df["dev_pct"] > 5),
        ("< -3% below EMA21", df["dev_pct"] < -3),
        ("< -5% below EMA21", df["dev_pct"] < -5),
    ]:
        # Find longest consecutive streak
        streaks = []
        current = 0
        start_idx = None
        for i in range(len(df)):
            if condition.iloc[i]:
                if current == 0:
                    start_idx = i
                current += 1
            else:
                if current > 0:
                    streaks.append((current, df.index[start_idx].date(), df.index[i - 1].date()))
                current = 0
        if current > 0:
            streaks.append((current, df.index[start_idx].date(), df.index[-1].date()))

        streaks.sort(reverse=True)
        total_days = condition.sum()
        print(f"\n  {threshold_label}: {total_days} total days ({total_days/n*100:.1f}%)")
        if streaks:
            print(f"    Longest streaks:")
            for length, start, end in streaks[:5]:
                print(f"      {length:3d} days: {start} → {end}")

    conn.close()
    print(f"\n{'=' * 70}")
    print("STUDY COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
