"""
4H PO Extension → Daily 21 EMA Mean Reversion Study

Signal: 4H PO peaks above threshold (110 or 100), then crosses below 100
Target: Daily low touches daily 21 EMA

Key question: Does the 4H PO rollover predict a daily-timeframe mean reversion?

Measures:
1. Touch rate and timing (trading days to daily 21 EMA)
2. Gap decomposition: consolidation (EMA rising to price) vs drop (price falling to EMA)
3. Also checks: does price reach daily 48 EMA?
4. Post-touch behavior: bounce, chop, or continuation lower
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
from study_utils import dedupe_signals_by_daily_cooldown, intraday_signal_daily_locs
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load 4h indicator data (for signal detection)
    print("Loading 4h data...")
    df4h = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_8, ema_21, "
        "phase_oscillator FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df4h = df4h.set_index("timestamp").sort_index()
    df4h = df4h.dropna(subset=["phase_oscillator"])

    # Load daily indicator data (for target: daily 21 EMA and 48 EMA)
    print("Loading daily data...")
    df1d = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_8, ema_21, ema_48, "
        "phase_oscillator FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df1d = df1d.set_index("timestamp").sort_index()
    df1d = df1d.dropna(subset=["ema_21", "ema_48"])

    conn.close()

    # ═══════════════════════════════════════════════════════════════
    # Study A: 4H PO peaked above 110, crosses below 100
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STUDY A: 4H PO Peaked Above 110 → Falls Below 100 → Daily 21 EMA Mean Reversion")
    print("=" * 90)
    analyze(df4h, df1d, peak_threshold=110, cross_threshold=100)

    # ═══════════════════════════════════════════════════════════════
    # Study B: 4H PO peaked above 100, crosses below 100 (broader set)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("STUDY B: 4H PO Peaked Above 100 → Falls Below 100 → Daily 21 EMA Mean Reversion")
    print("=" * 90)
    analyze(df4h, df1d, peak_threshold=100, cross_threshold=100)


def analyze(df4h, df1d, peak_threshold, cross_threshold):
    """Find 4H PO rollover events, track forward on daily chart to EMA21 and EMA48."""

    po = df4h["phase_oscillator"]

    # ─── Step 1: Find 4H PO rollover signals ───
    was_above_peak = False
    peak_po = 0
    peak_time = None
    signals = []

    for i in range(1, len(df4h)):
        current_po = po.iloc[i]
        prev_po = po.iloc[i - 1]

        if prev_po >= peak_threshold:
            if not was_above_peak:
                was_above_peak = True
                peak_po = prev_po
                peak_time = df4h.index[i - 1]
            elif prev_po > peak_po:
                peak_po = prev_po
                peak_time = df4h.index[i - 1]

        if was_above_peak and prev_po >= cross_threshold and current_po < cross_threshold:
            signal_time = df4h.index[i]
            signals.append({
                "signal_time": signal_time,
                "signal_date": signal_time.normalize(),  # trading day
                "peak_po": peak_po,
                "peak_time": peak_time,
                "signal_po": current_po,
                "signal_4h_close": df4h.iloc[i]["close"],
            })
            was_above_peak = False
            peak_po = 0

    max_days_forward = 40  # look ahead up to 40 trading days
    signals = dedupe_signals_by_daily_cooldown(signals, df1d.index, max_days_forward)

    print(f"\nIndependent 4H PO rollover signals found: {len(signals)}")
    if len(signals) == 0:
        return

    # ─── Step 2: For each signal, track forward on daily chart ───
    results = []

    for sig in signals:
        daily_idx, prior_daily_idx, next_daily_idx = intraday_signal_daily_locs(
            df1d.index, sig["signal_time"]
        )
        if daily_idx is None or prior_daily_idx is None or next_daily_idx is None:
            continue

        signal_day = sig["signal_time"].normalize()
        prior_daily_row = df1d.iloc[prior_daily_idx]
        signal_close = sig["signal_4h_close"]
        signal_ema21 = prior_daily_row["ema_21"]
        signal_ema48 = prior_daily_row["ema_48"]

        # Use the most recent completed daily EMA levels available at signal time.
        if signal_close <= signal_ema21:
            continue

        gap_at_signal = signal_close - signal_ema21
        gap_pct = gap_at_signal / signal_ema21 * 100

        # Track forward day by day
        touched_ema21 = False
        touched_ema48 = False
        days_to_ema21 = None
        days_to_ema48 = None
        ema21_touch_info = {}
        ema48_touch_info = {}

        # Track max drawdown from signal close during the path
        max_drawdown_pct = 0

        for d in range(1, min(max_days_forward + 1, len(df1d) - daily_idx)):
            j = daily_idx + d
            day_row = df1d.iloc[j]
            day_low = day_row["low"]
            day_close = day_row["close"]
            day_ema21 = day_row["ema_21"]
            day_ema48 = day_row["ema_48"]

            # Track drawdown
            dd = (day_low - signal_close) / signal_close * 100
            if dd < max_drawdown_pct:
                max_drawdown_pct = dd

            # Check EMA21 touch
            if not touched_ema21 and day_low <= day_ema21:
                touched_ema21 = True
                days_to_ema21 = d
                ema21_touch_info = {
                    "touch_date": df1d.index[j],
                    "touch_low": day_low,
                    "touch_close": day_close,
                    "ema21_at_touch": day_ema21,
                    "ema48_at_touch": day_ema48,
                    "ema21_at_signal": signal_ema21,
                    # Gap decomposition
                    "ema_moved": day_ema21 - signal_ema21,
                    "price_dropped": signal_close - day_low,
                }

            # Check EMA48 touch
            if not touched_ema48 and day_low <= day_ema48:
                touched_ema48 = True
                days_to_ema48 = d
                ema48_touch_info = {
                    "touch_date": df1d.index[j],
                    "touch_low": day_low,
                    "ema48_at_touch": day_ema48,
                }

            # If both touched, stop early
            if touched_ema21 and touched_ema48:
                break

        # ─── Gap decomposition for EMA21 touch ───
        ema_contribution_pct = None
        price_contribution_pct = None
        gap_type = "NO TOUCH"

        if touched_ema21 and gap_at_signal > 0:
            ema_moved = ema21_touch_info["ema_moved"]
            ema_contribution_pct = ema_moved / gap_at_signal * 100
            price_contribution_pct = 100 - ema_contribution_pct

            if ema_contribution_pct >= 60:
                gap_type = "CONSOLIDATION"  # EMA rose to meet price
            elif ema_contribution_pct <= 40:
                gap_type = "DROP"  # Price fell to meet EMA
            else:
                gap_type = "MIXED"

        # ─── Post-touch behavior (if EMA21 was touched) ───
        post_touch = {}
        if touched_ema21:
            touch_idx = daily_idx + days_to_ema21
            touch_low = ema21_touch_info["touch_low"]

            # Track 1, 3, 5, 10 days after touch
            for horizon in [1, 3, 5, 10]:
                h_idx = touch_idx + horizon
                if h_idx < len(df1d):
                    h_row = df1d.iloc[h_idx]
                    # Is price above or below daily 21 EMA?
                    post_touch[f"close_vs_ema21_d{horizon}"] = (
                        h_row["close"] - h_row["ema_21"]
                    ) / h_row["ema_21"] * 100
                    post_touch[f"close_d{horizon}"] = h_row["close"]
                    post_touch[f"ema21_d{horizon}"] = h_row["ema_21"]

            # Max bounce from touch low (next 10 days)
            max_bounce = 0
            max_further_drop = 0
            for bd in range(1, min(11, len(df1d) - touch_idx)):
                b_idx = touch_idx + bd
                b_row = df1d.iloc[b_idx]
                bounce = (b_row["high"] - touch_low) / touch_low * 100
                drop = (b_row["low"] - touch_low) / touch_low * 100
                if bounce > max_bounce:
                    max_bounce = bounce
                if drop < max_further_drop:
                    max_further_drop = drop

            post_touch["max_bounce_10d_pct"] = max_bounce
            post_touch["max_further_drop_10d_pct"] = max_further_drop

            # Classify post-touch behavior
            if max_further_drop < -1.5:
                post_touch["post_behavior"] = "CONTINUATION_DOWN"
            elif max_bounce > 1.5 and max_further_drop > -0.5:
                post_touch["post_behavior"] = "BOUNCE"
            else:
                post_touch["post_behavior"] = "CHOP"

        results.append({
            "signal_date": signal_day,
            "peak_po": sig["peak_po"],
            "signal_po": sig["signal_po"],
            "signal_close": signal_close,
            "signal_ema21": signal_ema21,
            "signal_ema48": signal_ema48,
            "gap_pct": gap_pct,
            "touched_ema21": touched_ema21,
            "days_to_ema21": days_to_ema21,
            "touched_ema48": touched_ema48,
            "days_to_ema48": days_to_ema48,
            "max_drawdown_pct": max_drawdown_pct,
            "ema_contribution_pct": ema_contribution_pct,
            "price_contribution_pct": price_contribution_pct,
            "gap_type": gap_type,
            **ema21_touch_info,
            **post_touch,
        })

    rdf = pd.DataFrame(results)

    if len(rdf) == 0:
        print("No valid events (all were already at/below EMA21 at signal).")
        return

    # ═══════════════════════════════════════════════════════════════
    # SUMMARY STATS
    # ═══════════════════════════════════════════════════════════════
    n_total = len(rdf)
    n_touch21 = rdf["touched_ema21"].sum()
    n_touch48 = rdf["touched_ema48"].sum()
    touch21_rate = n_touch21 / n_total * 100
    touch48_rate = n_touch48 / n_total * 100

    print(f"\n{'═' * 90}")
    print(f"  SUMMARY ({n_total} events where price was above daily 21 EMA at signal)")
    print(f"{'═' * 90}")
    print(f"\n  Touch Rates (within {40} trading days):")
    print(f"    Daily 21 EMA: {n_touch21}/{n_total} = {touch21_rate:.1f}%")
    print(f"    Daily 48 EMA: {n_touch48}/{n_total} = {touch48_rate:.1f}%")

    if n_touch21 > 0:
        t21 = rdf[rdf["touched_ema21"]]
        days21 = t21["days_to_ema21"]

        print(f"\n  Timing to Daily 21 EMA (trading days):")
        print(f"    Median:  {days21.median():.0f} days")
        print(f"    Mean:    {days21.mean():.1f} days")
        print(f"    Min:     {days21.min():.0f} days")
        print(f"    Max:     {days21.max():.0f} days")
        print(f"    25th %%:  {days21.quantile(0.25):.0f} days")
        print(f"    75th %%:  {days21.quantile(0.75):.0f} days")

        print(f"\n  Gap at Signal (close vs daily 21 EMA):")
        print(f"    Median:  {rdf['gap_pct'].median():.2f}%")
        print(f"    Mean:    {rdf['gap_pct'].mean():.2f}%")
        print(f"    Max:     {rdf['gap_pct'].max():.2f}%")

        print(f"\n  Max Drawdown (signal close → lowest low before EMA21 touch):")
        print(f"    Median:  {rdf['max_drawdown_pct'].median():.2f}%")
        print(f"    Mean:    {rdf['max_drawdown_pct'].mean():.2f}%")
        print(f"    Worst:   {rdf['max_drawdown_pct'].min():.2f}%")

    # ═══════════════════════════════════════════════════════════════
    # GAP DECOMPOSITION: HOW did the gap close?
    # ═══════════════════════════════════════════════════════════════
    if n_touch21 > 0:
        t21 = rdf[rdf["touched_ema21"]]

        print(f"\n{'═' * 90}")
        print(f"  GAP DECOMPOSITION: How did the gap between price and daily 21 EMA close?")
        print(f"{'═' * 90}")

        ema_cont = t21["ema_contribution_pct"]
        price_cont = t21["price_contribution_pct"]

        print(f"\n  Overall averages:")
        print(f"    EMA rising (consolidation):  {ema_cont.mean():.1f}% of gap closure")
        print(f"    Price dropping:              {price_cont.mean():.1f}% of gap closure")
        print(f"    Median EMA contribution:     {ema_cont.median():.1f}%")

        # Classification breakdown
        n_consol = (t21["gap_type"] == "CONSOLIDATION").sum()
        n_drop = (t21["gap_type"] == "DROP").sum()
        n_mixed = (t21["gap_type"] == "MIXED").sum()

        print(f"\n  Classification:")
        print(f"    CONSOLIDATION (EMA ≥60%):  {n_consol}/{n_touch21} = {n_consol/n_touch21*100:.1f}%")
        print(f"      → Price went sideways, daily 21 EMA rose up to meet it")
        print(f"    DROP (Price ≥60%):         {n_drop}/{n_touch21} = {n_drop/n_touch21*100:.1f}%")
        print(f"      → Price fell sharply/steadily to the daily 21 EMA")
        print(f"    MIXED (40-60% each):       {n_mixed}/{n_touch21} = {n_mixed/n_touch21*100:.1f}%")
        print(f"      → Both contributed meaningfully")

        # Timing by type
        for gtype in ["CONSOLIDATION", "DROP", "MIXED"]:
            subset = t21[t21["gap_type"] == gtype]
            if len(subset) > 0:
                print(f"\n  {gtype} events ({len(subset)}):")
                print(f"    Median days to touch: {subset['days_to_ema21'].median():.0f}")
                print(f"    Mean days to touch:   {subset['days_to_ema21'].mean():.1f}")
                print(f"    Median gap at signal: {subset['gap_pct'].median():.2f}%")

    # ═══════════════════════════════════════════════════════════════
    # POST-TOUCH BEHAVIOR
    # ═══════════════════════════════════════════════════════════════
    if n_touch21 > 0 and "post_behavior" in rdf.columns:
        t21 = rdf[rdf["touched_ema21"]].copy()

        print(f"\n{'═' * 90}")
        print(f"  POST-TOUCH BEHAVIOR (after price touches daily 21 EMA)")
        print(f"{'═' * 90}")

        n_bounce = (t21["post_behavior"] == "BOUNCE").sum()
        n_chop = (t21["post_behavior"] == "CHOP").sum()
        n_cont = (t21["post_behavior"] == "CONTINUATION_DOWN").sum()

        print(f"\n  10-day post-touch classification:")
        print(f"    BOUNCE (>1.5% up, <0.5% further down):       {n_bounce}/{n_touch21} = {n_bounce/n_touch21*100:.1f}%")
        print(f"    CHOP (modest moves both ways):                {n_chop}/{n_touch21} = {n_chop/n_touch21*100:.1f}%")
        print(f"    CONTINUATION DOWN (>1.5% further drop):       {n_cont}/{n_touch21} = {n_cont/n_touch21*100:.1f}%")

        if "max_bounce_10d_pct" in t21.columns:
            print(f"\n  10-day post-touch stats:")
            print(f"    Max bounce (median):        +{t21['max_bounce_10d_pct'].median():.2f}%")
            print(f"    Max further drop (median):  {t21['max_further_drop_10d_pct'].median():.2f}%")

        # Close vs EMA21 at various horizons
        for horizon in [1, 3, 5, 10]:
            col = f"close_vs_ema21_d{horizon}"
            if col in t21.columns:
                valid = t21[col].dropna()
                if len(valid) > 0:
                    above = (valid > 0).sum()
                    print(f"\n  Day +{horizon} after touch:")
                    print(f"    Close above daily 21 EMA: {above}/{len(valid)} = {above/len(valid)*100:.1f}%")
                    print(f"    Median distance from EMA21: {valid.median():.2f}%")

    # ═══════════════════════════════════════════════════════════════
    # TIMING DISTRIBUTION
    # ═══════════════════════════════════════════════════════════════
    if n_touch21 >= 5:
        t21 = rdf[rdf["touched_ema21"]]

        print(f"\n{'═' * 90}")
        print(f"  TIMING DISTRIBUTION (trading days to daily 21 EMA)")
        print(f"{'═' * 90}")

        for label, lo, hi in [
            ("1 day", 1, 1),
            ("2-3 days", 2, 3),
            ("4-5 days (1 week)", 4, 5),
            ("6-10 days (1-2 weeks)", 6, 10),
            ("11-15 days (2-3 weeks)", 11, 15),
            ("16-20 days (3-4 weeks)", 16, 20),
            ("21-30 days (4-6 weeks)", 21, 30),
            ("31+ days", 31, 999),
        ]:
            count = ((t21["days_to_ema21"] >= lo) & (t21["days_to_ema21"] <= hi)).sum()
            pct = count / n_touch21 * 100
            print(f"    {label:<30s}: {count:3d} ({pct:5.1f}%)")

    # ═══════════════════════════════════════════════════════════════
    # EVENT DETAIL TABLE
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'═' * 90}")
    print(f"  EVENT DETAILS")
    print(f"{'═' * 90}")
    header = (
        f"  {'Signal Date':<12s} {'PkPO':>6s} {'Gap%':>6s} "
        f"{'Days':>5s} {'EMA%':>5s} {'Prc%':>5s} {'Type':<14s} "
        f"{'Post':>14s} {'DD%':>6s}"
    )
    print(header)
    print(f"  {'─' * 86}")

    for _, r in rdf.iterrows():
        sig_d = str(r["signal_date"])[:10]
        pk = f"{r['peak_po']:.0f}"
        gap = f"{r['gap_pct']:.2f}"

        if r["touched_ema21"]:
            days_s = f"{r['days_to_ema21']:.0f}"
            ema_s = f"{r['ema_contribution_pct']:.0f}" if pd.notna(r.get("ema_contribution_pct")) else "—"
            prc_s = f"{r['price_contribution_pct']:.0f}" if pd.notna(r.get("price_contribution_pct")) else "—"
            gtype = r["gap_type"]
            post = r.get("post_behavior", "—")
        else:
            days_s = "—"
            ema_s = "—"
            prc_s = "—"
            gtype = "NO TOUCH"
            post = "—"

        dd = f"{r['max_drawdown_pct']:.1f}"
        print(f"  {sig_d:<12s} {pk:>6s} {gap:>6s} {days_s:>5s} {ema_s:>5s} {prc_s:>5s} {gtype:<14s} {post:>14s} {dd:>6s}")

    # ═══════════════════════════════════════════════════════════════
    # CROSS-TAB: Gap type vs Post-touch behavior
    # ═══════════════════════════════════════════════════════════════
    if n_touch21 >= 5 and "post_behavior" in rdf.columns:
        t21 = rdf[rdf["touched_ema21"]]

        print(f"\n{'═' * 90}")
        print(f"  CROSS-TAB: Gap Closure Type → Post-Touch Behavior")
        print(f"{'═' * 90}")
        print(f"  {'Type':<16s} {'N':>4s} {'BOUNCE':>10s} {'CHOP':>10s} {'CONT_DOWN':>10s}")
        print(f"  {'─' * 52}")

        for gtype in ["CONSOLIDATION", "DROP", "MIXED"]:
            subset = t21[t21["gap_type"] == gtype]
            n = len(subset)
            if n == 0:
                continue
            nb = (subset["post_behavior"] == "BOUNCE").sum()
            nc = (subset["post_behavior"] == "CHOP").sum()
            nd = (subset["post_behavior"] == "CONTINUATION_DOWN").sum()
            print(f"  {gtype:<16s} {n:>4d} {nb:>4d} ({nb/n*100:4.0f}%) {nc:>4d} ({nc/n*100:4.0f}%) {nd:>4d} ({nd/n*100:4.0f}%)")


if __name__ == "__main__":
    main()
