"""
Multi-Day ATR +1 on Wednesday: What Happens Next?

Hypothesis: When SPY hits the +100% level of the weekly (multi-day) ATR on a
Wednesday, what happens to price immediately after — same day, rest of week,
and into next week?

Multi-day mode = Weekly ATR levels:
  - prev_close = previous week's close
  - atr_upper_100 = prev_close + weekly_atr_14

We use 10m intraday bars to pinpoint the exact moment +1 ATR is hit on
Wednesday, then track:
  1. Same-day aftermath (from hit to close)
  2. Thursday/Friday returns
  3. Next week returns
  4. Conditioning on time of hit, trend state, Phase Oscillator
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    # ─────────────────────────────────────────────
    # Load weekly ATR levels
    # ─────────────────────────────────────────────
    print("Loading weekly indicator data...")
    wk = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, prev_close, atr_14, "
        "atr_upper_100, atr_lower_100, atr_upper_trigger, atr_upper_0382, "
        "atr_upper_0618, atr_upper_0786, atr_upper_1236, "
        "phase_oscillator, phase_zone, compression, atr_trend "
        "FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    wk = wk.set_index("timestamp").sort_index()
    wk = wk.dropna(subset=["prev_close", "atr_14"])

    # Weekly timestamps are Sundays — the week covers Mon through Fri after
    # Build a lookup: for each Sunday start, store the weekly ATR levels
    week_levels = {}
    for ts, row in wk.iterrows():
        week_levels[ts.date()] = row

    # ─────────────────────────────────────────────
    # Load daily data for forward returns
    # ─────────────────────────────────────────────
    print("Loading daily data...")
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume, "
        "phase_oscillator, phase_zone, atr_trend, compression, "
        "ema_8, ema_21, ema_48, candle_bias "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()
    daily["date"] = daily.index.date
    daily["dow"] = daily.index.dayofweek  # 0=Mon, 2=Wed, 4=Fri

    # Build date -> daily row lookup
    daily_by_date = {row.name.date(): row for _, row in daily.iterrows()}
    all_dates = sorted(daily_by_date.keys())
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    # ─────────────────────────────────────────────
    # Load 10m intraday data for Wednesdays
    # ─────────────────────────────────────────────
    print("Loading 10m intraday data...")
    intra = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    intra = intra.set_index("timestamp").sort_index()
    intra = intra.between_time("09:30", "15:59")
    intra["date"] = intra.index.date
    intra["dow"] = intra.index.dayofweek

    # Filter to Wednesdays only
    wed_intra = intra[intra["dow"] == 2]
    print(f"Wednesday 10m bars: {len(wed_intra):,}")

    # ─────────────────────────────────────────────
    # Map each Wednesday to its weekly ATR levels
    # ─────────────────────────────────────────────
    def get_week_sunday(d):
        """Get the Sunday that starts the trading week containing date d."""
        # Sunday = weekday 6. For a Wednesday (weekday 2), Sunday is 3 days before
        days_since_sunday = d.weekday() + 1  # Mon=1, Tue=2, Wed=3, ...
        if d.weekday() == 6:
            days_since_sunday = 0
        sunday = d - timedelta(days=days_since_sunday)
        return sunday

    # ─────────────────────────────────────────────
    # Find Wednesdays where +1 weekly ATR is hit
    # ─────────────────────────────────────────────
    print("Scanning for +1 weekly ATR hits on Wednesdays...\n")

    events = []

    for wed_date, group in wed_intra.groupby("date"):
        sunday = get_week_sunday(wed_date)
        if sunday not in week_levels:
            continue

        wk_row = week_levels[sunday]
        target = wk_row["atr_upper_100"]
        prev_close = wk_row["prev_close"]
        atr = wk_row["atr_14"]

        if pd.isna(target) or pd.isna(atr) or atr == 0:
            continue

        # Check if Wednesday high reaches +1 ATR
        bars_above = group[group["high"] >= target]
        if len(bars_above) == 0:
            continue

        # Found a hit — record the event
        hit_time = bars_above.index[0]
        hit_bar = bars_above.iloc[0]
        hit_hour = hit_time.hour

        # Price at hit moment
        hit_price = hit_bar["high"]

        # Remaining bars after hit
        remaining = group[group.index >= hit_time]
        wed_close = group.iloc[-1]["close"]

        # Return from hit to Wednesday close
        wed_aftermath = (wed_close - target) / target * 100

        # Did price continue higher or reverse?
        post_hit_high = remaining["high"].max()
        post_hit_low = remaining["low"].min()
        max_extension = (post_hit_high - target) / atr * 100  # % of ATR above +1
        max_drawdown = (post_hit_low - target) / atr * 100    # % of ATR below +1

        # Forward daily returns
        wed_idx = date_to_idx.get(wed_date)
        if wed_idx is None:
            continue

        thu_ret = fri_ret = mon_ret = next_week_ret = np.nan
        thu_date = fri_date = mon_date = None

        # Thursday (next trading day)
        if wed_idx + 1 < len(all_dates):
            nd = all_dates[wed_idx + 1]
            if nd in daily_by_date:
                nr = daily_by_date[nd]
                thu_ret = (nr["close"] - nr["open"]) / nr["open"] * 100
                thu_date = nd

        # Friday (2 trading days ahead)
        if wed_idx + 2 < len(all_dates):
            nd = all_dates[wed_idx + 2]
            if nd in daily_by_date:
                nr = daily_by_date[nd]
                fri_ret = (nr["close"] - nr["open"]) / nr["open"] * 100
                fri_date = nd

        # Next Monday
        if wed_idx + 3 < len(all_dates):
            nd = all_dates[wed_idx + 3]
            if nd in daily_by_date:
                nr = daily_by_date[nd]
                mon_ret = (nr["close"] - nr["open"]) / nr["open"] * 100
                mon_date = nd

        # Rest of week return (Wed close -> Fri close)
        rest_of_week = np.nan
        if wed_idx + 2 < len(all_dates):
            fri_d = all_dates[wed_idx + 2]
            if fri_d in daily_by_date:
                rest_of_week = (daily_by_date[fri_d]["close"] - wed_close) / wed_close * 100

        # Full next week return (Fri close -> next Fri close)
        next_week_close = np.nan
        if wed_idx + 7 < len(all_dates):
            nf = all_dates[wed_idx + 7]
            if nf in daily_by_date and wed_idx + 2 < len(all_dates):
                fri_d = all_dates[wed_idx + 2]
                if fri_d in daily_by_date:
                    next_week_close = (daily_by_date[nf]["close"] - daily_by_date[fri_d]["close"]) / daily_by_date[fri_d]["close"] * 100

        # Weekly phase oscillator at time of hit
        wk_po = wk_row["phase_oscillator"]
        wk_zone = wk_row["phase_zone"]
        wk_trend = wk_row["atr_trend"]
        wk_compression = wk_row["compression"]

        # How much of the weekly ATR was already consumed before Wednesday?
        # Check Mon-Tue high
        week_dates_before = []
        for delta in [1, 2]:  # Mon=1, Tue=2 days after Sunday
            check = sunday + timedelta(days=delta)
            if check in date_to_idx:
                week_dates_before.append(check)

        pre_wed_high = 0
        for bd in week_dates_before:
            if bd in daily_by_date:
                pre_wed_high = max(pre_wed_high, daily_by_date[bd]["high"])

        pct_atr_before_wed = (pre_wed_high - prev_close) / atr * 100 if atr > 0 and pre_wed_high > 0 else np.nan

        events.append({
            "date": wed_date,
            "hit_hour": hit_hour,
            "hit_price": hit_price,
            "target": target,
            "prev_close": prev_close,
            "atr": atr,
            "wed_close": wed_close,
            "wed_aftermath": wed_aftermath,
            "max_extension": max_extension,
            "max_drawdown": max_drawdown,
            "thu_ret": thu_ret,
            "fri_ret": fri_ret,
            "mon_ret": mon_ret,
            "rest_of_week": rest_of_week,
            "next_week": next_week_close,
            "wk_po": wk_po,
            "wk_zone": wk_zone,
            "wk_trend": wk_trend,
            "wk_compression": wk_compression,
            "pct_atr_before_wed": pct_atr_before_wed,
        })

    edf = pd.DataFrame(events)
    n = len(edf)
    print(f"Found {n} Wednesdays where SPY hit +1 weekly ATR\n")

    if n == 0:
        print("No events found!")
        conn.close()
        return

    # ─────────────────────────────────────────────
    # SECTION 1: Overall Statistics
    # ─────────────────────────────────────────────
    print("=" * 70)
    print("SECTION 1: OVERALL — WHAT HAPPENS AFTER +1 WEEKLY ATR ON WEDNESDAY")
    print("=" * 70)
    print(f"\nTotal events: {n}")
    print(f"Date range: {edf['date'].min()} to {edf['date'].max()}")

    print(f"\n  --- Same-Day Aftermath (hit → Wednesday close) ---")
    wa = edf["wed_aftermath"]
    print(f"  Mean return:    {wa.mean():+.3f}%")
    print(f"  Median return:  {wa.median():+.3f}%")
    print(f"  % positive:     {(wa > 0).mean()*100:.1f}%")
    print(f"  % negative:     {(wa < 0).mean()*100:.1f}%")

    print(f"\n  --- Max Extension After Hit (same day, % of weekly ATR) ---")
    me = edf["max_extension"]
    print(f"  Mean:    {me.mean():+.1f}% of ATR further")
    print(f"  Median:  {me.median():+.1f}% of ATR")
    print(f"  75th:    {me.quantile(0.75):+.1f}% of ATR")
    print(f"  Max:     {me.max():+.1f}% of ATR")

    print(f"\n  --- Max Drawdown After Hit (same day, % of weekly ATR) ---")
    md = edf["max_drawdown"]
    print(f"  Mean:    {md.mean():+.1f}% of ATR")
    print(f"  Median:  {md.median():+.1f}% of ATR")
    print(f"  25th:    {md.quantile(0.25):+.1f}% of ATR (worst quarter)")

    # ─────────────────────────────────────────────
    # SECTION 2: Forward Returns
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 2: FORWARD RETURNS")
    print("=" * 70)

    for label, col in [
        ("Thursday (next day)", "thu_ret"),
        ("Friday (2 days)", "fri_ret"),
        ("Monday (3 days)", "mon_ret"),
        ("Rest of Week (Wed close → Fri close)", "rest_of_week"),
        ("Next Full Week", "next_week"),
    ]:
        vals = edf[col].dropna()
        if len(vals) < 10:
            continue
        print(f"\n  {label} (n={len(vals)}):")
        print(f"    Mean:      {vals.mean():+.3f}%")
        print(f"    Median:    {vals.median():+.3f}%")
        print(f"    Green %:   {(vals > 0).mean()*100:.1f}%")
        print(f"    Std:       {vals.std():.3f}%")
        # Percentiles
        print(f"    10th/90th: {vals.quantile(0.10):+.3f}% / {vals.quantile(0.90):+.3f}%")

    # ─────────────────────────────────────────────
    # Compare to baseline Wednesdays
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 3: COMPARISON TO ALL WEDNESDAYS (baseline)")
    print("=" * 70)

    all_wed = daily[daily["dow"] == 2].copy()
    all_wed["daily_return"] = (all_wed["close"] - all_wed["open"]) / all_wed["open"] * 100

    # Forward returns for all Wednesdays
    all_wed_thu = []
    all_wed_row = []
    all_wed_nw = []
    for _, row in all_wed.iterrows():
        d = row["date"]
        idx = date_to_idx.get(d)
        if idx is None:
            continue
        if idx + 1 < len(all_dates):
            nd = all_dates[idx + 1]
            if nd in daily_by_date:
                nr = daily_by_date[nd]
                all_wed_thu.append((nr["close"] - nr["open"]) / nr["open"] * 100)
        if idx + 2 < len(all_dates):
            fd = all_dates[idx + 2]
            if fd in daily_by_date:
                wed_c = row["close"]
                all_wed_row.append((daily_by_date[fd]["close"] - wed_c) / wed_c * 100)
        if idx + 7 < len(all_dates) and idx + 2 < len(all_dates):
            fd = all_dates[idx + 2]
            nf = all_dates[idx + 7]
            if fd in daily_by_date and nf in daily_by_date:
                all_wed_nw.append((daily_by_date[nf]["close"] - daily_by_date[fd]["close"]) / daily_by_date[fd]["close"] * 100)

    all_wed_thu = np.array(all_wed_thu)
    all_wed_row = np.array(all_wed_row)
    all_wed_nw = np.array(all_wed_nw)

    print(f"\n  {'Metric':<40s} {'After +1 ATR':>14s} {'All Wednesdays':>16s} {'Diff':>10s}")
    print("  " + "-" * 82)

    comparisons = [
        ("Thursday return", edf["thu_ret"].dropna(), all_wed_thu),
        ("Rest of week (Wed→Fri)", edf["rest_of_week"].dropna(), all_wed_row),
        ("Next week", edf["next_week"].dropna(), all_wed_nw),
    ]
    for label, event_vals, base_vals in comparisons:
        em = event_vals.mean()
        bm = base_vals.mean()
        eg = (event_vals > 0).mean() * 100
        bg = (base_vals > 0).mean() * 100
        print(f"  {label + ' (mean)':<40s} {em:+13.3f}% {bm:+15.3f}% {em - bm:+9.3f}%")
        print(f"  {label + ' (green%)':<40s} {eg:13.1f}% {bg:15.1f}% {eg - bg:+9.1f}%")

    # ─────────────────────────────────────────────
    # SECTION 4: By Time of Hit
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 4: CONDITIONED ON TIME OF HIT")
    print("=" * 70)

    print(f"\n  {'Hit Hour':<10s} {'n':>4s} {'Wed Afterm':>12s} {'Thu Ret':>10s} {'RoW':>10s} {'Green Thu%':>12s}")
    print("  " + "-" * 60)
    for hour in sorted(edf["hit_hour"].unique()):
        subset = edf[edf["hit_hour"] == hour]
        sn = len(subset)
        if sn < 3:
            continue
        wa_m = subset["wed_aftermath"].mean()
        thu_m = subset["thu_ret"].mean()
        row_m = subset["rest_of_week"].mean()
        thu_g = (subset["thu_ret"] > 0).mean() * 100
        flag = " *" if sn < 20 else ""
        print(f"  {hour:02d}:00     {sn:4d} {wa_m:+11.3f}% {thu_m:+9.3f}% {row_m:+9.3f}% {thu_g:11.1f}%{flag}")

    # ─────────────────────────────────────────────
    # SECTION 5: By Weekly PO Zone
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 5: CONDITIONED ON WEEKLY PHASE OSCILLATOR ZONE")
    print("=" * 70)

    print(f"\n  {'PO Zone':<18s} {'n':>4s} {'Wed Afterm':>12s} {'Thu Ret':>10s} {'RoW':>10s} {'NextWk':>10s}")
    print("  " + "-" * 66)
    for zone in ["extended_up", "distribution", "neutral_up", "neutral",
                  "neutral_down", "accumulation", "extended_down"]:
        subset = edf[edf["wk_zone"] == zone]
        sn = len(subset)
        if sn < 3:
            continue
        wa_m = subset["wed_aftermath"].mean()
        thu_m = subset["thu_ret"].dropna().mean()
        row_m = subset["rest_of_week"].dropna().mean()
        nw_m = subset["next_week"].dropna().mean()
        flag = " *" if sn < 20 else ""
        print(f"  {zone:<18s} {sn:4d} {wa_m:+11.3f}% {thu_m:+9.3f}% {row_m:+9.3f}% {nw_m:+9.3f}%{flag}")

    # ─────────────────────────────────────────────
    # SECTION 6: By Weekly ATR Trend
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 6: CONDITIONED ON WEEKLY ATR TREND")
    print("=" * 70)

    trend_labels = {1: "Bullish", 0: "Neutral", -1: "Bearish"}
    print(f"\n  {'Trend':<12s} {'n':>4s} {'Wed Afterm':>12s} {'Thu Ret':>10s} {'RoW':>10s} {'NextWk':>10s}")
    print("  " + "-" * 60)
    for trend_val, trend_name in trend_labels.items():
        subset = edf[edf["wk_trend"] == trend_val]
        sn = len(subset)
        if sn < 3:
            continue
        wa_m = subset["wed_aftermath"].mean()
        thu_m = subset["thu_ret"].dropna().mean()
        row_m = subset["rest_of_week"].dropna().mean()
        nw_m = subset["next_week"].dropna().mean()
        flag = " *" if sn < 20 else ""
        print(f"  {trend_name:<12s} {sn:4d} {wa_m:+11.3f}% {thu_m:+9.3f}% {row_m:+9.3f}% {nw_m:+9.3f}%{flag}")

    # ─────────────────────────────────────────────
    # SECTION 7: Did It Already Hit +1 ATR Before Wednesday?
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 7: FIRST HIT vs ALREADY EXTENDED")
    print("=" * 70)
    print("  (Was +1 ATR already reached Mon/Tue, or is Wednesday the first touch?)\n")

    # Check Mon/Tue highs vs the weekly +1 ATR level
    first_touch = []
    already_ext = []
    for _, ev in edf.iterrows():
        sunday = get_week_sunday(ev["date"])
        if sunday not in week_levels:
            first_touch.append(True)
            continue
        target = ev["target"]
        # Check Mon and Tue
        pre_hit = False
        for delta in [1, 2]:
            check = sunday + timedelta(days=delta)
            if check in daily_by_date:
                if daily_by_date[check]["high"] >= target:
                    pre_hit = True
                    break
        if pre_hit:
            already_ext.append(ev)
        else:
            first_touch.append(ev)

    # Hmm, let me redo this properly
    first_events = []
    repeat_events = []
    for _, ev in edf.iterrows():
        wed_d = ev["date"]
        sunday = get_week_sunday(wed_d)
        target = ev["target"]

        pre_hit = False
        for delta in [1, 2]:  # Mon, Tue
            check = sunday + timedelta(days=delta)
            if check in daily_by_date:
                if daily_by_date[check]["high"] >= target:
                    pre_hit = True
                    break

        if pre_hit:
            repeat_events.append(ev)
        else:
            first_events.append(ev)

    first_df = pd.DataFrame(first_events) if first_events else pd.DataFrame()
    repeat_df = pd.DataFrame(repeat_events) if repeat_events else pd.DataFrame()

    print(f"  First touch on Wednesday: {len(first_df)}")
    print(f"  Already hit Mon/Tue:      {len(repeat_df)}")

    for label, sub in [("FIRST TOUCH (Wed is the breakout)", first_df),
                        ("ALREADY EXTENDED (hit before Wed)", repeat_df)]:
        if len(sub) < 5:
            continue
        print(f"\n  --- {label} (n={len(sub)}) ---")
        for metric, col in [("Wed aftermath", "wed_aftermath"),
                             ("Thursday ret", "thu_ret"),
                             ("Rest of week", "rest_of_week"),
                             ("Next week", "next_week")]:
            vals = sub[col].dropna()
            if len(vals) < 3:
                continue
            print(f"    {metric:<18s} mean={vals.mean():+.3f}%  median={vals.median():+.3f}%  green={((vals>0).mean()*100):.1f}%")

    # ─────────────────────────────────────────────
    # SECTION 8: Year-by-Year
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 8: YEAR-BY-YEAR FREQUENCY")
    print("=" * 70)

    edf["year"] = edf["date"].apply(lambda d: d.year)
    print(f"\n  {'Year':<6s} {'Events':>7s} {'Wed Afterm':>12s} {'Thu Ret':>10s} {'RoW':>10s}")
    print("  " + "-" * 48)
    for year in sorted(edf["year"].unique()):
        yr = edf[edf["year"] == year]
        wa = yr["wed_aftermath"].mean()
        thu = yr["thu_ret"].dropna().mean()
        row = yr["rest_of_week"].dropna().mean()
        print(f"  {year:<6d} {len(yr):7d} {wa:+11.3f}% {thu:+9.3f}% {row:+9.3f}%")

    # ─────────────────────────────────────────────
    # SECTION 9: Immediate Reaction Buckets
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 9: IMMEDIATE REACTION — DOES IT HOLD OR REVERSE?")
    print("=" * 70)

    # Categorize: did price close Wednesday above or below the +1 ATR level?
    edf["held_above"] = edf["wed_close"] >= edf["target"]
    held = edf[edf["held_above"]]
    failed = edf[~edf["held_above"]]

    print(f"\n  Closed Wednesday ABOVE +1 ATR: {len(held)} ({len(held)/n*100:.1f}%)")
    print(f"  Closed Wednesday BELOW +1 ATR: {len(failed)} ({len(failed)/n*100:.1f}%)")

    for label, sub in [("HELD ABOVE +1 ATR at close", held),
                        ("FAILED / REVERSED below +1 ATR", failed)]:
        if len(sub) < 5:
            continue
        print(f"\n  --- {label} (n={len(sub)}) ---")
        for metric, col in [("Thursday ret", "thu_ret"),
                             ("Friday ret", "fri_ret"),
                             ("Rest of week", "rest_of_week"),
                             ("Next week", "next_week")]:
            vals = sub[col].dropna()
            if len(vals) < 3:
                continue
            print(f"    {metric:<18s} mean={vals.mean():+.3f}%  green={((vals>0).mean()*100):.1f}%  n={len(vals)}")

    # ─────────────────────────────────────────────
    # SECTION 10: Event List (most recent 20)
    # ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("SECTION 10: MOST RECENT 20 EVENTS")
    print("=" * 70)

    recent = edf.sort_values("date", ascending=False).head(20)
    print(f"\n  {'Date':<12s} {'Hit Hr':>6s} {'Target':>8s} {'WedClose':>9s} {'WedAft':>8s} {'ThuRet':>8s} {'RoW':>8s} {'PO Zone':<14s}")
    print("  " + "-" * 78)
    for _, row in recent.iterrows():
        print(f"  {str(row['date']):<12s} {row['hit_hour']:5d}h {row['target']:8.2f} {row['wed_close']:9.2f} "
              f"{row['wed_aftermath']:+7.3f}% {row['thu_ret']:+7.3f}% {row['rest_of_week']:+7.3f}% "
              f"{str(row['wk_zone']):<14s}")

    conn.close()
    print(f"\n{'=' * 70}")
    print("STUDY COMPLETE")
    print("=" * 70)


def get_week_sunday(d):
    """Get the Sunday that starts the trading week containing date d."""
    days_since_sunday = d.weekday() + 1
    if d.weekday() == 6:
        days_since_sunday = 0
    sunday = d - timedelta(days=days_since_sunday)
    return sunday


if __name__ == "__main__":
    main()
