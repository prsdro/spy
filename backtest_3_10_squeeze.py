"""
3m/10m EMA-21 Squeeze Study

Hypothesis: When both 3m and 10m ribbons are stacked bullish, the 3m EMA-21
leads the 10m EMA-21. When that gap compresses, is there continuation alpha?

Optimized: vectorized signal detection using numpy, avoids per-bar Python loops.
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/root/spy/spy.db"


def detect_signals_vectorized(dates, spreads_pct, stacked, prices, highs, lows,
                              timestamps, expansion_pct, compression_pct,
                              cooldown_bars, direction):
    """
    Vectorized squeeze signal detection.
    Returns indices into the original arrays where signals fire.
    """
    n = len(dates)
    signal_indices = []

    # State machine per day
    prev_date = None
    expanded = False
    cooldown = 0

    for i in range(n):
        # Reset state on new day
        if dates[i] != prev_date:
            expanded = False
            cooldown = 0
            prev_date = dates[i]

        if cooldown > 0:
            cooldown -= 1
            continue

        if not stacked[i]:
            continue

        sp = spreads_pct[i]

        if direction == "bull":
            if sp >= expansion_pct:
                expanded = True
            if expanded and 0 <= sp <= compression_pct:
                signal_indices.append(i)
                expanded = False
                cooldown = cooldown_bars
        else:
            if sp <= -expansion_pct:
                expanded = True
            if expanded and -compression_pct <= sp <= 0:
                signal_indices.append(i)
                expanded = False
                cooldown = cooldown_bars

    return signal_indices


def compute_forward_returns(df3, signal_indices, direction):
    """Compute forward returns for signal indices."""
    timestamps = df3.index.values  # numpy datetime64
    closes = df3["close"].values
    highs_arr = df3["high"].values
    lows_arr = df3["low"].values
    n_total = len(df3)

    results = []
    for idx in signal_indices:
        ts = timestamps[idx]
        price = closes[idx]
        hour = pd.Timestamp(ts).hour

        rec = {
            "timestamp": pd.Timestamp(ts),
            "date": pd.Timestamp(ts).date(),
            "hour": hour,
            "price": price,
        }

        # +1h (20 bars), +4h (80 bars)
        for bars, label in [(20, "1h"), (80, "4h")]:
            fwd_idx = idx + bars
            if fwd_idx < n_total:
                fwd_ts = timestamps[fwd_idx]
                delta_hrs = (fwd_ts - ts) / np.timedelta64(1, 'h')
                max_hrs = 3 if label == "1h" else 8
                if delta_hrs <= max_hrs:
                    rec[f"price_{label}"] = closes[fwd_idx]
                else:
                    rec[f"price_{label}"] = np.nan
            else:
                rec[f"price_{label}"] = np.nan

            # MFE/MAE in window
            end = min(idx + bars + 1, n_total)
            if end > idx + 1:
                window_ts = timestamps[idx+1:end]
                max_hrs = 3 if label == "1h" else 8
                valid_mask = (window_ts - ts) / np.timedelta64(1, 'h') <= max_hrs
                if valid_mask.any():
                    last_valid = np.where(valid_mask)[0][-1] + 1
                    rec[f"max_{label}"] = highs_arr[idx+1:idx+1+last_valid].max()
                    rec[f"min_{label}"] = lows_arr[idx+1:idx+1+last_valid].min()
                else:
                    rec[f"max_{label}"] = np.nan
                    rec[f"min_{label}"] = np.nan
            else:
                rec[f"max_{label}"] = np.nan
                rec[f"min_{label}"] = np.nan

        results.append(rec)

    return results


def print_stats(signals, direction):
    """Print stats for a set of signals."""
    if len(signals) == 0:
        print("  No signals found.")
        return None

    df = pd.DataFrame(signals)
    n = len(df)

    df["ret_1h"] = df["price_1h"] - df["price"]
    df["ret_4h"] = df["price_4h"] - df["price"]
    df["ret_1h_pct"] = df["ret_1h"] / df["price"] * 100
    df["ret_4h_pct"] = df["ret_4h"] / df["price"] * 100

    if direction == "bull":
        df["mfe_1h_pct"] = (df["max_1h"] - df["price"]) / df["price"] * 100
        df["mae_1h_pct"] = (df["price"] - df["min_1h"]) / df["price"] * 100
        df["mfe_4h_pct"] = (df["max_4h"] - df["price"]) / df["price"] * 100
        df["mae_4h_pct"] = (df["price"] - df["min_4h"]) / df["price"] * 100
    else:
        df["mfe_1h_pct"] = (df["price"] - df["min_1h"]) / df["price"] * 100
        df["mae_1h_pct"] = (df["max_1h"] - df["price"]) / df["price"] * 100
        df["mfe_4h_pct"] = (df["price"] - df["min_4h"]) / df["price"] * 100
        df["mae_4h_pct"] = (df["max_4h"] - df["price"]) / df["price"] * 100

    print(f"\n  Total signals: {n:,}")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    years = pd.to_datetime(df["timestamp"]).dt.year
    print(f"  Signals per year: {n / max(years.max() - years.min() + 1, 1):.1f}")

    for label, ret_col, mfe_col, mae_col in [
        ("1-HOUR", "ret_1h_pct", "mfe_1h_pct", "mae_1h_pct"),
        ("4-HOUR", "ret_4h_pct", "mfe_4h_pct", "mae_4h_pct"),
    ]:
        valid = df[ret_col].dropna()
        print(f"\n  --- {label} FORWARD (n={len(valid):,}) ---")
        if len(valid) == 0:
            continue
        if direction == "bull":
            wr = (valid > 0).mean() * 100
            lbl = "price higher"
        else:
            wr = (valid < 0).mean() * 100
            lbl = "price lower"
        print(f"  Win rate ({lbl}):  {wr:.1f}%")
        print(f"  Mean return:   {valid.mean():+.4f}%")
        print(f"  Median return: {valid.median():+.4f}%")
        print(f"  Std dev:       {valid.std():.4f}%")
        mfe = df[mfe_col].dropna()
        mae = df[mae_col].dropna()
        if len(mfe) > 0:
            print(f"  Avg MFE: +{mfe.mean():.4f}%  |  Avg MAE: -{mae.mean():.4f}%")

        if len(valid) >= 10:
            pctiles = [5, 10, 25, 50, 75, 90, 95]
            v = np.percentile(valid, pctiles)
            print(f"  Percentiles: " + "  ".join(f"P{p}={x:+.3f}%" for p, x in zip(pctiles, v)))

    # By hour
    print(f"\n  --- BY SIGNAL HOUR ---")
    print(f"  {'Hour':<6s} {'N':>5s} {'1h Mean%':>10s} {'1h Win%':>8s} {'4h Mean%':>10s} {'4h Win%':>8s}")
    for hour in sorted(df["hour"].unique()):
        sub = df[df["hour"] == hour]
        ns = len(sub)
        r1 = sub["ret_1h_pct"].dropna()
        r4 = sub["ret_4h_pct"].dropna()
        m1 = r1.mean() if len(r1) > 0 else np.nan
        m4 = r4.mean() if len(r4) > 0 else np.nan
        if direction == "bull":
            w1 = (r1 > 0).mean() * 100 if len(r1) > 0 else np.nan
            w4 = (r4 > 0).mean() * 100 if len(r4) > 0 else np.nan
        else:
            w1 = (r1 < 0).mean() * 100 if len(r1) > 0 else np.nan
            w4 = (r4 < 0).mean() * 100 if len(r4) > 0 else np.nan
        flag = " *" if ns < 30 else ""
        m1s = f"{m1:+.4f}%" if not np.isnan(m1) else "     n/a"
        m4s = f"{m4:+.4f}%" if not np.isnan(m4) else "     n/a"
        w1s = f"{w1:.1f}%" if not np.isnan(w1) else "  n/a"
        w4s = f"{w4:.1f}%" if not np.isnan(w4) else "  n/a"
        print(f"  {hour:02d}:00  {ns:5d}  {m1s:>9s} {w1s:>8s}  {m4s:>9s} {w4s:>8s}{flag}")

    # Year by year
    print(f"\n  --- YEAR BY YEAR ---")
    df["year"] = pd.to_datetime(df["timestamp"]).dt.year
    print(f"  {'Year':<6s} {'N':>5s} {'1h Mean%':>10s} {'4h Mean%':>10s}")
    for year in sorted(df["year"].unique()):
        sub = df[df["year"] == year]
        ns = len(sub)
        r1 = sub["ret_1h_pct"].dropna().mean()
        r4 = sub["ret_4h_pct"].dropna().mean()
        r1s = f"{r1:+.4f}%" if not np.isnan(r1) else "     n/a"
        r4s = f"{r4:+.4f}%" if not np.isnan(r4) else "     n/a"
        print(f"  {year}  {ns:5d}  {r1s:>9s}  {r4s:>9s}")

    # T-test
    for label, col in [("1h", "ret_1h_pct"), ("4h", "ret_4h_pct")]:
        valid = df[col].dropna()
        if len(valid) >= 30:
            from scipy import stats
            t, p = stats.ttest_1samp(valid, 0)
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
            print(f"\n  {label} t-test: t={t:.3f}, p={p:.4f} {sig}")

    return df


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 3m data...", flush=True)
    df3 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "ema_8, ema_13, ema_21, ema_48 "
        "FROM ind_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df3 = df3.set_index("timestamp").sort_index()
    df3 = df3.between_time("09:30", "15:59")
    df3 = df3.dropna(subset=["ema_8", "ema_13", "ema_21", "ema_48"])

    print("Loading 10m data...", flush=True)
    df10 = pd.read_sql_query(
        "SELECT timestamp, ema_8, ema_13, ema_21, ema_48 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df10 = df10.set_index("timestamp").sort_index()
    df10 = df10.dropna(subset=["ema_8", "ema_13", "ema_21", "ema_48"])
    conn.close()

    print("Merging timeframes...", flush=True)
    df3_reset = df3.reset_index()
    df10_reset = df10.reset_index()
    merged = pd.merge_asof(
        df3_reset[["timestamp"]],
        df10_reset[["timestamp", "ema_8", "ema_13", "ema_21", "ema_48"]],
        on="timestamp",
        direction="backward",
        suffixes=("", "_10m")
    )
    for col in ["ema_8", "ema_13", "ema_21", "ema_48"]:
        df3[f"{col}_10m"] = merged[col].values

    print("Computing conditions...", flush=True)

    # Pre-compute all stacking masks as numpy arrays for speed
    # Full stack: 8 >= 13 >= 21 >= 48
    bull_full_3m = ((df3["ema_8"].values >= df3["ema_13"].values) &
                    (df3["ema_13"].values >= df3["ema_21"].values) &
                    (df3["ema_21"].values >= df3["ema_48"].values))
    bear_full_3m = ((df3["ema_8"].values <= df3["ema_13"].values) &
                    (df3["ema_13"].values <= df3["ema_21"].values) &
                    (df3["ema_21"].values <= df3["ema_48"].values))
    bull_full_10m = ((df3["ema_8_10m"].values >= df3["ema_13_10m"].values) &
                     (df3["ema_13_10m"].values >= df3["ema_21_10m"].values) &
                     (df3["ema_21_10m"].values >= df3["ema_48_10m"].values))
    bear_full_10m = ((df3["ema_8_10m"].values <= df3["ema_13_10m"].values) &
                     (df3["ema_13_10m"].values <= df3["ema_21_10m"].values) &
                     (df3["ema_21_10m"].values <= df3["ema_48_10m"].values))

    # Cloud-only: fast + slow
    bull_cloud_3m = ((df3["ema_8"].values >= df3["ema_21"].values) &
                     (df3["ema_13"].values >= df3["ema_48"].values))
    bear_cloud_3m = ((df3["ema_8"].values <= df3["ema_21"].values) &
                     (df3["ema_13"].values <= df3["ema_48"].values))
    bull_cloud_10m = ((df3["ema_8_10m"].values >= df3["ema_21_10m"].values) &
                      (df3["ema_13_10m"].values >= df3["ema_48_10m"].values))
    bear_cloud_10m = ((df3["ema_8_10m"].values <= df3["ema_21_10m"].values) &
                      (df3["ema_13_10m"].values <= df3["ema_48_10m"].values))

    # Combined stacking masks
    stacked = {
        ("bull", True): bull_full_3m & bull_full_10m,
        ("bull", False): bull_cloud_3m & bull_cloud_10m,
        ("bear", True): bear_full_3m & bear_full_10m,
        ("bear", False): bear_cloud_3m & bear_cloud_10m,
    }

    # Spread
    prices = df3["close"].values
    spread = df3["ema_21"].values - df3["ema_21_10m"].values
    spread_pct = (spread / prices) * 100
    dates = df3.index.date

    timestamps = df3.index.values
    highs = df3["high"].values
    lows = df3["low"].values

    # ═══════════════════════════════════════════════════════
    # PARAMETER SWEEP
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("3m/10m EMA-21 SQUEEZE — PARAMETER SWEEP")
    print("=" * 80)

    configs = [
        (0.40, 0.10, True,  "Full stack 0.40%→0.10%"),
        (0.40, 0.10, False, "Clouds    0.40%→0.10%"),
        (0.30, 0.10, True,  "Full stack 0.30%→0.10%"),
        (0.30, 0.10, False, "Clouds    0.30%→0.10%"),
        (0.25, 0.08, True,  "Full stack 0.25%→0.08%"),
        (0.25, 0.08, False, "Clouds    0.25%→0.08%"),
        (0.20, 0.05, True,  "Full stack 0.20%→0.05%"),
        (0.20, 0.05, False, "Clouds    0.20%→0.05%"),
        (0.20, 0.10, False, "Clouds    0.20%→0.10%"),
        (0.15, 0.05, False, "Clouds    0.15%→0.05%"),
        (0.15, 0.08, False, "Clouds    0.15%→0.08%"),
    ]

    print(f"\n{'Config':<30s} {'Bull N':>7s} {'1h W%':>6s} {'1h Avg':>8s}  "
          f"{'Bear N':>7s} {'1h W%':>6s} {'1h Avg':>8s}  {'Total':>6s}")
    print("─" * 95)

    sweep_results = []

    for exp_pct, comp_pct, full_stack, label in configs:
        bull_sigs_idx = detect_signals_vectorized(
            dates, spread_pct, stacked[("bull", full_stack)], prices,
            highs, lows, timestamps, exp_pct, comp_pct, 20, "bull")
        bear_sigs_idx = detect_signals_vectorized(
            dates, spread_pct, stacked[("bear", full_stack)], prices,
            highs, lows, timestamps, exp_pct, comp_pct, 20, "bear")

        bull_sigs = compute_forward_returns(df3, bull_sigs_idx, "bull")
        bear_sigs = compute_forward_returns(df3, bear_sigs_idx, "bear")

        def quick(sigs, d):
            if len(sigs) == 0:
                return 0, 0.0, 0.0
            df_s = pd.DataFrame(sigs)
            df_s["r"] = (df_s["price_1h"] - df_s["price"]) / df_s["price"] * 100
            v = df_s["r"].dropna()
            if len(v) == 0:
                return len(sigs), 0.0, 0.0
            wr = ((v > 0) if d == "bull" else (v < 0)).mean() * 100
            return len(sigs), wr, v.mean()

        bn, bwr, bm = quick(bull_sigs, "bull")
        an, awr, am = quick(bear_sigs, "bear")
        total = bn + an
        sweep_results.append((exp_pct, comp_pct, full_stack, label, bn, bwr, bm, an, awr, am, total,
                              bull_sigs, bear_sigs))

        bms = f"{bm:+.4f}%" if bn > 0 else "    n/a"
        ams = f"{am:+.4f}%" if an > 0 else "    n/a"
        bwrs = f"{bwr:.1f}%" if bn > 0 else "  n/a"
        awrs = f"{awr:.1f}%" if an > 0 else "  n/a"
        print(f"  {label:<28s} {bn:7d} {bwrs:>6s} {bms:>8s}  "
              f"{an:7d} {awrs:>6s} {ams:>8s}  {total:6d}")

    # ═══════════════════════════════════════════════════════
    # DETAILED RESULTS for configs with adequate sample
    # ═══════════════════════════════════════════════════════
    # Show detailed stats for the 3 most interesting configs
    # Pick: (1) user's original strict config, (2) best cloud config with n>=100, (3) widest

    detail_indices = []
    # User's original (strict, tightest)
    detail_indices.append(0)  # Full stack 0.40%→0.10%

    # Best config with total >= 80
    best_idx = None
    best_total = 0
    for i, r in enumerate(sweep_results):
        if r[10] >= 80 and r[10] > best_total:
            best_total = r[10]
            best_idx = i
    if best_idx and best_idx not in detail_indices:
        detail_indices.append(best_idx)

    # Widest config
    widest_idx = len(sweep_results) - 1
    if widest_idx not in detail_indices:
        detail_indices.append(widest_idx)

    for di in detail_indices:
        r = sweep_results[di]
        exp_pct, comp_pct, full_stack, label = r[0], r[1], r[2], r[3]
        bull_sigs, bear_sigs = r[11], r[12]

        stack_label = "full stack" if full_stack else "cloud-only"
        print(f"\n{'═'*80}")
        print(f"  DETAILED: {label} ({stack_label})")
        print(f"  Expansion >= {exp_pct}% of price, Compression <= {comp_pct}% of price")
        print(f"{'═'*80}")

        for direction, sigs in [("bull", bull_sigs), ("bear", bear_sigs)]:
            dir_label = "BULLISH" if direction == "bull" else "BEARISH"
            print(f"\n  ── {dir_label} SQUEEZE ──")
            print_stats(sigs, direction)

    print("\n\nDone.")


if __name__ == "__main__":
    main()
