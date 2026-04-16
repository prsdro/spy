"""
Call Trigger Confirmation Study

Setup: Day opens inside the trigger box (between lower and upper trigger at ±23.6%)
Signal: First 3-minute candle closes above the call trigger (upper 23.6%)
Target: Price hits the next ATR level up (38.2%)

Questions:
1. What is the probability of hitting 38.2% after a confirmed 3m close above trigger?
2. Does that probability change by time of day?
3. Does a 3-minute close back below the call trigger invalidate the play?
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

DB_PATH = "/root/spy/spy.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 3m data...", flush=True)
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, atr_upper_0382, atr_lower_0382, "
        "prev_close, atr_14 "
        "FROM ind_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()

    # RTH only
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14", "atr_upper_trigger"])
    df["date"] = df.index.date
    df["hour"] = df.index.hour
    df["minute"] = df.index.minute

    print(f"Total RTH 3m bars: {len(df):,}")

    # ──────────────────────────────────────────────
    # Results accumulators
    # ──────────────────────────────────────────────

    # Overall stats
    total_days = 0
    days_open_inside_box = 0
    days_with_trigger_close = 0  # got a 3m close above call trigger
    days_hit_0382 = 0            # hit the 38.2% level after trigger close
    days_hit_0382_no_invalidation = 0  # hit 38.2% without closing back below trigger
    days_invalidated = 0         # got a 3m close back below trigger after signal
    days_invalidated_then_hit = 0  # invalidated but still hit 38.2%
    days_invalidated_no_hit = 0    # invalidated and did NOT hit 38.2%
    days_no_invalidation_hit = 0   # no invalidation AND hit 38.2%
    days_no_invalidation_no_hit = 0

    # By trigger hour
    by_hour = defaultdict(lambda: {
        "total": 0, "hit_0382": 0,
        "invalidated": 0, "invalidated_hit": 0, "invalidated_no_hit": 0,
        "clean_hit": 0, "clean_no_hit": 0,
    })

    # By trigger half-hour for finer granularity (with clean/invalid split)
    by_halfhour = defaultdict(lambda: {
        "total": 0, "hit_0382": 0,
        "clean_hit": 0, "clean_no_hit": 0,
        "invalidated_hit": 0, "invalidated_no_hit": 0,
    })

    # Time to target (how many bars after trigger close to hit 38.2%)
    bars_to_target = []
    minutes_to_target = []

    # Track max adverse excursion (how far below trigger before hitting 38.2%)
    max_adverse = []

    # Date lists for charting: by_halfhour_key -> list of {date, hit, clean}
    date_lists = defaultdict(list)

    for date, group in df.groupby("date"):
        total_days += 1
        first = group.iloc[0]

        upper_trigger = first["atr_upper_trigger"]
        lower_trigger = first["atr_lower_trigger"]
        target_0382 = first["atr_upper_0382"]
        day_open = first["open"]

        # Check if open is inside the trigger box
        if not (lower_trigger <= day_open <= upper_trigger):
            continue

        days_open_inside_box += 1

        # Find first 3m bar that CLOSES above the call trigger
        trigger_bars = group[group["close"] > upper_trigger]
        if len(trigger_bars) == 0:
            continue

        trigger_bar = trigger_bars.iloc[0]
        trigger_time = trigger_bars.index[0]
        trigger_hour = trigger_time.hour
        trigger_halfhour = f"{trigger_time.hour:02d}:{0 if trigger_time.minute < 30 else 30:02d}"

        days_with_trigger_close += 1

        # Look at all bars after the trigger close
        remaining = group[group.index > trigger_time]

        # Did price hit 38.2%?
        hit_target = False
        bars_to_hit = None
        if trigger_bar["high"] >= target_0382:
            # The trigger bar itself hit the target
            hit_target = True
            bars_to_hit = 0
        elif len(remaining) > 0:
            target_hits = remaining[remaining["high"] >= target_0382]
            if len(target_hits) > 0:
                hit_target = True
                # Count bars from trigger to target
                trigger_pos = group.index.get_loc(trigger_time)
                target_pos = group.index.get_loc(target_hits.index[0])
                bars_to_hit = target_pos - trigger_pos

        # Did we get a 3m close back below the trigger? (invalidation)
        invalidated = False
        invalidation_time = None
        if len(remaining) > 0:
            inv_bars = remaining[remaining["close"] < upper_trigger]
            if len(inv_bars) > 0:
                invalidated = True
                invalidation_time = inv_bars.index[0]

                # If invalidated, did we still hit? Only count hits AFTER invalidation
                # Actually, let's track two things:
                # 1. Was invalidation before or after the hit?
                # 2. Overall: did invalidation happen at all before EOD?

        # For the invalidation analysis, we care about:
        # - Did invalidation happen BEFORE hitting the target?
        invalidated_before_target = False
        if invalidated and hit_target:
            if bars_to_hit is not None and bars_to_hit > 0:
                target_hit_time = remaining[remaining["high"] >= target_0382].index[0]
                if invalidation_time < target_hit_time:
                    invalidated_before_target = True
            # If bars_to_hit == 0, target was hit on trigger bar itself, so no invalidation before
        elif invalidated and not hit_target:
            invalidated_before_target = True

        # Accumulate results
        if hit_target:
            days_hit_0382 += 1
            if bars_to_hit is not None:
                bars_to_target.append(bars_to_hit)
                minutes_to_target.append(bars_to_hit * 3)

        if invalidated_before_target or (invalidated and not hit_target):
            days_invalidated += 1
            if hit_target:
                days_invalidated_then_hit += 1
            else:
                days_invalidated_no_hit += 1
        else:
            if hit_target:
                days_no_invalidation_hit += 1
            else:
                days_no_invalidation_no_hit += 1

        # By hour
        by_hour[trigger_hour]["total"] += 1
        if hit_target:
            by_hour[trigger_hour]["hit_0382"] += 1
        if invalidated_before_target or (invalidated and not hit_target):
            by_hour[trigger_hour]["invalidated"] += 1
            if hit_target:
                by_hour[trigger_hour]["invalidated_hit"] += 1
            else:
                by_hour[trigger_hour]["invalidated_no_hit"] += 1
        else:
            if hit_target:
                by_hour[trigger_hour]["clean_hit"] += 1
            else:
                by_hour[trigger_hour]["clean_no_hit"] += 1

        # By half-hour (with clean/invalid split)
        is_inv = invalidated_before_target or (invalidated and not hit_target)
        by_halfhour[trigger_halfhour]["total"] += 1
        if hit_target:
            by_halfhour[trigger_halfhour]["hit_0382"] += 1
        if is_inv:
            if hit_target:
                by_halfhour[trigger_halfhour]["invalidated_hit"] += 1
            else:
                by_halfhour[trigger_halfhour]["invalidated_no_hit"] += 1
        else:
            if hit_target:
                by_halfhour[trigger_halfhour]["clean_hit"] += 1
            else:
                by_halfhour[trigger_halfhour]["clean_no_hit"] += 1

        # Record date for charting
        date_lists[trigger_halfhour].append({
            "date": str(date),
            "hit": hit_target,
            "clean": not is_inv,
            "trigger_time": str(trigger_time),
        })

        # Max adverse excursion before target
        if hit_target and len(remaining) > 0 and bars_to_hit is not None and bars_to_hit > 0:
            target_hit_time = remaining[remaining["high"] >= target_0382].index[0]
            bars_before_target = group[(group.index > trigger_time) & (group.index <= target_hit_time)]
            if len(bars_before_target) > 0:
                worst_low = bars_before_target["low"].min()
                adverse = (upper_trigger - worst_low) / upper_trigger * 100
                max_adverse.append(adverse)

    # ──────────────────────────────────────────────
    # Print Results
    # ──────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("CALL TRIGGER CONFIRMATION STUDY")
    print("Setup: Open inside trigger box → 3m close above call trigger → 38.2%")
    print("=" * 70)

    print(f"\n--- Universe ---")
    print(f"  Total trading days:              {total_days:>6,}")
    print(f"  Days opening inside trigger box:  {days_open_inside_box:>6,} ({days_open_inside_box/total_days*100:.1f}%)")
    print(f"  Days with 3m close above trigger: {days_with_trigger_close:>6,} ({days_with_trigger_close/days_open_inside_box*100:.1f}% of box days)")

    print(f"\n--- Question 1: Probability of hitting 38.2% after confirmed trigger ---")
    hit_pct = days_hit_0382 / days_with_trigger_close * 100
    print(f"  Hit 38.2%: {days_hit_0382:,} / {days_with_trigger_close:,} = {hit_pct:.1f}%")
    miss_pct = 100 - hit_pct
    print(f"  Missed:    {days_with_trigger_close - days_hit_0382:,} / {days_with_trigger_close:,} = {miss_pct:.1f}%")

    if bars_to_target:
        bars_arr = np.array(bars_to_target)
        mins_arr = np.array(minutes_to_target)
        print(f"\n  Time to target (when hit):")
        print(f"    Median: {np.median(bars_arr):.0f} bars ({np.median(mins_arr):.0f} min)")
        print(f"    Mean:   {np.mean(bars_arr):.1f} bars ({np.mean(mins_arr):.1f} min)")
        print(f"    75th:   {np.percentile(bars_arr, 75):.0f} bars ({np.percentile(mins_arr, 75):.0f} min)")
        print(f"    90th:   {np.percentile(bars_arr, 90):.0f} bars ({np.percentile(mins_arr, 90):.0f} min)")
        print(f"    Hit on trigger bar itself: {sum(1 for b in bars_to_target if b == 0)} times")

    print(f"\n--- Question 2: Probability by time of day ---")
    print(f"  {'Hour':<8s} {'Total':>6s} {'Hit':>6s} {'Hit%':>7s} {'Clean':>7s} {'Inval':>7s}")
    print(f"  {'-'*42}")
    for hour in sorted(by_hour.keys()):
        h = by_hour[hour]
        hit_pct_h = h["hit_0382"] / h["total"] * 100 if h["total"] > 0 else 0
        clean_pct = h["clean_hit"] / h["total"] * 100 if h["total"] > 0 else 0
        inv_pct = h["invalidated"] / h["total"] * 100 if h["total"] > 0 else 0
        flag = " *" if h["total"] < 50 else ""
        print(f"  {hour:02d}:00   {h['total']:6d} {h['hit_0382']:6d} {hit_pct_h:6.1f}% {clean_pct:6.1f}% {inv_pct:6.1f}%{flag}")

    print(f"\n  By half-hour (with clean/invalid split):")
    print(f"  {'Time':<8s} {'Total':>6s} {'Hit':>6s} {'Hit%':>7s} {'ClnN':>6s} {'ClnHit':>6s} {'Cln%':>7s} {'InvN':>6s} {'InvHit':>6s} {'Inv%':>7s} {'Edge':>8s}")
    print(f"  {'-'*90}")
    for hh in sorted(by_halfhour.keys()):
        h = by_halfhour[hh]
        hit_pct_hh = h["hit_0382"] / h["total"] * 100 if h["total"] > 0 else 0
        cln_n = h["clean_hit"] + h["clean_no_hit"]
        inv_n = h["invalidated_hit"] + h["invalidated_no_hit"]
        cln_pct = h["clean_hit"] / cln_n * 100 if cln_n > 0 else 0
        inv_pct = h["invalidated_hit"] / inv_n * 100 if inv_n > 0 else 0
        edge = cln_pct - inv_pct if cln_n > 0 and inv_n > 0 else 0
        flag = " *" if h["total"] < 50 else ""
        print(f"  {hh}   {h['total']:6d} {h['hit_0382']:6d} {hit_pct_hh:6.1f}% {cln_n:6d} {h['clean_hit']:6d} {cln_pct:6.1f}% {inv_n:6d} {h['invalidated_hit']:6d} {inv_pct:6.1f}% {edge:+7.1f}pp{flag}")

    print(f"\n--- Question 3: Does a 3m close back below trigger invalidate? ---")
    total_inv = days_invalidated
    total_clean = days_with_trigger_close - days_invalidated
    print(f"  Days with invalidation (close back below trigger): {days_invalidated:,} ({days_invalidated/days_with_trigger_close*100:.1f}%)")
    print(f"  Days without invalidation (clean run):             {total_clean:,} ({total_clean/days_with_trigger_close*100:.1f}%)")

    if total_inv > 0:
        inv_hit_pct = days_invalidated_then_hit / total_inv * 100
        print(f"\n  After invalidation:")
        print(f"    Still hit 38.2%: {days_invalidated_then_hit:,} / {total_inv:,} = {inv_hit_pct:.1f}%")
        print(f"    Did NOT hit:     {days_invalidated_no_hit:,} / {total_inv:,} = {100-inv_hit_pct:.1f}%")

    if total_clean > 0:
        clean_hit_pct = days_no_invalidation_hit / total_clean * 100
        print(f"\n  Without invalidation (clean):")
        print(f"    Hit 38.2%:   {days_no_invalidation_hit:,} / {total_clean:,} = {clean_hit_pct:.1f}%")
        print(f"    Did NOT hit: {days_no_invalidation_no_hit:,} / {total_clean:,} = {100-clean_hit_pct:.1f}%")

    if total_inv > 0 and total_clean > 0:
        inv_hit_pct = days_invalidated_then_hit / total_inv * 100
        clean_hit_pct = days_no_invalidation_hit / total_clean * 100
        edge = clean_hit_pct - inv_hit_pct
        print(f"\n  EDGE from avoiding invalidated trades: {edge:+.1f} percentage points")
        print(f"  Clean trades hit rate:       {clean_hit_pct:.1f}%")
        print(f"  Invalidated trades hit rate: {inv_hit_pct:.1f}%")

    # Invalidation breakdown by hour
    print(f"\n  Invalidation impact by trigger hour:")
    print(f"  {'Hour':<8s} {'Clean%':>8s} {'(n)':>6s} {'Inval%':>8s} {'(n)':>6s} {'Edge':>8s}")
    print(f"  {'-'*46}")
    for hour in sorted(by_hour.keys()):
        h = by_hour[hour]
        clean_n = h["clean_hit"] + h["clean_no_hit"]
        inv_n = h["invalidated_hit"] + h["invalidated_no_hit"]
        if clean_n > 0 and inv_n > 0:
            clean_r = h["clean_hit"] / clean_n * 100
            inv_r = h["invalidated_hit"] / inv_n * 100
            edge = clean_r - inv_r
            c_flag = "*" if clean_n < 30 else " "
            i_flag = "*" if inv_n < 30 else " "
            print(f"  {hour:02d}:00   {clean_r:7.1f}%{c_flag} {clean_n:5d} {inv_r:7.1f}%{i_flag} {inv_n:5d} {edge:+7.1f}pp")
        elif clean_n > 0:
            clean_r = h["clean_hit"] / clean_n * 100
            print(f"  {hour:02d}:00   {clean_r:7.1f}%  {clean_n:5d}    n/a        0       n/a")

    # Max adverse excursion
    if max_adverse:
        ae = np.array(max_adverse)
        print(f"\n--- Max Adverse Excursion (before hitting 38.2%) ---")
        print(f"  Median: {np.median(ae):.3f}%")
        print(f"  Mean:   {np.mean(ae):.3f}%")
        print(f"  75th:   {np.percentile(ae, 75):.3f}%")
        print(f"  90th:   {np.percentile(ae, 90):.3f}%")

    # ──────────────────────────────────────────────
    # Export data for visualization
    # ──────────────────────────────────────────────
    print("\n\n--- DATA FOR VISUALIZATION (JSON-ready) ---")
    print("OVERALL:", {
        "total_days": total_days,
        "box_days": days_open_inside_box,
        "trigger_days": days_with_trigger_close,
        "hit_0382": days_hit_0382,
        "hit_pct": round(days_hit_0382 / days_with_trigger_close * 100, 1),
        "invalidated": days_invalidated,
        "invalidated_hit": days_invalidated_then_hit,
        "clean_total": total_clean,
        "clean_hit": days_no_invalidation_hit,
    })

    print("\nBY_HOUR:", {
        hour: {
            "total": h["total"],
            "hit": h["hit_0382"],
            "hit_pct": round(h["hit_0382"] / h["total"] * 100, 1) if h["total"] > 0 else 0,
            "clean_n": h["clean_hit"] + h["clean_no_hit"],
            "clean_hit": h["clean_hit"],
            "inv_n": h["invalidated_hit"] + h["invalidated_no_hit"],
            "inv_hit": h["invalidated_hit"],
        }
        for hour in sorted(by_hour.keys())
    })

    print("\nBY_HALFHOUR:", {
        hh: {
            "total": h["total"],
            "hit": h["hit_0382"],
            "hit_pct": round(h["hit_0382"] / h["total"] * 100, 1) if h["total"] > 0 else 0,
        }
        for hh in sorted(by_halfhour.keys())
    })

    if bars_to_target:
        print("\nTIME_TO_TARGET:", {
            "median_bars": int(np.median(bars_to_target)),
            "median_min": int(np.median(minutes_to_target)),
            "p75_bars": int(np.percentile(bars_to_target, 75)),
            "p75_min": int(np.percentile(minutes_to_target, 75)),
            "p90_bars": int(np.percentile(bars_to_target, 90)),
            "p90_min": int(np.percentile(minutes_to_target, 90)),
            "on_trigger_bar": sum(1 for b in bars_to_target if b == 0),
        })

    # ──────────────────────────────────────────────
    # Export date lists as JSON for the study page
    # ──────────────────────────────────────────────
    import json
    export = {}
    for hh in sorted(date_lists.keys()):
        entries = date_lists[hh]
        export[hh] = [
            {"d": e["date"], "h": 1 if e["hit"] else 0, "c": 1 if e["clean"] else 0}
            for e in entries
        ]
    with open("/root/milkman/data/call-trigger-dates.json", "w") as f:
        json.dump(export, f, separators=(",", ":"))
    print(f"\nExported {sum(len(v) for v in export.values())} dates to /root/milkman/data/call-trigger-dates.json")

    conn.close()


if __name__ == "__main__":
    main()
