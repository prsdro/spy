"""
4-Hour Phase Oscillator Mean Reversion Study

Hypothesis: When the 4h PO is extended above 110 and then falls below 100,
how often does price mean-revert to the 4h 8 EMA, and how long does it take?

Also studies the broader case of PO extended above 100 then falling below 100.

Mean reversion = price low touches or crosses below the 4h EMA8.
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
from study_utils import dedupe_records_by_index_gap
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load 4h indicator data
    print("Loading 4h data...")
    df4h = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_8, ema_21, ema_48, "
        "phase_oscillator, phase_zone, compression "
        "FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df4h = df4h.set_index("timestamp").sort_index()
    df4h = df4h.dropna(subset=["phase_oscillator", "ema_8"])

    # Also load 1h data for finer-grained timing of the EMA8 touch
    print("Loading 1h data for precise timing...")
    df1h = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df1h = df1h.set_index("timestamp").sort_index()

    po = df4h["phase_oscillator"]

    # ═══════════════════════════════════════════════════════════════
    # Study 1: PO peaked above 110, then crossed below 100
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("STUDY 1: 4h PO Extended Above 110 → Falls Below 100 → Mean Reversion to 8 EMA")
    print("=" * 80)
    analyze_threshold(df4h, df1h, peak_threshold=110, cross_threshold=100)

    # ═══════════════════════════════════════════════════════════════
    # Study 2: PO peaked above 100, then crossed below 100 (broader set)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("STUDY 2: 4h PO Extended Above 100 → Falls Below 100 → Mean Reversion to 8 EMA")
    print("=" * 80)
    analyze_threshold(df4h, df1h, peak_threshold=100, cross_threshold=100)

    # ═══════════════════════════════════════════════════════════════
    # Study 3: PO peaked above 100, crossed below 61.8 (deeper pullback)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("STUDY 3: 4h PO Extended Above 100 → Falls Below 61.8 → Mean Reversion to 8 EMA")
    print("=" * 80)
    analyze_threshold(df4h, df1h, peak_threshold=100, cross_threshold=61.8)

    # ═══════════════════════════════════════════════════════════════
    # Mirror: Bearish side (PO below -110, rises above -100)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("STUDY 4 (BEARISH): 4h PO Extended Below -110 → Rises Above -100 → Mean Reversion to 8 EMA")
    print("=" * 80)
    analyze_threshold_bearish(df4h, df1h, peak_threshold=-110, cross_threshold=-100)

    print("\n" + "=" * 80)
    print("STUDY 5 (BEARISH): 4h PO Extended Below -100 → Rises Above -100 → Mean Reversion to 8 EMA")
    print("=" * 80)
    analyze_threshold_bearish(df4h, df1h, peak_threshold=-100, cross_threshold=-100)

    conn.close()


def analyze_threshold(df4h, df1h, peak_threshold, cross_threshold):
    """Bullish side: PO was above peak_threshold, then crosses below cross_threshold.
    Track mean reversion = price low touches 4h EMA8."""

    po = df4h["phase_oscillator"]

    # Find episodes
    was_above_peak = False
    peak_po = 0
    peak_time = None
    events = []

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
            signal_row = df4h.iloc[i]
            events.append({
                "signal_time": signal_time,
                "signal_idx": i,
                "peak_po": peak_po,
                "peak_time": peak_time,
                "signal_po": current_po,
                "signal_close": signal_row["close"],
                "signal_ema8": signal_row["ema_8"],
                "signal_ema21": signal_row["ema_21"],
            })
            was_above_peak = False
            peak_po = 0

    max_bars_forward = 50  # look ahead up to 50 4h bars (~200 hours)
    events = dedupe_records_by_index_gap(events, "signal_idx", max_bars_forward)

    print(f"\nIndependent events found: {len(events)}")
    if len(events) == 0:
        print("No events to analyze.")
        return

    # Track forward from each event
    results = []

    for evt in events:
        i = evt["signal_idx"]
        signal_time = evt["signal_time"]
        ema8_at_signal = evt["signal_ema8"]
        close_at_signal = evt["signal_close"]

        # How far is price from EMA8 at signal time?
        gap_pct = (close_at_signal - ema8_at_signal) / ema8_at_signal * 100

        # Look forward bar by bar (EMA8 changes each bar!)
        touched = False
        for j in range(i + 1, min(i + max_bars_forward + 1, len(df4h))):
            bar = df4h.iloc[j]
            bar_low = bar["low"]
            bar_ema8 = bar["ema_8"]

            if bar_low <= bar_ema8:
                bars_elapsed = j - i
                time_elapsed = df4h.index[j] - signal_time
                hours_elapsed = time_elapsed.total_seconds() / 3600
                overshoot = (bar_low - bar_ema8) / bar_ema8 * 100

                results.append({
                    **evt,
                    "touched_ema8": True,
                    "bars_to_touch": bars_elapsed,
                    "hours_to_touch": hours_elapsed,
                    "gap_pct_at_signal": gap_pct,
                    "touch_time": df4h.index[j],
                    "overshoot_pct": overshoot,
                    "price_at_touch": bar_low,
                    "ema8_at_touch": bar_ema8,
                })
                touched = True
                break

        if not touched:
            results.append({
                **evt,
                "touched_ema8": False,
                "bars_to_touch": None,
                "hours_to_touch": None,
                "gap_pct_at_signal": gap_pct,
                "touch_time": None,
                "overshoot_pct": None,
                "price_at_touch": None,
                "ema8_at_touch": None,
            })

    rdf = pd.DataFrame(results)

    # ─── Summary Stats ───
    n_total = len(rdf)
    n_touched = rdf["touched_ema8"].sum()
    touch_rate = n_touched / n_total * 100

    print(f"\n{'─' * 60}")
    print(f"  Mean reversion to 4h EMA8: {n_touched}/{n_total} = {touch_rate:.1f}%")
    print(f"{'─' * 60}")

    if n_touched > 0:
        touched_df = rdf[rdf["touched_ema8"]]
        bars = touched_df["bars_to_touch"]
        hours = touched_df["hours_to_touch"]

        print(f"\n  Timing (4h bars to touch EMA8):")
        print(f"    Median:  {bars.median():.0f} bars ({hours.median():.0f} hours)")
        print(f"    Mean:    {bars.mean():.1f} bars ({hours.mean():.0f} hours)")
        print(f"    Min:     {bars.min():.0f} bars ({hours.min():.0f} hours)")
        print(f"    Max:     {bars.max():.0f} bars ({hours.max():.0f} hours)")
        print(f"    25th %%:  {bars.quantile(0.25):.0f} bars")
        print(f"    75th %%:  {bars.quantile(0.75):.0f} bars")

        print(f"\n  Gap at signal (close vs EMA8):")
        print(f"    Median gap: {rdf['gap_pct_at_signal'].median():.2f}%")
        print(f"    Mean gap:   {rdf['gap_pct_at_signal'].mean():.2f}%")

        print(f"\n  Overshoot past EMA8 at touch:")
        print(f"    Median: {touched_df['overshoot_pct'].median():.2f}%")
        print(f"    Mean:   {touched_df['overshoot_pct'].mean():.2f}%")

    # ─── Event Detail Table ───
    print(f"\n{'─' * 60}")
    print(f"  Event Details")
    print(f"{'─' * 60}")
    print(f"  {'Signal Time':<22s} {'Peak PO':>8s} {'Sig PO':>8s} {'Gap%':>7s} {'Bars':>5s} {'Hours':>7s} {'Touch?':>7s}")
    print(f"  {'─' * 70}")

    for _, r in rdf.iterrows():
        sig_t = str(r["signal_time"])[:19]
        peak = f"{r['peak_po']:.1f}"
        sig_po = f"{r['signal_po']:.1f}"
        gap = f"{r['gap_pct_at_signal']:.2f}"
        if r["touched_ema8"]:
            bars_s = f"{r['bars_to_touch']:.0f}"
            hours_s = f"{r['hours_to_touch']:.0f}"
            touch_s = "YES"
        else:
            bars_s = "—"
            hours_s = "—"
            touch_s = "NO"
        print(f"  {sig_t:<22s} {peak:>8s} {sig_po:>8s} {gap:>7s} {bars_s:>5s} {hours_s:>7s} {touch_s:>7s}")

    # ─── Distribution of timing ───
    if n_touched >= 5:
        print(f"\n  Timing Distribution (bars to touch EMA8):")
        for bucket_label, lo, hi in [
            ("1-2 bars (4-8h)", 1, 2),
            ("3-5 bars (12-20h)", 3, 5),
            ("6-10 bars (24-40h)", 6, 10),
            ("11-20 bars (44-80h)", 11, 20),
            ("21+ bars (84h+)", 21, 999),
        ]:
            count = ((touched_df["bars_to_touch"] >= lo) & (touched_df["bars_to_touch"] <= hi)).sum()
            pct = count / n_touched * 100
            print(f"    {bucket_label:<25s}: {count:3d} ({pct:5.1f}%)")


def analyze_threshold_bearish(df4h, df1h, peak_threshold, cross_threshold):
    """Bearish side: PO was below peak_threshold (e.g. -110), then rises above cross_threshold (e.g. -100).
    Track mean reversion = price high touches 4h EMA8 from below."""

    po = df4h["phase_oscillator"]

    was_below_peak = False
    trough_po = 0
    trough_time = None
    events = []

    for i in range(1, len(df4h)):
        current_po = po.iloc[i]
        prev_po = po.iloc[i - 1]

        if prev_po <= peak_threshold:
            if not was_below_peak:
                was_below_peak = True
                trough_po = prev_po
                trough_time = df4h.index[i - 1]
            elif prev_po < trough_po:
                trough_po = prev_po
                trough_time = df4h.index[i - 1]

        if was_below_peak and prev_po <= cross_threshold and current_po > cross_threshold:
            signal_time = df4h.index[i]
            signal_row = df4h.iloc[i]
            events.append({
                "signal_time": signal_time,
                "signal_idx": i,
                "trough_po": trough_po,
                "trough_time": trough_time,
                "signal_po": current_po,
                "signal_close": signal_row["close"],
                "signal_ema8": signal_row["ema_8"],
                "signal_ema21": signal_row["ema_21"],
            })
            was_below_peak = False
            trough_po = 0

    max_bars_forward = 50
    events = dedupe_records_by_index_gap(events, "signal_idx", max_bars_forward)

    print(f"\nIndependent events found: {len(events)}")
    if len(events) == 0:
        print("No events to analyze.")
        return

    results = []

    for evt in events:
        i = evt["signal_idx"]
        signal_time = evt["signal_time"]
        ema8_at_signal = evt["signal_ema8"]
        close_at_signal = evt["signal_close"]

        gap_pct = (close_at_signal - ema8_at_signal) / ema8_at_signal * 100

        # Bearish: price is below EMA8, mean reversion = price HIGH touches EMA8
        touched = False
        for j in range(i + 1, min(i + max_bars_forward + 1, len(df4h))):
            bar = df4h.iloc[j]
            if bar["high"] >= bar["ema_8"]:
                bars_elapsed = j - i
                time_elapsed = df4h.index[j] - signal_time
                hours_elapsed = time_elapsed.total_seconds() / 3600

                results.append({
                    **evt,
                    "touched_ema8": True,
                    "bars_to_touch": bars_elapsed,
                    "hours_to_touch": hours_elapsed,
                    "gap_pct_at_signal": gap_pct,
                    "touch_time": df4h.index[j],
                })
                touched = True
                break

        if not touched:
            results.append({
                **evt,
                "touched_ema8": False,
                "bars_to_touch": None,
                "hours_to_touch": None,
                "gap_pct_at_signal": gap_pct,
                "touch_time": None,
            })

    rdf = pd.DataFrame(results)

    n_total = len(rdf)
    n_touched = rdf["touched_ema8"].sum()
    touch_rate = n_touched / n_total * 100

    print(f"\n{'─' * 60}")
    print(f"  Mean reversion to 4h EMA8: {n_touched}/{n_total} = {touch_rate:.1f}%")
    print(f"{'─' * 60}")

    if n_touched > 0:
        touched_df = rdf[rdf["touched_ema8"]]
        bars = touched_df["bars_to_touch"]
        hours = touched_df["hours_to_touch"]

        print(f"\n  Timing (4h bars to touch EMA8):")
        print(f"    Median:  {bars.median():.0f} bars ({hours.median():.0f} hours)")
        print(f"    Mean:    {bars.mean():.1f} bars ({hours.mean():.0f} hours)")
        print(f"    Min:     {bars.min():.0f} bars ({hours.min():.0f} hours)")
        print(f"    Max:     {bars.max():.0f} bars ({hours.max():.0f} hours)")

    print(f"\n  Event Details")
    print(f"  {'Signal Time':<22s} {'Trgh PO':>8s} {'Sig PO':>8s} {'Gap%':>7s} {'Bars':>5s} {'Hours':>7s} {'Touch?':>7s}")
    print(f"  {'─' * 70}")

    for _, r in rdf.iterrows():
        sig_t = str(r["signal_time"])[:19]
        trough = f"{r['trough_po']:.1f}"
        sig_po = f"{r['signal_po']:.1f}"
        gap = f"{r['gap_pct_at_signal']:.2f}"
        if r["touched_ema8"]:
            bars_s = f"{r['bars_to_touch']:.0f}"
            hours_s = f"{r['hours_to_touch']:.0f}"
            touch_s = "YES"
        else:
            bars_s = "—"
            hours_s = "—"
            touch_s = "NO"
        print(f"  {sig_t:<22s} {trough:>8s} {sig_po:>8s} {gap:>7s} {bars_s:>5s} {hours_s:>7s} {touch_s:>7s}")

    if n_touched >= 5:
        touched_df = rdf[rdf["touched_ema8"]]
        print(f"\n  Timing Distribution (bars to touch EMA8):")
        for bucket_label, lo, hi in [
            ("1-2 bars (4-8h)", 1, 2),
            ("3-5 bars (12-20h)", 3, 5),
            ("6-10 bars (24-40h)", 6, 10),
            ("11-20 bars (44-80h)", 11, 20),
            ("21+ bars (84h+)", 21, 999),
        ]:
            count = ((touched_df["bars_to_touch"] >= lo) & (touched_df["bars_to_touch"] <= hi)).sum()
            pct = count / n_touched * 100
            print(f"    {bucket_label:<25s}: {count:3d} ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
