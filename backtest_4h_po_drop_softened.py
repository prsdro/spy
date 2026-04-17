"""
Softened 4H PO Rollover → Drop Study

Looser signal definitions to build significant N for ATR stratification.

Signal variants tested:
  V1: Peak >= 61.8, cross below 61.8 (classic "leaving distribution")
  V2: Peak >= 80,   cross below 80   (moderate extension rollover)
  V3: Peak >= 100,  cross below 100  (original — for comparison)

Primary metric: did intraday low hit -1.0% within 5 days?
Stratification: weekly ATR position, monthly ATR position, combined
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def find_signals(df4h, peak_thr, cross_thr):
    po = df4h["phase_oscillator"]
    was_above = False
    peak = 0
    sigs = []
    for i in range(1, len(df4h)):
        cur = po.iloc[i]
        prev = po.iloc[i - 1]
        if prev >= peak_thr:
            if not was_above:
                was_above = True
                peak = prev
            elif prev > peak:
                peak = prev
        if was_above and prev >= cross_thr and cur < cross_thr:
            sigs.append({
                "signal_time": df4h.index[i],
                "peak_po": peak,
                "signal_po": cur,
                "signal_close_4h": df4h.iloc[i]["close"],
            })
            was_above = False
            peak = 0
    return sigs


def compute_monthly_ref(df_d, atr_period=14):
    m = df_d.resample("ME").agg({"high": "max", "low": "min", "close": "last"})
    m["pc"] = m["close"].shift(1)
    m["tr"] = m.apply(
        lambda r: max(r["high"] - r["low"],
                      abs(r["high"] - r["pc"]) if pd.notna(r["pc"]) else 0,
                      abs(r["low"] - r["pc"]) if pd.notna(r["pc"]) else 0),
        axis=1
    )
    m["atr"] = m["tr"].rolling(atr_period).mean()
    ref = pd.DataFrame({
        "prev_month_close": m["close"].shift(1),
        "monthly_atr": m["atr"].shift(1),
    })
    return ref.reindex(df_d.index, method="ffill")


def compute_weekly_ref(df_d, atr_period=14):
    wk_close = df_d["close"].resample("W-FRI").last()
    wk_high = df_d["high"].resample("W-FRI").max()
    wk_low = df_d["low"].resample("W-FRI").min()
    pc = wk_close.shift(1)
    tr_df = pd.DataFrame({"h": wk_high, "l": wk_low, "pc": pc})
    tr_df["tr"] = tr_df.apply(
        lambda r: max(r["h"] - r["l"],
                      abs(r["h"] - r["pc"]) if pd.notna(r["pc"]) else 0,
                      abs(r["l"] - r["pc"]) if pd.notna(r["pc"]) else 0),
        axis=1
    )
    atr = tr_df["tr"].rolling(atr_period).mean()
    ref = pd.DataFrame({
        "prev_wk_close": wk_close.shift(1),
        "wk_atr": atr.shift(1),
    })
    return ref


def build_results(signals, df1d_enriched):
    results = []
    for sig in signals:
        sig_time = sig["signal_time"]
        sig_date = sig_time.normalize()
        dloc = df1d_enriched.index.searchsorted(sig_date)
        if dloc >= len(df1d_enriched):
            continue
        if df1d_enriched.index[dloc] < sig_date:
            dloc += 1
        if dloc >= len(df1d_enriched):
            continue

        drow = df1d_enriched.iloc[dloc]
        sig_close = sig["signal_close_4h"]

        wk_pos = None
        if pd.notna(drow.get("prev_wk_close")) and pd.notna(drow.get("wk_atr")) and drow["wk_atr"] > 0:
            wk_pos = (sig_close - drow["prev_wk_close"]) / drow["wk_atr"]

        mo_pos = None
        if pd.notna(drow.get("prev_month_close")) and pd.notna(drow.get("monthly_atr")) and drow["monthly_atr"] > 0:
            mo_pos = (sig_close - drow["prev_month_close"]) / drow["monthly_atr"]

        row = {
            "signal_date": sig_date,
            "peak_po": sig["peak_po"],
            "sig_close": sig_close,
            "wk_atr_pos": wk_pos,
            "mo_atr_pos": mo_pos,
        }

        for horizon in [3, 5, 10]:
            end_idx = min(dloc + horizon + 1, len(df1d_enriched))
            future = df1d_enriched.iloc[dloc + 1:end_idx]
            if len(future) == 0:
                continue
            min_low = future["low"].min()
            row[f"max_drop_{horizon}d"] = (min_low - sig_close) / sig_close * 100
            for thresh in [0.5, 1.0, 2.0]:
                target = sig_close * (1 - thresh / 100)
                row[f"hit_{int(thresh*10):02d}_{horizon}d"] = (future["low"] <= target).any()

        results.append(row)
    return pd.DataFrame(results)


def report_stratification(rdf, label):
    print(f"\n{'=' * 90}")
    print(f"  {label}")
    print(f"{'=' * 90}")
    n_total = len(rdf)
    print(f"\n  N = {n_total}")
    print(f"\n  Baseline hit rates (intraday low reaches target within N days):")
    print(f"  {'Target':<15s} {'3d':>8s} {'5d':>8s} {'10d':>8s}")
    for thresh, col_suffix in [(0.5, "05"), (1.0, "10"), (2.0, "20")]:
        h3 = rdf[f"hit_{col_suffix}_3d"].sum()
        h5 = rdf[f"hit_{col_suffix}_5d"].sum()
        h10 = rdf[f"hit_{col_suffix}_10d"].sum()
        print(f"  {'≥' + str(thresh) + '%':<15s} "
              f"{h3/n_total*100:>7.0f}% {h5/n_total*100:>7.0f}% {h10/n_total*100:>7.0f}%")

    print(f"\n  Max drop distribution:")
    for h in [3, 5, 10]:
        v = rdf[f"max_drop_{h}d"].dropna()
        print(f"    {h}d: median {v.median():.2f}%, 25th {v.quantile(0.25):.2f}%, "
              f"worst {v.min():.2f}%")

    # Wider ATR buckets
    buckets = [
        ("Bearish (<-0.236)", -99, -0.236),
        ("Neutral (-0.236 to 0.382)", -0.236, 0.382),
        ("Bullish (0.382 to 1.0)", 0.382, 1.0),
        ("Extended (>= 1.0)", 1.0, 99),
    ]

    # Weekly ATR stratification
    wk_rdf = rdf.dropna(subset=["wk_atr_pos"])
    print(f"\n  ─ WEEKLY ATR POSITION → 1% drop in 5d ─")
    print(f"  {'Bucket':<28s} {'N':>4s} {'≥0.5%':>7s} {'≥1.0%':>7s} {'≥2.0%':>7s} {'Med5d':>8s}")
    for bl, lo, hi in buckets:
        s = wk_rdf[(wk_rdf["wk_atr_pos"] >= lo) & (wk_rdf["wk_atr_pos"] < hi)]
        n = len(s)
        if n < 3:
            continue
        h05 = s["hit_05_5d"].sum() / n * 100
        h10 = s["hit_10_5d"].sum() / n * 100
        h20 = s["hit_20_5d"].sum() / n * 100
        med = s["max_drop_5d"].median()
        print(f"  {bl:<28s} {n:>4d} {h05:>6.0f}% {h10:>6.0f}% {h20:>6.0f}% {med:>7.2f}%")

    # Monthly ATR stratification
    mo_rdf = rdf.dropna(subset=["mo_atr_pos"])
    print(f"\n  ─ MONTHLY ATR POSITION → 1% drop in 5d ─")
    print(f"  {'Bucket':<28s} {'N':>4s} {'≥0.5%':>7s} {'≥1.0%':>7s} {'≥2.0%':>7s} {'Med5d':>8s}")
    for bl, lo, hi in buckets:
        s = mo_rdf[(mo_rdf["mo_atr_pos"] >= lo) & (mo_rdf["mo_atr_pos"] < hi)]
        n = len(s)
        if n < 3:
            continue
        h05 = s["hit_05_5d"].sum() / n * 100
        h10 = s["hit_10_5d"].sum() / n * 100
        h20 = s["hit_20_5d"].sum() / n * 100
        med = s["max_drop_5d"].median()
        print(f"  {bl:<28s} {n:>4d} {h05:>6.0f}% {h10:>6.0f}% {h20:>6.0f}% {med:>7.2f}%")

    # Cross-tab: weekly × monthly
    print(f"\n  ─ CROSS-TAB: Weekly × Monthly (1% drop in 5d hit rate) ─")
    both = rdf.dropna(subset=["wk_atr_pos", "mo_atr_pos"])
    print(f"  {'Weekly \\ Monthly':<28s}", end="")
    for ml, _, _ in buckets:
        print(f"{ml:>24s}", end="")
    print()
    for wl, wlo, whi in buckets:
        print(f"  {wl:<28s}", end="")
        for ml, mlo, mhi in buckets:
            cell = both[(both["wk_atr_pos"] >= wlo) & (both["wk_atr_pos"] < whi) &
                        (both["mo_atr_pos"] >= mlo) & (both["mo_atr_pos"] < mhi)]
            n = len(cell)
            if n < 3:
                print(f"{'n=' + str(n):>24s}", end="")
            else:
                rate = cell["hit_10_5d"].sum() / n * 100
                med = cell["max_drop_5d"].median()
                print(f"{f'n={n}: {rate:.0f}% / {med:.1f}%':>24s}", end="")
        print()


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

    wk_ref = compute_weekly_ref(df1d)
    df1d_enriched = pd.merge_asof(
        df1d.reset_index().sort_values("timestamp"),
        wk_ref.reset_index().sort_values("timestamp"),
        on="timestamp", direction="backward"
    ).set_index("timestamp")
    mo_ref = compute_monthly_ref(df1d)
    df1d_enriched = df1d_enriched.join(mo_ref)

    variants = [
        ("V1: Peak ≥ 61.8, cross below 61.8 (leaving distribution zone)", 61.8, 61.8),
        ("V2: Peak ≥ 80, cross below 80 (moderate extension rollover)", 80, 80),
        ("V3: Peak ≥ 100, cross below 100 (strict — original)", 100, 100),
    ]

    for label, peak_thr, cross_thr in variants:
        sigs = find_signals(df4h, peak_thr, cross_thr)
        rdf = build_results(sigs, df1d_enriched)
        report_stratification(rdf, label + f"  —  {len(sigs)} signals")


if __name__ == "__main__":
    main()
