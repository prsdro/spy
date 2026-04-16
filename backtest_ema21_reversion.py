"""
Price >4% Above Daily 21 EMA: Reversion Signal Analysis

When SPY stretches >4% above its daily 21 EMA, what signals predict
the reversion? How fast does it come, and what does the path look like?

Investigates: PO zone, leaving_distribution, candle bias flips,
conviction arrows, fast cloud flips, compression state, ATR trend.
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query(
        "SELECT * FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.dropna(subset=["ema_21"])
    df["date"] = df.index.date

    # Core metric
    df["dev_pct"] = (df["close"] - df["ema_21"]) / df["ema_21"] * 100
    df["prev_dev"] = df["dev_pct"].shift(1)

    # Forward returns
    for d in [1, 2, 3, 5, 10, 20]:
        df[f"fwd_{d}d"] = df["close"].pct_change(d).shift(-d) * 100

    # Next-day metrics
    df["next_return"] = df["fwd_1d"]
    df["next_green"] = (df["close"].shift(-1) > df["open"].shift(-1)).astype(float)

    n_total = len(df)

    # ─────────────────────────────────────────────
    # Find all entries into the >4% zone
    # ─────────────────────────────────────────────
    above4 = df[df["dev_pct"] > 4].copy()
    print(f"Total daily bars: {n_total:,}")
    print(f"Days with close >4% above EMA21: {len(above4)} ({len(above4)/n_total*100:.2f}%)\n")

    # Group into "episodes" — consecutive stretches above 4%
    episodes = []
    current_ep = []
    prev_above = False
    for i in range(len(df)):
        is_above = df["dev_pct"].iloc[i] > 4
        if is_above:
            current_ep.append(i)
        else:
            if current_ep:
                episodes.append(current_ep)
                current_ep = []
        prev_above = is_above
    if current_ep:
        episodes.append(current_ep)

    print(f"Distinct episodes (consecutive stretches >4%): {len(episodes)}")
    print(f"Mean episode length: {np.mean([len(e) for e in episodes]):.1f} days")
    print(f"Max episode length: {max(len(e) for e in episodes)} days")

    # ─────────────────────────────────────────────
    # SECTION 1: The First Day Above 4% (entry signal)
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 1: FIRST DAY CROSSING >4% ABOVE EMA21")
    print("=" * 70)

    # First day of each episode
    entry_indices = [e[0] for e in episodes]
    entries = df.iloc[entry_indices].copy()

    print(f"\n  Total first-day entries: {len(entries)}")

    print(f"\n  Forward returns from first day >4%:")
    print(f"  {'Horizon':<12s} {'Mean':>8s} {'Median':>8s} {'Green%':>8s} {'n':>5s}")
    print("  " + "-" * 44)
    for d in [1, 2, 3, 5, 10, 20]:
        vals = entries[f"fwd_{d}d"].dropna()
        print(f"  {d:>2d}-day       {vals.mean():+7.3f}% {vals.median():+7.3f}% "
              f"{(vals > 0).mean()*100:7.1f}% {len(vals):5d}")

    # ─────────────────────────────────────────────
    # SECTION 2: Path to Reversion — Days to EMA21 Touch
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 2: PATH TO REVERSION")
    print("=" * 70)

    # For each episode, how many days from first >4% until price touches EMA21?
    days_to_ema21 = []
    reversion_returns = []
    max_before_revert = []

    for ep in episodes:
        start_idx = ep[0]
        start_row = df.iloc[start_idx]
        entry_close = start_row["close"]

        # Search forward from episode start (up to 60 days)
        found = False
        peak_dev = 0
        for j in range(start_idx + 1, min(start_idx + 61, len(df))):
            row = df.iloc[j]
            peak_dev = max(peak_dev, row["dev_pct"])

            # Check if low touched EMA21 (or crossed below)
            if row["low"] <= row["ema_21"]:
                days = j - start_idx
                ret = (row["close"] - entry_close) / entry_close * 100
                days_to_ema21.append(days)
                reversion_returns.append(ret)
                max_before_revert.append(peak_dev)
                found = True
                break

        if not found:
            days_to_ema21.append(np.nan)
            reversion_returns.append(np.nan)
            max_before_revert.append(peak_dev)

    days_arr = np.array(days_to_ema21)
    valid_days = days_arr[~np.isnan(days_arr)]

    print(f"\n  From first close >4% above EMA21, days until price touches EMA21:")
    print(f"    Mean:   {np.mean(valid_days):.1f} days")
    print(f"    Median: {np.median(valid_days):.0f} days")
    print(f"    P25:    {np.percentile(valid_days, 25):.0f} days")
    print(f"    P75:    {np.percentile(valid_days, 75):.0f} days")
    print(f"    Max:    {np.max(valid_days):.0f} days")
    print(f"    Reverted within 60d: {len(valid_days)}/{len(days_arr)} ({len(valid_days)/len(days_arr)*100:.1f}%)")

    rev_ret = np.array(reversion_returns)
    valid_ret = rev_ret[~np.isnan(rev_ret)]
    print(f"\n  Return from entry to EMA21 touch:")
    print(f"    Mean:   {np.mean(valid_ret):+.3f}%")
    print(f"    Median: {np.median(valid_ret):+.3f}%")

    print(f"\n  Distribution of days to revert:")
    for bucket, lo, hi in [("1-3 days", 1, 3), ("4-5 days", 4, 5), ("6-10 days", 6, 10),
                            ("11-20 days", 11, 20), ("21-40 days", 21, 40), ("41-60 days", 41, 60)]:
        count = ((valid_days >= lo) & (valid_days <= hi)).sum()
        print(f"    {bucket:<12s}: {count:3d} ({count/len(valid_days)*100:5.1f}%)")

    # ─────────────────────────────────────────────
    # SECTION 3: Reversion Signals — What Predicts the Turn?
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 3: REVERSION SIGNALS (conditions on the day >4% is first reached)")
    print("=" * 70)

    # Phase Oscillator zone at entry
    print(f"\n  --- PO Zone at Entry ---")
    print(f"  {'Zone':<18s} {'n':>4s} {'5d Fwd':>8s} {'10d Fwd':>8s} {'Days→EMA':>10s}")
    print("  " + "-" * 52)
    for zone in ["extended_up", "distribution", "neutral_up", "neutral"]:
        mask = entries["phase_zone"] == zone
        sub = entries[mask]
        if len(sub) < 3:
            continue
        f5 = sub["fwd_5d"].dropna().mean()
        f10 = sub["fwd_10d"].dropna().mean()
        # Get days to EMA21 for these episodes
        zone_days = [days_to_ema21[i] for i, idx in enumerate(entry_indices)
                     if df.iloc[idx]["phase_zone"] == zone and not np.isnan(days_to_ema21[i])]
        d_mean = np.mean(zone_days) if zone_days else np.nan
        flag = " *" if len(sub) < 20 else ""
        print(f"  {zone:<18s} {len(sub):4d} {f5:+7.3f}% {f10:+7.3f}% {d_mean:9.1f}d{flag}")

    # ATR trend at entry
    print(f"\n  --- ATR Trend at Entry ---")
    trend_labels = {1.0: "Bullish", 0.0: "Neutral", -1.0: "Bearish"}
    print(f"  {'Trend':<12s} {'n':>4s} {'5d Fwd':>8s} {'10d Fwd':>8s}")
    print("  " + "-" * 36)
    for tv, tl in trend_labels.items():
        sub = entries[entries["atr_trend"] == tv]
        if len(sub) < 3:
            continue
        f5 = sub["fwd_5d"].dropna().mean()
        f10 = sub["fwd_10d"].dropna().mean()
        flag = " *" if len(sub) < 20 else ""
        print(f"  {tl:<12s} {len(sub):4d} {f5:+7.3f}% {f10:+7.3f}%{flag}")

    # Compression state
    print(f"\n  --- Compression at Entry ---")
    for val, label in [(1, "Compression ON"), (0, "Compression OFF")]:
        sub = entries[entries["compression"] == val]
        if len(sub) < 3:
            continue
        f5 = sub["fwd_5d"].dropna().mean()
        f10 = sub["fwd_10d"].dropna().mean()
        print(f"  {label:<18s} n={len(sub):3d}  5d={f5:+.3f}%  10d={f10:+.3f}%")

    # Deviation magnitude at entry
    print(f"\n  --- Deviation Size at Entry ---")
    for lo, hi, label in [(4.0, 4.5, "4.0-4.5%"), (4.5, 5.0, "4.5-5.0%"),
                           (5.0, 6.0, "5.0-6.0%"), (6.0, 10.0, "6.0%+")]:
        sub = entries[(entries["dev_pct"] >= lo) & (entries["dev_pct"] < hi)]
        if len(sub) < 3:
            continue
        f5 = sub["fwd_5d"].dropna().mean()
        f10 = sub["fwd_10d"].dropna().mean()
        flag = " *" if len(sub) < 20 else ""
        print(f"  {label:<12s} n={len(sub):3d}  5d={f5:+.3f}%  10d={f10:+.3f}%{flag}")

    # ─────────────────────────────────────────────
    # SECTION 4: Daily Signals While in >4% Zone
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 4: DAILY REVERSION SIGNALS WHILE >4% ABOVE EMA21")
    print("=" * 70)
    print("  (Checking signals on ANY day in the >4% zone, not just first day)\n")

    # leaving_distribution signal
    ld = above4[above4["leaving_distribution"] == 1]
    print(f"  Leaving Distribution signal fired while >4%: {len(ld)} times")
    if len(ld) >= 5:
        for d in [1, 3, 5, 10]:
            vals = ld[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # leaving_extreme_up signal
    leu = above4[above4["leaving_extreme_up"] == 1]
    print(f"\n  Leaving Extreme Up signal fired while >4%: {len(leu)} times")
    if len(leu) >= 3:
        for d in [1, 3, 5, 10]:
            vals = leu[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # First red candle after stretch
    # Candle bias 4 = bear down (red), 2 = bearish up (orange)
    bearish_candle = above4[above4["candle_bias"].isin([2, 4])]
    print(f"\n  Bearish candle bias (orange/red) while >4%: {len(bearish_candle)} times")
    if len(bearish_candle) >= 5:
        for d in [1, 3, 5, 10]:
            vals = bearish_candle[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # Fast cloud flip (bearish) while >4%
    # Fast cloud just flipped bearish: was bullish yesterday, bearish today
    df["fc_flip_bear"] = ((df["fast_cloud_bullish"] == 0) &
                           (df["fast_cloud_bullish"].shift(1) == 1)).astype(int)
    above4_fc = df[(df["dev_pct"] > 4) & (df["fc_flip_bear"] == 1)]
    print(f"\n  Fast Cloud flipped BEARISH while >4%: {len(above4_fc)} times")
    if len(above4_fc) >= 3:
        for d in [1, 3, 5, 10]:
            vals = above4_fc[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # Conviction bear arrow while >4%
    conv_bear = above4[above4["conviction_bear"] == 1]
    print(f"\n  Conviction BEAR arrow while >4%: {len(conv_bear)} times")
    if len(conv_bear) >= 3:
        for d in [1, 3, 5, 10]:
            vals = conv_bear[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # Down day (red candle) while >4%
    down_day = above4[above4["close"] < above4["open"]]
    print(f"\n  Down/red close while >4%: {len(down_day)} times ({len(down_day)/len(above4)*100:.1f}%)")
    if len(down_day) >= 5:
        for d in [1, 3, 5, 10]:
            vals = down_day[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # PO declining while >4%
    df["po_declining"] = (df["phase_oscillator"] < df["phase_oscillator"].shift(1)).astype(int)
    po_dec_above4 = df[(df["dev_pct"] > 4) & (df["po_declining"] == 1)]
    print(f"\n  PO declining while >4%: {len(po_dec_above4)} times ({len(po_dec_above4)/len(above4)*100:.1f}%)")
    if len(po_dec_above4) >= 5:
        for d in [1, 3, 5, 10]:
            vals = po_dec_above4[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # ─────────────────────────────────────────────
    # SECTION 5: Combo Signals
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 5: COMBINATION SIGNALS (stacking conditions)")
    print("=" * 70)

    # PO declining + down candle while >4%
    combo1 = df[(df["dev_pct"] > 4) & (df["po_declining"] == 1) & (df["close"] < df["open"])]
    print(f"\n  PO declining + Red candle while >4%: {len(combo1)} times")
    if len(combo1) >= 5:
        for d in [1, 3, 5, 10]:
            vals = combo1[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # Leaving distribution + >4%
    combo2 = df[(df["dev_pct"] > 4) & (df["leaving_distribution"] == 1)]
    print(f"\n  Leaving Distribution + >4%: {len(combo2)} times")
    if len(combo2) >= 3:
        for d in [1, 3, 5, 10]:
            vals = combo2[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # PO in distribution + declining + >4%
    combo3 = df[(df["dev_pct"] > 4) & (df["phase_zone"] == "distribution") & (df["po_declining"] == 1)]
    print(f"\n  PO in Distribution zone + declining + >4%: {len(combo3)} times")
    if len(combo3) >= 3:
        for d in [1, 3, 5, 10]:
            vals = combo3[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # Dev >4% but deviation SHRINKING from yesterday
    df["dev_shrinking"] = (df["dev_pct"] < df["prev_dev"]).astype(int)
    combo4 = df[(df["dev_pct"] > 4) & (df["dev_shrinking"] == 1)]
    print(f"\n  >4% but deviation shrinking (pulling back toward EMA): {len(combo4)} times")
    if len(combo4) >= 5:
        for d in [1, 3, 5, 10]:
            vals = combo4[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # Dev >4% + deviation shrinking + PO declining
    combo5 = df[(df["dev_pct"] > 4) & (df["dev_shrinking"] == 1) & (df["po_declining"] == 1)]
    print(f"\n  >4% + deviation shrinking + PO declining: {len(combo5)} times")
    if len(combo5) >= 5:
        for d in [1, 3, 5, 10]:
            vals = combo5[f"fwd_{d}d"].dropna()
            print(f"    {d:>2d}d fwd: {vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # ─────────────────────────────────────────────
    # SECTION 6: The Peak Day (max deviation in episode)
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 6: PEAK DAY OF EACH EPISODE (max deviation day)")
    print("=" * 70)

    peak_indices = []
    for ep in episodes:
        max_dev = -999
        max_idx = ep[0]
        for idx in ep:
            if df["dev_pct"].iloc[idx] > max_dev:
                max_dev = df["dev_pct"].iloc[idx]
                max_idx = idx
        peak_indices.append(max_idx)

    peaks = df.iloc[peak_indices].copy()
    print(f"\n  Peak day forward returns ({len(peaks)} episodes):")
    print(f"  {'Horizon':<12s} {'Mean':>8s} {'Median':>8s} {'Green%':>8s}")
    print("  " + "-" * 40)
    for d in [1, 2, 3, 5, 10, 20]:
        vals = peaks[f"fwd_{d}d"].dropna()
        print(f"  {d:>2d}-day       {vals.mean():+7.3f}% {vals.median():+7.3f}% "
              f"{(vals > 0).mean()*100:7.1f}%")

    # ─────────────────────────────────────────────
    # SECTION 7: All Episodes Detail
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 7: ALL EPISODES (chronological)")
    print("=" * 70)

    print(f"\n  {'#':>3s} {'Start':<12s} {'Days':>5s} {'Peak Dev':>9s} {'Days→EMA':>9s} {'5d Fwd':>8s} {'10d Fwd':>8s} {'PO Zone':<14s}")
    print("  " + "-" * 74)
    for i, ep in enumerate(episodes):
        start = df.iloc[ep[0]]
        peak_dev_val = max(df["dev_pct"].iloc[idx] for idx in ep)
        f5 = start[f"fwd_5d"] if not pd.isna(start["fwd_5d"]) else np.nan
        f10 = start[f"fwd_10d"] if not pd.isna(start["fwd_10d"]) else np.nan
        dte = days_to_ema21[i] if not np.isnan(days_to_ema21[i]) else ">60"
        print(f"  {i+1:3d} {start.name.date()!s:<12s} {len(ep):5d} {peak_dev_val:+8.2f}% "
              f"{str(dte):>9s} {f5:+7.3f}% {f10:+7.3f}% {str(start['phase_zone']):<14s}")

    conn.close()
    print(f"\n{'=' * 70}")
    print("STUDY COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
