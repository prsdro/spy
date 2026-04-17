"""
4H PO Rollover → Drop Magnitude Study, Stratified by ATR Position

Real trading question: 4H PO rolls over. Where is price in the weekly/monthly ATR grid?
Does that position predict whether we get a tradeable drop (0.5-2%+) or pure chop?

Drop thresholds: 0.5%, 1.0%, 1.5%, 2.0%, 3.0%
Horizons: 1d, 2d, 3d, 5d, 10d

Stratification:
- Weekly ATR bucket (prev week close ± weekly ATR multiplier)
- Monthly ATR bucket (prev month close ± monthly ATR multiplier)
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def compute_monthly_atr_grid(df_d, atr_period=14):
    """Compute monthly ATR grid per day, using prev month's close and monthly ATR.
    Returns a series indexed by daily date with columns for ATR position."""
    # Resample daily to monthly
    m = df_d.resample("ME").agg({"open": "first", "high": "max",
                                "low": "min", "close": "last"})
    # True Range at monthly level
    m["prev_close"] = m["close"].shift(1)
    m["tr"] = m[["high", "low", "prev_close"]].apply(
        lambda r: max(r["high"] - r["low"],
                      abs(r["high"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
                      abs(r["low"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0),
        axis=1
    )
    m["atr"] = m["tr"].rolling(atr_period).mean()
    # For each daily bar, assign the prev month's close and atr
    monthly_ref = m[["close", "atr"]].shift(1).rename(
        columns={"close": "prev_month_close", "atr": "monthly_atr"}
    )
    # Reindex to daily, forward-fill
    daily_monthly = monthly_ref.reindex(df_d.index, method="ffill")
    return daily_monthly


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 4h data...")
    df4h = pd.read_sql_query(
        "SELECT timestamp, close, phase_oscillator FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp").dropna(subset=["phase_oscillator"])

    print("Loading daily data...")
    df1d = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_21, atr_14, prev_close "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")

    print("Loading weekly data...")
    df1w = pd.read_sql_query(
        "SELECT timestamp, close, atr_14, prev_close FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")

    conn.close()

    # For each daily bar, attach the prev week's close and weekly ATR
    # df1w timestamp is the week's start; for a daily bar on date D, find the
    # most recent weekly bar whose timestamp is <= D-6 (i.e. prev week)
    df1w["week_start"] = df1w.index
    # Use asof: for each daily date, get the most recent weekly bar that ended before that date
    # Simplification: map each daily bar to the weekly bar it's contained in, then shift back 1
    df1d_weekly = pd.merge_asof(
        df1d.reset_index().sort_values("timestamp"),
        df1w[["close", "atr_14"]].reset_index().sort_values("timestamp").rename(
            columns={"close": "week_close", "atr_14": "week_atr"}
        ),
        on="timestamp", direction="backward"
    ).set_index("timestamp")
    # Shift so we use PREVIOUS week's close + atr (week whose end precedes signal week)
    # Actually: the weekly bar at timestamp T represents the week STARTING at T.
    # The "prev week close" we want is the close of the week ending just before today.
    # Simplest approach: group daily bars by ISO week, then map each week's group to
    # the prior week's close.
    df1d_weekly["iso_week"] = df1d_weekly.index.isocalendar().year.astype(str) + "-W" + \
                              df1d_weekly.index.isocalendar().week.astype(str).str.zfill(2)

    # Compute each week's close (last daily close of the week) and weekly ATR series
    weekly_close = df1d.groupby(df1d.index.isocalendar().week.astype(str) + "-" +
                                 df1d.index.isocalendar().year.astype(str))["close"].last()

    # Simpler: use weekly resample from daily
    weekly_resample = df1d["close"].resample("W-FRI").last().rename("wk_close")
    weekly_high = df1d["high"].resample("W-FRI").max()
    weekly_low = df1d["low"].resample("W-FRI").min()
    wk_tr = pd.DataFrame({"h": weekly_high, "l": weekly_low,
                          "pc": weekly_resample.shift(1)})
    wk_tr["tr"] = wk_tr.apply(
        lambda r: max(r["h"] - r["l"],
                      abs(r["h"] - r["pc"]) if pd.notna(r["pc"]) else 0,
                      abs(r["l"] - r["pc"]) if pd.notna(r["pc"]) else 0),
        axis=1
    )
    wk_tr["wk_atr"] = wk_tr["tr"].rolling(14).mean()

    # For each daily date, attach PREVIOUS week's close and ATR
    wk_ref = wk_tr[["wk_close" if "wk_close" in wk_tr.columns else "h"]].copy()
    wk_ref = pd.DataFrame({
        "prev_wk_close": weekly_resample.shift(1),  # prev week's close
        "wk_atr": wk_tr["wk_atr"].shift(1),         # atr as-of prev week end
    })
    # merge_asof to daily
    df1d_enriched = pd.merge_asof(
        df1d.reset_index().sort_values("timestamp"),
        wk_ref.reset_index().sort_values("timestamp"),
        on="timestamp", direction="backward"
    ).set_index("timestamp")

    # Monthly ATR grid
    monthly_ref = compute_monthly_atr_grid(df1d)
    df1d_enriched = df1d_enriched.join(monthly_ref)

    # ─── Find 4H PO rollover signals ───
    print("\nFinding 4H PO rollover signals (peak >=100, cross below 100)...")
    po = df4h["phase_oscillator"]
    was_above = False
    peak = 0
    signals = []
    for i in range(1, len(df4h)):
        cur = po.iloc[i]
        prev = po.iloc[i - 1]
        if prev >= 100:
            if not was_above:
                was_above = True
                peak = prev
            elif prev > peak:
                peak = prev
        if was_above and prev >= 100 and cur < 100:
            signals.append({
                "signal_time": df4h.index[i],
                "peak_po": peak,
                "signal_po": cur,
                "signal_close_4h": df4h.iloc[i]["close"],
            })
            was_above = False
            peak = 0

    print(f"Total signals: {len(signals)}")

    # ─── For each signal, compute ATR position and forward drops ───
    results = []
    for sig in signals:
        sig_time = sig["signal_time"]
        sig_date = sig_time.normalize()

        # Find daily bar for signal date
        dloc = df1d_enriched.index.searchsorted(sig_date)
        if dloc >= len(df1d_enriched):
            continue
        if df1d_enriched.index[dloc] < sig_date:
            dloc += 1
        if dloc >= len(df1d_enriched):
            continue

        drow = df1d_enriched.iloc[dloc]
        sig_close = sig["signal_close_4h"]

        # Weekly ATR position: (sig_close - prev_wk_close) / wk_atr
        wk_pos = None
        if pd.notna(drow.get("prev_wk_close")) and pd.notna(drow.get("wk_atr")) and drow["wk_atr"] > 0:
            wk_pos = (sig_close - drow["prev_wk_close"]) / drow["wk_atr"]

        # Monthly ATR position
        mo_pos = None
        if pd.notna(drow.get("prev_month_close")) and pd.notna(drow.get("monthly_atr")) and drow["monthly_atr"] > 0:
            mo_pos = (sig_close - drow["prev_month_close"]) / drow["monthly_atr"]

        # Daily ATR position (where today's close sits relative to prev close)
        d_pos = None
        if pd.notna(drow.get("prev_close")) and pd.notna(drow.get("atr_14")) and drow["atr_14"] > 0:
            d_pos = (sig_close - drow["prev_close"]) / drow["atr_14"]

        # ─── Forward drops: max drop from sig_close over horizons ───
        drop_data = {}
        for horizon in [1, 2, 3, 5, 10]:
            end_idx = min(dloc + horizon + 1, len(df1d_enriched))
            future = df1d_enriched.iloc[dloc + 1:end_idx]
            if len(future) == 0:
                continue
            min_low = future["low"].min()
            max_drop = (min_low - sig_close) / sig_close * 100  # negative
            drop_data[f"max_drop_{horizon}d"] = max_drop
            # Bars to reach various thresholds
            for thresh in [0.5, 1.0, 1.5, 2.0, 3.0]:
                target = sig_close * (1 - thresh / 100)
                hit = future[future["low"] <= target]
                if len(hit) > 0:
                    drop_data[f"days_to_{thresh}pct_{horizon}d"] = (
                        df1d_enriched.index.get_loc(hit.index[0]) - dloc
                    )
                else:
                    drop_data[f"days_to_{thresh}pct_{horizon}d"] = None

        # Also compute: did we get a 1% drop within 5 days (our key metric)?
        hit_05_5d = drop_data.get("days_to_0.5pct_5d") is not None
        hit_10_5d = drop_data.get("days_to_1.0pct_5d") is not None
        hit_15_5d = drop_data.get("days_to_1.5pct_5d") is not None
        hit_20_5d = drop_data.get("days_to_2.0pct_5d") is not None

        results.append({
            "signal_date": sig_date,
            "peak_po": sig["peak_po"],
            "sig_close": sig_close,
            "wk_atr_pos": wk_pos,
            "mo_atr_pos": mo_pos,
            "d_atr_pos": d_pos,
            "max_drop_1d": drop_data.get("max_drop_1d"),
            "max_drop_2d": drop_data.get("max_drop_2d"),
            "max_drop_3d": drop_data.get("max_drop_3d"),
            "max_drop_5d": drop_data.get("max_drop_5d"),
            "max_drop_10d": drop_data.get("max_drop_10d"),
            "hit_05_5d": hit_05_5d,
            "hit_10_5d": hit_10_5d,
            "hit_15_5d": hit_15_5d,
            "hit_20_5d": hit_20_5d,
        })

    rdf = pd.DataFrame(results)
    rdf = rdf.dropna(subset=["wk_atr_pos"])

    print(f"\nValid events (with weekly ATR data): {len(rdf)}")

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  BASELINE: Drop Rates After 4H PO Rollover (all events)")
    print("=" * 90)
    n = len(rdf)
    for thresh_col, label in [("hit_05_5d", "≥0.5% drop within 5d"),
                               ("hit_10_5d", "≥1.0% drop within 5d"),
                               ("hit_15_5d", "≥1.5% drop within 5d"),
                               ("hit_20_5d", "≥2.0% drop within 5d")]:
        c = rdf[thresh_col].sum()
        print(f"  {label:<35s}: {c}/{n} = {c/n*100:.1f}%")

    print(f"\n  Max drop stats (percent):")
    for h in [1, 2, 3, 5, 10]:
        col = f"max_drop_{h}d"
        v = rdf[col].dropna()
        print(f"    {h}-day: median {v.median():.2f}%, mean {v.mean():.2f}%, "
              f"worst {v.min():.2f}%, 25th {v.quantile(0.25):.2f}%")

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  CURRENT ATR POSITION DISTRIBUTION (at signal time)")
    print("=" * 90)
    print(f"\n  Daily ATR position (signal close vs prev day close, in ATR units):")
    print(f"    Median: {rdf['d_atr_pos'].median():.2f}  Mean: {rdf['d_atr_pos'].mean():.2f}")
    print(f"    Range:  {rdf['d_atr_pos'].min():.2f} to {rdf['d_atr_pos'].max():.2f}")

    print(f"\n  Weekly ATR position (signal close vs prev week close, in weekly ATR units):")
    print(f"    Median: {rdf['wk_atr_pos'].median():.2f}  Mean: {rdf['wk_atr_pos'].mean():.2f}")
    print(f"    Range:  {rdf['wk_atr_pos'].min():.2f} to {rdf['wk_atr_pos'].max():.2f}")

    print(f"\n  Monthly ATR position (signal close vs prev month close):")
    mo_valid = rdf.dropna(subset=["mo_atr_pos"])
    if len(mo_valid) > 0:
        print(f"    Median: {mo_valid['mo_atr_pos'].median():.2f}  Mean: {mo_valid['mo_atr_pos'].mean():.2f}")
        print(f"    Range:  {mo_valid['mo_atr_pos'].min():.2f} to {mo_valid['mo_atr_pos'].max():.2f}")

    # ═══════════════════════════════════════════════════════════════
    # Stratify by WEEKLY ATR position
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  DROP RATES STRATIFIED BY WEEKLY ATR POSITION")
    print("=" * 90)

    buckets = [
        ("Below -0.236 (below put trigger)", -99, -0.236),
        ("-0.236 to 0.236 (trigger box)", -0.236, 0.236),
        ("0.236 to 0.382", 0.236, 0.382),
        ("0.382 to 0.618 (GG open)", 0.382, 0.618),
        ("0.618 to 1.00 (past GG 61.8%)", 0.618, 1.0),
        ("1.00 to 1.236 (past full ATR)", 1.0, 1.236),
        ("1.236+ (super extended)", 1.236, 99),
    ]

    print(f"\n  {'Bucket':<40s} {'N':>4s} {'≥0.5%':>8s} {'≥1.0%':>8s} {'≥1.5%':>8s} {'≥2.0%':>8s} {'Med5d':>8s} {'Worst5d':>8s}")
    print(f"  {'─' * 100}")
    for label, lo, hi in buckets:
        subset = rdf[(rdf["wk_atr_pos"] >= lo) & (rdf["wk_atr_pos"] < hi)]
        n = len(subset)
        if n == 0:
            continue
        h05 = subset["hit_05_5d"].sum()
        h10 = subset["hit_10_5d"].sum()
        h15 = subset["hit_15_5d"].sum()
        h20 = subset["hit_20_5d"].sum()
        med5 = subset["max_drop_5d"].median()
        worst5 = subset["max_drop_5d"].min()
        print(f"  {label:<40s} {n:>4d} "
              f"{h05/n*100:>7.0f}% {h10/n*100:>7.0f}% {h15/n*100:>7.0f}% {h20/n*100:>7.0f}% "
              f"{med5:>7.2f}% {worst5:>7.2f}%")

    # ═══════════════════════════════════════════════════════════════
    # Stratify by MONTHLY ATR position
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  DROP RATES STRATIFIED BY MONTHLY (SWING) ATR POSITION")
    print("=" * 90)

    mo_rdf = rdf.dropna(subset=["mo_atr_pos"])

    print(f"\n  {'Bucket':<40s} {'N':>4s} {'≥0.5%':>8s} {'≥1.0%':>8s} {'≥1.5%':>8s} {'≥2.0%':>8s} {'Med5d':>8s} {'Worst5d':>8s}")
    print(f"  {'─' * 100}")
    for label, lo, hi in buckets:
        subset = mo_rdf[(mo_rdf["mo_atr_pos"] >= lo) & (mo_rdf["mo_atr_pos"] < hi)]
        n = len(subset)
        if n == 0:
            continue
        h05 = subset["hit_05_5d"].sum()
        h10 = subset["hit_10_5d"].sum()
        h15 = subset["hit_15_5d"].sum()
        h20 = subset["hit_20_5d"].sum()
        med5 = subset["max_drop_5d"].median()
        worst5 = subset["max_drop_5d"].min()
        print(f"  {label:<40s} {n:>4d} "
              f"{h05/n*100:>7.0f}% {h10/n*100:>7.0f}% {h15/n*100:>7.0f}% {h20/n*100:>7.0f}% "
              f"{med5:>7.2f}% {worst5:>7.2f}%")

    # ═══════════════════════════════════════════════════════════════
    # Cross-tab: Weekly × Monthly (find the strongest combo)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  CROSS-TAB: Weekly × Monthly ATR Position (≥1.0% drop rate within 5d)")
    print("=" * 90)

    simple_buckets = [
        ("Low (<0.382)", -99, 0.382),
        ("Mid (0.382-0.618)", 0.382, 0.618),
        ("High (0.618-1.0)", 0.618, 1.0),
        ("Extended (>=1.0)", 1.0, 99),
    ]

    print(f"\n  {'Weekly \\ Monthly':<22s} ", end="")
    for mlabel, _, _ in simple_buckets:
        print(f"{mlabel:>18s}", end="")
    print()
    print(f"  {'─' * 94}")

    for wlabel, wlo, whi in simple_buckets:
        wsubset = mo_rdf[(mo_rdf["wk_atr_pos"] >= wlo) & (mo_rdf["wk_atr_pos"] < whi)]
        print(f"  {wlabel:<22s} ", end="")
        for mlabel, mlo, mhi in simple_buckets:
            cell = wsubset[(wsubset["mo_atr_pos"] >= mlo) & (wsubset["mo_atr_pos"] < mhi)]
            n = len(cell)
            if n == 0:
                print(f"{'—':>18s}", end="")
            else:
                rate = cell["hit_10_5d"].sum() / n * 100
                print(f"   {n:>3d}: {rate:>5.0f}%     ", end="")
        print()

    # ═══════════════════════════════════════════════════════════════
    # Event listing ranked by weekly ATR pos
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  EVENT DETAILS (sorted by weekly ATR position, extended first)")
    print("=" * 90)
    print(f"  {'Date':<12s} {'PkPO':>6s} {'WkATR':>7s} {'MoATR':>7s} "
          f"{'Drop1d':>7s} {'Drop3d':>7s} {'Drop5d':>7s} {'≥1%5d':>6s}")
    print(f"  {'─' * 75}")

    sorted_rdf = rdf.sort_values("wk_atr_pos", ascending=False)
    for _, r in sorted_rdf.iterrows():
        d = str(r["signal_date"])[:10]
        pk = f"{r['peak_po']:.0f}"
        wk = f"{r['wk_atr_pos']:.2f}" if pd.notna(r["wk_atr_pos"]) else "—"
        mo = f"{r['mo_atr_pos']:.2f}" if pd.notna(r["mo_atr_pos"]) else "—"
        d1 = f"{r['max_drop_1d']:.2f}" if pd.notna(r["max_drop_1d"]) else "—"
        d3 = f"{r['max_drop_3d']:.2f}" if pd.notna(r["max_drop_3d"]) else "—"
        d5 = f"{r['max_drop_5d']:.2f}" if pd.notna(r["max_drop_5d"]) else "—"
        hit = "YES" if r["hit_10_5d"] else "no"
        print(f"  {d:<12s} {pk:>6s} {wk:>7s} {mo:>7s} {d1:>7s} {d3:>7s} {d5:>7s} {hit:>6s}")

    # Save results for reference
    rdf.to_csv(os.path.join(BASE_DIR, "drop_by_atr_position_results.csv"), index=False)
    print(f"\nResults saved to drop_by_atr_position_results.csv")


if __name__ == "__main__":
    main()
