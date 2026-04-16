"""
10-Minute Compression → Expansion Study
========================================

WHAT THIS STUDIES
When the 10m Phase Oscillator enters compression (Bollinger Band squeeze),
price consolidates in a tight range. Eventually the squeeze releases —
"expansion" — and price moves directionally. This study measures:

1. How do compressions resolve? (bullish vs bearish expansion)
2. What are the max profit % and max drawdown % over 120 minutes after
   expansion fires, using the midpoint of the compression range as the base?
3. Does the 10m 21 EMA bias (price above/below EMA 21 at expansion) help
   predict which direction expansion will fire into?
4. Does compression length correlate with expansion magnitude or direction?


METHODOLOGY
-----------

1. EVENT IDENTIFICATION

   We scan 10-minute RTH bars (09:30–15:59) for contiguous runs where
   compression=1. A "compression period" is a sequence of consecutive
   bars with compression=1.

   Because compression can flicker (toggle off for 1 bar then back on),
   we apply a GAP TOLERANCE of 1 bar: if compression=0 for a single bar
   surrounded by compression=1 on both sides, we treat it as part of the
   same compression period.

   MINIMUM DURATION: We require at least 3 bars (30 minutes) of
   compression to filter out noise. Shorter squeezes are ignored.

   The compression period ends (expansion fires) on the first bar where
   compression=0 AND the previous bar had compression=1 (after gap
   tolerance is applied).


2. COMPRESSION METRICS

   For each compression period we record:
     - Duration: number of 10m bars in the squeeze
     - Price range: highest high and lowest low during compression
     - Midpoint: (compression_high + compression_low) / 2
     - EMA 21 bias at expansion: close vs ema_21 on the expansion bar


3. EXPANSION DIRECTION

   Determined by the first bar AFTER compression ends:
     - BULLISH: close > compression midpoint
     - BEARISH: close < compression midpoint

   If close == midpoint exactly (rare), we use PO sign as tiebreaker.


4. OUTCOME MEASUREMENT (120 minutes after expansion)

   Starting from the expansion bar, we look forward 12 bars (120 min)
   or to end of RTH, whichever comes first.

   All measurements are relative to the compression MIDPOINT:
     - Max profit %:   max favorable excursion in expansion direction
       Bullish: (highest_high - midpoint) / midpoint × 100
       Bearish: (midpoint - lowest_low) / midpoint × 100
     - Max drawdown %: max adverse excursion against expansion direction
       Bullish: (midpoint - lowest_low) / midpoint × 100
       Bearish: (highest_high - midpoint) / midpoint × 100
     - Net move %: (close_at_end - midpoint) / midpoint × 100
       Positive = moved in expansion direction, negative = reversed


5. SEGMENTATION DIMENSIONS

   a) COMPRESSION DURATION (10m bars):
      - Short:   3-5 bars   (30-50 min)
      - Medium:  6-11 bars  (60-110 min)
      - Long:    12-17 bars (120-170 min)
      - XLong:   18+ bars   (180+ min)

   b) EMA 21 BIAS AT EXPANSION:
      - Bullish: close > ema_21 on the expansion bar
      - Bearish: close < ema_21 on the expansion bar

   c) EMA 21 vs EMA 48 TREND:
      - Bullish: ema_21 > ema_48 (uptrend structure)
      - Bearish: ema_21 < ema_48 (downtrend structure)

   d) ATR LEVEL POSITION at expansion:
      - above 61.8% / 38.2%-61.8% / trigger-38.2% / trigger box / below PDC
      (and mirrored for bearish side)

   e) TIME OF DAY of expansion:
      - open (9:30-10:30) / mid (10:30-14:00) / close (14:00-16:00)


6. OUTPUT

   Baseline: total events, bullish %, bearish %, mean/median profit & drawdown
   Contingency tables for each dimension × expansion direction
   Cross-tab: duration × EMA21 bias (the two key questions)
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/root/spy/spy.db"

# ── Parameters ──
MIN_COMPRESSION_BARS = 3    # minimum 30 min of compression
GAP_TOLERANCE = 1           # allow 1-bar interruption in compression
FORWARD_BARS = 12           # 120 min after expansion
OUTCOME_WINDOW_MIN = 120    # for labeling


def find_compression_periods(group):
    """
    Find compression periods in a day's worth of 10m bars.
    Returns list of (start_idx, end_idx, duration) tuples.
    end_idx is the index of the FIRST non-compression bar (the expansion bar).
    """
    comp = group["compression"].values
    n = len(comp)

    # Apply gap tolerance: fill single-bar gaps
    smoothed = comp.copy()
    for i in range(1, n - 1):
        if smoothed[i] == 0 and smoothed[i-1] == 1 and smoothed[i+1] == 1:
            smoothed[i] = 1

    # Find contiguous runs of compression=1
    periods = []
    in_run = False
    start = 0

    for i in range(n):
        if smoothed[i] == 1 and not in_run:
            start = i
            in_run = True
        elif smoothed[i] == 0 and in_run:
            duration = i - start
            if duration >= MIN_COMPRESSION_BARS:
                periods.append((start, i, duration))
            in_run = False

    # Don't count compressions that run to end of day (no expansion observed)

    return periods


def get_atr_position_at(bar):
    """Categorize where price is on the ATR grid."""
    price = bar["close"]
    pdc = bar["prev_close"]

    if pd.isna(pdc) or pd.isna(bar.get("atr_upper_trigger")):
        return "unknown"

    if price > bar["atr_upper_0618"]:
        return "above 61.8%"
    elif price > bar["atr_upper_0382"]:
        return "38.2%-61.8%"
    elif price > bar["atr_upper_trigger"]:
        return "trigger-38.2%"
    elif price > pdc:
        return "bull trigger box"
    elif price > bar["atr_lower_trigger"]:
        return "bear trigger box"
    elif price > bar["atr_lower_0382"]:
        return "trigger to -38.2%"
    elif price > bar["atr_lower_0618"]:
        return "-38.2% to -61.8%"
    else:
        return "below -61.8%"


def get_time_bucket(timestamp):
    t = timestamp.time()
    if t < pd.Timestamp("10:30").time():
        return "open (9:30-10:30)"
    elif t < pd.Timestamp("14:00").time():
        return "mid (10:30-14:00)"
    else:
        return "close (14:00-16:00)"


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 10m data...", flush=True)
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "ema_21, ema_48, "
        "fast_cloud_bullish, slow_cloud_bullish, "
        "compression, phase_oscillator, "
        "prev_close, atr_14, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    conn.close()

    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["ema_21", "ema_48", "prev_close", "atr_14"])
    df["date"] = df.index.date

    print(f"10m RTH bars: {len(df):,}")
    print("Scanning for compression → expansion events...\n", flush=True)

    events = []

    for date, group in df.groupby("date"):
        if len(group) < MIN_COMPRESSION_BARS + FORWARD_BARS:
            continue

        periods = find_compression_periods(group)

        for start_idx, end_idx, duration in periods:
            # Compression range
            comp_bars = group.iloc[start_idx:end_idx]
            comp_high = comp_bars["high"].max()
            comp_low = comp_bars["low"].min()
            midpoint = (comp_high + comp_low) / 2
            comp_range_pct = (comp_high - comp_low) / midpoint * 100

            # Expansion bar (first bar after compression)
            if end_idx >= len(group):
                continue
            exp_bar = group.iloc[end_idx]
            exp_ts = group.index[end_idx]

            # Expansion direction
            if exp_bar["close"] > midpoint:
                direction = "bullish"
            elif exp_bar["close"] < midpoint:
                direction = "bearish"
            else:
                # Tiebreak on PO
                direction = "bullish" if exp_bar["phase_oscillator"] > 0 else "bearish"

            # Forward window
            fwd_start = end_idx
            fwd_end = min(end_idx + FORWARD_BARS, len(group))
            forward = group.iloc[fwd_start:fwd_end]

            if len(forward) < 3:
                continue

            fwd_high = forward["high"].max()
            fwd_low = forward["low"].min()
            fwd_close = forward.iloc[-1]["close"]

            # Profit and drawdown relative to midpoint
            if direction == "bullish":
                max_profit_pct = (fwd_high - midpoint) / midpoint * 100
                max_drawdown_pct = (midpoint - fwd_low) / midpoint * 100
            else:
                max_profit_pct = (midpoint - fwd_low) / midpoint * 100
                max_drawdown_pct = (fwd_high - midpoint) / midpoint * 100

            # Net move in expansion direction
            net_move_pct = (fwd_close - midpoint) / midpoint * 100
            if direction == "bearish":
                net_move_pct = -net_move_pct  # positive = moved in expansion dir

            # ── Context variables ──

            # EMA 21 bias
            ema21_bias = "bullish" if exp_bar["close"] > exp_bar["ema_21"] else "bearish"

            # EMA 21 vs 48 trend
            ema_trend = "bullish" if exp_bar["ema_21"] > exp_bar["ema_48"] else "bearish"

            # ATR position
            atr_pos = get_atr_position_at(exp_bar)

            # Time of day
            time_bucket = get_time_bucket(exp_ts)

            # Duration bucket
            if duration <= 5:
                dur_bucket = "short (30-50m)"
            elif duration <= 11:
                dur_bucket = "medium (60-110m)"
            elif duration <= 17:
                dur_bucket = "long (120-170m)"
            else:
                dur_bucket = "xlong (180m+)"

            events.append({
                "date": date,
                "expansion_time": exp_ts,
                "direction": direction,
                "duration_bars": duration,
                "duration_bucket": dur_bucket,
                "comp_high": comp_high,
                "comp_low": comp_low,
                "midpoint": midpoint,
                "comp_range_pct": comp_range_pct,
                "max_profit_pct": max_profit_pct,
                "max_drawdown_pct": max_drawdown_pct,
                "net_move_pct": net_move_pct,
                "ema21_bias": ema21_bias,
                "ema_trend": ema_trend,
                "atr_position": atr_pos,
                "time_bucket": time_bucket,
            })

    df_ev = pd.DataFrame(events)
    if len(df_ev) == 0:
        print("No events found.")
        return

    pct = lambda n, d: f"{n/d*100:.1f}%" if d > 0 else "n/a"
    total = len(df_ev)
    bull = (df_ev["direction"] == "bullish").sum()
    bear = (df_ev["direction"] == "bearish").sum()

    print(f"{'='*80}")
    print(f"  10-MINUTE COMPRESSION → EXPANSION STUDY")
    print(f"  Outcome window: {OUTCOME_WINDOW_MIN} min after expansion | Min compression: {MIN_COMPRESSION_BARS * 10} min")
    print(f"{'='*80}")
    print(f"  Total events:      {total:,}")
    print(f"  Date range:        {df_ev['date'].min()} to {df_ev['date'].max()}")
    print(f"  Bullish expansion: {pct(bull, total):>6}  ({bull:,})")
    print(f"  Bearish expansion: {pct(bear, total):>6}  ({bear:,})")
    print()

    # ── Baseline profit/drawdown by direction ──
    print(f"  --- Baseline Outcomes (120 min after expansion, from compression midpoint) ---")
    for dir_label, dir_val in [("Bullish", "bullish"), ("Bearish", "bearish")]:
        sub = df_ev[df_ev["direction"] == dir_val]
        n = len(sub)
        if n == 0:
            continue
        print(f"  {dir_label} expansions (n={n:,}):")
        print(f"    Max profit:    mean={sub['max_profit_pct'].mean():.3f}%  median={sub['max_profit_pct'].median():.3f}%")
        print(f"    Max drawdown:  mean={sub['max_drawdown_pct'].mean():.3f}%  median={sub['max_drawdown_pct'].median():.3f}%")
        print(f"    Net move:      mean={sub['net_move_pct'].mean():.3f}%  median={sub['net_move_pct'].median():.3f}%")
        print(f"    Profit > DD:   {pct((sub['max_profit_pct'] > sub['max_drawdown_pct']).sum(), n)}  ← expansion direction was right")
        print(f"    Comp range:    mean={sub['comp_range_pct'].mean():.3f}%  median={sub['comp_range_pct'].median():.3f}%")
        print()

    # ── Segmentation tables ──
    dimensions = [
        ("Compression Duration", "duration_bucket",
         ["short (30-50m)", "medium (60-110m)", "long (120-170m)", "xlong (180m+)"]),
        ("EMA 21 Bias (price vs 21)", "ema21_bias", ["bullish", "bearish"]),
        ("EMA Trend (21 vs 48)", "ema_trend", ["bullish", "bearish"]),
        ("ATR Level Position", "atr_position",
         ["above 61.8%", "38.2%-61.8%", "trigger-38.2%", "bull trigger box",
          "bear trigger box", "trigger to -38.2%", "-38.2% to -61.8%", "below -61.8%"]),
        ("Time of Day", "time_bucket",
         ["open (9:30-10:30)", "mid (10:30-14:00)", "close (14:00-16:00)"]),
    ]

    for dim_label, dim_col, categories in dimensions:
        print(f"  --- By {dim_label} ---")
        print(f"  {'Category':24s} {'Total':>6} {'Bull%':>7} {'Bear%':>7} │ {'BullProfit':>11} {'BullDD':>9} {'BearProfit':>11} {'BearDD':>9}")
        print(f"  {'-'*24} {'-'*6} {'-'*7} {'-'*7} │ {'-'*11} {'-'*9} {'-'*11} {'-'*9}")
        for cat in categories:
            sub = df_ev[df_ev[dim_col] == cat]
            n = len(sub)
            if n == 0:
                continue
            b = sub[sub["direction"] == "bullish"]
            br = sub[sub["direction"] == "bearish"]
            bp = f"{b['max_profit_pct'].mean():.3f}%" if len(b) > 0 else "—"
            bd = f"{b['max_drawdown_pct'].mean():.3f}%" if len(b) > 0 else "—"
            brp = f"{br['max_profit_pct'].mean():.3f}%" if len(br) > 0 else "—"
            brd = f"{br['max_drawdown_pct'].mean():.3f}%" if len(br) > 0 else "—"
            print(f"  {str(cat):24s} {n:>6} {pct(len(b),n):>7} {pct(len(br),n):>7} │ {bp:>11} {bd:>9} {brp:>11} {brd:>9}")
        print()

    # ── KEY QUESTION: Does EMA 21 bias predict expansion direction? ──
    print(f"  {'='*80}")
    print(f"  KEY QUESTION: Does EMA 21 bias predict expansion direction?")
    print(f"  {'='*80}")
    for bias in ["bullish", "bearish"]:
        sub = df_ev[df_ev["ema21_bias"] == bias]
        n = len(sub)
        b = (sub["direction"] == "bullish").sum()
        br = (sub["direction"] == "bearish").sum()
        print(f"  When EMA 21 bias is {bias:8s}:  {pct(b,n)} expand bullish, {pct(br,n)} expand bearish  (n={n:,})")
    print()

    # Same for EMA trend (21 vs 48)
    print(f"  KEY QUESTION: Does EMA 21/48 trend predict expansion direction?")
    print(f"  {'-'*80}")
    for trend in ["bullish", "bearish"]:
        sub = df_ev[df_ev["ema_trend"] == trend]
        n = len(sub)
        b = (sub["direction"] == "bullish").sum()
        br = (sub["direction"] == "bearish").sum()
        print(f"  When EMA trend is {trend:8s}:   {pct(b,n)} expand bullish, {pct(br,n)} expand bearish  (n={n:,})")
    print()

    # ── KEY QUESTION: Does compression length affect magnitude? ──
    print(f"  KEY QUESTION: Does compression length affect expansion magnitude?")
    print(f"  {'-'*80}")
    dur_cats = ["short (30-50m)", "medium (60-110m)", "long (120-170m)", "xlong (180m+)"]
    print(f"  {'Duration':24s} {'N':>6} {'MeanProfit':>11} {'MedProfit':>11} {'MeanDD':>9} {'MedDD':>9} {'Net>0%':>8}")
    for dur in dur_cats:
        sub = df_ev[df_ev["duration_bucket"] == dur]
        n = len(sub)
        if n == 0:
            continue
        net_pos = (sub["net_move_pct"] > 0).sum()
        print(f"  {dur:24s} {n:>6} {sub['max_profit_pct'].mean():>10.3f}% {sub['max_profit_pct'].median():>10.3f}% "
              f"{sub['max_drawdown_pct'].mean():>8.3f}% {sub['max_drawdown_pct'].median():>8.3f}% {pct(net_pos,n):>8}")
    print()

    # ── CROSS-TAB: Duration × EMA21 Bias → Bullish expansion % ──
    print(f"  CROSS-TAB: Duration × EMA21 Bias → % that expand bullish")
    print(f"  {'-'*80}")
    print(f"  {'Duration':24s} {'EMA21 Bull':>16} {'EMA21 Bear':>16}")
    for dur in dur_cats:
        row = f"  {dur:24s}"
        for bias in ["bullish", "bearish"]:
            sub = df_ev[(df_ev["duration_bucket"] == dur) & (df_ev["ema21_bias"] == bias)]
            n = len(sub)
            if n < 10:
                row += f"{'— (n<10)':>16}"
            else:
                b = (sub["direction"] == "bullish").sum()
                row += f"{b/n*100:>9.1f}% n={n:<4d}"
        print(row)
    print()

    # ── CROSS-TAB: Duration × EMA21 Bias → Mean profit % for bullish expansions ──
    print(f"  CROSS-TAB: Duration × EMA21 Bias → Mean profit % (bullish expansions only)")
    print(f"  {'-'*80}")
    print(f"  {'Duration':24s} {'EMA21 Bull':>16} {'EMA21 Bear':>16}")
    for dur in dur_cats:
        row = f"  {dur:24s}"
        for bias in ["bullish", "bearish"]:
            sub = df_ev[(df_ev["duration_bucket"] == dur) &
                        (df_ev["ema21_bias"] == bias) &
                        (df_ev["direction"] == "bullish")]
            n = len(sub)
            if n < 10:
                row += f"{'— (n<10)':>16}"
            else:
                row += f"{sub['max_profit_pct'].mean():>9.3f}% n={n:<4d}"
        print(row)
    print()

    # ── CROSS-TAB: Duration × EMA Trend → Bullish expansion % ──
    print(f"  CROSS-TAB: Duration × EMA Trend (21v48) → % that expand bullish")
    print(f"  {'-'*80}")
    print(f"  {'Duration':24s} {'Trend Bull':>16} {'Trend Bear':>16}")
    for dur in dur_cats:
        row = f"  {dur:24s}"
        for trend in ["bullish", "bearish"]:
            sub = df_ev[(df_ev["duration_bucket"] == dur) & (df_ev["ema_trend"] == trend)]
            n = len(sub)
            if n < 10:
                row += f"{'— (n<10)':>16}"
            else:
                b = (sub["direction"] == "bullish").sum()
                row += f"{b/n*100:>9.1f}% n={n:<4d}"
        print(row)
    print()

    print("Done.")


if __name__ == "__main__":
    main()
