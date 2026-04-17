"""
Study: Sustained 10m Phase Oscillator Above 61.8 in the Morning

Hypothesis: When the 10-minute PO crosses above 61.8 during bullish expansion
in the first 30 minutes of RTH (9:30-10:00), and stays above 61.8 through
11:00 AM ET — what happens to price for the rest of the day?

This tests whether early sustained distribution-zone momentum is a
continuation or exhaustion signal.

Setup conditions:
1. 10m PO crosses above 61.8 between 9:30 and 10:00 ET
2. At the cross, the ribbon is in bullish expansion (not compression)
3. PO stays >= 61.8 on every 10m bar through 11:00 AM ET

Measurements (from 11:00 AM onward):
- Rest-of-day price change (11am to close)
- Max gain / max drawdown from 11am
- ATR level progression (which levels get hit)
- Distribution of outcomes by bucket
- Comparison to non-qualifying days
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

    # ── Load 10m indicator data (RTH only) ──
    print("Loading 10m indicator data...", flush=True)
    df = pd.read_sql_query(
        "SELECT * FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14", "phase_oscillator"])
    df["date"] = df.index.date
    df["time"] = df.index.time

    print(f"Loaded {len(df):,} bars across {df['date'].nunique():,} trading days\n")

    # ── Identify qualifying days ──
    qualifying_days = []
    non_qualifying_days = []

    for date, group in df.groupby("date"):
        # Need bars from 9:30 through at least 11:00
        if len(group) < 10:
            continue

        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]
        if pd.isna(prev_close) or pd.isna(atr) or atr == 0:
            continue

        # Get the first 30 minutes (9:30 - 9:50, three 10m bars: 9:30, 9:40, 9:50)
        first_30 = group.between_time("09:30", "09:50")
        if len(first_30) == 0:
            continue

        # Find the bar where PO crosses above 61.8 in first 30 minutes
        cross_bar = None
        for i in range(len(first_30)):
            row = first_30.iloc[i]
            po = row["phase_oscillator"]
            compression = row["compression"]
            bull_expanding = (
                row.get("fast_cloud_bullish", 0) == 1 and
                row.get("slow_cloud_bullish", 0) == 1 and
                compression != 1
            )

            if po > 61.8 and bull_expanding:
                # Check that it's a cross (previous bar was <= 61.8)
                if i == 0:
                    # First bar of day — check if PO is above 61.8
                    # We need the previous bar's PO to confirm a cross
                    # For first bar, we accept it if PO > 61.8 (gap into distribution)
                    cross_bar = first_30.index[i]
                    break
                else:
                    prev_po = first_30.iloc[i - 1]["phase_oscillator"]
                    if prev_po <= 61.8:
                        cross_bar = first_30.index[i]
                        break
                    elif prev_po > 61.8:
                        # Already above 61.8, check if the very first bar crossed
                        # This means the cross happened on an earlier bar
                        # Set cross_bar to the first bar that was above 61.8
                        pass

        # Also check: did PO start the day already above 61.8?
        if cross_bar is None:
            first_po = first_30.iloc[0]["phase_oscillator"]
            first_bull_expanding = (
                first_30.iloc[0].get("fast_cloud_bullish", 0) == 1 and
                first_30.iloc[0].get("slow_cloud_bullish", 0) == 1 and
                first_30.iloc[0]["compression"] != 1
            )
            if first_po > 61.8 and first_bull_expanding:
                cross_bar = first_30.index[0]

        if cross_bar is None:
            non_qualifying_days.append((date, group))
            continue

        # Now check: does PO stay >= 61.8 through 11:00 AM?
        # 10m bars from cross through 10:50 (the bar that covers 10:50-11:00)
        sustained_period = group.loc[cross_bar:]
        sustained_period = sustained_period.between_time("09:30", "10:50")

        if len(sustained_period) == 0:
            non_qualifying_days.append((date, group))
            continue

        # Check every bar in sustained period has PO >= 61.8
        all_above = (sustained_period["phase_oscillator"] >= 61.8).all()

        if not all_above:
            non_qualifying_days.append((date, group))
            continue

        # ✓ Qualifying day — record metrics
        # Price at cross
        cross_row = group.loc[cross_bar]
        cross_price = cross_row["close"]

        # Price at 11:00 AM (the bar starting at 11:00)
        bars_11am = group.between_time("11:00", "11:00")
        if len(bars_11am) == 0:
            non_qualifying_days.append((date, group))
            continue

        price_11am = bars_11am.iloc[0]["close"]

        # Rest of day from 11:00 onward
        rest_of_day = group.between_time("11:00", "15:59")
        if len(rest_of_day) == 0:
            non_qualifying_days.append((date, group))
            continue

        rod_high = rest_of_day["high"].max()
        rod_low = rest_of_day["low"].min()
        rod_close = rest_of_day.iloc[-1]["close"]
        day_open = first["open"]
        day_close = rod_close

        # ATR level info
        upper_trigger = first["atr_upper_trigger"]
        upper_0382 = first["atr_upper_0382"]
        upper_0618 = first["atr_upper_0618"]
        upper_0786 = first["atr_upper_0786"]
        upper_100 = first["atr_upper_100"]
        upper_1236 = first.get("atr_upper_1236", np.nan)
        lower_trigger = first["atr_lower_trigger"]

        # What levels did price hit during the REST of day (after 11am)?
        hit_upper_0618_rod = rod_high >= upper_0618
        hit_upper_0786_rod = rod_high >= upper_0786
        hit_upper_100_rod = rod_high >= upper_100

        # What was the max ATR % move from prev close during rest of day?
        max_up_from_pc = (rod_high - prev_close) / atr * 100
        max_down_from_pc = (prev_close - rod_low) / atr * 100
        close_from_pc = (rod_close - prev_close) / atr * 100

        # Return from 11am to close
        ret_11am_to_close = (rod_close - price_11am) / price_11am * 100
        # Max gain from 11am
        max_gain_from_11am = (rod_high - price_11am) / price_11am * 100
        # Max drawdown from 11am
        max_dd_from_11am = (rod_low - price_11am) / price_11am * 100
        # Return from open to close
        ret_open_to_close = (day_close - day_open) / day_open * 100

        # PO at 11am
        po_at_11am = bars_11am.iloc[0]["phase_oscillator"]

        # What was PO at end of day?
        po_eod = rest_of_day.iloc[-1]["phase_oscillator"]

        # Did PO stay above 61.8 ALL day?
        full_day_above = (group["phase_oscillator"] >= 61.8).all()

        # How many bars after 11am did PO stay above 61.8?
        po_above_count = (rest_of_day["phase_oscillator"] >= 61.8).sum()
        po_total_rod = len(rest_of_day)

        qualifying_days.append({
            "date": date,
            "cross_time": cross_bar,
            "cross_price": cross_price,
            "price_11am": price_11am,
            "prev_close": prev_close,
            "atr": atr,
            "day_open": day_open,
            "rod_close": rod_close,
            "rod_high": rod_high,
            "rod_low": rod_low,
            "ret_11am_to_close": ret_11am_to_close,
            "max_gain_from_11am": max_gain_from_11am,
            "max_dd_from_11am": max_dd_from_11am,
            "ret_open_to_close": ret_open_to_close,
            "max_up_atr_pct": max_up_from_pc,
            "max_down_atr_pct": max_down_from_pc,
            "close_atr_pct": close_from_pc,
            "hit_upper_0618_rod": hit_upper_0618_rod,
            "hit_upper_0786_rod": hit_upper_0786_rod,
            "hit_upper_100_rod": hit_upper_100_rod,
            "po_at_11am": po_at_11am,
            "po_eod": po_eod,
            "full_day_above": full_day_above,
            "po_above_pct_rod": po_above_count / po_total_rod * 100,
        })

    n_qual = len(qualifying_days)
    n_total = n_qual + len(non_qualifying_days)

    print("=" * 70)
    print("SUSTAINED MORNING PO > 61.8 IN BULLISH EXPANSION — RESULTS")
    print("=" * 70)
    print(f"\nQualifying days: {n_qual} out of {n_total} total ({n_qual/n_total*100:.1f}%)")

    if n_qual == 0:
        print("No qualifying days found!")
        conn.close()
        return

    qdf = pd.DataFrame(qualifying_days)

    # ── Summary Statistics ──
    print(f"\n{'─' * 50}")
    print("PRICE ACTION FROM 11:00 AM TO CLOSE")
    print(f"{'─' * 50}")

    print(f"\n  Return 11am → Close:")
    print(f"    Mean:   {qdf['ret_11am_to_close'].mean():+.3f}%")
    print(f"    Median: {qdf['ret_11am_to_close'].median():+.3f}%")
    print(f"    Stdev:  {qdf['ret_11am_to_close'].std():.3f}%")
    print(f"    Min:    {qdf['ret_11am_to_close'].min():+.3f}%")
    print(f"    Max:    {qdf['ret_11am_to_close'].max():+.3f}%")

    positive = (qdf["ret_11am_to_close"] > 0).sum()
    negative = (qdf["ret_11am_to_close"] < 0).sum()
    flat = (qdf["ret_11am_to_close"] == 0).sum()
    print(f"    Positive: {positive} ({positive/n_qual*100:.1f}%)")
    print(f"    Negative: {negative} ({negative/n_qual*100:.1f}%)")

    print(f"\n  Max Gain from 11am:")
    print(f"    Mean:   {qdf['max_gain_from_11am'].mean():+.3f}%")
    print(f"    Median: {qdf['max_gain_from_11am'].median():+.3f}%")

    print(f"\n  Max Drawdown from 11am:")
    print(f"    Mean:   {qdf['max_dd_from_11am'].mean():+.3f}%")
    print(f"    Median: {qdf['max_dd_from_11am'].median():+.3f}%")

    print(f"\n  Full Day Return (Open → Close):")
    print(f"    Mean:   {qdf['ret_open_to_close'].mean():+.3f}%")
    print(f"    Median: {qdf['ret_open_to_close'].median():+.3f}%")
    full_day_pos = (qdf["ret_open_to_close"] > 0).sum()
    print(f"    Green days: {full_day_pos} ({full_day_pos/n_qual*100:.1f}%)")

    # ── ATR Level Progression (rest of day) ──
    print(f"\n{'─' * 50}")
    print("ATR LEVEL HITS (AFTER 11:00 AM)")
    print(f"{'─' * 50}")

    for col, label in [
        ("hit_upper_0618_rod", "61.8% (Midrange)"),
        ("hit_upper_0786_rod", "78.6%"),
        ("hit_upper_100_rod", "100% (Full ATR)"),
    ]:
        hits = qdf[col].sum()
        print(f"  Reached +{label}: {hits}/{n_qual} ({hits/n_qual*100:.1f}%)")

    # ── ATR % from prev close at various points ──
    print(f"\n{'─' * 50}")
    print("ATR POSITION (% of ATR from prev close)")
    print(f"{'─' * 50}")
    print(f"  Max upside (rest of day):   {qdf['max_up_atr_pct'].mean():.1f}% ATR avg, "
          f"{qdf['max_up_atr_pct'].median():.1f}% median")
    print(f"  Max downside (rest of day): {qdf['max_down_atr_pct'].mean():.1f}% ATR avg, "
          f"{qdf['max_down_atr_pct'].median():.1f}% median")
    print(f"  Close position:             {qdf['close_atr_pct'].mean():.1f}% ATR avg, "
          f"{qdf['close_atr_pct'].median():.1f}% median")

    # ── PO behavior rest of day ──
    print(f"\n{'─' * 50}")
    print("PHASE OSCILLATOR BEHAVIOR AFTER 11AM")
    print(f"{'─' * 50}")
    print(f"  PO at 11am:   {qdf['po_at_11am'].mean():.1f} avg, {qdf['po_at_11am'].median():.1f} median")
    print(f"  PO at close:  {qdf['po_eod'].mean():.1f} avg, {qdf['po_eod'].median():.1f} median")
    stayed_above = (qdf["po_above_pct_rod"] == 100).sum()
    print(f"  PO stayed >= 61.8 ALL day: {stayed_above}/{n_qual} ({stayed_above/n_qual*100:.1f}%)")
    print(f"  Avg % of afternoon bars above 61.8: {qdf['po_above_pct_rod'].mean():.1f}%")

    # ── Return Distribution Buckets ──
    print(f"\n{'─' * 50}")
    print("11AM→CLOSE RETURN DISTRIBUTION")
    print(f"{'─' * 50}")

    buckets = [
        (-999, -1.0, "< -1.0%"),
        (-1.0, -0.5, "-1.0% to -0.5%"),
        (-0.5, -0.25, "-0.5% to -0.25%"),
        (-0.25, 0.0, "-0.25% to 0.0%"),
        (0.0, 0.25, "0.0% to +0.25%"),
        (0.25, 0.5, "+0.25% to +0.5%"),
        (0.5, 1.0, "+0.5% to +1.0%"),
        (1.0, 999, "> +1.0%"),
    ]

    for lo, hi, label in buckets:
        count = ((qdf["ret_11am_to_close"] >= lo) & (qdf["ret_11am_to_close"] < hi)).sum()
        bar = "█" * int(count / max(1, n_qual) * 50)
        print(f"  {label:>18s}: {count:4d} ({count/n_qual*100:5.1f}%) {bar}")

    # ── By Decade ──
    print(f"\n{'─' * 50}")
    print("BY ERA")
    print(f"{'─' * 50}")

    qdf["year"] = qdf["date"].apply(lambda d: d.year)
    for era_label, y_start, y_end in [
        ("2000-2004", 2000, 2004),
        ("2005-2009", 2005, 2009),
        ("2010-2014", 2010, 2014),
        ("2015-2019", 2015, 2019),
        ("2020-2025", 2020, 2025),
    ]:
        subset = qdf[(qdf["year"] >= y_start) & (qdf["year"] <= y_end)]
        if len(subset) == 0:
            continue
        n = len(subset)
        avg_ret = subset["ret_11am_to_close"].mean()
        pos = (subset["ret_11am_to_close"] > 0).sum()
        print(f"  {era_label}: n={n:4d}, avg return={avg_ret:+.3f}%, positive={pos/n*100:.0f}%")

    # ── Compare to baseline (all days) ──
    print(f"\n{'─' * 50}")
    print("BASELINE COMPARISON (ALL DAYS)")
    print(f"{'─' * 50}")

    baseline_returns = []
    for date, group in df.groupby("date"):
        bars_11am = group.between_time("11:00", "11:00")
        rest_of_day = group.between_time("11:00", "15:59")
        if len(bars_11am) == 0 or len(rest_of_day) == 0:
            continue
        p_11 = bars_11am.iloc[0]["close"]
        p_close = rest_of_day.iloc[-1]["close"]
        baseline_returns.append((p_close - p_11) / p_11 * 100)

    baseline_returns = np.array(baseline_returns)
    print(f"  All days 11am→Close: mean={baseline_returns.mean():+.3f}%, "
          f"median={np.median(baseline_returns):+.3f}%, "
          f"positive={np.mean(baseline_returns > 0)*100:.1f}%")
    print(f"  Study days 11am→Close: mean={qdf['ret_11am_to_close'].mean():+.3f}%, "
          f"median={qdf['ret_11am_to_close'].median():+.3f}%, "
          f"positive={positive/n_qual*100:.1f}%")

    edge = qdf["ret_11am_to_close"].mean() - baseline_returns.mean()
    print(f"  Edge vs baseline: {edge:+.3f}%")

    # ── Hourly progression from cross to close ──
    print(f"\n{'─' * 50}")
    print("AVERAGE PRICE PATH (% from 11am price)")
    print(f"{'─' * 50}")

    checkpoints = ["11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"]
    checkpoint_returns = {t: [] for t in checkpoints}

    for _, row in qdf.iterrows():
        date = row["date"]
        group = df[df["date"] == date]
        price_11 = row["price_11am"]

        for t_str in checkpoints:
            h, m = int(t_str.split(":")[0]), int(t_str.split(":")[1])
            import datetime
            t = datetime.time(h, m)
            bars_at_t = group[group["time"] == t]
            if len(bars_at_t) > 0:
                p = bars_at_t.iloc[0]["close"]
                checkpoint_returns[t_str].append((p - price_11) / price_11 * 100)

    for t_str in checkpoints:
        vals = checkpoint_returns[t_str]
        if vals:
            avg = np.mean(vals)
            med = np.median(vals)
            pos = np.mean(np.array(vals) > 0) * 100
            print(f"  {t_str}: avg={avg:+.4f}%, median={med:+.4f}%, positive={pos:.0f}% (n={len(vals)})")

    # ── Sample days for review ──
    print(f"\n{'─' * 50}")
    print("SAMPLE QUALIFYING DAYS (most recent 15)")
    print(f"{'─' * 50}")
    print(f"  {'Date':>12s} {'Cross':>8s} {'11am→Close':>12s} {'Open→Close':>12s} {'PO@11am':>8s} {'PO@EOD':>8s}")
    for _, row in qdf.tail(15).iterrows():
        cross_t = str(row["cross_time"])[-8:-3] if not pd.isna(row["cross_time"]) else "?"
        print(f"  {str(row['date']):>12s} {cross_t:>8s} {row['ret_11am_to_close']:+11.3f}% "
              f"{row['ret_open_to_close']:+11.3f}% {row['po_at_11am']:7.1f} {row['po_eod']:7.1f}")

    # ── What about days where PO is above 61.8 at 11am but DIDN'T qualify? ──
    # (crossed above 61.8 in first 30 min but dipped below before 11am)
    print(f"\n{'─' * 50}")
    print("CONTROL: PO crossed > 61.8 early but DIPPED below before 11am")
    print(f"{'─' * 50}")

    dipped_days = []
    for date, group in non_qualifying_days:
        first = group.iloc[0]
        if pd.isna(first.get("phase_oscillator")):
            continue

        first_30 = group.between_time("09:30", "09:50")
        if len(first_30) == 0:
            continue

        # Check if PO crossed above 61.8 in first 30 min
        crossed_early = False
        for i in range(len(first_30)):
            if first_30.iloc[i]["phase_oscillator"] > 61.8 and first_30.iloc[i]["compression"] != 1:
                crossed_early = True
                break

        if not crossed_early:
            continue

        # But didn't stay — this is a "dipped" day
        bars_11am = group.between_time("11:00", "11:00")
        rest_of_day = group.between_time("11:00", "15:59")
        if len(bars_11am) == 0 or len(rest_of_day) == 0:
            continue

        price_11 = bars_11am.iloc[0]["close"]
        rod_close = rest_of_day.iloc[-1]["close"]
        ret = (rod_close - price_11) / price_11 * 100
        dipped_days.append(ret)

    if dipped_days:
        dipped = np.array(dipped_days)
        print(f"  n = {len(dipped)}")
        print(f"  11am→Close: mean={dipped.mean():+.3f}%, median={np.median(dipped):+.3f}%, "
              f"positive={np.mean(dipped > 0)*100:.1f}%")
        print(f"\n  COMPARISON:")
        print(f"    Sustained (stayed > 61.8): {qdf['ret_11am_to_close'].mean():+.3f}% avg, "
              f"{positive/n_qual*100:.0f}% positive (n={n_qual})")
        print(f"    Dipped (crossed but lost it): {dipped.mean():+.3f}% avg, "
              f"{np.mean(dipped > 0)*100:.0f}% positive (n={len(dipped)})")
        print(f"    All days baseline:           {baseline_returns.mean():+.3f}% avg, "
              f"{np.mean(baseline_returns > 0)*100:.0f}% positive")

    conn.close()
    print("\n✓ Study complete.")


if __name__ == "__main__":
    main()
