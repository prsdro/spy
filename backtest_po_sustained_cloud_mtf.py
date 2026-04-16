"""
Multi-timeframe fast cloud flip analysis on days where 10m PO sustained > 61.8
through 11am in bullish expansion.

Compares the fast cloud (EMA8/EMA21) flip as a reversal signal on:
- 3-minute bars
- 10-minute bars
- 1-hour bars
"""

import sqlite3
import pandas as pd
import numpy as np
import json

DB_PATH = "/root/spy/spy.db"


def get_qualifying_dates(df10):
    """Reproduce qualifying days from the main study."""
    qualifying = []
    for date, group in df10.groupby("date"):
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

        qualifying.append(date)

    return qualifying


def analyze_cloud_flip(data, qualifying_dates, tf_label):
    """Analyze fast cloud flip as reversal signal for a given timeframe."""
    results = {
        "tf": tf_label,
        "flipped_days": 0,
        "no_flip_days": 0,
        "total": 0,
        "flip_returns": [],
        "no_flip_returns": [],
        "flip_times": [],
        "flip_ret_by_half": {},
        # For days that flip: return from 11am to close
        "flip_11am_returns": [],
        "no_flip_11am_returns": [],
    }

    for date in qualifying_dates:
        group = data[data["date"] == date]
        if len(group) == 0:
            continue

        after_11 = group.between_time("11:00", "15:59")
        if len(after_11) < 2:
            continue

        results["total"] += 1

        price_11 = after_11.iloc[0]["close"]
        close_price = after_11.iloc[-1]["close"]
        ret_11_close = (close_price - price_11) / price_11 * 100

        # Find first fast cloud flip bearish after 11am
        flipped = False
        flip_time = None
        flip_price = None
        for i in range(1, len(after_11)):
            if after_11.iloc[i]["fast_cloud_bullish"] == 0 and after_11.iloc[i-1]["fast_cloud_bullish"] == 1:
                flipped = True
                flip_time = after_11.index[i].time()
                flip_price = after_11.iloc[i]["close"]
                break

        if flipped:
            results["flipped_days"] += 1
            ret_flip_close = (close_price - flip_price) / flip_price * 100
            results["flip_returns"].append(ret_flip_close)
            results["flip_11am_returns"].append(ret_11_close)
            results["flip_times"].append(flip_time)

            half = f"{flip_time.hour:02d}:{0 if flip_time.minute < 30 else 30:02d}"
            if half not in results["flip_ret_by_half"]:
                results["flip_ret_by_half"][half] = []
            results["flip_ret_by_half"][half].append(ret_flip_close)
        else:
            results["no_flip_days"] += 1
            results["no_flip_returns"].append(ret_11_close)
            results["no_flip_11am_returns"].append(ret_11_close)

    return results


def print_results(r):
    """Print analysis results for one timeframe."""
    total = r["total"]
    flipped = r["flipped_days"]
    no_flip = r["no_flip_days"]

    print(f"\n  {'─' * 55}")
    print(f"  {r['tf']} FAST CLOUD (EMA8/EMA21)")
    print(f"  {'─' * 55}")
    print(f"  Flipped bearish after 11am: {flipped}/{total} ({flipped/total*100:.1f}%)")
    print(f"  Stayed bullish all day:     {no_flip}/{total} ({no_flip/total*100:.1f}%)")

    if flipped > 0:
        fr = np.array(r["flip_returns"])
        print(f"\n  AFTER FAST CLOUD FLIPS BEARISH:")
        print(f"    Flip → Close:  mean={fr.mean():+.3f}%, median={np.median(fr):+.3f}%")
        neg = (fr < 0).sum()
        print(f"    Negative: {neg}/{flipped} ({neg/flipped*100:.1f}%)")

        f11 = np.array(r["flip_11am_returns"])
        print(f"    11am → Close (flip days): mean={f11.mean():+.3f}%, median={np.median(f11):+.3f}%")

        print(f"\n    Flip timing:")
        for half in sorted(r["flip_ret_by_half"].keys()):
            vals = r["flip_ret_by_half"][half]
            n = len(vals)
            if n >= 3:
                avg = np.mean(vals)
                print(f"      {half}: n={n:3d}, avg flip→close={avg:+.3f}%")

    if no_flip > 0:
        nfr = np.array(r["no_flip_returns"])
        print(f"\n  WHEN FAST CLOUD STAYS BULLISH:")
        print(f"    11am → Close: mean={nfr.mean():+.3f}%, median={np.median(nfr):+.3f}%")
        pos = (nfr > 0).sum()
        print(f"    Positive: {pos}/{no_flip} ({pos/no_flip*100:.1f}%)")

    # Edge
    if flipped > 0 and no_flip > 0:
        f11 = np.array(r["flip_11am_returns"])
        nfr = np.array(r["no_flip_returns"])
        print(f"\n  EDGE (no-flip vs flip, 11am→close): {nfr.mean() - f11.mean():+.3f}%")


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load 10m data for qualifying day detection
    print("Loading 10m data for qualifying dates...", flush=True)
    df10 = pd.read_sql_query("SELECT * FROM ind_10m ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df10 = df10.set_index("timestamp").sort_index()
    df10 = df10.between_time("09:30", "15:59")
    df10 = df10.dropna(subset=["prev_close", "atr_14", "phase_oscillator"])
    df10["date"] = df10.index.date

    qualifying_dates = get_qualifying_dates(df10)
    print(f"Qualifying days: {len(qualifying_dates)}")

    # Load 3m data
    print("Loading 3m data...", flush=True)
    df3 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, fast_cloud_bullish FROM ind_3m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df3 = df3.set_index("timestamp").sort_index()
    df3 = df3.between_time("09:30", "15:59")
    df3["date"] = df3.index.date

    # Load 1h data
    print("Loading 1h data...", flush=True)
    df1h = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, fast_cloud_bullish FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df1h = df1h.set_index("timestamp").sort_index()
    df1h = df1h.between_time("09:30", "15:59")
    df1h["date"] = df1h.index.date

    print("\n" + "=" * 70)
    print("MULTI-TIMEFRAME FAST CLOUD FLIP ANALYSIS")
    print("On days where 10m PO sustained > 61.8 through 11am")
    print("=" * 70)

    # Analyze each timeframe
    r3 = analyze_cloud_flip(df3, qualifying_dates, "3-MINUTE")
    r10 = analyze_cloud_flip(df10, qualifying_dates, "10-MINUTE")
    r1h = analyze_cloud_flip(df1h, qualifying_dates, "1-HOUR")

    print_results(r3)
    print_results(r10)
    print_results(r1h)

    # ── Head-to-head comparison ──
    print(f"\n{'=' * 70}")
    print("HEAD-TO-HEAD COMPARISON")
    print("=" * 70)
    print(f"\n  {'Timeframe':>12s} {'Flip%':>7s} {'Flip→Close':>12s} {'Neg%':>6s} "
          f"{'NoFlip→Close':>14s} {'Pos%':>6s} {'Edge':>8s}")
    print(f"  {'─' * 70}")

    for r in [r3, r10, r1h]:
        tf = r["tf"]
        total = r["total"]
        flipped = r["flipped_days"]
        no_flip = r["no_flip_days"]
        flip_pct = flipped / total * 100 if total > 0 else 0

        if flipped > 0:
            fr = np.array(r["flip_returns"])
            flip_avg = fr.mean()
            flip_neg = (fr < 0).mean() * 100
            f11 = np.array(r["flip_11am_returns"])
        else:
            flip_avg = 0
            flip_neg = 0
            f11 = np.array([0])

        if no_flip > 0:
            nfr = np.array(r["no_flip_returns"])
            nf_avg = nfr.mean()
            nf_pos = (nfr > 0).mean() * 100
        else:
            nf_avg = 0
            nf_pos = 0

        edge = nf_avg - f11.mean() if flipped > 0 and no_flip > 0 else 0

        print(f"  {tf:>12s} {flip_pct:6.1f}% {flip_avg:+11.3f}% {flip_neg:5.1f}% "
              f"{nf_avg:+13.3f}% {nf_pos:5.1f}% {edge:+7.3f}%")

    # ── Export data for visualization ──
    print("\nExporting data for visualization...", flush=True)

    viz_data = {
        "qualifying_count": len(qualifying_dates),
        "total_days": df10["date"].nunique(),
        "timeframes": {}
    }

    for r in [r3, r10, r1h]:
        tf_key = r["tf"].lower().replace("-", "").replace(" ", "_")
        fr = np.array(r["flip_returns"]) if r["flip_returns"] else np.array([])
        nfr = np.array(r["no_flip_returns"]) if r["no_flip_returns"] else np.array([])
        f11 = np.array(r["flip_11am_returns"]) if r["flip_11am_returns"] else np.array([])

        viz_data["timeframes"][tf_key] = {
            "label": r["tf"],
            "total": r["total"],
            "flipped": r["flipped_days"],
            "no_flip": r["no_flip_days"],
            "flip_ret_avg": float(fr.mean()) if len(fr) > 0 else 0,
            "flip_ret_med": float(np.median(fr)) if len(fr) > 0 else 0,
            "flip_neg_pct": float((fr < 0).mean() * 100) if len(fr) > 0 else 0,
            "flip_11am_ret_avg": float(f11.mean()) if len(f11) > 0 else 0,
            "noflip_ret_avg": float(nfr.mean()) if len(nfr) > 0 else 0,
            "noflip_ret_med": float(np.median(nfr)) if len(nfr) > 0 else 0,
            "noflip_pos_pct": float((nfr > 0).mean() * 100) if len(nfr) > 0 else 0,
            "flip_by_half": {k: {"n": len(v), "avg": float(np.mean(v))}
                            for k, v in r["flip_ret_by_half"].items() if len(v) >= 3},
        }

    # Also gather the main study stats for the viz
    # Recompute key numbers from original study
    day_stats = []
    for date in qualifying_dates:
        group = df10[df10["date"] == date]
        first = group.iloc[0]
        prev_close = first["prev_close"]
        atr = first["atr_14"]
        day_open = first["open"]

        bars_11am = group.between_time("11:00", "11:00")
        rest_of_day = group.between_time("11:00", "15:59")
        if len(bars_11am) == 0 or len(rest_of_day) == 0:
            continue

        price_11 = bars_11am.iloc[0]["close"]
        rod_close = rest_of_day.iloc[-1]["close"]
        rod_high = rest_of_day["high"].max()
        rod_low = rest_of_day["low"].min()
        day_high = group["high"].max()

        ret_11_close = (rod_close - price_11) / price_11 * 100
        ret_open_close = (rod_close - day_open) / day_open * 100
        max_gain = (rod_high - price_11) / price_11 * 100
        max_dd = (rod_low - price_11) / price_11 * 100
        high_atr = (day_high - prev_close) / atr * 100
        close_atr = (rod_close - prev_close) / atr * 100

        # PO path
        po_11 = bars_11am.iloc[0]["phase_oscillator"]
        po_close = rest_of_day.iloc[-1]["phase_oscillator"]

        # high time
        high_idx = group["high"].idxmax()
        high_time = f"{high_idx.hour:02d}:{high_idx.minute:02d}"

        day_stats.append({
            "date": str(date),
            "ret_11_close": round(ret_11_close, 4),
            "ret_open_close": round(ret_open_close, 4),
            "max_gain": round(max_gain, 4),
            "max_dd": round(max_dd, 4),
            "high_atr": round(high_atr, 1),
            "close_atr": round(close_atr, 1),
            "po_11": round(po_11, 1),
            "po_close": round(po_close, 1),
            "high_time": high_time,
        })

    viz_data["day_stats"] = day_stats

    # Return distribution buckets
    rets = [d["ret_11_close"] for d in day_stats]
    buckets = [(-999,-1), (-1,-0.5), (-0.5,-0.25), (-0.25,0), (0,0.25), (0.25,0.5), (0.5,1), (1,999)]
    bucket_labels = ["< -1%", "-1 to -0.5%", "-0.5 to -0.25%", "-0.25 to 0%",
                     "0 to +0.25%", "+0.25 to +0.5%", "+0.5 to +1%", "> +1%"]
    bucket_counts = []
    for lo, hi in buckets:
        count = sum(1 for r in rets if lo <= r < hi)
        bucket_counts.append(count)
    viz_data["return_distribution"] = {"labels": bucket_labels, "counts": bucket_counts}

    # ATR bracket distribution
    atr_brackets = [
        (0, 61.8, "< 61.8%"), (61.8, 78.6, "61.8-78.6%"), (78.6, 100, "78.6-100%"),
        (100, 123.6, "100-123.6%"), (123.6, 161.8, "123.6-161.8%"), (161.8, 999, "> 161.8%")
    ]
    atr_bracket_data = []
    for lo, hi, label in atr_brackets:
        count = sum(1 for d in day_stats if lo <= d["high_atr"] < hi)
        atr_bracket_data.append({"label": label, "count": count})
    viz_data["atr_brackets"] = atr_bracket_data

    # High time distribution
    high_time_buckets = {}
    for d in day_stats:
        h = int(d["high_time"].split(":")[0])
        m = int(d["high_time"].split(":")[1])
        half = f"{h:02d}:{0 if m < 30 else 30:02d}"
        high_time_buckets[half] = high_time_buckets.get(half, 0) + 1
    viz_data["high_time_dist"] = dict(sorted(high_time_buckets.items()))

    # PO path averages
    checkpoints = ["09:30","09:40","09:50","10:00","10:10","10:20","10:30","10:40","10:50",
                   "11:00","11:10","11:20","11:30","11:40","11:50",
                   "12:00","12:30","13:00","13:30","14:00","14:30","15:00","15:30"]
    po_path = {}
    price_path = {}
    import datetime
    for t_str in checkpoints:
        h, m = int(t_str.split(":")[0]), int(t_str.split(":")[1])
        t = datetime.time(h, m)
        po_vals = []
        price_vals = []
        for date in qualifying_dates:
            group = df10[df10["date"] == date]
            bars = group[group.index.time == t]
            if len(bars) > 0:
                po_vals.append(bars.iloc[0]["phase_oscillator"])
                # Price as % return from 11am
                bars_11 = group.between_time("11:00", "11:00")
                if len(bars_11) > 0:
                    p11 = bars_11.iloc[0]["close"]
                    price_vals.append((bars.iloc[0]["close"] - p11) / p11 * 100)
        if po_vals:
            po_path[t_str] = {"mean": round(np.mean(po_vals), 1), "median": round(np.median(po_vals), 1)}
        if price_vals:
            price_path[t_str] = {"mean": round(np.mean(price_vals), 4), "median": round(np.median(price_vals), 4)}

    viz_data["po_path"] = po_path
    viz_data["price_path"] = price_path

    # Summary stats
    rets_arr = np.array(rets)
    open_rets = np.array([d["ret_open_close"] for d in day_stats])
    viz_data["summary"] = {
        "ret_11_close_mean": round(float(rets_arr.mean()), 3),
        "ret_11_close_median": round(float(np.median(rets_arr)), 3),
        "ret_11_close_pos_pct": round(float((rets_arr > 0).mean() * 100), 1),
        "ret_open_close_mean": round(float(open_rets.mean()), 3),
        "ret_open_close_pos_pct": round(float((open_rets > 0).mean() * 100), 1),
        "median_high_atr": round(float(np.median([d["high_atr"] for d in day_stats])), 1),
        "po_11_mean": round(float(np.mean([d["po_11"] for d in day_stats])), 1),
        "po_close_mean": round(float(np.mean([d["po_close"] for d in day_stats])), 1),
    }

    with open("/root/spy/po_sustained_viz_data.json", "w") as f:
        json.dump(viz_data, f)

    print("✓ Data exported to po_sustained_viz_data.json")

    conn.close()
    print("\n✓ Multi-timeframe analysis complete.")


if __name__ == "__main__":
    main()
