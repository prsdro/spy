"""
Follow-up: On days where 10m PO sustained > 61.8 through 11am in bullish expansion,
what signals precede the mean reversion / reversal?

We examine:
1. When PO leaves distribution (crosses back below 61.8) — what happens next?
2. ATR level where price tops out — does it cluster at key levels?
3. Pivot ribbon state changes (fast cloud flip, compression entry)
4. Does the PO slope turning negative (while still > 61.8) front-run the reversal?
5. Drawdown from day high — magnitude and timing
"""

import sqlite3
import pandas as pd
import numpy as np
import datetime

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
    df = df.dropna(subset=["prev_close", "atr_14", "phase_oscillator"])
    df["date"] = df.index.date
    df["time"] = df.index.time

    # ── Reproduce qualifying days ──
    qualifying_dates = []

    for date, group in df.groupby("date"):
        if len(group) < 10:
            continue
        first = group.iloc[0]
        if pd.isna(first["prev_close"]) or pd.isna(first["atr_14"]) or first["atr_14"] == 0:
            continue

        first_30 = group.between_time("09:30", "09:50")
        if len(first_30) == 0:
            continue

        cross_bar = None
        for i in range(len(first_30)):
            row = first_30.iloc[i]
            if row["phase_oscillator"] > 61.8 and row["compression"] != 1:
                if i == 0:
                    cross_bar = first_30.index[i]
                    break
                else:
                    prev_po = first_30.iloc[i - 1]["phase_oscillator"]
                    if prev_po <= 61.8:
                        cross_bar = first_30.index[i]
                        break

        if cross_bar is None:
            first_po = first_30.iloc[0]["phase_oscillator"]
            first_comp = first_30.iloc[0]["compression"]
            if first_po > 61.8 and first_comp != 1:
                cross_bar = first_30.index[0]

        if cross_bar is None:
            continue

        sustained_period = group.loc[cross_bar:]
        sustained_period = sustained_period.between_time("09:30", "10:50")
        if len(sustained_period) == 0:
            continue
        if not (sustained_period["phase_oscillator"] >= 61.8).all():
            continue

        bars_11am = group.between_time("11:00", "11:00")
        rest_of_day = group.between_time("11:00", "15:59")
        if len(bars_11am) == 0 or len(rest_of_day) == 0:
            continue

        qualifying_dates.append(date)

    print(f"Qualifying days: {len(qualifying_dates)}\n")

    # ══════════════════════════════════════════════
    # ANALYSIS 1: When PO leaves distribution (crosses below 61.8)
    # ══════════════════════════════════════════════
    print("=" * 70)
    print("1. PO LEAVING DISTRIBUTION — TIMING & PRICE IMPACT")
    print("=" * 70)

    leave_data = []

    for date in qualifying_dates:
        group = df[df["date"] == date]
        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]

        # Find the bar where PO first drops below 61.8 (after being above)
        leave_bar = None
        leave_idx = None
        for i in range(1, len(group)):
            if group.iloc[i]["phase_oscillator"] < 61.8 and group.iloc[i - 1]["phase_oscillator"] >= 61.8:
                leave_bar = group.index[i]
                leave_idx = i
                break

        if leave_bar is None:
            continue

        leave_price = group.iloc[leave_idx]["close"]
        leave_time = leave_bar.time()
        leave_po = group.iloc[leave_idx]["phase_oscillator"]

        # Day high up to the leave point
        pre_leave = group.iloc[:leave_idx + 1]
        high_before_leave = pre_leave["high"].max()

        # Price action AFTER leaving distribution
        post_leave = group.iloc[leave_idx:]
        if len(post_leave) < 2:
            continue

        post_high = post_leave["high"].max()
        post_low = post_leave["low"].min()
        post_close = post_leave.iloc[-1]["close"]

        ret_leave_to_close = (post_close - leave_price) / leave_price * 100
        max_gain_after = (post_high - leave_price) / leave_price * 100
        max_dd_after = (post_low - leave_price) / leave_price * 100

        # Where was price relative to ATR at the leave point?
        price_atr_pct = (leave_price - prev_close) / atr * 100

        # Did price make a new high after leaving distribution?
        new_high_after = post_high > high_before_leave

        # How far did price pull back from the day high?
        day_high = group["high"].max()
        day_close = group.iloc[-1]["close"]
        pullback_from_high = (day_close - day_high) / day_high * 100

        leave_data.append({
            "date": date,
            "leave_time": leave_time,
            "leave_po": leave_po,
            "price_atr_pct": price_atr_pct,
            "ret_leave_to_close": ret_leave_to_close,
            "max_gain_after": max_gain_after,
            "max_dd_after": max_dd_after,
            "new_high_after": new_high_after,
            "pullback_from_high": pullback_from_high,
        })

    ldf = pd.DataFrame(leave_data)
    n_leave = len(ldf)
    print(f"\nDays where PO left distribution: {n_leave}/{len(qualifying_dates)}")

    # Time distribution
    print(f"\n  When PO leaves distribution:")
    ldf["leave_hour"] = ldf["leave_time"].apply(lambda t: t.hour)
    ldf["leave_half"] = ldf["leave_time"].apply(lambda t: f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}")
    for half, sub in ldf.groupby("leave_half"):
        n = len(sub)
        avg_ret = sub["ret_leave_to_close"].mean()
        pct_neg = (sub["ret_leave_to_close"] < 0).mean() * 100
        print(f"    {half}: n={n:4d} ({n/n_leave*100:5.1f}%), "
              f"avg leave→close={avg_ret:+.3f}%, negative={pct_neg:.0f}%")

    print(f"\n  After PO leaves distribution:")
    print(f"    Return to close: mean={ldf['ret_leave_to_close'].mean():+.3f}%, "
          f"median={ldf['ret_leave_to_close'].median():+.3f}%")
    neg = (ldf["ret_leave_to_close"] < 0).sum()
    print(f"    Negative: {neg}/{n_leave} ({neg/n_leave*100:.1f}%)")
    print(f"    Max gain after:  mean={ldf['max_gain_after'].mean():+.3f}%, "
          f"median={ldf['max_gain_after'].median():+.3f}%")
    print(f"    Max DD after:    mean={ldf['max_dd_after'].mean():+.3f}%, "
          f"median={ldf['max_dd_after'].median():+.3f}%")

    new_highs = ldf["new_high_after"].sum()
    print(f"\n  Made NEW HIGH after leaving distribution: {new_highs}/{n_leave} ({new_highs/n_leave*100:.1f}%)")
    print(f"  Pullback from day high to close: mean={ldf['pullback_from_high'].mean():.3f}%, "
          f"median={ldf['pullback_from_high'].median():.3f}%")

    # ══════════════════════════════════════════════
    # ANALYSIS 2: ATR level where price tops out
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("2. WHERE DOES PRICE TOP OUT? (Day High vs ATR Levels)")
    print("=" * 70)

    top_data = []
    for date in qualifying_dates:
        group = df[df["date"] == date]
        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]
        if atr == 0:
            continue

        day_high = group["high"].max()
        high_atr_pct = (day_high - prev_close) / atr * 100

        # Find the bar with the day high
        high_idx = group["high"].idxmax()
        high_time = high_idx.time()

        # Which ATR level bracket does the high fall in?
        levels = {
            "< 61.8%": high_atr_pct < 61.8,
            "61.8-78.6%": 61.8 <= high_atr_pct < 78.6,
            "78.6-100%": 78.6 <= high_atr_pct < 100,
            "100-123.6%": 100 <= high_atr_pct < 123.6,
            "123.6-161.8%": 123.6 <= high_atr_pct < 161.8,
            "> 161.8%": high_atr_pct >= 161.8,
        }
        bracket = [k for k, v in levels.items() if v][0]

        top_data.append({
            "date": date,
            "high_atr_pct": high_atr_pct,
            "high_time": high_time,
            "bracket": bracket,
        })

    tdf = pd.DataFrame(top_data)
    n_top = len(tdf)

    print(f"\n  Day high ATR position: mean={tdf['high_atr_pct'].mean():.1f}%, "
          f"median={tdf['high_atr_pct'].median():.1f}%")

    print(f"\n  Day high falls in which ATR bracket:")
    bracket_order = ["< 61.8%", "61.8-78.6%", "78.6-100%", "100-123.6%", "123.6-161.8%", "> 161.8%"]
    for b in bracket_order:
        count = (tdf["bracket"] == b).sum()
        bar = "█" * int(count / n_top * 50)
        print(f"    {b:>15s}: {count:4d} ({count/n_top*100:5.1f}%) {bar}")

    # Time of day high
    print(f"\n  When does the day high occur:")
    tdf["high_half"] = tdf["high_time"].apply(lambda t: f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}")
    for half in sorted(tdf["high_half"].unique()):
        count = (tdf["high_half"] == half).sum()
        bar = "█" * int(count / n_top * 50)
        print(f"    {half}: {count:4d} ({count/n_top*100:5.1f}%) {bar}")

    # ══════════════════════════════════════════════
    # ANALYSIS 3: Pivot Ribbon signals on reversal
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("3. PIVOT RIBBON STATE AT KEY MOMENTS")
    print("=" * 70)

    ribbon_data = []
    for date in qualifying_dates:
        group = df[df["date"] == date]
        first = group.iloc[0]

        # At 11am
        bars_11 = group.between_time("11:00", "11:00")
        if len(bars_11) == 0:
            continue

        r11 = bars_11.iloc[0]
        fast_bull_11 = r11["fast_cloud_bullish"]
        slow_bull_11 = r11["slow_cloud_bullish"]
        comp_11 = r11["compression"]

        # Did fast cloud flip bearish at any point after 11am?
        after_11 = group.between_time("11:00", "15:59")
        fast_flipped = False
        flip_time = None
        for i in range(1, len(after_11)):
            if after_11.iloc[i]["fast_cloud_bullish"] == 0 and after_11.iloc[i-1]["fast_cloud_bullish"] == 1:
                fast_flipped = True
                flip_time = after_11.index[i].time()
                break

        # Did compression activate after 11am?
        comp_activated = False
        comp_time = None
        for i in range(len(after_11)):
            if after_11.iloc[i]["compression"] == 1:
                comp_activated = True
                comp_time = after_11.index[i].time()
                break

        # Return based on fast cloud flip
        if fast_flipped:
            flip_idx = list(after_11.index).index(after_11.index[
                next(i for i in range(1, len(after_11))
                     if after_11.iloc[i]["fast_cloud_bullish"] == 0 and after_11.iloc[i-1]["fast_cloud_bullish"] == 1)
            ])
            flip_price = after_11.iloc[flip_idx]["close"]
            close_price = after_11.iloc[-1]["close"]
            ret_flip_to_close = (close_price - flip_price) / flip_price * 100
        else:
            ret_flip_to_close = np.nan

        rod_close = after_11.iloc[-1]["close"]
        price_11 = r11["close"]
        ret_11_close = (rod_close - price_11) / price_11 * 100

        ribbon_data.append({
            "date": date,
            "fast_bull_11": fast_bull_11,
            "slow_bull_11": slow_bull_11,
            "comp_11": comp_11,
            "fast_flipped": fast_flipped,
            "flip_time": flip_time,
            "comp_activated": comp_activated,
            "comp_time": comp_time,
            "ret_flip_to_close": ret_flip_to_close,
            "ret_11_close": ret_11_close,
        })

    rdf = pd.DataFrame(ribbon_data)
    n_rib = len(rdf)

    flipped = rdf["fast_flipped"].sum()
    print(f"\n  Fast cloud flipped bearish after 11am: {flipped}/{n_rib} ({flipped/n_rib*100:.1f}%)")

    if flipped > 0:
        flip_sub = rdf[rdf["fast_flipped"]]
        print(f"  When fast cloud flips:")
        flip_sub_sorted = flip_sub.copy()
        flip_sub_sorted["flip_half"] = flip_sub_sorted["flip_time"].apply(
            lambda t: f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}")
        for half in sorted(flip_sub_sorted["flip_half"].unique()):
            count = (flip_sub_sorted["flip_half"] == half).sum()
            print(f"    {half}: {count:4d} ({count/flipped*100:5.1f}%)")

        print(f"\n  After fast cloud flips bearish:")
        print(f"    Return flip→close: mean={flip_sub['ret_flip_to_close'].mean():+.3f}%, "
              f"median={flip_sub['ret_flip_to_close'].median():+.3f}%")
        neg = (flip_sub["ret_flip_to_close"] < 0).sum()
        print(f"    Negative: {neg}/{flipped} ({neg/flipped*100:.1f}%)")

    no_flip = rdf[~rdf["fast_flipped"]]
    print(f"\n  Days where fast cloud STAYED bullish all day: {len(no_flip)}/{n_rib}")
    if len(no_flip) > 0:
        print(f"    11am→close: mean={no_flip['ret_11_close'].mean():+.3f}%, "
              f"median={no_flip['ret_11_close'].median():+.3f}%")

    comp_act = rdf["comp_activated"].sum()
    print(f"\n  Compression activated after 11am: {comp_act}/{n_rib} ({comp_act/n_rib*100:.1f}%)")

    # ══════════════════════════════════════════════
    # ANALYSIS 4: PO slope as early warning
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("4. PO SLOPE AS EARLY WARNING (while PO still > 61.8)")
    print("=" * 70)

    slope_data = []
    for date in qualifying_dates:
        group = df[df["date"] == date]
        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]

        # Find peak PO value and when it occurs
        peak_po_idx = group["phase_oscillator"].idxmax()
        peak_po_val = group.loc[peak_po_idx, "phase_oscillator"]
        peak_po_time = peak_po_idx.time()
        peak_po_price = group.loc[peak_po_idx, "close"]

        # Find when PO first starts declining (first bar where PO < previous bar, while still > 61.8)
        po_series = group["phase_oscillator"]
        first_decline = None
        for i in range(1, len(group)):
            if (po_series.iloc[i] < po_series.iloc[i-1] and
                po_series.iloc[i] > 61.8 and
                group.index[i] >= pd.Timestamp(f"{date} 10:00")):
                first_decline = i
                break

        if first_decline is None:
            continue

        decline_time = group.index[first_decline].time()
        decline_price = group.iloc[first_decline]["close"]
        decline_po = group.iloc[first_decline]["phase_oscillator"]

        # What happens after PO starts declining?
        remaining = group.iloc[first_decline:]
        if len(remaining) < 2:
            continue

        close_price = remaining.iloc[-1]["close"]
        ret_decline_to_close = (close_price - decline_price) / decline_price * 100
        max_gain = (remaining["high"].max() - decline_price) / decline_price * 100
        max_dd = (remaining["low"].min() - decline_price) / decline_price * 100

        # Price high vs ATR at decline point
        price_high = group["high"].max()
        high_atr_pct = (price_high - prev_close) / atr * 100

        slope_data.append({
            "date": date,
            "peak_po": peak_po_val,
            "peak_po_time": peak_po_time,
            "decline_time": decline_time,
            "decline_po": decline_po,
            "ret_decline_to_close": ret_decline_to_close,
            "max_gain": max_gain,
            "max_dd": max_dd,
        })

    sdf = pd.DataFrame(slope_data)
    n_slope = len(sdf)

    print(f"\n  Peak PO value: mean={sdf['peak_po'].mean():.1f}, median={sdf['peak_po'].median():.1f}")
    print(f"  Peak PO time:")
    sdf["peak_half"] = sdf["peak_po_time"].apply(lambda t: f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}")
    for half in sorted(sdf["peak_half"].unique()):
        count = (sdf["peak_half"] == half).sum()
        if count >= 5:
            print(f"    {half}: {count:4d} ({count/n_slope*100:5.1f}%)")

    print(f"\n  First PO downtick (after 10am, while still > 61.8):")
    sdf["decline_half"] = sdf["decline_time"].apply(lambda t: f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}")
    for half in sorted(sdf["decline_half"].unique()):
        count = (sdf["decline_half"] == half).sum()
        sub = sdf[sdf["decline_half"] == half]
        avg_ret = sub["ret_decline_to_close"].mean()
        if count >= 5:
            print(f"    {half}: n={count:4d}, avg decline→close={avg_ret:+.3f}%")

    print(f"\n  After first PO downtick:")
    print(f"    Return to close: mean={sdf['ret_decline_to_close'].mean():+.3f}%, "
          f"median={sdf['ret_decline_to_close'].median():+.3f}%")
    neg = (sdf["ret_decline_to_close"] < 0).sum()
    print(f"    Negative: {neg}/{n_slope} ({neg/n_slope*100:.1f}%)")

    # ══════════════════════════════════════════════
    # ANALYSIS 5: Drawdown from day high — magnitude and timing
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("5. DRAWDOWN FROM DAY HIGH")
    print("=" * 70)

    dd_data = []
    for date in qualifying_dates:
        group = df[df["date"] == date]
        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]

        day_high = group["high"].max()
        high_idx = group["high"].idxmax()
        high_time = high_idx.time()

        # Everything after the high
        after_high_loc = group.index.get_loc(high_idx)
        after_high = group.iloc[after_high_loc:]
        if len(after_high) < 2:
            continue

        post_low = after_high["low"].min()
        close_price = after_high.iloc[-1]["close"]

        dd_from_high = (post_low - day_high) / day_high * 100
        close_from_high = (close_price - day_high) / day_high * 100

        # PO at the high
        po_at_high = group.loc[high_idx, "phase_oscillator"]

        # How many bars between high and close?
        bars_after_high = len(after_high)

        dd_data.append({
            "date": date,
            "high_time": high_time,
            "dd_from_high": dd_from_high,
            "close_from_high": close_from_high,
            "po_at_high": po_at_high,
            "bars_after_high": bars_after_high,
        })

    ddf = pd.DataFrame(dd_data)
    n_dd = len(ddf)

    print(f"\n  Drawdown from day high to post-high low:")
    print(f"    Mean:   {ddf['dd_from_high'].mean():.3f}%")
    print(f"    Median: {ddf['dd_from_high'].median():.3f}%")
    print(f"    25th:   {ddf['dd_from_high'].quantile(0.25):.3f}%")
    print(f"    75th:   {ddf['dd_from_high'].quantile(0.75):.3f}%")

    print(f"\n  Close relative to day high:")
    print(f"    Mean:   {ddf['close_from_high'].mean():.3f}%")
    print(f"    Median: {ddf['close_from_high'].median():.3f}%")

    print(f"\n  PO at the moment of day high:")
    print(f"    Mean: {ddf['po_at_high'].mean():.1f}, Median: {ddf['po_at_high'].median():.1f}")

    # PO at high vs drawdown
    print(f"\n  PO at high vs subsequent drawdown:")
    po_bins = [(0, 40, "PO < 40"), (40, 61.8, "PO 40-61.8"),
               (61.8, 80, "PO 61.8-80"), (80, 100, "PO 80-100"), (100, 999, "PO > 100")]
    for lo, hi, label in po_bins:
        sub = ddf[(ddf["po_at_high"] >= lo) & (ddf["po_at_high"] < hi)]
        if len(sub) >= 10:
            print(f"    {label:>14s}: n={len(sub):3d}, avg drawdown={sub['dd_from_high'].mean():.3f}%, "
                  f"avg close from high={sub['close_from_high'].mean():.3f}%")

    # ══════════════════════════════════════════════
    # ANALYSIS 6: What if PO crosses below 23.6 after being sustained?
    # (Complete mean reversion signal)
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("6. DEEP MEAN REVERSION: PO drops below 23.6 after sustained > 61.8")
    print("=" * 70)

    deep_rev_data = []
    for date in qualifying_dates:
        group = df[df["date"] == date]
        first = group.iloc[0]

        # Find when PO drops below 23.6
        cross_below = None
        for i in range(1, len(group)):
            if group.iloc[i]["phase_oscillator"] < 23.6 and group.iloc[i-1]["phase_oscillator"] >= 23.6:
                cross_below = i
                break

        if cross_below is None:
            continue

        cross_time = group.index[cross_below].time()
        cross_price = group.iloc[cross_below]["close"]
        cross_po = group.iloc[cross_below]["phase_oscillator"]

        remaining = group.iloc[cross_below:]
        if len(remaining) < 2:
            continue

        close_price = remaining.iloc[-1]["close"]
        ret = (close_price - cross_price) / cross_price * 100
        max_gain = (remaining["high"].max() - cross_price) / cross_price * 100
        max_dd = (remaining["low"].min() - cross_price) / cross_price * 100

        # Did PO go negative?
        went_negative = (remaining["phase_oscillator"] < 0).any()

        deep_rev_data.append({
            "date": date,
            "cross_time": cross_time,
            "cross_po": cross_po,
            "ret_to_close": ret,
            "max_gain": max_gain,
            "max_dd": max_dd,
            "went_negative": went_negative,
        })

    drdf = pd.DataFrame(deep_rev_data)
    n_dr = len(drdf)
    print(f"\n  Days where PO dropped below 23.6: {n_dr}/{len(qualifying_dates)} ({n_dr/len(qualifying_dates)*100:.1f}%)")

    if n_dr > 0:
        print(f"\n  When PO crosses below 23.6:")
        drdf["cross_half"] = drdf["cross_time"].apply(lambda t: f"{t.hour:02d}:{0 if t.minute < 30 else 30:02d}")
        for half in sorted(drdf["cross_half"].unique()):
            count = (drdf["cross_half"] == half).sum()
            if count >= 3:
                sub = drdf[drdf["cross_half"] == half]
                print(f"    {half}: n={count:4d}, avg ret to close={sub['ret_to_close'].mean():+.3f}%")

        print(f"\n  After PO drops below 23.6:")
        print(f"    Return to close: mean={drdf['ret_to_close'].mean():+.3f}%, "
              f"median={drdf['ret_to_close'].median():+.3f}%")
        neg = (drdf["ret_to_close"] < 0).sum()
        print(f"    Negative: {neg}/{n_dr} ({neg/n_dr*100:.1f}%)")
        print(f"    Max gain: mean={drdf['max_gain'].mean():+.3f}%")
        print(f"    Max DD: mean={drdf['max_dd'].mean():+.3f}%")

        went_neg = drdf["went_negative"].sum()
        print(f"    PO went negative (bearish): {went_neg}/{n_dr} ({went_neg/n_dr*100:.1f}%)")

    # ══════════════════════════════════════════════
    # SYNTHESIS
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("SYNTHESIS: REVERSAL SIGNAL SCORECARD")
    print("=" * 70)

    print(f"""
  On these 289 days where 10m PO sustained > 61.8 through 11am:

  SIGNAL 1 — PO Leaves Distribution (drops below 61.8):
    Occurs on {n_leave}/{len(qualifying_dates)} days ({n_leave/len(qualifying_dates)*100:.0f}%)
    Avg return after: {ldf['ret_leave_to_close'].mean():+.3f}%
    Goes negative: {(ldf['ret_leave_to_close'] < 0).sum()}/{n_leave} ({(ldf['ret_leave_to_close'] < 0).mean()*100:.0f}%)

  SIGNAL 2 — Fast Cloud Flips Bearish:
    Occurs on {flipped}/{n_rib} days ({flipped/n_rib*100:.0f}%)
    Avg return after flip: {rdf[rdf['fast_flipped']]['ret_flip_to_close'].mean():+.3f}%
    Goes negative: {(rdf[rdf['fast_flipped']]['ret_flip_to_close'] < 0).sum()}/{flipped} ({(rdf[rdf['fast_flipped']]['ret_flip_to_close'] < 0).mean()*100:.0f}%)

  SIGNAL 3 — PO First Downtick (slope turns negative while > 61.8):
    Avg return after: {sdf['ret_decline_to_close'].mean():+.3f}%
    Goes negative: {(sdf['ret_decline_to_close'] < 0).sum()}/{n_slope} ({(sdf['ret_decline_to_close'] < 0).mean()*100:.0f}%)

  SIGNAL 4 — PO Drops Below 23.6 (deep reversion):
    Occurs on {n_dr}/{len(qualifying_dates)} days ({n_dr/len(qualifying_dates)*100:.0f}%)
    Avg return after: {drdf['ret_to_close'].mean():+.3f}% (n={n_dr})

  DAY HIGH PROFILE:
    Median high at {tdf['high_atr_pct'].median():.0f}% of ATR
    Avg drawdown from high: {ddf['dd_from_high'].mean():.3f}%
    Avg close from high: {ddf['close_from_high'].mean():.3f}%
""")

    conn.close()
    print("✓ Reversal analysis complete.")


if __name__ == "__main__":
    main()
