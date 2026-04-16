"""
4h Phase Oscillator as Reversion Filter for >4% Above Daily 21 EMA

Compare daily PO vs 4h PO signals for predicting mean reversion when
price is stretched >4% above the daily 21 EMA. The 4h PO should react
faster, potentially giving earlier and better reversion signals.
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/root/spy/spy.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    # ─────────────────────────────────────────────
    # Load daily data
    # ─────────────────────────────────────────────
    print("Loading daily data...")
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_21, "
        "phase_oscillator, phase_zone, leaving_distribution, leaving_extreme_up, "
        "compression, atr_trend, candle_bias, fast_cloud_bullish "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()
    daily = daily.dropna(subset=["ema_21"])
    daily["date"] = daily.index.date
    daily["dev_pct"] = (daily["close"] - daily["ema_21"]) / daily["ema_21"] * 100

    # Forward returns
    for d in [1, 2, 3, 5, 10, 20]:
        daily[f"fwd_{d}d"] = daily["close"].pct_change(d).shift(-d) * 100

    daily["prev_dev"] = daily["dev_pct"].shift(1)
    daily["d_po_prev"] = daily["phase_oscillator"].shift(1)
    daily["d_po_declining"] = (daily["phase_oscillator"] < daily["d_po_prev"]).astype(int)

    # ─────────────────────────────────────────────
    # Load 4h PO data
    # ─────────────────────────────────────────────
    print("Loading 4h data...")
    h4 = pd.read_sql_query(
        "SELECT timestamp, close as h4_close, phase_oscillator as po_4h, phase_zone as zone_4h, "
        "leaving_distribution as ld_4h, leaving_extreme_up as leu_4h, compression as comp_4h "
        "FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    h4 = h4.set_index("timestamp").sort_index()
    h4["date"] = h4.index.date
    h4["hour"] = h4.index.hour

    # Previous 4h bar's PO (for slope)
    h4["po_4h_prev"] = h4["po_4h"].shift(1)
    h4["po_4h_declining"] = (h4["po_4h"] < h4["po_4h_prev"]).astype(int)

    # PO change magnitude
    h4["po_4h_delta"] = h4["po_4h"] - h4["po_4h_prev"]

    # ─────────────────────────────────────────────
    # For each daily bar, attach 4h PO readings
    # ─────────────────────────────────────────────
    print("Merging 4h PO onto daily bars...\n")

    # Get the 16:00 (close) 4h bar for each day
    h4_close = h4[h4["hour"] == 16].copy()
    h4_close_map = {d: row for d, row in zip(h4_close["date"], h4_close.itertuples())}

    # Get the 12:00 (midday) 4h bar
    h4_mid = h4[h4["hour"] == 12].copy()
    h4_mid_map = {d: row for d, row in zip(h4_mid["date"], h4_mid.itertuples())}

    # Get the 08:00 (morning) 4h bar
    h4_morn = h4[h4["hour"] == 8].copy()
    h4_morn_map = {d: row for d, row in zip(h4_morn["date"], h4_morn.itertuples())}

    # Attach to daily
    po_4h_close = []
    po_4h_close_prev = []  # previous 4h bar (12:00)
    po_4h_declining_close = []
    po_4h_zone_close = []
    ld_4h_any = []  # leaving_distribution on any 4h bar that day
    leu_4h_any = []
    po_4h_mid_declining = []  # 12:00 bar declining vs 08:00
    po_4h_delta_close = []
    po_4h_peaked = []  # did 4h PO peak intraday (rise then fall)?

    for _, row in daily.iterrows():
        d = row["date"]

        # Close bar (16:00)
        if d in h4_close_map:
            cr = h4_close_map[d]
            po_4h_close.append(cr.po_4h)
            po_4h_declining_close.append(cr.po_4h_declining)
            po_4h_zone_close.append(cr.zone_4h)
            po_4h_delta_close.append(cr.po_4h_delta)
        else:
            po_4h_close.append(np.nan)
            po_4h_declining_close.append(np.nan)
            po_4h_zone_close.append(np.nan)
            po_4h_delta_close.append(np.nan)

        # Check if any 4h bar that day had leaving_distribution or leaving_extreme_up
        day_bars = h4[h4["date"] == d]
        ld_4h_any.append(1 if (day_bars["ld_4h"] == 1).any() else 0)
        leu_4h_any.append(1 if (day_bars["leu_4h"] == 1).any() else 0)

        # Midday declining
        if d in h4_mid_map and d in h4_morn_map:
            mid_po = h4_mid_map[d].po_4h
            morn_po = h4_morn_map[d].po_4h
            po_4h_mid_declining.append(1 if mid_po < morn_po else 0)
        else:
            po_4h_mid_declining.append(np.nan)

        # Did PO peak intraday? (any bar higher than both previous and next)
        if len(day_bars) >= 3:
            po_vals = day_bars["po_4h"].values
            peaked = False
            for k in range(1, len(po_vals)):
                if po_vals[k] < po_vals[k - 1]:
                    peaked = True
                    break
            po_4h_peaked.append(1 if peaked else 0)
        else:
            po_4h_peaked.append(np.nan)

    daily["po_4h"] = po_4h_close
    daily["po_4h_declining"] = po_4h_declining_close
    daily["po_4h_zone"] = po_4h_zone_close
    daily["po_4h_delta"] = po_4h_delta_close
    daily["ld_4h_fired"] = ld_4h_any
    daily["leu_4h_fired"] = leu_4h_any
    daily["po_4h_mid_dec"] = po_4h_mid_declining
    daily["po_4h_peaked"] = po_4h_peaked

    # ─────────────────────────────────────────────
    # Filter to >4% above daily EMA21
    # ─────────────────────────────────────────────
    above4 = daily[daily["dev_pct"] > 4].copy()
    n = len(above4)
    print(f"Days >4% above daily EMA21: {n}")
    print(f"Days with valid 4h PO: {above4['po_4h'].notna().sum()}\n")

    # ─────────────────────────────────────────────
    # SECTION 1: Head-to-Head — Daily PO vs 4h PO Declining
    # ─────────────────────────────────────────────
    print("=" * 70)
    print("SECTION 1: HEAD-TO-HEAD — DAILY PO vs 4h PO DECLINING")
    print("=" * 70)
    print("  (All days where close >4% above daily 21 EMA)\n")

    def signal_stats(label, mask, df_ref=above4):
        sub = df_ref[mask]
        sn = len(sub)
        if sn < 3:
            print(f"  {label:<45s} n={sn:3d} — too few")
            return
        results = []
        for d in [1, 3, 5, 10]:
            vals = sub[f"fwd_{d}d"].dropna()
            results.append(f"{vals.mean():+.3f}%")
        g1 = (sub["fwd_1d"].dropna() > 0).mean() * 100
        print(f"  {label:<45s} n={sn:3d}  1d={results[0]:>8s}  3d={results[1]:>8s}  "
              f"5d={results[2]:>8s}  10d={results[3]:>8s}  1d-green={g1:.0f}%")

    print("  --- Baseline ---")
    signal_stats("All days >4%", above4.index.notna())

    print("\n  --- Daily PO signals ---")
    signal_stats("Daily PO declining", above4["d_po_declining"] == 1)
    signal_stats("Daily PO NOT declining", above4["d_po_declining"] == 0)
    signal_stats("Daily leaving_distribution", above4["leaving_distribution"] == 1)

    print("\n  --- 4h PO signals (close bar, 16:00) ---")
    signal_stats("4h PO declining (16:00 vs 12:00)", above4["po_4h_declining"] == 1)
    signal_stats("4h PO NOT declining", above4["po_4h_declining"] == 0)
    signal_stats("4h PO leaving_distribution (any bar)", above4["ld_4h_fired"] == 1)
    signal_stats("4h PO leaving_extreme_up (any bar)", above4["leu_4h_fired"] == 1)

    print("\n  --- 4h PO intraday signals ---")
    signal_stats("4h PO peaked intraday (rolled over)", above4["po_4h_peaked"] == 1)
    signal_stats("4h PO did NOT peak (still rising)", above4["po_4h_peaked"] == 0)
    signal_stats("4h midday (12:00) declining vs AM", above4["po_4h_mid_dec"] == 1)

    # ─────────────────────────────────────────────
    # SECTION 2: 4h PO Zone Distribution While >4%
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 2: 4h PO ZONE WHILE >4% ABOVE EMA21")
    print("=" * 70)

    print(f"\n  {'4h PO Zone':<18s} {'n':>4s} {'1d Fwd':>8s} {'3d Fwd':>8s} {'5d Fwd':>8s} {'10d':>8s} {'1d Grn':>8s}")
    print("  " + "-" * 58)
    for zone in ["extended_up", "distribution", "neutral_up", "neutral",
                  "neutral_down", "accumulation", "extended_down"]:
        sub = above4[above4["po_4h_zone"] == zone]
        if len(sub) < 3:
            continue
        f1 = sub["fwd_1d"].dropna().mean()
        f3 = sub["fwd_3d"].dropna().mean()
        f5 = sub["fwd_5d"].dropna().mean()
        f10 = sub["fwd_10d"].dropna().mean()
        g1 = (sub["fwd_1d"].dropna() > 0).mean() * 100
        flag = " *" if len(sub) < 20 else ""
        print(f"  {zone:<18s} {len(sub):4d} {f1:+7.3f}% {f3:+7.3f}% {f5:+7.3f}% {f10:+7.3f}% {g1:7.1f}%{flag}")

    # ─────────────────────────────────────────────
    # SECTION 3: 4h PO Delta Magnitude
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 3: 4h PO DELTA MAGNITUDE (how fast is PO moving?)")
    print("=" * 70)

    valid_delta = above4.dropna(subset=["po_4h_delta"])
    print(f"\n  4h PO delta stats while >4%:")
    print(f"    Mean:   {valid_delta['po_4h_delta'].mean():+.2f}")
    print(f"    Median: {valid_delta['po_4h_delta'].median():+.2f}")
    print(f"    Std:    {valid_delta['po_4h_delta'].std():.2f}")

    # Bucket by delta magnitude
    print(f"\n  {'PO Delta Bucket':<25s} {'n':>4s} {'1d Fwd':>8s} {'3d Fwd':>8s} {'5d Fwd':>8s} {'1d Grn':>8s}")
    print("  " + "-" * 56)
    delta_buckets = [
        ("Big drop (< -10)", valid_delta["po_4h_delta"] < -10),
        ("Drop (-10 to -3)", (valid_delta["po_4h_delta"] >= -10) & (valid_delta["po_4h_delta"] < -3)),
        ("Small drop (-3 to 0)", (valid_delta["po_4h_delta"] >= -3) & (valid_delta["po_4h_delta"] < 0)),
        ("Small rise (0 to +3)", (valid_delta["po_4h_delta"] >= 0) & (valid_delta["po_4h_delta"] < 3)),
        ("Rise (3 to 10)", (valid_delta["po_4h_delta"] >= 3) & (valid_delta["po_4h_delta"] < 10)),
        ("Big rise (> +10)", valid_delta["po_4h_delta"] >= 10),
    ]
    for label, mask in delta_buckets:
        sub = valid_delta[mask]
        if len(sub) < 3:
            continue
        f1 = sub["fwd_1d"].dropna().mean()
        f3 = sub["fwd_3d"].dropna().mean()
        f5 = sub["fwd_5d"].dropna().mean()
        g1 = (sub["fwd_1d"].dropna() > 0).mean() * 100
        flag = " *" if len(sub) < 15 else ""
        print(f"  {label:<25s} {len(sub):4d} {f1:+7.3f}% {f3:+7.3f}% {f5:+7.3f}% {g1:7.1f}%{flag}")

    # ─────────────────────────────────────────────
    # SECTION 4: Combo Signals with 4h PO
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 4: COMBINATION SIGNALS WITH 4h PO")
    print("=" * 70)

    print("\n  --- Stacking 4h PO with other conditions ---")

    # 4h PO declining + red candle
    signal_stats("4h PO declining + red candle",
                 (above4["po_4h_declining"] == 1) & (above4["close"] < above4["open"]))

    # 4h PO declining + deviation shrinking
    above4_dev_shrink = above4["dev_pct"] < above4["prev_dev"]
    signal_stats("4h PO declining + dev shrinking",
                 (above4["po_4h_declining"] == 1) & above4_dev_shrink)

    # 4h PO peaked + red candle
    signal_stats("4h PO peaked intraday + red candle",
                 (above4["po_4h_peaked"] == 1) & (above4["close"] < above4["open"]))

    # 4h PO peaked + dev shrinking
    signal_stats("4h PO peaked + dev shrinking",
                 (above4["po_4h_peaked"] == 1) & above4_dev_shrink)

    # 4h leaving_distribution + dev shrinking
    signal_stats("4h LD fired + dev shrinking",
                 (above4["ld_4h_fired"] == 1) & above4_dev_shrink)

    # 4h PO in distribution + declining
    signal_stats("4h PO in distribution + declining",
                 (above4["po_4h_zone"] == "distribution") & (above4["po_4h_declining"] == 1))

    # 4h PO in neutral (dropped from distribution) while daily still >4%
    signal_stats("4h PO dropped to neutral zone",
                 (above4["po_4h_zone"].isin(["neutral", "neutral_up"])) & (above4["po_4h_declining"] == 1))

    # Daily PO declining + 4h PO declining (both agree)
    signal_stats("BOTH daily & 4h PO declining",
                 (above4["d_po_declining"] == 1) & (above4["po_4h_declining"] == 1))

    # 4h PO declining but daily PO still rising (4h leads)
    signal_stats("4h PO declining, daily PO still rising (4h leads)",
                 (above4["po_4h_declining"] == 1) & (above4["d_po_declining"] == 0))

    # ─────────────────────────────────────────────
    # SECTION 5: Direct Comparison — Same Signal, Different Timeframe
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 5: DIRECT COMPARISON — DECLINING PO: DAILY vs 4h")
    print("=" * 70)

    # For each signal, show 1d/3d/5d side by side
    print(f"\n  {'Metric':<25s} {'Daily PO Dec':>14s} {'4h PO Dec':>14s} {'4h Peaked':>14s} {'All >4%':>14s}")
    print("  " + "-" * 83)

    masks = {
        "Daily PO Dec": above4["d_po_declining"] == 1,
        "4h PO Dec": above4["po_4h_declining"] == 1,
        "4h Peaked": above4["po_4h_peaked"] == 1,
        "All >4%": above4.index.notna(),
    }

    for horizon in [1, 3, 5, 10]:
        row = f"  {f'{horizon}d mean return':<25s}"
        for label in ["Daily PO Dec", "4h PO Dec", "4h Peaked", "All >4%"]:
            sub = above4[masks[label]]
            vals = sub[f"fwd_{horizon}d"].dropna()
            row += f" {vals.mean():+13.3f}%"
        print(row)

    row = f"  {'1d green %':<25s}"
    for label in ["Daily PO Dec", "4h PO Dec", "4h Peaked", "All >4%"]:
        sub = above4[masks[label]]
        vals = sub["fwd_1d"].dropna()
        g = (vals > 0).mean() * 100
        row += f" {g:13.1f}%"
    print(row)

    row = f"  {'n':<25s}"
    for label in ["Daily PO Dec", "4h PO Dec", "4h Peaked", "All >4%"]:
        sub = above4[masks[label]]
        row += f" {len(sub):>14d}"
    print(row)

    # ─────────────────────────────────────────────
    # SECTION 6: Frequency — How Often Does Each Signal Fire?
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 6: SIGNAL FREQUENCY WHILE >4%")
    print("=" * 70)

    print(f"\n  {'Signal':<45s} {'Fires':>6s} {'%':>8s}")
    print("  " + "-" * 61)
    signals = [
        ("Daily PO declining", above4["d_po_declining"] == 1),
        ("4h PO declining (close bar)", above4["po_4h_declining"] == 1),
        ("4h PO peaked intraday", above4["po_4h_peaked"] == 1),
        ("4h PO midday declining", above4["po_4h_mid_dec"] == 1),
        ("4h leaving_distribution fired", above4["ld_4h_fired"] == 1),
        ("4h leaving_extreme_up fired", above4["leu_4h_fired"] == 1),
        ("Daily leaving_distribution", above4["leaving_distribution"] == 1),
        ("Red candle (close < open)", above4["close"] < above4["open"]),
        ("Deviation shrinking", above4["dev_pct"] < above4["prev_dev"]),
    ]
    for label, mask in signals:
        count = mask.sum()
        pct = count / n * 100
        print(f"  {label:<45s} {count:6d} {pct:7.1f}%")

    # ─────────────────────────────────────────────
    # SECTION 7: Episode-Level Analysis with 4h PO
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 7: FIRST 4h PO DECLINE IN EACH EPISODE")
    print("=" * 70)
    print("  (For each >4% episode: when does the 4h PO first decline?)\n")

    # Re-identify episodes
    episodes = []
    current_ep = []
    for i in range(len(daily)):
        if daily["dev_pct"].iloc[i] > 4:
            current_ep.append(i)
        else:
            if current_ep:
                episodes.append(current_ep)
                current_ep = []
    if current_ep:
        episodes.append(current_ep)

    # For each episode, find first day where 4h PO declined
    early_signal_fwd = []
    no_signal_fwd = []

    print(f"  {'#':>3s} {'Start':<12s} {'EpLen':>5s} {'1st 4h Dec':>11s} {'Day#':>5s} {'5d Fwd':>8s} {'10d Fwd':>9s}")
    print("  " + "-" * 58)

    for ep_num, ep in enumerate(episodes):
        start_row = daily.iloc[ep[0]]
        ep_len = len(ep)

        first_decline_day = None
        for j, idx in enumerate(ep):
            row = daily.iloc[idx]
            if row.get("po_4h_declining") == 1:
                first_decline_day = j
                decline_row = row
                break

        if first_decline_day is not None:
            f5 = decline_row.get("fwd_5d", np.nan)
            f10 = decline_row.get("fwd_10d", np.nan)
            if not pd.isna(f5):
                early_signal_fwd.append((f5, decline_row.get("fwd_10d", np.nan)))
            day_label = f"Day {first_decline_day}"
            print(f"  {ep_num+1:3d} {start_row.name.date()!s:<12s} {ep_len:5d} {day_label:>11s} {first_decline_day:5d} "
                  f"{f5:+7.3f}% {f10:+8.3f}%")
        else:
            f5 = start_row.get("fwd_5d", np.nan)
            f10 = start_row.get("fwd_10d", np.nan)
            if not pd.isna(f5):
                no_signal_fwd.append((f5, f10))
            print(f"  {ep_num+1:3d} {start_row.name.date()!s:<12s} {ep_len:5d} {'never':>11s} {'—':>5s} "
                  f"{f5:+7.3f}% {f10:+8.3f}%")

    if early_signal_fwd:
        f5s = [x[0] for x in early_signal_fwd]
        f10s = [x[1] for x in early_signal_fwd if not np.isnan(x[1])]
        print(f"\n  Episodes with 4h PO decline signal:")
        print(f"    Mean 5d fwd:  {np.mean(f5s):+.3f}%  (n={len(f5s)})")
        print(f"    Mean 10d fwd: {np.mean(f10s):+.3f}%  (n={len(f10s)})")
    if no_signal_fwd:
        f5s = [x[0] for x in no_signal_fwd]
        f10s = [x[1] for x in no_signal_fwd if not np.isnan(x[1])]
        print(f"  Episodes WITHOUT 4h PO decline signal:")
        print(f"    Mean 5d fwd:  {np.mean(f5s):+.3f}%  (n={len(f5s)})")
        print(f"    Mean 10d fwd: {np.mean(f10s):+.3f}%  (n={len(f10s)})")

    conn.close()
    print(f"\n{'=' * 70}")
    print("STUDY COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
