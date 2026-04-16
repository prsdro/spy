"""
Study: Time in Chop After Golden Gate Completion

Hypothesis: After a Golden Gate completes (price reaches 61.8% ATR), price often
stalls between 61.8% and 78.6%. Is there a "time in chop" duration that predicts
reversal back below 61.8% vs continuation through 78.6%?

Setup:
- GG completion = bar where high >= upper_0618 (bullish) or low <= lower_0618 (bearish)
- "Chop zone" = price between 61.8% and 78.6% ATR levels
- Track consecutive 10m bars where close stays >= 61.8% but high hasn't hit 78.6%
- Resolution: "continuation" = high reaches 78.6%, "reversal" = close drops below 61.8%

Measurements:
- Bars in chop before resolution
- Reversal rate by chop duration (1 bar, 2 bars, 3 bars, etc.)
- Does a long chop guarantee reversal?
- Time-of-day effects
- PO / ribbon state during chop
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

DB_PATH = "/root/spy/spy.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 10m indicator data...", flush=True)
    df = pd.read_sql_query(
        "SELECT * FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date
    df["time"] = df.index.time

    print(f"Loaded {len(df):,} bars across {df['date'].nunique():,} trading days\n")

    # ── Find GG completions and track chop zone behavior ──
    events = []  # both bull and bear

    for date, group in df.groupby("date"):
        if len(group) < 3:
            continue

        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]
        if pd.isna(prev_close) or pd.isna(atr) or atr == 0:
            continue

        upper_0618 = first["atr_upper_0618"]
        upper_0786 = first["atr_upper_0786"]
        upper_100 = first["atr_upper_100"]
        lower_0618 = first["atr_lower_0618"]
        lower_0786 = first["atr_lower_0786"]
        lower_100 = first["atr_lower_100"]

        if pd.isna(upper_0618):
            continue

        # ── BULLISH GG completion ──
        # Find first bar where high >= upper_0618
        bull_comp_idx = None
        for i in range(len(group)):
            if group.iloc[i]["high"] >= upper_0618:
                bull_comp_idx = i
                break

        if bull_comp_idx is not None:
            comp_bar = group.iloc[bull_comp_idx]
            comp_time = group.index[bull_comp_idx]

            # Did this bar ALSO hit 78.6%? If so, no chop — instant continuation
            if comp_bar["high"] >= upper_0786:
                events.append({
                    "date": date,
                    "direction": "bull",
                    "comp_time": comp_time.time(),
                    "comp_hour": comp_time.hour,
                    "chop_bars": 0,
                    "chop_minutes": 0,
                    "resolution": "instant_continuation",
                    "po_at_comp": comp_bar.get("phase_oscillator", np.nan),
                    "po_at_exit": comp_bar.get("phase_oscillator", np.nan),
                    "compression_at_comp": comp_bar.get("compression", 0),
                    "fast_cloud_at_comp": comp_bar.get("fast_cloud_bullish", np.nan),
                    "hit_100": comp_bar["high"] >= upper_100,
                    "exit_time": comp_time.time(),
                })
            else:
                # Track chop zone: bars after completion where close >= 0618 and high < 0786
                chop_bars = 0
                resolution = "eod_in_chop"  # default if day ends while still chopping
                exit_idx = None

                for j in range(bull_comp_idx + 1, len(group)):
                    bar = group.iloc[j]

                    # Check exit conditions FIRST
                    if bar["high"] >= upper_0786:
                        resolution = "continuation"
                        exit_idx = j
                        break
                    elif bar["close"] < upper_0618:
                        resolution = "reversal"
                        exit_idx = j
                        break
                    else:
                        # Still in chop zone
                        chop_bars += 1

                if exit_idx is None:
                    exit_idx = len(group) - 1

                exit_bar = group.iloc[exit_idx]

                # Did price eventually hit 100% ATR today?
                remaining = group.iloc[bull_comp_idx:]
                hit_100 = (remaining["high"] >= upper_100).any()

                events.append({
                    "date": date,
                    "direction": "bull",
                    "comp_time": comp_time.time(),
                    "comp_hour": comp_time.hour,
                    "chop_bars": chop_bars,
                    "chop_minutes": chop_bars * 10,
                    "resolution": resolution,
                    "po_at_comp": comp_bar.get("phase_oscillator", np.nan),
                    "po_at_exit": exit_bar.get("phase_oscillator", np.nan),
                    "compression_at_comp": comp_bar.get("compression", 0),
                    "fast_cloud_at_comp": comp_bar.get("fast_cloud_bullish", np.nan),
                    "hit_100": hit_100,
                    "exit_time": group.index[exit_idx].time(),
                })

        # ── BEARISH GG completion ──
        bear_comp_idx = None
        for i in range(len(group)):
            if group.iloc[i]["low"] <= lower_0618:
                bear_comp_idx = i
                break

        if bear_comp_idx is not None:
            comp_bar = group.iloc[bear_comp_idx]
            comp_time = group.index[bear_comp_idx]

            if comp_bar["low"] <= lower_0786:
                events.append({
                    "date": date,
                    "direction": "bear",
                    "comp_time": comp_time.time(),
                    "comp_hour": comp_time.hour,
                    "chop_bars": 0,
                    "chop_minutes": 0,
                    "resolution": "instant_continuation",
                    "po_at_comp": comp_bar.get("phase_oscillator", np.nan),
                    "po_at_exit": comp_bar.get("phase_oscillator", np.nan),
                    "compression_at_comp": comp_bar.get("compression", 0),
                    "fast_cloud_at_comp": comp_bar.get("fast_cloud_bullish", np.nan),
                    "hit_100": comp_bar["low"] <= lower_100,
                    "exit_time": comp_time.time(),
                })
            else:
                chop_bars = 0
                resolution = "eod_in_chop"
                exit_idx = None

                for j in range(bear_comp_idx + 1, len(group)):
                    bar = group.iloc[j]

                    if bar["low"] <= lower_0786:
                        resolution = "continuation"
                        exit_idx = j
                        break
                    elif bar["close"] > lower_0618:
                        resolution = "reversal"
                        exit_idx = j
                        break
                    else:
                        chop_bars += 1

                if exit_idx is None:
                    exit_idx = len(group) - 1

                exit_bar = group.iloc[exit_idx]
                remaining = group.iloc[bear_comp_idx:]
                hit_100 = (remaining["low"] <= lower_100).any()

                events.append({
                    "date": date,
                    "direction": "bear",
                    "comp_time": comp_time.time(),
                    "comp_hour": comp_time.hour,
                    "chop_bars": chop_bars,
                    "chop_minutes": chop_bars * 10,
                    "resolution": resolution,
                    "po_at_comp": comp_bar.get("phase_oscillator", np.nan),
                    "po_at_exit": exit_bar.get("phase_oscillator", np.nan),
                    "compression_at_comp": comp_bar.get("compression", 0),
                    "fast_cloud_at_comp": comp_bar.get("fast_cloud_bullish", np.nan),
                    "hit_100": hit_100,
                    "exit_time": group.index[exit_idx].time(),
                })

    edf = pd.DataFrame(events)
    n_total = len(edf)
    n_bull = (edf["direction"] == "bull").sum()
    n_bear = (edf["direction"] == "bear").sum()

    print("=" * 70)
    print("GOLDEN GATE CHOP ZONE: TIME BETWEEN 61.8% AND 78.6%")
    print("=" * 70)
    print(f"\nTotal GG completions: {n_total:,}")
    print(f"  Bullish: {n_bull:,}")
    print(f"  Bearish: {n_bear:,}")

    # ── Overall resolution breakdown ──
    print(f"\n{'─' * 55}")
    print("OVERALL RESOLUTION")
    print(f"{'─' * 55}")

    for direction in ["bull", "bear", "both"]:
        if direction == "both":
            sub = edf
            label = "COMBINED"
        else:
            sub = edf[edf["direction"] == direction]
            label = direction.upper()

        n = len(sub)
        print(f"\n  {label} (n={n:,}):")
        for res in ["instant_continuation", "continuation", "reversal", "eod_in_chop"]:
            count = (sub["resolution"] == res).sum()
            print(f"    {res:>25s}: {count:5d} ({count/n*100:5.1f}%)")

    # ── The key question: reversal rate by chop duration ──
    # Exclude instant continuations (0 bars in chop = blew right through)
    # Focus on events that actually entered the chop zone
    chop_events = edf[edf["resolution"].isin(["continuation", "reversal", "eod_in_chop"])].copy()
    n_chop = len(chop_events)

    print(f"\n{'─' * 55}")
    print("CHOP ZONE EVENTS (excluding instant continuations)")
    print(f"{'─' * 55}")
    print(f"  Total events that entered chop: {n_chop:,}")

    cont = (chop_events["resolution"] == "continuation").sum()
    rev = (chop_events["resolution"] == "reversal").sum()
    eod = (chop_events["resolution"] == "eod_in_chop").sum()
    print(f"  Continuation (hit 78.6%): {cont} ({cont/n_chop*100:.1f}%)")
    print(f"  Reversal (fell below 61.8%): {rev} ({rev/n_chop*100:.1f}%)")
    print(f"  EOD still in chop: {eod} ({eod/n_chop*100:.1f}%)")

    # ── CORE TABLE: Reversal rate by number of bars in chop ──
    print(f"\n{'─' * 55}")
    print("REVERSAL RATE BY TIME IN CHOP (10-minute bars)")
    print(f"{'─' * 55}")

    # Combined
    print(f"\n  COMBINED (Bull + Bear):")
    print(f"  {'Bars':>6s} {'Minutes':>8s} {'n':>6s} {'Cont':>6s} {'Rev':>6s} {'EOD':>6s} {'Rev%':>7s} {'Cont%':>7s} {'Cum Rev%':>9s}")

    max_bars = min(int(chop_events["chop_bars"].quantile(0.99)) + 1, 40)
    cum_cont = 0
    cum_rev = 0
    cum_eod = 0

    for bars in range(0, max_bars + 1):
        sub = chop_events[chop_events["chop_bars"] == bars]
        n = len(sub)
        if n == 0:
            continue
        c = (sub["resolution"] == "continuation").sum()
        r = (sub["resolution"] == "reversal").sum()
        e = (sub["resolution"] == "eod_in_chop").sum()

        cum_cont += c
        cum_rev += r
        cum_eod += e

        rev_pct = r / n * 100 if n > 0 else 0
        cont_pct = c / n * 100 if n > 0 else 0

        # Cumulative: of events that chopped AT LEAST this long, what % reversed?
        still_chopping = n_chop - cum_cont - cum_rev - cum_eod + r + e + c
        # Actually, let's do: of events that have AT LEAST this many bars, what % eventually reverse?
        at_least = chop_events[chop_events["chop_bars"] >= bars]
        al_n = len(at_least)
        al_rev = (at_least["resolution"] == "reversal").sum()
        al_cont = (at_least["resolution"] == "continuation").sum()
        # Among resolved events with at least N bars
        al_resolved = al_rev + al_cont
        cum_rev_pct = al_rev / al_resolved * 100 if al_resolved > 0 else 0

        marker = "  ***" if rev_pct >= 70 and n >= 20 else ("  **" if rev_pct >= 60 and n >= 20 else "")
        print(f"  {bars:6d} {bars*10:7d}m {n:6d} {c:6d} {r:6d} {e:6d} {rev_pct:6.1f}% {cont_pct:6.1f}% {cum_rev_pct:7.1f}%{marker}")

    # ── Bucketed view for cleaner reading ──
    print(f"\n{'─' * 55}")
    print("REVERSAL RATE BY CHOP DURATION BUCKET")
    print(f"{'─' * 55}")

    buckets = [
        (0, 0, "0 bars (instant exit)"),
        (1, 1, "1 bar (10 min)"),
        (2, 2, "2 bars (20 min)"),
        (3, 3, "3 bars (30 min)"),
        (4, 5, "4-5 bars (40-50 min)"),
        (6, 8, "6-8 bars (60-80 min)"),
        (9, 12, "9-12 bars (90-120 min)"),
        (13, 18, "13-18 bars (130-180 min)"),
        (19, 50, "19+ bars (190+ min)"),
    ]

    for direction in ["bull", "bear", "both"]:
        if direction == "both":
            sub_all = chop_events
            label = "COMBINED"
        else:
            sub_all = chop_events[chop_events["direction"] == direction]
            label = direction.upper()

        print(f"\n  {label}:")
        print(f"  {'Bucket':>28s} {'n':>6s} {'Cont':>6s} {'Rev':>6s} {'Rev%':>7s} {'Cont%':>7s}")

        for lo, hi, blabel in buckets:
            sub = sub_all[(sub_all["chop_bars"] >= lo) & (sub_all["chop_bars"] <= hi)]
            n = len(sub)
            if n == 0:
                continue
            c = (sub["resolution"] == "continuation").sum()
            r = (sub["resolution"] == "reversal").sum()
            resolved = c + r
            rev_pct = r / resolved * 100 if resolved > 0 else 0
            cont_pct = c / resolved * 100 if resolved > 0 else 0
            flag = " <<<" if rev_pct >= 65 and resolved >= 30 else ""
            print(f"  {blabel:>28s} {n:6d} {c:6d} {r:6d} {rev_pct:6.1f}% {cont_pct:6.1f}%{flag}")

    # ── "At least N bars" survival analysis ──
    print(f"\n{'─' * 55}")
    print("SURVIVAL ANALYSIS: If chopping for at least N bars...")
    print(f"{'─' * 55}")

    print(f"\n  {'>=Bars':>7s} {'Min':>5s} {'Still':>7s} {'Will Cont':>10s} {'Will Rev':>10s} {'Rev%':>7s}")

    for threshold in [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 20, 25, 30]:
        at_least = chop_events[chop_events["chop_bars"] >= threshold]
        n = len(at_least)
        if n < 10:
            continue
        c = (at_least["resolution"] == "continuation").sum()
        r = (at_least["resolution"] == "reversal").sum()
        resolved = c + r
        if resolved == 0:
            continue
        rev_pct = r / resolved * 100
        print(f"  {threshold:>5d}b {threshold*10:>4d}m {n:7d} {c:>5d} ({c/resolved*100:4.1f}%) "
              f"{r:>5d} ({rev_pct:4.1f}%){' <<<' if rev_pct >= 65 and resolved >= 30 else ''}")

    # ── Time of day effect ──
    print(f"\n{'─' * 55}")
    print("CHOP RESOLUTION BY GG COMPLETION HOUR")
    print(f"{'─' * 55}")

    for direction in ["bull", "bear"]:
        sub_all = chop_events[chop_events["direction"] == direction]
        label = direction.upper()
        print(f"\n  {label}:")
        print(f"  {'Hour':>6s} {'n':>6s} {'Cont':>6s} {'Rev':>6s} {'EOD':>6s} "
              f"{'Rev%':>7s} {'Avg Chop':>9s}")

        for hour in range(9, 16):
            sub = sub_all[sub_all["comp_hour"] == hour]
            n = len(sub)
            if n < 10:
                continue
            c = (sub["resolution"] == "continuation").sum()
            r = (sub["resolution"] == "reversal").sum()
            e = (sub["resolution"] == "eod_in_chop").sum()
            resolved = c + r
            rev_pct = r / resolved * 100 if resolved > 0 else 0
            avg_chop = sub["chop_bars"].mean()
            print(f"  {hour:02d}:00 {n:6d} {c:6d} {r:6d} {e:6d} {rev_pct:6.1f}% {avg_chop:7.1f} bars")

    # ── PO at completion vs resolution ──
    print(f"\n{'─' * 55}")
    print("PO AT GG COMPLETION vs RESOLUTION")
    print(f"{'─' * 55}")

    chop_with_po = chop_events.dropna(subset=["po_at_comp"])

    po_bins = [
        (-999, -61.8, "PO < -61.8"),
        (-61.8, -23.6, "PO -61.8 to -23.6"),
        (-23.6, 23.6, "PO -23.6 to +23.6"),
        (23.6, 61.8, "PO +23.6 to +61.8"),
        (61.8, 100, "PO +61.8 to +100"),
        (100, 999, "PO > +100"),
    ]

    # For bullish: high PO = in the direction of the move
    print(f"\n  BULLISH GG completions:")
    print(f"  {'PO Zone':>22s} {'n':>5s} {'Cont%':>7s} {'Rev%':>7s} {'Avg Chop':>9s}")
    bull_chop = chop_with_po[chop_with_po["direction"] == "bull"]
    for lo, hi, label in po_bins:
        sub = bull_chop[(bull_chop["po_at_comp"] >= lo) & (bull_chop["po_at_comp"] < hi)]
        n = len(sub)
        if n < 15:
            continue
        c = (sub["resolution"] == "continuation").sum()
        r = (sub["resolution"] == "reversal").sum()
        resolved = c + r
        if resolved == 0:
            continue
        avg_chop = sub["chop_bars"].mean()
        print(f"  {label:>22s} {n:5d} {c/resolved*100:6.1f}% {r/resolved*100:6.1f}% {avg_chop:7.1f} bars")

    print(f"\n  BEARISH GG completions:")
    print(f"  {'PO Zone':>22s} {'n':>5s} {'Cont%':>7s} {'Rev%':>7s} {'Avg Chop':>9s}")
    bear_chop = chop_with_po[chop_with_po["direction"] == "bear"]
    for lo, hi, label in po_bins:
        sub = bear_chop[(bear_chop["po_at_comp"] >= lo) & (bear_chop["po_at_comp"] < hi)]
        n = len(sub)
        if n < 15:
            continue
        c = (sub["resolution"] == "continuation").sum()
        r = (sub["resolution"] == "reversal").sum()
        resolved = c + r
        if resolved == 0:
            continue
        avg_chop = sub["chop_bars"].mean()
        print(f"  {label:>22s} {n:5d} {c/resolved*100:6.1f}% {r/resolved*100:6.1f}% {avg_chop:7.1f} bars")

    # ── Fast cloud state at completion ──
    print(f"\n{'─' * 55}")
    print("FAST CLOUD (10m) AT GG COMPLETION vs RESOLUTION")
    print(f"{'─' * 55}")

    for direction in ["bull", "bear"]:
        sub_all = chop_events[chop_events["direction"] == direction].dropna(subset=["fast_cloud_at_comp"])
        label = direction.upper()
        print(f"\n  {label}:")
        for cloud_val, cloud_label in [(1, "Bullish cloud"), (0, "Bearish cloud")]:
            sub = sub_all[sub_all["fast_cloud_at_comp"] == cloud_val]
            n = len(sub)
            if n < 20:
                continue
            c = (sub["resolution"] == "continuation").sum()
            r = (sub["resolution"] == "reversal").sum()
            resolved = c + r
            if resolved == 0:
                continue
            rev_pct = r / resolved * 100
            avg_chop = sub["chop_bars"].mean()
            print(f"    {cloud_label:>16s}: n={n:5d}, cont={c/resolved*100:.1f}%, "
                  f"rev={rev_pct:.1f}%, avg chop={avg_chop:.1f} bars")

    # ── Compression at completion ──
    print(f"\n{'─' * 55}")
    print("COMPRESSION AT GG COMPLETION vs RESOLUTION")
    print(f"{'─' * 55}")

    for direction in ["bull", "bear"]:
        sub_all = chop_events[chop_events["direction"] == direction]
        label = direction.upper()
        print(f"\n  {label}:")
        for comp_val, comp_label in [(1, "In compression"), (0, "In expansion")]:
            sub = sub_all[sub_all["compression_at_comp"] == comp_val]
            n = len(sub)
            if n < 20:
                continue
            c = (sub["resolution"] == "continuation").sum()
            r = (sub["resolution"] == "reversal").sum()
            resolved = c + r
            if resolved == 0:
                continue
            rev_pct = r / resolved * 100
            avg_chop = sub["chop_bars"].mean()
            print(f"    {comp_label:>16s}: n={n:5d}, cont={c/resolved*100:.1f}%, "
                  f"rev={rev_pct:.1f}%, avg chop={avg_chop:.1f} bars")

    # ── Combined signal: long chop + adverse PO ──
    print(f"\n{'─' * 55}")
    print("COMBINED SIGNAL: CHOP DURATION + PO ZONE")
    print(f"{'─' * 55}")

    print("\n  BULLISH — chop bars >= N AND PO < 61.8 at completion:")
    for threshold in [3, 5, 6, 8, 10]:
        sub = bull_chop[(bull_chop["chop_bars"] >= threshold) & (bull_chop["po_at_comp"] < 61.8)]
        n = len(sub)
        if n < 10:
            continue
        c = (sub["resolution"] == "continuation").sum()
        r = (sub["resolution"] == "reversal").sum()
        resolved = c + r
        if resolved == 0:
            continue
        rev_pct = r / resolved * 100
        print(f"    >= {threshold} bars + PO < 61.8: n={n}, cont={c}, rev={r}, rev%={rev_pct:.1f}%")

    print("\n  BULLISH — chop bars >= N AND PO >= 61.8 at completion:")
    for threshold in [3, 5, 6, 8, 10]:
        sub = bull_chop[(bull_chop["chop_bars"] >= threshold) & (bull_chop["po_at_comp"] >= 61.8)]
        n = len(sub)
        if n < 10:
            continue
        c = (sub["resolution"] == "continuation").sum()
        r = (sub["resolution"] == "reversal").sum()
        resolved = c + r
        if resolved == 0:
            continue
        rev_pct = r / resolved * 100
        print(f"    >= {threshold} bars + PO >= 61.8: n={n}, cont={c}, rev={r}, rev%={rev_pct:.1f}%")

    print("\n  BEARISH — chop bars >= N AND PO > -61.8 at completion:")
    for threshold in [3, 5, 6, 8, 10]:
        sub = bear_chop[(bear_chop["chop_bars"] >= threshold) & (bear_chop["po_at_comp"] > -61.8)]
        n = len(sub)
        if n < 10:
            continue
        c = (sub["resolution"] == "continuation").sum()
        r = (sub["resolution"] == "reversal").sum()
        resolved = c + r
        if resolved == 0:
            continue
        rev_pct = r / resolved * 100
        print(f"    >= {threshold} bars + PO > -61.8: n={n}, cont={c}, rev={r}, rev%={rev_pct:.1f}%")

    # ── What happens to "reversal" events? Do they bounce back? ──
    print(f"\n{'─' * 55}")
    print("AFTER REVERSAL: Does price recover back above 61.8%?")
    print(f"{'─' * 55}")

    rev_events = edf[edf["resolution"] == "reversal"]
    # We need to go back to the raw data for this
    bounce_count = 0
    total_rev = 0

    for _, ev in rev_events.iterrows():
        date = ev["date"]
        group = df[df["date"] == date]
        if len(group) == 0:
            continue

        first = group.iloc[0]
        if ev["direction"] == "bull":
            level = first["atr_upper_0618"]
            # Find exit bar
            exit_bars = group[group.index.time >= ev["exit_time"]]
            if len(exit_bars) < 2:
                continue
            after_exit = exit_bars.iloc[1:]  # bars after the reversal bar
            if len(after_exit) == 0:
                continue
            total_rev += 1
            if (after_exit["high"] >= level).any():
                bounce_count += 1
        else:
            level = first["atr_lower_0618"]
            exit_bars = group[group.index.time >= ev["exit_time"]]
            if len(exit_bars) < 2:
                continue
            after_exit = exit_bars.iloc[1:]
            if len(after_exit) == 0:
                continue
            total_rev += 1
            if (after_exit["low"] <= level).any():
                bounce_count += 1

    print(f"  Price recovered back to 61.8% after reversal: {bounce_count}/{total_rev} "
          f"({bounce_count/total_rev*100:.1f}%)" if total_rev > 0 else "  No data")

    # ── Summary statistics ──
    print(f"\n{'─' * 55}")
    print("CHOP DURATION STATISTICS (for events that entered chop)")
    print(f"{'─' * 55}")

    for direction in ["bull", "bear"]:
        sub = chop_events[chop_events["direction"] == direction]
        label = direction.upper()
        print(f"\n  {label}:")
        print(f"    Mean chop bars:   {sub['chop_bars'].mean():.1f} ({sub['chop_bars'].mean()*10:.0f} min)")
        print(f"    Median chop bars: {sub['chop_bars'].median():.0f} ({sub['chop_bars'].median()*10:.0f} min)")
        print(f"    75th pctl:        {sub['chop_bars'].quantile(0.75):.0f} bars ({sub['chop_bars'].quantile(0.75)*10:.0f} min)")
        print(f"    90th pctl:        {sub['chop_bars'].quantile(0.90):.0f} bars ({sub['chop_bars'].quantile(0.90)*10:.0f} min)")
        print(f"    Max:              {sub['chop_bars'].max():.0f} bars ({sub['chop_bars'].max()*10:.0f} min)")

        # By resolution
        for res in ["continuation", "reversal"]:
            rs = sub[sub["resolution"] == res]
            if len(rs) > 0:
                print(f"    {res} avg chop: {rs['chop_bars'].mean():.1f} bars ({rs['chop_bars'].mean()*10:.0f} min)")

    conn.close()
    print("\n✓ Study complete.")


if __name__ == "__main__":
    main()
