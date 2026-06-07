"""
Bilbo Box Breakout Study
========================

WHAT THIS STUDIES
-----------------
When the Saty Phase Oscillator enters compression (BB squeeze), price
consolidates into a range. The "Bilbo Box" is the range of the first
5 compression bars. Once price breaks out of that range, it tends to
follow through. This study measures that follow-through and compares
three entry variants: immediate, close-outside, retest.

See proposal_bilbo_box.md for the full design doc and codex-reviewed
decisions.

OUTPUT
------
- stdout: per-timeframe summaries, segmentation tables
- analyst/bilbo_box_events.parquet: event-level data
- analyst/bilbo_box_summary.json: JSON summary for HTML page
"""

import os
import sys
import json
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
ANALYST_DIR = os.path.join(BASE_DIR, "analyst")

# ── Parameters ──
BREAK_LOOKBACK = 20         # bars to wait for a break after box locks
CLOSE_CONFIRM_LOOKBACK = 5  # bars to wait for a close beyond boundary
RETEST_LOOKBACK = 10        # bars to wait for a retest after break
WINDOWS = [5, 10, 15]       # forward-measurement windows in bars
MIN_SAMPLE_REPORT = 20      # do not report results below this n
FLAG_SAMPLE = 50            # flag results with warning below this n

TIMEFRAMES = [
    # (table, label, intraday_rth_only)
    ("ind_3m",  "3m",  True),
    ("ind_10m", "10m", True),
    ("ind_1h",  "1h",  False),
    ("ind_4h",  "4h",  False),
    ("ind_1d",  "1d",  False),
]


def scan_bilbo_boxes(df, intraday_rth):
    """
    Scan bars for bilbo box events.

    Box formation: first 5 contiguous compression bars define range.
    Early-exit: if compression ends before bar 5, use the bars up to that
    point. Break-watch always starts at lock_bar + 1 (never same-bar).

    Returns a list of event dicts.
    """
    comp = df["compression"].fillna(0).astype(int).values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values
    ts = df.index.values  # numpy datetimes

    ema21 = df["ema_21"].values if "ema_21" in df.columns else np.full(len(df), np.nan)
    ema48 = df["ema_48"].values if "ema_48" in df.columns else np.full(len(df), np.nan)
    atr14 = df["atr_14"].values if "atr_14" in df.columns else np.full(len(df), np.nan)

    n = len(df)
    events = []

    i = 0
    while i < n:
        # Skip until a fresh compression start
        if comp[i] != 1 or (i > 0 and comp[i-1] == 1):
            i += 1
            continue

        box_start = i
        box_high = highs[i]
        box_low = lows[i]

        # Form box: extend while compression active, max 5 bars
        j = i + 1
        while j < n and (j - box_start) < 5 and comp[j] == 1:
            if highs[j] > box_high:
                box_high = highs[j]
            if lows[j] < box_low:
                box_low = lows[j]
            j += 1

        lock_bar = j - 1
        box_bars_count = j - box_start

        # Break-watch starts at lock_bar + 1 == j
        break_start = j
        if break_start >= n:
            break  # ran out of data mid-box

        break_end = min(break_start + BREAK_LOOKBACK, n)

        break_bar = None
        break_dir = None
        break_price = None
        gap_through = False
        ambiguous_outside = False
        stale_rollover_at = None

        for k in range(break_start, break_end):
            # Stale-box rollover: new compression starts before break
            if comp[k] == 1 and comp[k-1] == 0:
                stale_rollover_at = k
                break

            h = highs[k]
            l = lows[k]
            o = opens[k]

            above = h > box_high
            below = l < box_low

            if above and below:
                # Outside bar — classify by close position; if close is inside
                # the box, direction is truly ambiguous and we flag+exclude.
                ambiguous_outside = True
                break_bar = k
                if closes[k] > box_high:
                    break_dir = "bull"
                    break_price = box_high
                elif closes[k] < box_low:
                    break_dir = "bear"
                    break_price = box_low
                else:
                    # close inside the box → direction unresolvable
                    break_dir = "ambiguous"
                    break_price = closes[k]
                break
            elif above:
                break_bar = k
                break_dir = "bull"
                if o > box_high:
                    gap_through = True
                    break_price = o
                else:
                    break_price = box_high
                break
            elif below:
                break_bar = k
                break_dir = "bear"
                if o < box_low:
                    gap_through = True
                    break_price = o
                else:
                    break_price = box_low
                break

        if break_bar is None:
            # Expired or stale rollover
            if stale_rollover_at is not None:
                i = stale_rollover_at  # reprocess as fresh start
            else:
                i = break_end
            continue

        # We have a break — build event
        R = box_high - box_low
        if R <= 0:
            i = break_bar + 1
            continue

        atr_at = atr14[break_bar] if not np.isnan(atr14[break_bar]) else np.nan
        box_width_atr = (R / atr_at) if (atr_at and atr_at > 0) else np.nan
        ema_trend = "bull" if ema21[break_bar] > ema48[break_bar] else "bear"

        break_ts = pd.Timestamp(ts[break_bar])
        tod_bucket = time_of_day_bucket(break_ts) if intraday_rth else "n/a"

        # Compute entry variants & outcomes
        variant_outcomes = compute_entries_and_outcomes(
            break_bar, break_dir, break_price, ambiguous_outside,
            box_high, box_low, highs, lows, opens, closes, ts,
            intraday_rth,
        )

        event = {
            "box_start_ts": pd.Timestamp(ts[box_start]),
            "lock_bar_ts": pd.Timestamp(ts[lock_bar]),
            "break_bar_ts": break_ts,
            "box_bars": box_bars_count,
            "box_high": box_high,
            "box_low": box_low,
            "box_width_pts": R,
            "box_width_atr": box_width_atr,
            "direction": break_dir,
            "break_price": break_price,
            "gap_through": gap_through,
            "ambiguous_outside": ambiguous_outside,
            "ema_trend_at_break": ema_trend,
            "atr14_at_break": atr_at,
            "tod_bucket": tod_bucket,
        }
        for variant, outcome in variant_outcomes.items():
            event[f"{variant}_fired"] = outcome is not None
            if outcome is None:
                continue
            event[f"{variant}_entry_ts"] = outcome["entry_ts"]
            event[f"{variant}_entry_price"] = outcome["entry_price"]
            for w in WINDOWS:
                for metric in ["mfe_pts", "mae_pts", "net_pts", "stopped_out", "valid"]:
                    event[f"{variant}_w{w}_{metric}"] = outcome[f"w{w}_{metric}"]

        events.append(event)

        # Advance past break bar; next fresh compression will be detected
        i = break_bar + 1

    return events


def compute_entries_and_outcomes(
    break_bar, direction, break_price, ambiguous_outside,
    box_high, box_low, highs, lows, opens, closes, ts, intraday_rth,
):
    """Return {variant_name: outcome_dict_or_None}."""
    results = {"immediate": None, "close_outside": None, "retest": None}
    n = len(ts)

    # IMMEDIATE: fires on every clean break (skip ambiguous outside bars)
    if not ambiguous_outside:
        results["immediate"] = measure_outcomes(
            break_bar, break_price, direction, box_high, box_low,
            highs, lows, closes, ts, intraday_rth,
        )

    # CLOSE OUTSIDE: first bar at/after break whose close is beyond boundary
    for k in range(break_bar, min(break_bar + CLOSE_CONFIRM_LOOKBACK, n)):
        c = closes[k]
        confirmed = (direction == "bull" and c > box_high) or \
                    (direction == "bear" and c < box_low)
        if confirmed:
            results["close_outside"] = measure_outcomes(
                k, c, direction, box_high, box_low,
                highs, lows, closes, ts, intraday_rth,
            )
            break

    # RETEST: after break, price returns to broken boundary
    # Invalidation: opposite boundary hit first
    for k in range(break_bar + 1, min(break_bar + 1 + RETEST_LOOKBACK, n)):
        h = highs[k]
        l = lows[k]
        # Opposite-boundary invalidation check
        if direction == "bull" and l < box_low:
            break
        if direction == "bear" and h > box_high:
            break
        # Retest check
        if direction == "bull" and l <= box_high:
            results["retest"] = measure_outcomes(
                k, box_high, direction, box_high, box_low,
                highs, lows, closes, ts, intraday_rth,
            )
            break
        if direction == "bear" and h >= box_low:
            results["retest"] = measure_outcomes(
                k, box_low, direction, box_high, box_low,
                highs, lows, closes, ts, intraday_rth,
            )
            break

    return results


def measure_outcomes(entry_idx, entry_price, direction, box_high, box_low,
                     highs, lows, closes, ts, intraday_rth):
    """Compute MFE, MAE, net, stopped_out for 5/10/15-bar windows."""
    n = len(ts)
    out = {
        "entry_idx": entry_idx,
        "entry_ts": pd.Timestamp(ts[entry_idx]),
        "entry_price": entry_price,
    }

    entry_date = pd.Timestamp(ts[entry_idx]).date() if intraday_rth else None

    for N in WINDOWS:
        # Determine actual end index with intraday truncation
        end_idx = entry_idx
        for step in range(1, N + 1):
            nxt = entry_idx + step
            if nxt >= n:
                break
            if intraday_rth and pd.Timestamp(ts[nxt]).date() != entry_date:
                break
            end_idx = nxt

        bars_avail = end_idx - entry_idx
        if bars_avail < N:
            out[f"w{N}_valid"] = False
            out[f"w{N}_mfe_pts"] = np.nan
            out[f"w{N}_mae_pts"] = np.nan
            out[f"w{N}_net_pts"] = np.nan
            out[f"w{N}_stopped_out"] = np.nan
            continue

        mfe = 0.0
        mae = 0.0
        stopped_out = False
        for m in range(entry_idx + 1, end_idx + 1):
            h = highs[m]
            l = lows[m]
            if direction == "bull":
                fav = h - entry_price
                adv = entry_price - l
                hit_stop = l <= box_low
            else:
                fav = entry_price - l
                adv = h - entry_price
                hit_stop = h >= box_high
            if fav > mfe:
                mfe = fav
            if adv > mae:
                mae = adv
            if hit_stop and not stopped_out:
                stopped_out = True

        final_close = closes[end_idx]
        if direction == "bull":
            net = final_close - entry_price
        else:
            net = entry_price - final_close

        out[f"w{N}_valid"] = True
        out[f"w{N}_mfe_pts"] = float(mfe)
        out[f"w{N}_mae_pts"] = float(mae)
        out[f"w{N}_net_pts"] = float(net)
        out[f"w{N}_stopped_out"] = bool(stopped_out)

    return out


def time_of_day_bucket(ts):
    t = ts.time()
    if t < pd.Timestamp("10:30").time():
        return "open (9:30-10:30)"
    elif t < pd.Timestamp("14:00").time():
        return "mid (10:30-14:00)"
    else:
        return "close (14:00-16:00)"


def load_timeframe(conn, table, intraday_rth):
    """Load indicator table with required columns."""
    cols = ("timestamp, open, high, low, close, compression, "
            "ema_21, ema_48, atr_14")
    df = pd.read_sql_query(
        f"SELECT {cols} FROM {table} ORDER BY timestamp",
        conn, parse_dates=["timestamp"],
    )
    df = df.set_index("timestamp").sort_index()
    if intraday_rth:
        df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["compression", "open", "high", "low", "close"])
    return df


# ────────────────────────────────────────────────────────────
#  Reporting
# ────────────────────────────────────────────────────────────

def fmt(n, d):
    return f"{n/d*100:.1f}%" if d > 0 else "n/a"


def summarize_variant_window(df_ev, variant, window, filter_mask=None):
    """Return dict of summary stats for a given variant × window."""
    col_valid = f"{variant}_w{window}_valid"
    col_fired = f"{variant}_fired"
    col_mfe = f"{variant}_w{window}_mfe_pts"
    col_mae = f"{variant}_w{window}_mae_pts"
    col_net = f"{variant}_w{window}_net_pts"
    col_stop = f"{variant}_w{window}_stopped_out"

    sub = df_ev if filter_mask is None else df_ev[filter_mask]
    total = len(sub)
    fired = sub[col_fired].fillna(False)
    valid = sub[col_valid].fillna(False) & fired
    elig = sub[valid]

    n = len(elig)
    if n == 0:
        return {"n": 0, "trigger_rate": 0.0}
    # Also compute R-multiple using box width
    if n > 0:
        mfe = elig[col_mfe].astype(float)
        mae = elig[col_mae].astype(float)
        net = elig[col_net].astype(float)
        R = elig["box_width_pts"].astype(float)
        mfe_R = (mfe / R).replace([np.inf, -np.inf], np.nan)
        mae_R = (mae / R).replace([np.inf, -np.inf], np.nan)
        net_R = (net / R).replace([np.inf, -np.inf], np.nan)

    return {
        "n": int(n),
        "trigger_rate": float(fired.sum() / total) if total > 0 else 0.0,
        "total_breaks": int(total),
        "mfe_pts_mean": float(mfe.mean()),
        "mfe_pts_median": float(mfe.median()),
        "mae_pts_mean": float(mae.mean()),
        "mae_pts_median": float(mae.median()),
        "net_pts_mean": float(net.mean()),
        "net_pts_median": float(net.median()),
        "net_positive_rate": float((net > 0).sum() / n),
        "stopped_out_rate": float(elig[col_stop].fillna(False).sum() / n),
        "mfe_R_median": float(mfe_R.median()),
        "mae_R_median": float(mae_R.median()),
        "net_R_mean": float(net_R.mean()),
        "net_R_median": float(net_R.median()),
    }


def print_overall(tf_label, df_ev):
    total = len(df_ev)
    if total == 0:
        print(f"  [!] No events for {tf_label}")
        return
    bull = (df_ev["direction"] == "bull").sum()
    bear = (df_ev["direction"] == "bear").sum()
    gap = df_ev["gap_through"].sum()
    amb = df_ev["ambiguous_outside"].sum()

    print(f"\n{'='*80}")
    print(f"  BILBO BOX BREAKOUT — {tf_label}")
    print(f"{'='*80}")
    print(f"  Total break events:   {total:,}")
    print(f"  Bullish breaks:       {bull:,}  ({fmt(bull,total)})")
    print(f"  Bearish breaks:       {bear:,}  ({fmt(bear,total)})")
    print(f"  Gap-through breaks:   {gap:,}  ({fmt(gap,total)})")
    print(f"  Outside-bar breaks:   {amb:,}  ({fmt(amb,total)})")
    print(f"  Date range:           {df_ev['break_bar_ts'].min().date()} "
          f"→ {df_ev['break_bar_ts'].max().date()}")


def print_variant_table(tf_label, df_ev):
    print(f"\n  --- Per Entry Variant × Window (n reflects full-window eligibility) ---")
    header = (f"  {'Variant':14s} {'Win':>4s} {'n':>6s} {'Trig%':>7s} "
              f"{'MFE_pts':>9s} {'MAE_pts':>9s} {'Net_pts':>9s} "
              f"{'Net+%':>7s} {'Stop%':>7s} {'MFE_R':>7s} {'MAE_R':>7s} {'Net_R':>7s}")
    print(header)
    print(f"  {'-'*(len(header)-2)}")
    for variant in ["immediate", "close_outside", "retest"]:
        for w in WINDOWS:
            s = summarize_variant_window(df_ev, variant, w)
            if s["n"] < MIN_SAMPLE_REPORT:
                print(f"  {variant:14s} {w:>4d} {s['n']:>6d}  — insufficient sample —")
                continue
            flag = " *" if s["n"] < FLAG_SAMPLE else ""
            print(f"  {variant:14s} {w:>4d} {s['n']:>6d} "
                  f"{s['trigger_rate']*100:>6.1f}% "
                  f"{s['mfe_pts_median']:>9.3f} {s['mae_pts_median']:>9.3f} "
                  f"{s['net_pts_median']:>9.3f} "
                  f"{s['net_positive_rate']*100:>6.1f}% "
                  f"{s['stopped_out_rate']*100:>6.1f}% "
                  f"{s['mfe_R_median']:>7.2f} {s['mae_R_median']:>7.2f} "
                  f"{s['net_R_median']:>7.2f}{flag}")


def print_segmentations(tf_label, df_ev):
    """Break down immediate/w10 by several dimensions."""
    variant = "immediate"
    W = 10

    print(f"\n  --- Segmentations ({variant}, {W}-bar window) ---")

    segs = [
        ("Direction", "direction", ["bull", "bear"]),
        ("EMA trend at break", "ema_trend_at_break", ["bull", "bear"]),
        ("Box bars (formation)", "box_bars", [1, 2, 3, 4, 5]),
    ]
    if df_ev["tod_bucket"].nunique() > 1:
        segs.append(("Time of day", "tod_bucket",
                     ["open (9:30-10:30)", "mid (10:30-14:00)", "close (14:00-16:00)"]))

    for label, col, categories in segs:
        print(f"\n  {label}:")
        print(f"    {'Bucket':26s} {'n':>5s} {'Trig%':>7s} {'NetR_med':>9s} {'Net+%':>7s} {'Stop%':>7s}")
        for cat in categories:
            mask = df_ev[col] == cat
            if mask.sum() < 1:
                continue
            s = summarize_variant_window(df_ev, variant, W, filter_mask=mask)
            if s["n"] < MIN_SAMPLE_REPORT:
                print(f"    {str(cat):26s} {s['n']:>5d}  — insufficient sample —")
                continue
            flag = " *" if s["n"] < FLAG_SAMPLE else ""
            print(f"    {str(cat):26s} {s['n']:>5d} "
                  f"{s['trigger_rate']*100:>6.1f}% "
                  f"{s['net_R_median']:>9.3f} "
                  f"{s['net_positive_rate']*100:>6.1f}% "
                  f"{s['stopped_out_rate']*100:>6.1f}%{flag}")

    # Box width (normalized to ATR) terciles
    print(f"\n  Box width as % of ATR (terciles):")
    print(f"    {'Bucket':26s} {'n':>5s} {'Range':>18s} {'NetR_med':>9s} {'Net+%':>7s} {'Stop%':>7s}")
    valid_w = df_ev.dropna(subset=["box_width_atr"])
    if len(valid_w) >= 60:
        q = valid_w["box_width_atr"].quantile([0.333, 0.667]).values
        buckets = [
            (f"narrow (<{q[0]:.2f})", valid_w["box_width_atr"] <  q[0]),
            (f"medium", (valid_w["box_width_atr"] >= q[0]) & (valid_w["box_width_atr"] < q[1])),
            (f"wide (>={q[1]:.2f})",  valid_w["box_width_atr"] >= q[1]),
        ]
        for name, mask in buckets:
            idx = valid_w.index[mask]
            sub_mask = df_ev.index.isin(idx)
            s = summarize_variant_window(df_ev, variant, W, filter_mask=sub_mask)
            if s["n"] < MIN_SAMPLE_REPORT:
                print(f"    {name:26s} {s['n']:>5d}  — insufficient sample —")
                continue
            flag = " *" if s["n"] < FLAG_SAMPLE else ""
            r_range = f"{valid_w.loc[idx,'box_width_atr'].min():.2f}–{valid_w.loc[idx,'box_width_atr'].max():.2f}"
            print(f"    {name:26s} {s['n']:>5d} {r_range:>18s} "
                  f"{s['net_R_median']:>9.3f} "
                  f"{s['net_positive_rate']*100:>6.1f}% "
                  f"{s['stopped_out_rate']*100:>6.1f}%{flag}")


def run_timeframe(conn, table, label, intraday_rth):
    print(f"\nLoading {table} (intraday_rth={intraday_rth})...", flush=True)
    df = load_timeframe(conn, table, intraday_rth)
    print(f"  {len(df):,} bars after filter")
    print(f"  Scanning for bilbo box events...", flush=True)

    events = scan_bilbo_boxes(df, intraday_rth)
    df_ev = pd.DataFrame(events)
    if len(df_ev) == 0:
        print(f"  [!] No events found for {label}")
        return None
    df_ev["timeframe"] = label

    print_overall(label, df_ev)
    print_variant_table(label, df_ev)
    print_segmentations(label, df_ev)

    # Build summary dict
    summary = {"timeframe": label, "n_breaks": int(len(df_ev))}
    summary["bull_pct"] = float((df_ev["direction"] == "bull").mean())
    summary["gap_through_pct"] = float(df_ev["gap_through"].mean())
    summary["ambiguous_outside_pct"] = float(df_ev["ambiguous_outside"].mean())
    summary["variants"] = {}
    for variant in ["immediate", "close_outside", "retest"]:
        summary["variants"][variant] = {}
        for w in WINDOWS:
            summary["variants"][variant][f"w{w}"] = summarize_variant_window(df_ev, variant, w)

    return df_ev, summary


def main():
    if not os.path.exists(ANALYST_DIR):
        os.makedirs(ANALYST_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    tfs = TIMEFRAMES
    if len(sys.argv) > 1:
        picked = sys.argv[1]
        tfs = [t for t in TIMEFRAMES if t[1] == picked]
        if not tfs:
            print(f"Unknown timeframe: {picked}")
            sys.exit(1)

    all_events = []
    all_summaries = []
    for table, label, intraday_rth in tfs:
        result = run_timeframe(conn, table, label, intraday_rth)
        if result is None:
            continue
        df_ev, summary = result
        all_events.append(df_ev)
        all_summaries.append(summary)

    conn.close()

    if all_events:
        combined = pd.concat(all_events, ignore_index=True)
        csv_path = os.path.join(ANALYST_DIR, "bilbo_box_events.csv")
        combined.to_csv(csv_path, index=False)
        print(f"\nSaved {len(combined):,} events → {csv_path}")

        # Cross-timeframe comparison
        print(f"\n{'='*80}")
        print(f"  CROSS-TIMEFRAME COMPARISON (immediate, 10-bar window)")
        print(f"{'='*80}")
        print(f"  {'TF':>4s} {'n':>6s} {'Trig%':>7s} {'MFE_pts':>9s} {'MAE_pts':>9s} "
              f"{'Net_pts':>9s} {'Net_R':>7s} {'Net+%':>7s} {'Stop%':>7s}")
        for s in all_summaries:
            v = s["variants"]["immediate"]["w10"]
            if v["n"] < MIN_SAMPLE_REPORT:
                continue
            print(f"  {s['timeframe']:>4s} {v['n']:>6d} "
                  f"{v['trigger_rate']*100:>6.1f}% "
                  f"{v['mfe_pts_median']:>9.3f} {v['mae_pts_median']:>9.3f} "
                  f"{v['net_pts_median']:>9.3f} {v['net_R_median']:>7.2f} "
                  f"{v['net_positive_rate']*100:>6.1f}% "
                  f"{v['stopped_out_rate']*100:>6.1f}%")

        # JSON summary
        js_path = os.path.join(ANALYST_DIR, "bilbo_box_summary.json")
        with open(js_path, "w") as f:
            json.dump({"summaries": all_summaries,
                       "params": {
                           "break_lookback": BREAK_LOOKBACK,
                           "close_confirm_lookback": CLOSE_CONFIRM_LOOKBACK,
                           "retest_lookback": RETEST_LOOKBACK,
                           "windows": WINDOWS,
                           "min_sample_report": MIN_SAMPLE_REPORT,
                           "flag_sample": FLAG_SAMPLE,
                       }}, f, indent=2, default=str)
        print(f"Saved summary JSON → {js_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
