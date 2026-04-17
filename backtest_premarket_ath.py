"""
Backtest: Premarket All-Time Highs as Short Opportunities

Thesis: When SPY makes a new all-time high during premarket (before 9:30 AM ET),
it tends to fade during the morning trading session — making these good short entries.

Focus: Max morning drawdown from the open (the profit potential for a short).
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # ═══════════════════════════════════════════════════════════════
    # 1. Load daily close context
    # ═══════════════════════════════════════════════════════════════
    print("Loading daily data...", flush=True)
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close FROM candles_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()
    daily["date"] = daily.index.date
    daily["prev_close"] = daily["close"].shift(1)

    # ═══════════════════════════════════════════════════════════════
    # 2. Load 10m indicator data (all hours)
    # ═══════════════════════════════════════════════════════════════
    print("Loading 10m indicator data...", flush=True)
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume, "
        "prev_close as atr_prev_close, atr_14, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "phase_oscillator, phase_zone, ema_21, ema_48, "
        "fast_cloud_bullish, slow_cloud_bullish, compression "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date

    session_stats = df.groupby("date").agg(session_high=("high", "max"))
    session_stats["running_ath"] = session_stats["session_high"].cummax()
    session_stats["prior_ath"] = session_stats["running_ath"].shift(1)
    session_stats["prev_day_new_ath"] = (
        session_stats["session_high"] == session_stats["running_ath"]
    ).shift(1).fillna(False)
    prev_close_by_date = daily.set_index("date")["prev_close"]

    date_info = {}
    for date, row in session_stats.iterrows():
        date_info[date] = {
            "prior_ath": row["prior_ath"],
            "prev_day_new_ath": row["prev_day_new_ath"],
            "prev_close": prev_close_by_date.get(date, np.nan),
        }

    # ═══════════════════════════════════════════════════════════════
    # 3. Process each day
    # ═══════════════════════════════════════════════════════════════
    print("Processing days...\n", flush=True)

    premarket_ath_days = []
    rth_ath_days = []
    non_ath_days = []

    # Time points (minutes from open) for running-low profile
    time_points = [10, 20, 30, 40, 50, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390]

    for date, group in df.groupby("date"):
        info = date_info.get(date)
        if info is None or pd.isna(info["prior_ath"]):
            continue

        prior_ath = info["prior_ath"]
        prev_close = info["prev_close"]

        premarket = group.between_time("04:00", "09:29")
        rth = group.between_time("09:30", "15:59")

        if len(rth) == 0:
            continue

        open_price = rth.iloc[0]["open"]
        premarket_high = premarket["high"].max() if len(premarket) > 0 else 0
        premarket_n_bars = len(premarket)
        rth_high = rth["high"].max()
        rth_low = rth["low"].min()

        is_premarket_ath = (premarket_n_bars > 0) and (premarket_high > prior_ath)
        is_rth_ath_only = (not is_premarket_ath) and (rth_high > prior_ath)

        morning = rth[rth.index.time <= pd.Timestamp("11:59").time()]
        first_hour = rth[rth.index.time <= pd.Timestamp("10:29").time()]
        first_30 = rth[rth.index.time <= pd.Timestamp("09:59").time()]

        if len(morning) == 0:
            continue

        d = {
            "date": date,
            "prior_ath": prior_ath,
            "prev_close": prev_close,
            "premarket_high": premarket_high if premarket_n_bars > 0 else np.nan,
            "premarket_bars": premarket_n_bars,
            "open": open_price,
        }

        # ── Max drawdown metrics (core of this study) ──
        d["max_dd_30m"] = (first_30["low"].min() - open_price) / open_price * 100 if len(first_30) > 0 else np.nan
        d["max_dd_1h"] = (first_hour["low"].min() - open_price) / open_price * 100 if len(first_hour) > 0 else np.nan
        d["max_dd_morning"] = (morning["low"].min() - open_price) / open_price * 100
        d["max_dd_day"] = (rth_low - open_price) / open_price * 100

        # Max run-up (adverse for shorts)
        d["max_up_30m"] = (first_30["high"].max() - open_price) / open_price * 100 if len(first_30) > 0 else np.nan
        d["max_up_1h"] = (first_hour["high"].max() - open_price) / open_price * 100 if len(first_hour) > 0 else np.nan
        d["max_up_morning"] = (morning["high"].max() - open_price) / open_price * 100
        d["max_up_day"] = (rth_high - open_price) / open_price * 100

        # Time to morning low (minutes from open)
        morning_low_ts = morning.loc[morning["low"] == morning["low"].min()].index[0]
        d["time_to_morning_low_min"] = (morning_low_ts - rth.index[0]).total_seconds() / 60

        # Did we hit specific drawdown thresholds during morning?
        d["hit_10bps_morning"] = int(d["max_dd_morning"] <= -0.10)
        d["hit_25bps_morning"] = int(d["max_dd_morning"] <= -0.25)
        d["hit_50bps_morning"] = int(d["max_dd_morning"] <= -0.50)
        d["hit_75bps_morning"] = int(d["max_dd_morning"] <= -0.75)
        d["hit_100bps_morning"] = int(d["max_dd_morning"] <= -1.00)

        d["hit_10bps_day"] = int(d["max_dd_day"] <= -0.10)
        d["hit_25bps_day"] = int(d["max_dd_day"] <= -0.25)
        d["hit_50bps_day"] = int(d["max_dd_day"] <= -0.50)
        d["hit_75bps_day"] = int(d["max_dd_day"] <= -0.75)
        d["hit_100bps_day"] = int(d["max_dd_day"] <= -1.00)

        # Time to hit thresholds (minutes from open, NaN if never hit)
        for thresh, label in [(-0.10, "10bps"), (-0.25, "25bps"), (-0.50, "50bps")]:
            thresh_price = open_price * (1 + thresh / 100)
            hits = rth[rth["low"] <= thresh_price]
            if len(hits) > 0:
                d[f"time_to_{label}_min"] = (hits.index[0] - rth.index[0]).total_seconds() / 60
            else:
                d[f"time_to_{label}_min"] = np.nan

        # Running-low profile at each time point
        open_ts = rth.index[0]
        for mins in time_points:
            target_ts = open_ts + pd.Timedelta(minutes=mins)
            mask = rth.index <= target_ts
            if mask.any():
                d[f"running_low_{mins}m"] = (rth.loc[mask]["low"].min() - open_price) / open_price * 100
                d[f"running_high_{mins}m"] = (rth.loc[mask]["high"].max() - open_price) / open_price * 100

        # Premarket-ATH-specific metrics
        if is_premarket_ath:
            d["ath_extension_pct"] = (premarket_high - prior_ath) / prior_ath * 100
            d["ath_to_open_pct"] = (open_price - premarket_high) / premarket_high * 100
            d["ath_reclaimed_morning"] = int(morning["high"].max() >= premarket_high)
            d["ath_reclaimed_rth"] = int(rth_high >= premarket_high)
            d["prev_day_was_ath"] = int(info["prev_day_new_ath"])

            if prev_close and prev_close > 0:
                d["gap_pct"] = (open_price - prev_close) / prev_close * 100

            # Indicator context at open
            open_bar = rth.iloc[0]
            d["po_at_open"] = open_bar.get("phase_oscillator", np.nan)
            d["po_zone_at_open"] = open_bar.get("phase_zone", "")
            d["fast_cloud_bull"] = open_bar.get("fast_cloud_bullish", np.nan)
            d["slow_cloud_bull"] = open_bar.get("slow_cloud_bullish", np.nan)
            d["compression_at_open"] = open_bar.get("compression", 0)

            if pd.notna(open_bar.get("atr_14")) and open_bar["atr_14"] > 0:
                atr_prev_close = open_bar.get("atr_prev_close", np.nan)
                if pd.notna(atr_prev_close) and atr_prev_close > 0:
                    d["open_atr_pct"] = (open_price - atr_prev_close) / open_bar["atr_14"] * 100

        # Classify
        if is_premarket_ath:
            premarket_ath_days.append(d)
        elif is_rth_ath_only:
            rth_ath_days.append(d)
        else:
            non_ath_days.append(d)

    # ═══════════════════════════════════════════════════════════════
    # 4. RESULTS
    # ═══════════════════════════════════════════════════════════════
    pm = pd.DataFrame(premarket_ath_days)
    rth_df = pd.DataFrame(rth_ath_days)
    non = pd.DataFrame(non_ath_days)

    print("=" * 75)
    print("  PREMARKET ALL-TIME HIGHS AS SHORT OPPORTUNITIES — SPY 2000–2026")
    print("  Focus: Max morning drawdown from the open")
    print("=" * 75)

    total = len(pm) + len(rth_df) + len(non)
    print(f"\n  Universe: {total:,} trading days")
    print(f"  ├─ Premarket ATH days:  {len(pm):>5d}  ({len(pm)/total*100:.1f}%)")
    print(f"  ├─ RTH-only ATH days:   {len(rth_df):>5d}  ({len(rth_df)/total*100:.1f}%)")
    print(f"  └─ Non-ATH days:        {len(non):>5d}  ({len(non)/total*100:.1f}%)")
    print(f"\n  Date range: {pm['date'].min()} → {pm['date'].max()}")

    # ─────────────────────────────────────────────────────
    # A. MAX DRAWDOWN COMPARISON
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  A. MAX DRAWDOWN FROM OPEN (short profit potential)")
    print(f"{'─' * 75}")

    print(f"\n  {'Window':<18s} {'PM ATH':>20s} {'RTH ATH':>20s} {'Non-ATH':>20s}")
    print("  " + "-" * 78)

    for col, label in [
        ("max_dd_30m", "First 30 min"),
        ("max_dd_1h", "First hour"),
        ("max_dd_morning", "Morning (→12:00)"),
        ("max_dd_day", "Full day"),
    ]:
        vals = []
        for frame in [pm, rth_df, non]:
            if col in frame.columns and len(frame) > 0:
                v = frame[col].dropna()
                vals.append(f"{v.mean():>+.3f}% / {v.median():>+.3f}%")
            else:
                vals.append(f"{'N/A':>20s}")
        print(f"  {label:<18s} {vals[0]:>20s} {vals[1]:>20s} {vals[2]:>20s}")

    print(f"\n  (format: mean / median)")

    # ─────────────────────────────────────────────────────
    # B. DRAWDOWN THRESHOLD HIT RATES
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  B. DRAWDOWN THRESHOLD HIT RATES (% of days price drops at least X)")
    print(f"{'─' * 75}")

    print(f"\n  {'Threshold':<14s} {'PM ATH AM':>10s} {'PM ATH Day':>11s}  {'Non-ATH AM':>11s} {'Non-ATH Day':>12s}")
    print("  " + "-" * 60)

    for thresh, label in [
        ("10bps", "≥ 0.10%"),
        ("25bps", "≥ 0.25%"),
        ("50bps", "≥ 0.50%"),
        ("75bps", "≥ 0.75%"),
        ("100bps", "≥ 1.00%"),
    ]:
        pm_am = pm[f"hit_{thresh}_morning"].mean() * 100
        pm_day = pm[f"hit_{thresh}_day"].mean() * 100
        non_am = non[f"hit_{thresh}_morning"].mean() * 100
        non_day = non[f"hit_{thresh}_day"].mean() * 100
        print(f"  {label:<14s} {pm_am:>9.1f}% {pm_day:>10.1f}%  {non_am:>10.1f}% {non_day:>11.1f}%")

    # ─────────────────────────────────────────────────────
    # C. TIME TO DRAWDOWN THRESHOLDS
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  C. SPEED: Time to hit drawdown thresholds (minutes from open)")
    print(f"{'─' * 75}")

    print(f"\n  {'Threshold':<14s} {'Mean':>8s} {'Median':>8s} {'25th%':>8s} {'75th%':>8s} {'n hit':>6s} {'of':>5s}")
    print("  " + "-" * 55)

    for thresh, label in [("10bps", "≥ 0.10%"), ("25bps", "≥ 0.25%"), ("50bps", "≥ 0.50%")]:
        col = f"time_to_{thresh}_min"
        valid = pm[col].dropna()
        if len(valid) > 0:
            print(f"  {label:<14s} {valid.mean():>7.0f}m {valid.median():>7.0f}m "
                  f"{valid.quantile(0.25):>7.0f}m {valid.quantile(0.75):>7.0f}m "
                  f"{len(valid):>5d} {len(pm):>5d}")

    # ─────────────────────────────────────────────────────
    # D. TIME TO MORNING LOW
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  D. WHEN DOES THE MORNING LOW HAPPEN? (minutes from open)")
    print(f"{'─' * 75}")

    for label, frame in [("PM ATH", pm), ("Non-ATH", non)]:
        col = "time_to_morning_low_min"
        if col in frame.columns:
            v = frame[col]
            print(f"\n  {label}: mean {v.mean():.0f}m, median {v.median():.0f}m, "
                  f"25th {v.quantile(0.25):.0f}m, 75th {v.quantile(0.75):.0f}m")

            # Distribution by half hour
            buckets = [(0, 30, "0-30m"), (30, 60, "30-60m"), (60, 90, "60-90m"),
                       (90, 120, "90-120m"), (120, 150, "120-150m")]
            print(f"    ", end="")
            for lo, hi, bl in buckets:
                n = ((v >= lo) & (v < hi)).sum()
                pct = n / len(v) * 100
                print(f"{bl}: {pct:.0f}%   ", end="")
            print()

    # ─────────────────────────────────────────────────────
    # E. RUNNING LOW PROFILE (cumulative worst at each time point)
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  E. RUNNING LOW PROFILE: worst drawdown from open by time elapsed")
    print(f"{'─' * 75}")

    print(f"\n  {'Time':>6s}  {'PM ATH Mean':>12s} {'PM ATH Med':>12s}  {'Non-ATH Mean':>13s} {'Non-ATH Med':>12s}  {'PM Max Up':>10s}")
    print("  " + "-" * 72)

    for mins in time_points:
        col = f"running_low_{mins}m"
        hi_col = f"running_high_{mins}m"
        if col not in pm.columns:
            continue
        pm_v = pm[col].dropna()
        non_v = non[col].dropna()
        pm_hi = pm[hi_col].dropna() if hi_col in pm.columns else pd.Series()
        h = mins // 60
        m = mins % 60
        tlabel = f"{h}h{m:02d}m" if h > 0 else f"{m}m"
        pm_hi_mean = pm_hi.mean() if len(pm_hi) > 0 else np.nan
        print(f"  {tlabel:>6s}  {pm_v.mean():>+11.3f}% {pm_v.median():>+11.3f}%  "
              f"{non_v.mean():>+12.3f}% {non_v.median():>+11.3f}%  {pm_hi_mean:>+9.3f}%")

    # ─────────────────────────────────────────────────────
    # F. DRAWDOWN DISTRIBUTION
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  F. DISTRIBUTION: Max morning drawdown (PM ATH vs Non-ATH)")
    print(f"{'─' * 75}")

    buckets = [
        (-999, -1.5, "< -1.50%"),
        (-1.5, -1.0, "-1.50 to -1.00%"),
        (-1.0, -0.75, "-1.00 to -0.75%"),
        (-0.75, -0.50, "-0.75 to -0.50%"),
        (-0.50, -0.25, "-0.50 to -0.25%"),
        (-0.25, -0.10, "-0.25 to -0.10%"),
        (-0.10, 0.0, "-0.10 to  0.00%"),
        (0.0, 999, " 0.00% (no dd)"),
    ]

    pm_vals = pm["max_dd_morning"]
    non_vals = non["max_dd_morning"]

    print(f"\n  {'Max DD Bucket':<22s} {'PM ATH':>8s} {'%':>6s}  {'Non-ATH':>8s} {'%':>6s}")
    print("  " + "-" * 55)
    for lo, hi, label in buckets:
        pm_n = ((pm_vals >= lo) & (pm_vals < hi)).sum()
        pm_pct = pm_n / len(pm_vals) * 100
        non_n = ((non_vals >= lo) & (non_vals < hi)).sum()
        non_pct = non_n / len(non_vals) * 100
        pm_bar = "█" * int(pm_pct / 2)
        print(f"  {label:<22s} {pm_n:>7d} {pm_pct:>5.1f}%  {non_n:>7d} {non_pct:>5.1f}%  {pm_bar}")

    # ─────────────────────────────────────────────────────
    # G. BY ATH EXTENSION SIZE
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  G. MAX DRAWDOWN BY ATH EXTENSION SIZE")
    print(f"{'─' * 75}")

    ext_buckets = [
        (0, 0.05, "Marginal (<0.05%)"),
        (0.05, 0.15, "Small (0.05–0.15%)"),
        (0.15, 0.40, "Medium (0.15–0.40%)"),
        (0.40, 999, "Large (≥0.40%)"),
    ]

    print(f"\n  {'Extension':<22s} {'N':>4s}  {'DD 30m':>9s} {'DD 1h':>9s} {'DD Morn':>9s} {'DD Day':>9s}  {'≥25bp':>5s} {'≥50bp':>5s}")
    print("  " + "-" * 78)

    for lo, hi, label in ext_buckets:
        sub = pm[(pm["ath_extension_pct"] >= lo) & (pm["ath_extension_pct"] < hi)]
        if len(sub) < 3:
            continue
        dd30 = sub["max_dd_30m"].dropna().mean()
        dd1h = sub["max_dd_1h"].dropna().mean()
        ddam = sub["max_dd_morning"].mean()
        ddday = sub["max_dd_day"].mean()
        h25 = sub["hit_25bps_morning"].mean() * 100
        h50 = sub["hit_50bps_morning"].mean() * 100
        print(f"  {label:<22s} {len(sub):4d}  {dd30:>+8.3f}% {dd1h:>+8.3f}% {ddam:>+8.3f}% {ddday:>+8.3f}%  {h25:>4.0f}% {h50:>4.0f}%")

    # ─────────────────────────────────────────────────────
    # H. BY GAP SIZE
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  H. MAX DRAWDOWN BY GAP SIZE (prev close → open)")
    print(f"{'─' * 75}")

    gap_buckets = [
        (-999, 0, "Gap down"),
        (0, 0.25, "Tiny up (0–0.25%)"),
        (0.25, 0.5, "Small up (0.25–0.5%)"),
        (0.5, 999, "Large up (≥0.5%)"),
    ]

    valid_gap = pm.dropna(subset=["gap_pct"])
    print(f"\n  {'Gap':<22s} {'N':>4s}  {'DD 30m':>9s} {'DD 1h':>9s} {'DD Morn':>9s} {'DD Day':>9s}  {'≥25bp':>5s} {'≥50bp':>5s}")
    print("  " + "-" * 78)

    for lo, hi, label in gap_buckets:
        sub = valid_gap[(valid_gap["gap_pct"] >= lo) & (valid_gap["gap_pct"] < hi)]
        if len(sub) < 3:
            continue
        dd30 = sub["max_dd_30m"].dropna().mean()
        dd1h = sub["max_dd_1h"].dropna().mean()
        ddam = sub["max_dd_morning"].mean()
        ddday = sub["max_dd_day"].mean()
        h25 = sub["hit_25bps_morning"].mean() * 100
        h50 = sub["hit_50bps_morning"].mean() * 100
        print(f"  {label:<22s} {len(sub):4d}  {dd30:>+8.3f}% {dd1h:>+8.3f}% {ddam:>+8.3f}% {ddday:>+8.3f}%  {h25:>4.0f}% {h50:>4.0f}%")

    # ─────────────────────────────────────────────────────
    # I. BY PHASE OSCILLATOR ZONE
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  I. MAX DRAWDOWN BY PHASE OSCILLATOR ZONE AT OPEN")
    print(f"{'─' * 75}")

    valid_po = pm.dropna(subset=["po_at_open"])
    if len(valid_po) > 10:
        print(f"\n  {'PO Zone':<20s} {'N':>4s}  {'DD 30m':>9s} {'DD 1h':>9s} {'DD Morn':>9s}  {'≥25bp':>5s} {'≥50bp':>5s}")
        print("  " + "-" * 65)

        zone_order = ["extended_down", "accumulation", "neutral_down", "neutral",
                       "neutral_up", "distribution", "extended_up"]
        for zone in zone_order:
            sub = valid_po[valid_po["po_zone_at_open"] == zone]
            if len(sub) < 3:
                continue
            dd30 = sub["max_dd_30m"].dropna().mean()
            dd1h = sub["max_dd_1h"].dropna().mean()
            ddam = sub["max_dd_morning"].mean()
            h25 = sub["hit_25bps_morning"].mean() * 100
            h50 = sub["hit_50bps_morning"].mean() * 100
            print(f"  {zone:<20s} {len(sub):4d}  {dd30:>+8.3f}% {dd1h:>+8.3f}% {ddam:>+8.3f}%  {h25:>4.0f}% {h50:>4.0f}%")

    # ─────────────────────────────────────────────────────
    # J. BY ATR LEVEL POSITION AT OPEN
    # ─────────────────────────────────────────────────────
    if "open_atr_pct" in pm.columns:
        print(f"\n{'─' * 75}")
        print("  J. MAX DRAWDOWN BY OPEN POSITION IN ATR FRAMEWORK")
        print(f"{'─' * 75}")

        valid_atr = pm.dropna(subset=["open_atr_pct"])
        atr_buckets = [
            (-999, 0, "Below prev close"),
            (0, 23.6, "0–Trigger (0–23.6%)"),
            (23.6, 38.2, "Trigger–GG (23.6–38.2%)"),
            (38.2, 61.8, "GG zone (38.2–61.8%)"),
            (61.8, 100, "GG exit–ATR (61.8–100%)"),
            (100, 999, "Beyond full ATR"),
        ]

        print(f"\n  {'ATR Position':<28s} {'N':>4s}  {'DD 30m':>9s} {'DD 1h':>9s} {'DD Morn':>9s}  {'≥25bp':>5s} {'≥50bp':>5s}")
        print("  " + "-" * 72)

        for lo, hi, label in atr_buckets:
            sub = valid_atr[(valid_atr["open_atr_pct"] >= lo) & (valid_atr["open_atr_pct"] < hi)]
            if len(sub) < 3:
                continue
            dd30 = sub["max_dd_30m"].dropna().mean()
            dd1h = sub["max_dd_1h"].dropna().mean()
            ddam = sub["max_dd_morning"].mean()
            h25 = sub["hit_25bps_morning"].mean() * 100
            h50 = sub["hit_50bps_morning"].mean() * 100
            print(f"  {label:<28s} {len(sub):4d}  {dd30:>+8.3f}% {dd1h:>+8.3f}% {ddam:>+8.3f}%  {h25:>4.0f}% {h50:>4.0f}%")

    # ─────────────────────────────────────────────────────
    # K. FRESH VS CONTINUATION ATH
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  K. FRESH ATH vs CONTINUATION ATH")
    print(f"{'─' * 75}")

    if "prev_day_was_ath" in pm.columns:
        for label, sub in [("Fresh (prev day NOT ATH)", pm[pm["prev_day_was_ath"] == 0]),
                           ("Continuation (prev day WAS ATH)", pm[pm["prev_day_was_ath"] == 1])]:
            if len(sub) < 5:
                continue
            print(f"\n  {label} (n={len(sub)})")
            print(f"    DD 30m:    mean {sub['max_dd_30m'].dropna().mean():>+.3f}%, med {sub['max_dd_30m'].dropna().median():>+.3f}%")
            print(f"    DD 1h:     mean {sub['max_dd_1h'].dropna().mean():>+.3f}%, med {sub['max_dd_1h'].dropna().median():>+.3f}%")
            print(f"    DD Morn:   mean {sub['max_dd_morning'].mean():>+.3f}%, med {sub['max_dd_morning'].median():>+.3f}%")
            print(f"    DD Day:    mean {sub['max_dd_day'].mean():>+.3f}%, med {sub['max_dd_day'].median():>+.3f}%")
            h25 = sub["hit_25bps_morning"].mean() * 100
            h50 = sub["hit_50bps_morning"].mean() * 100
            print(f"    Hit ≥25bp (AM): {h25:.0f}%   Hit ≥50bp (AM): {h50:.0f}%")

    # ─────────────────────────────────────────────────────
    # L. RISK/REWARD (adverse excursion vs favorable)
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  L. RISK/REWARD: Max adverse (up) vs favorable (down) excursion")
    print(f"{'─' * 75}")

    for window, dd_col, up_col in [
        ("First 30m", "max_dd_30m", "max_up_30m"),
        ("First hour", "max_dd_1h", "max_up_1h"),
        ("Morning", "max_dd_morning", "max_up_morning"),
        ("Full day", "max_dd_day", "max_up_day"),
    ]:
        pm_dd = pm[dd_col].dropna().abs()
        pm_up = pm[up_col].dropna()
        non_dd = non[dd_col].dropna().abs()
        non_up = non[up_col].dropna()

        pm_rr = (pm_dd / pm_up.replace(0, np.nan)).dropna()
        non_rr = (non_dd / non_up.replace(0, np.nan)).dropna()

        print(f"\n  {window}:")
        print(f"    PM ATH  — down {pm_dd.mean():>+.3f}%, up {pm_up.mean():>+.3f}%, R:R med {pm_rr.median():.2f}")
        print(f"    Non-ATH — down {non_dd.mean():>+.3f}%, up {non_up.mean():>+.3f}%, R:R med {non_rr.median():.2f}")

    # ─────────────────────────────────────────────────────
    # M. YEAR-BY-YEAR
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  M. YEAR-BY-YEAR (Premarket ATH days)")
    print(f"{'─' * 75}")

    pm["year"] = pm["date"].apply(lambda d: d.year)
    print(f"\n  {'Year':<6s} {'N':>4s}  {'DD 30m':>9s} {'DD 1h':>9s} {'DD Morn':>9s} {'DD Day':>9s}  {'≥25bp':>5s}")
    print("  " + "-" * 58)
    for year, ydf in pm.groupby("year"):
        if len(ydf) == 0:
            continue
        dd30 = ydf["max_dd_30m"].dropna().mean()
        dd1h = ydf["max_dd_1h"].dropna().mean()
        ddam = ydf["max_dd_morning"].mean()
        ddday = ydf["max_dd_day"].mean()
        h25 = ydf["hit_25bps_morning"].mean() * 100
        print(f"  {year:<6d} {len(ydf):4d}  {dd30:>+8.3f}% {dd1h:>+8.3f}% {ddam:>+8.3f}% {ddday:>+8.3f}%  {h25:>4.0f}%")

    # ─────────────────────────────────────────────────────
    # N. DAY OF WEEK
    # ─────────────────────────────────────────────────────
    print(f"\n{'─' * 75}")
    print("  N. BY DAY OF WEEK")
    print(f"{'─' * 75}")

    pm["dow"] = pm["date"].apply(lambda d: d.weekday())
    dow_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
    print(f"\n  {'Day':<5s} {'N':>4s}  {'DD 30m':>9s} {'DD 1h':>9s} {'DD Morn':>9s}  {'≥25bp':>5s} {'≥50bp':>5s}")
    print("  " + "-" * 52)
    for dow in range(5):
        sub = pm[pm["dow"] == dow]
        if len(sub) < 3:
            continue
        dd30 = sub["max_dd_30m"].dropna().mean()
        dd1h = sub["max_dd_1h"].dropna().mean()
        ddam = sub["max_dd_morning"].mean()
        h25 = sub["hit_25bps_morning"].mean() * 100
        h50 = sub["hit_50bps_morning"].mean() * 100
        print(f"  {dow_names[dow]:<5s} {len(sub):4d}  {dd30:>+8.3f}% {dd1h:>+8.3f}% {ddam:>+8.3f}%  {h25:>4.0f}% {h50:>4.0f}%")

    # ═══════════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'=' * 75}")
    print("  VERDICT")
    print(f"{'=' * 75}")

    pm_dd_am = pm["max_dd_morning"].mean()
    non_dd_am = non["max_dd_morning"].mean()
    pm_h25 = pm["hit_25bps_morning"].mean() * 100
    non_h25 = non["hit_25bps_morning"].mean() * 100
    pm_h50 = pm["hit_50bps_morning"].mean() * 100
    non_h50 = non["hit_50bps_morning"].mean() * 100

    print(f"""
  Premarket ATH days: {len(pm)} ({len(pm)/total*100:.1f}% of all days)

  MAX MORNING DRAWDOWN (short profit potential):
    PM ATH mean:  {pm_dd_am:>+.3f}%   vs  Non-ATH: {non_dd_am:>+.3f}%
    PM ATH med:   {pm['max_dd_morning'].median():>+.3f}%   vs  Non-ATH: {non['max_dd_morning'].median():>+.3f}%

  THRESHOLD HIT RATES (morning):
    ≥ 25bp drop:  PM ATH {pm_h25:.0f}%  vs  Non-ATH {non_h25:.0f}%
    ≥ 50bp drop:  PM ATH {pm_h50:.0f}%  vs  Non-ATH {non_h50:.0f}%

  ADVERSE EXCURSION (max run-up = risk for shorts):
    Morning mean: PM ATH {pm['max_up_morning'].mean():>+.3f}%  vs  Non-ATH {non['max_up_morning'].mean():>+.3f}%

  KEY INSIGHT: PM ATH days have {abs(pm_dd_am/non_dd_am - 1)*100:.0f}% {"smaller" if abs(pm_dd_am) < abs(non_dd_am) else "larger"} morning drawdowns than average.
  The drawdown is smaller because ATH days are low-volatility bullish days.
  But the adverse excursion is also smaller — the range is compressed.
    """)

    # ─────────────────────────────────────────────────────
    # Export for visualization
    # ─────────────────────────────────────────────────────
    export = {
        "n_pm_ath": len(pm),
        "n_total": total,
        "date_range": [str(pm["date"].min()), str(pm["date"].max())],
        "dates": [str(d) for d in pm["date"].tolist()],
        "drawdowns": {
            "max_dd_30m": pm["max_dd_30m"].dropna().tolist(),
            "max_dd_1h": pm["max_dd_1h"].dropna().tolist(),
            "max_dd_morning": pm["max_dd_morning"].tolist(),
            "max_dd_day": pm["max_dd_day"].tolist(),
        },
        "running_low_profile": {},
        "comparison": {
            "pm_ath": {
                "dd_morning_mean": round(pm_dd_am, 4),
                "dd_morning_median": round(pm["max_dd_morning"].median(), 4),
                "hit_25bp_am": round(pm_h25, 1),
                "hit_50bp_am": round(pm_h50, 1),
            },
            "non_ath": {
                "dd_morning_mean": round(non_dd_am, 4),
                "dd_morning_median": round(non["max_dd_morning"].median(), 4),
                "hit_25bp_am": round(non_h25, 1),
                "hit_50bp_am": round(non_h50, 1),
            },
        },
        "by_extension": {},
        "by_gap": {},
        "by_po_zone": {},
        "by_atr_position": {},
        "by_year": {},
        "threshold_hit_rates": {
            "thresholds": [0.10, 0.25, 0.50, 0.75, 1.00],
            "pm_ath_morning": [pm[f"hit_{t}_morning"].mean() * 100 for t in ["10bps", "25bps", "50bps", "75bps", "100bps"]],
            "pm_ath_day": [pm[f"hit_{t}_day"].mean() * 100 for t in ["10bps", "25bps", "50bps", "75bps", "100bps"]],
            "non_ath_morning": [non[f"hit_{t}_morning"].mean() * 100 for t in ["10bps", "25bps", "50bps", "75bps", "100bps"]],
            "non_ath_day": [non[f"hit_{t}_day"].mean() * 100 for t in ["10bps", "25bps", "50bps", "75bps", "100bps"]],
        },
    }

    for mins in time_points:
        col = f"running_low_{mins}m"
        hi_col = f"running_high_{mins}m"
        if col in pm.columns:
            pm_v = pm[col].dropna()
            non_v = non[col].dropna()
            export["running_low_profile"][f"{mins}m"] = {
                "pm_ath_mean": round(pm_v.mean(), 4),
                "pm_ath_median": round(pm_v.median(), 4),
                "non_ath_mean": round(non_v.mean(), 4),
                "non_ath_median": round(non_v.median(), 4),
                "pm_ath_max_up_mean": round(pm[hi_col].dropna().mean(), 4) if hi_col in pm.columns else None,
            }

    for lo, hi, label in ext_buckets:
        sub = pm[(pm["ath_extension_pct"] >= lo) & (pm["ath_extension_pct"] < hi)]
        if len(sub) >= 3:
            export["by_extension"][label] = {
                "n": len(sub),
                "dd_morning_mean": round(sub["max_dd_morning"].mean(), 4),
                "dd_morning_median": round(sub["max_dd_morning"].median(), 4),
                "hit_25bp": round(sub["hit_25bps_morning"].mean() * 100, 1),
                "hit_50bp": round(sub["hit_50bps_morning"].mean() * 100, 1),
            }

    for lo, hi, label in gap_buckets:
        sub = valid_gap[(valid_gap["gap_pct"] >= lo) & (valid_gap["gap_pct"] < hi)]
        if len(sub) >= 3:
            export["by_gap"][label] = {
                "n": len(sub),
                "dd_morning_mean": round(sub["max_dd_morning"].mean(), 4),
                "dd_morning_median": round(sub["max_dd_morning"].median(), 4),
                "hit_25bp": round(sub["hit_25bps_morning"].mean() * 100, 1),
                "hit_50bp": round(sub["hit_50bps_morning"].mean() * 100, 1),
            }

    valid_po = pm.dropna(subset=["po_at_open"])
    zone_order = ["extended_down", "accumulation", "neutral_down", "neutral",
                   "neutral_up", "distribution", "extended_up"]
    for zone in zone_order:
        sub = valid_po[valid_po["po_zone_at_open"] == zone]
        if len(sub) >= 3:
            export["by_po_zone"][zone] = {
                "n": len(sub),
                "dd_morning_mean": round(sub["max_dd_morning"].mean(), 4),
                "hit_25bp": round(sub["hit_25bps_morning"].mean() * 100, 1),
                "hit_50bp": round(sub["hit_50bps_morning"].mean() * 100, 1),
            }

    valid_atr = pm.dropna(subset=["open_atr_pct"])
    atr_buckets = [
        (-999, 0, "Below prev close"),
        (0, 23.6, "0–Trigger"),
        (23.6, 38.2, "Trigger–GG"),
        (38.2, 61.8, "GG zone"),
        (61.8, 100, "GG exit–ATR"),
        (100, 999, "Beyond ATR"),
    ]
    for lo, hi, label in atr_buckets:
        sub = valid_atr[(valid_atr["open_atr_pct"] >= lo) & (valid_atr["open_atr_pct"] < hi)]
        if len(sub) >= 3:
            export["by_atr_position"][label] = {
                "n": len(sub),
                "dd_morning_mean": round(sub["max_dd_morning"].mean(), 4),
                "hit_25bp": round(sub["hit_25bps_morning"].mean() * 100, 1),
                "hit_50bp": round(sub["hit_50bps_morning"].mean() * 100, 1),
            }

    for year, ydf in pm.groupby("year"):
        export["by_year"][str(year)] = {
            "n": len(ydf),
            "dd_morning_mean": round(ydf["max_dd_morning"].mean(), 4),
            "hit_25bp": round(ydf["hit_25bps_morning"].mean() * 100, 1),
        }

    with open(os.path.join(BASE_DIR, "premarket_ath_results.json"), "w") as f:
        json.dump(export, f, indent=2, default=str)

    print(f"  Results exported to {os.path.join(BASE_DIR, 'premarket_ath_results.json')}")
    conn.close()


if __name__ == "__main__":
    main()
