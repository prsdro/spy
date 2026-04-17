"""
4H PO Rollover + OpEx Timing Study (Extended Conditions)

Focus: 4H PO rollover signals that fire during OpEx Friday or the 1-5 trading days
after, under EXTENDED market conditions (weekly or monthly ATR position ≥ 0.618).

Question: Does a 4H PO rollover near monthly OpEx, when the market is already
stretched on weekly/monthly ATR, produce a reliable post-OpEx drop?

Baseline signal: V2 — 4H PO peak ≥ 80, crosses below 80 (N=118, 25 years).
Extended filter: weekly ATR position ≥ 0.618 OR monthly ATR position ≥ 0.618.

Forward horizons: 1d, 3d, 5d, 10d from signal.
Drop thresholds: ≥0.5%, ≥1.0%, ≥1.5%, ≥2.0% (intraday low reaches target).

OpEx buckets:
  - OpEx Friday (day 0)
  - Post-OpEx day 1 (Monday)
  - Post-OpEx day 2 (Tuesday)
  - Post-OpEx day 3 (Wednesday)
  - Post-OpEx day 4 (Thursday)
  - Post-OpEx day 5 (Friday)
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
from study_utils import compute_resampled_atr_ref, dedupe_signals_by_daily_cooldown
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def third_friday(year, month):
    d = pd.Timestamp(year=year, month=month, day=1)
    first_fri_offset = (4 - d.dayofweek) % 7
    first_friday = d + pd.Timedelta(days=first_fri_offset)
    return (first_friday + pd.Timedelta(days=14)).normalize()


def days_to_opex(date, trading_days):
    """Return trading days to nearest monthly OpEx (negative = after, positive = before)."""
    y, m = date.year, date.month
    candidates = []
    for delta_m in [-1, 0, 1]:
        ny = y + (1 if m + delta_m > 12 else (-1 if m + delta_m < 1 else 0))
        nm = ((m + delta_m - 1) % 12) + 1
        candidates.append(third_friday(ny, nm))

    diffs = []
    for opex in candidates:
        try:
            if opex in trading_days:
                opex_idx = trading_days.get_loc(opex)
            else:
                opex_idx = trading_days.searchsorted(opex)
                if opex_idx >= len(trading_days):
                    continue
            if date in trading_days:
                date_idx = trading_days.get_loc(date)
            else:
                date_idx = trading_days.searchsorted(date)
                if date_idx >= len(trading_days):
                    continue
            diffs.append((opex_idx - date_idx, opex))
        except Exception:
            continue

    if not diffs:
        return None
    nearest = min(diffs, key=lambda x: abs(x[0]))
    return nearest[0]


def compute_weekly_ref(df_d, atr_period=14):
    return compute_resampled_atr_ref(df_d, "W-FRI", atr_period).rename(
        columns={"prev_close": "prev_wk_close", "atr": "wk_atr"}
    )


def compute_monthly_ref(df_d, atr_period=14):
    ref = compute_resampled_atr_ref(df_d, "ME", atr_period).rename(
        columns={"prev_close": "prev_month_close", "atr": "monthly_atr"}
    )
    return ref.reindex(df_d.index, method="ffill")


def main():
    conn = sqlite3.connect(DB_PATH)
    print("Loading data...")
    df4h = pd.read_sql_query(
        "SELECT timestamp, close, phase_oscillator FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp").dropna(subset=["phase_oscillator"])

    df1d = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")
    conn.close()

    # ATR refs
    wk_ref = compute_weekly_ref(df1d)
    df1d_enr = pd.merge_asof(
        df1d.reset_index().sort_values("timestamp"),
        wk_ref.reset_index().sort_values("timestamp"),
        on="timestamp", direction="backward"
    ).set_index("timestamp")
    df1d_enr = df1d_enr.join(compute_monthly_ref(df1d))

    trading_days = df1d.index

    # ─── Find V2 signals ───
    po = df4h["phase_oscillator"]
    was_above = False
    peak = 0
    sigs = []
    for i in range(1, len(df4h)):
        cur = po.iloc[i]
        prev = po.iloc[i - 1]
        if prev >= 80:
            if not was_above:
                was_above = True
                peak = prev
            elif prev > peak:
                peak = prev
        if was_above and prev >= 80 and cur < 80:
            sigs.append({
                "signal_time": df4h.index[i],
                "peak_po": peak,
                "signal_close": df4h.iloc[i]["close"],
            })
            was_above = False
            peak = 0

    sigs = dedupe_signals_by_daily_cooldown(sigs, df1d.index, 10)

    # ─── Build results ───
    results = []
    for s in sigs:
        sig_date = s["signal_time"].normalize()
        sig_close = s["signal_close"]

        dloc = df1d_enr.index.searchsorted(sig_date)
        if dloc >= len(df1d_enr):
            continue
        if df1d_enr.index[dloc] < sig_date:
            dloc += 1
        if dloc >= len(df1d_enr):
            continue

        drow = df1d_enr.iloc[dloc]
        actual_date = df1d_enr.index[dloc]

        # OpEx offset in trading days
        opex_offset = days_to_opex(actual_date, trading_days)
        if opex_offset is None:
            continue

        # ATR positions
        wk_pos = None
        if pd.notna(drow.get("prev_wk_close")) and pd.notna(drow.get("wk_atr")) and drow["wk_atr"] > 0:
            wk_pos = (sig_close - drow["prev_wk_close"]) / drow["wk_atr"]
        mo_pos = None
        if pd.notna(drow.get("prev_month_close")) and pd.notna(drow.get("monthly_atr")) and drow["monthly_atr"] > 0:
            mo_pos = (sig_close - drow["prev_month_close"]) / drow["monthly_atr"]

        # Forward drops
        row = {
            "signal_date": actual_date,
            "peak_po": s["peak_po"],
            "opex_offset": opex_offset,  # 0=OpEx, -1=next trading day after OpEx, +1=day before
            "wk_atr_pos": wk_pos,
            "mo_atr_pos": mo_pos,
        }
        for h in [1, 3, 5, 10]:
            end = min(dloc + h + 1, len(df1d_enr))
            fut = df1d_enr.iloc[dloc + 1:end]
            if len(fut) == 0:
                row[f"max_drop_{h}d"] = None
                continue
            min_low = fut["low"].min()
            row[f"max_drop_{h}d"] = (min_low - sig_close) / sig_close * 100
            for thr, key in [(0.5, "05"), (1.0, "10"), (1.5, "15"), (2.0, "20")]:
                row[f"hit_{key}_{h}d"] = (fut["low"] <= sig_close * (1 - thr/100)).any()
        results.append(row)

    rdf = pd.DataFrame(results)
    print(f"Total V2 signals: {len(rdf)}")

    # ─── Extended condition filter ───
    # Extended = weekly OR monthly ATR pos >= 0.618
    rdf["extended"] = (
        (rdf["wk_atr_pos"] >= 0.618) | (rdf["mo_atr_pos"] >= 0.618)
    )
    rdf["deep_ext"] = (
        (rdf["wk_atr_pos"] >= 1.0) | (rdf["mo_atr_pos"] >= 1.0)
    )

    print(f"Extended (wk or mo ≥0.618): {rdf['extended'].sum()}")
    print(f"Deep extended (wk or mo ≥1.0): {rdf['deep_ext'].sum()}")

    def report(label, df_subset):
        print(f"\n{'═' * 80}")
        print(f"  {label}   (N total = {len(df_subset)})")
        print(f"{'═' * 80}")
        if len(df_subset) == 0:
            print("  (no events)")
            return

        # Bucket by OpEx offset
        # Positive offset = before OpEx, negative = after, 0 = OpEx day
        buckets = [
            ("OpEx Friday (day 0)", lambda d: d == 0),
            ("Post-OpEx day 1", lambda d: d == -1),
            ("Post-OpEx day 2", lambda d: d == -2),
            ("Post-OpEx day 3", lambda d: d == -3),
            ("Post-OpEx day 4", lambda d: d == -4),
            ("Post-OpEx day 5", lambda d: d == -5),
            ("Post-OpEx day 1-5 (combined)", lambda d: -5 <= d <= -1),
            ("OpEx Fri + Post-OpEx 1-5 (full window)", lambda d: -5 <= d <= 0),
            ("Other (not in OpEx window)", lambda d: d > 0 or d < -5),
        ]

        print(f"  {'Bucket':<42s} {'N':>4s} {'≥0.5%5d':>9s} {'≥1.0%5d':>9s} "
              f"{'≥1.5%5d':>9s} {'Med5d':>8s} {'Med10d':>8s}")
        for bname, bfn in buckets:
            bdf = df_subset[df_subset["opex_offset"].apply(bfn)]
            n = len(bdf)
            if n == 0:
                print(f"  {bname:<42s} {n:>4d}   (no events)")
                continue
            h05 = bdf["hit_05_5d"].mean() * 100 if n > 0 else 0
            h10 = bdf["hit_10_5d"].mean() * 100 if n > 0 else 0
            h15 = bdf["hit_15_5d"].mean() * 100 if n > 0 else 0
            med5 = bdf["max_drop_5d"].median()
            med10 = bdf["max_drop_10d"].median()
            print(f"  {bname:<42s} {n:>4d} {h05:>8.0f}% {h10:>8.0f}% {h15:>8.0f}% "
                  f"{med5:>7.2f}% {med10:>7.2f}%")

        # Horizon breakdown for the key window (OpEx Fri + post 1-5)
        key_window = df_subset[df_subset["opex_offset"].apply(lambda d: -5 <= d <= 0)]
        if len(key_window) >= 3:
            print(f"\n  ─── KEY WINDOW (OpEx Fri + Post 1-5d), forward horizons ───")
            print(f"  {'Horizon':<10s} {'N':>4s} {'≥0.5%':>7s} {'≥1.0%':>7s} "
                  f"{'≥1.5%':>7s} {'≥2.0%':>7s} {'Median':>8s} {'25th':>8s} {'Worst':>8s}")
            for h in [1, 3, 5, 10]:
                kw_h = key_window.dropna(subset=[f"max_drop_{h}d"])
                if len(kw_h) == 0:
                    continue
                n = len(kw_h)
                h05 = kw_h[f"hit_05_{h}d"].mean() * 100
                h10 = kw_h[f"hit_10_{h}d"].mean() * 100
                h15 = kw_h[f"hit_15_{h}d"].mean() * 100
                h20 = kw_h[f"hit_20_{h}d"].mean() * 100
                med = kw_h[f"max_drop_{h}d"].median()
                q25 = kw_h[f"max_drop_{h}d"].quantile(0.25)
                worst = kw_h[f"max_drop_{h}d"].min()
                print(f"  {str(h)+'d':<10s} {n:>4d} {h05:>6.0f}% {h10:>6.0f}% "
                      f"{h15:>6.0f}% {h20:>6.0f}% {med:>7.2f}% {q25:>7.2f}% {worst:>7.2f}%")

            # Event list for key window
            print(f"\n  ─── KEY WINDOW EVENT LIST ───")
            print(f"  {'Signal Date':<12s} {'OpEx Off':>9s} {'PkPO':>6s} "
                  f"{'WkATR':>7s} {'MoATR':>7s} {'Drop1d':>8s} {'Drop3d':>8s} "
                  f"{'Drop5d':>8s} {'Drop10d':>9s}")
            key_sorted = key_window.sort_values("signal_date")
            for _, r in key_sorted.iterrows():
                d = str(r["signal_date"])[:10]
                off = f"{int(r['opex_offset']):+d}"
                pk = f"{r['peak_po']:.0f}"
                wk = f"{r['wk_atr_pos']:.2f}" if pd.notna(r["wk_atr_pos"]) else "—"
                mo = f"{r['mo_atr_pos']:.2f}" if pd.notna(r["mo_atr_pos"]) else "—"
                d1 = f"{r['max_drop_1d']:.2f}" if pd.notna(r.get("max_drop_1d")) else "—"
                d3 = f"{r['max_drop_3d']:.2f}" if pd.notna(r.get("max_drop_3d")) else "—"
                d5 = f"{r['max_drop_5d']:.2f}" if pd.notna(r.get("max_drop_5d")) else "—"
                d10 = f"{r['max_drop_10d']:.2f}" if pd.notna(r.get("max_drop_10d")) else "—"
                print(f"  {d:<12s} {off:>9s} {pk:>6s} {wk:>7s} {mo:>7s} "
                      f"{d1:>8s} {d3:>8s} {d5:>8s} {d10:>9s}")

    # ─── Run all three: unfiltered, extended, deep extended ───
    report("ALL V2 SIGNALS (unfiltered baseline)", rdf)
    report("EXTENDED (weekly OR monthly ATR ≥ 0.618)", rdf[rdf["extended"]])
    report("DEEP EXTENDED (weekly OR monthly ATR ≥ 1.0)", rdf[rdf["deep_ext"]])

    # Save
    rdf.to_csv(os.path.join(BASE_DIR, "opex_extended_results.csv"), index=False)
    print("\nSaved to opex_extended_results.csv")


if __name__ == "__main__":
    main()
