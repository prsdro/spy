"""
OpEx Friday Intraday Patterns — Extended Above Daily 21 EMA

Hypothesis: When SPY opens OpEx Friday (monthly options expiration, 3rd Friday)
extended above the daily 21 EMA, the intraday session exhibits characteristic pin
behavior: muted drawdowns, tight ranges, close-to-open.

Signal conditions:
- Date is the 3rd Friday of the calendar month
- 9:30 open is above the previous day's daily EMA21
- Extension tiers (open % above EMA21):
    Mild      1-2%
    Extended  2-4%
    Deeply    4%+

Forward measurement (RTH 9:30-16:00, same day only):
- Max high from open
- Max low from open (= intraday drawdown)
- Close vs open
- Intraday range (high-low)
- Time of day of intraday high and low

Comparisons:
- OpEx Friday by tier
- Non-OpEx Friday by tier (the pin effect isolated)
- All non-Friday days by tier
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def third_friday(year, month):
    d = pd.Timestamp(year=year, month=month, day=1)
    first_fri_offset = (4 - d.dayofweek) % 7
    return (d + pd.Timedelta(days=first_fri_offset + 14)).normalize()


def is_opex_friday(date):
    return date == third_friday(date.year, date.month)


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading daily data...")
    df1d = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_21, phase_oscillator "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp").sort_index()

    print("Loading 10m RTH data...")
    df10 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close FROM candles_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")
    df10 = df10.between_time("09:30", "15:59")
    df10["date"] = df10.index.normalize()

    conn.close()

    # Build per-day records with extension + intraday stats
    print("Building per-day records...")
    records = []
    prev_ema21 = None
    prev_close = None

    # Group 10m bars by date for fast lookup
    groups = {d: g for d, g in df10.groupby("date")}

    for i, (date, drow) in enumerate(df1d.iterrows()):
        if pd.isna(drow.get("ema_21")) or prev_ema21 is None:
            prev_ema21 = drow.get("ema_21")
            prev_close = drow.get("close")
            continue

        # Extension measured at 9:30 open vs prior day's EMA21
        open_px = drow["open"]
        if pd.isna(open_px) or pd.isna(prev_ema21) or prev_ema21 <= 0:
            prev_ema21 = drow.get("ema_21")
            prev_close = drow.get("close")
            continue

        ext_pct = (open_px - prev_ema21) / prev_ema21 * 100

        # Only consider days above EMA21 (bullish extension)
        if ext_pct <= 0:
            prev_ema21 = drow.get("ema_21")
            prev_close = drow.get("close")
            continue

        # Intraday stats from 10m RTH bars
        g = groups.get(date)
        if g is None or len(g) < 10:
            prev_ema21 = drow.get("ema_21")
            prev_close = drow.get("close")
            continue

        # The 9:30 bar open is the "session open" we measure from
        session_open = g["open"].iloc[0]
        session_high = g["high"].max()
        session_low = g["low"].min()
        session_close = g["close"].iloc[-1]
        high_time = g["high"].idxmax()
        low_time = g["low"].idxmin()

        max_high_pct = (session_high - session_open) / session_open * 100
        max_low_pct = (session_low - session_open) / session_open * 100  # negative
        close_vs_open_pct = (session_close - session_open) / session_open * 100
        range_pct = (session_high - session_low) / session_open * 100

        is_friday = date.dayofweek == 4
        opex = is_opex_friday(date)

        records.append({
            "date": date,
            "dow": date.dayofweek,
            "is_friday": is_friday,
            "is_opex_friday": opex,
            "ext_pct": ext_pct,
            "session_open": session_open,
            "session_close": session_close,
            "max_high_pct": max_high_pct,
            "max_low_pct": max_low_pct,
            "close_vs_open_pct": close_vs_open_pct,
            "range_pct": range_pct,
            "high_time": high_time.time().strftime("%H:%M"),
            "low_time": low_time.time().strftime("%H:%M"),
            "high_hour": high_time.hour,
            "low_hour": low_time.hour,
        })

        prev_ema21 = drow.get("ema_21")
        prev_close = drow.get("close")

    rdf = pd.DataFrame(records)
    print(f"\nTotal bullish-extension days (open above prev d21 EMA): {len(rdf)}")
    print(f"OpEx Fridays: {rdf['is_opex_friday'].sum()}")
    print(f"Non-OpEx Fridays: {((rdf['is_friday']) & (~rdf['is_opex_friday'])).sum()}")
    print(f"Non-Friday days: {(~rdf['is_friday']).sum()}")

    # ─── Tier definitions ───
    tiers = [
        ("Mild (1-2%)", 1.0, 2.0),
        ("Extended (2-4%)", 2.0, 4.0),
        ("Deeply Ext (4%+)", 4.0, 999),
    ]

    def stats(group, label):
        n = len(group)
        if n == 0:
            return None
        return {
            "label": label,
            "n": n,
            "median_max_high": group["max_high_pct"].median(),
            "median_max_low": group["max_low_pct"].median(),
            "median_close_vs_open": group["close_vs_open_pct"].median(),
            "median_range": group["range_pct"].median(),
            "pct_close_up": (group["close_vs_open_pct"] > 0).mean() * 100,
            "pct_close_flat": (group["close_vs_open_pct"].abs() < 0.25).mean() * 100,
            "pct_range_under_0_5": (group["range_pct"] < 0.5).mean() * 100,
            "pct_range_under_1_0": (group["range_pct"] < 1.0).mean() * 100,
            "pct_dd_under_0_25": (group["max_low_pct"] > -0.25).mean() * 100,
            "pct_dd_under_0_5": (group["max_low_pct"] > -0.5).mean() * 100,
            "pct_dd_over_1": (group["max_low_pct"] < -1.0).mean() * 100,
            "worst_dd": group["max_low_pct"].min(),
            "best_high": group["max_high_pct"].max(),
        }

    def print_stats_table(rows):
        if not rows or all(r is None for r in rows):
            print("  (no data)")
            return
        print(f"  {'Group':<30s} {'N':>4s} {'MedDD':>7s} {'MedHi':>7s} {'MedC/O':>7s} "
              f"{'MedRng':>7s} {'Up%':>5s} {'Flat%':>6s} {'Rng<0.5':>8s} {'DD<0.25':>8s} "
              f"{'DD>1%':>6s}")
        for r in rows:
            if r is None:
                continue
            print(f"  {r['label']:<30s} {r['n']:>4d} "
                  f"{r['median_max_low']:>6.2f}% {r['median_max_high']:>6.2f}% "
                  f"{r['median_close_vs_open']:>6.2f}% {r['median_range']:>6.2f}% "
                  f"{r['pct_close_up']:>4.0f}% {r['pct_close_flat']:>5.0f}% "
                  f"{r['pct_range_under_0_5']:>7.0f}% {r['pct_dd_under_0_25']:>7.0f}% "
                  f"{r['pct_dd_over_1']:>5.0f}%")

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  OpEx FRIDAY INTRADAY STATS BY EXTENSION TIER")
    print("=" * 100)
    print(f"\n  Legend: MedDD=median max intraday drawdown, MedHi=median max rally, "
          f"MedC/O=median close-vs-open, MedRng=median range")
    print(f"          Up%=% closed above open, Flat%=% closed within ±0.25% of open, "
          f"Rng<0.5%=% days with range <0.5%")
    print(f"          DD<0.25%=% days with drawdown shallower than 0.25%, "
          f"DD>1%=% days with drawdown >1%\n")

    rows = []
    for tier, lo, hi in tiers:
        subset = rdf[rdf["is_opex_friday"] & (rdf["ext_pct"] >= lo) & (rdf["ext_pct"] < hi)]
        rows.append(stats(subset, tier))
    # Combined
    all_ext = rdf[rdf["is_opex_friday"] & (rdf["ext_pct"] >= 1.0)]
    rows.append(stats(all_ext, "ALL OpEx Fri (ext >=1%)"))
    print_stats_table(rows)

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  NON-OpEx FRIDAYS (BASELINE — same extension tiers)")
    print("=" * 100 + "\n")

    rows = []
    for tier, lo, hi in tiers:
        subset = rdf[(rdf["is_friday"]) & (~rdf["is_opex_friday"]) &
                     (rdf["ext_pct"] >= lo) & (rdf["ext_pct"] < hi)]
        rows.append(stats(subset, tier))
    all_ext = rdf[(rdf["is_friday"]) & (~rdf["is_opex_friday"]) & (rdf["ext_pct"] >= 1.0)]
    rows.append(stats(all_ext, "ALL Non-OpEx Fri (ext >=1%)"))
    print_stats_table(rows)

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  NON-FRIDAY DAYS (BASELINE — same extension tiers)")
    print("=" * 100 + "\n")

    rows = []
    for tier, lo, hi in tiers:
        subset = rdf[(~rdf["is_friday"]) & (rdf["ext_pct"] >= lo) & (rdf["ext_pct"] < hi)]
        rows.append(stats(subset, tier))
    all_ext = rdf[(~rdf["is_friday"]) & (rdf["ext_pct"] >= 1.0)]
    rows.append(stats(all_ext, "ALL Non-Fri (ext >=1%)"))
    print_stats_table(rows)

    # ═══════════════════════════════════════════════════════════════
    # Head-to-head at each tier: OpEx Fri vs Non-OpEx Fri vs Non-Friday
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  HEAD-TO-HEAD: Pin behavior comparison within each extension tier")
    print("=" * 100 + "\n")

    for tier, lo, hi in tiers:
        print(f"─ {tier} ─")
        rows = []
        rows.append(stats(rdf[rdf["is_opex_friday"] & (rdf["ext_pct"] >= lo) & (rdf["ext_pct"] < hi)],
                          "OpEx Friday"))
        rows.append(stats(rdf[rdf["is_friday"] & ~rdf["is_opex_friday"] &
                              (rdf["ext_pct"] >= lo) & (rdf["ext_pct"] < hi)],
                          "Non-OpEx Friday"))
        rows.append(stats(rdf[~rdf["is_friday"] & (rdf["ext_pct"] >= lo) & (rdf["ext_pct"] < hi)],
                          "Non-Friday"))
        print_stats_table(rows)
        print()

    # ═══════════════════════════════════════════════════════════════
    # Time-of-day distribution for intraday highs and lows (OpEx Fri only, ext >=1%)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  OpEx FRIDAY (ext >=1%) — TIME-OF-DAY DISTRIBUTION OF HIGH & LOW")
    print("=" * 100)
    opex_ext = rdf[rdf["is_opex_friday"] & (rdf["ext_pct"] >= 1.0)]
    n = len(opex_ext)
    print(f"\n  N = {n}\n")
    print(f"  {'Hour':<8s} {'Hi Count':>10s} {'Hi %':>6s} {'Lo Count':>10s} {'Lo %':>6s}")
    for h in range(9, 16):
        hi_c = (opex_ext["high_hour"] == h).sum()
        lo_c = (opex_ext["low_hour"] == h).sum()
        print(f"  {str(h)+':00':<8s} {hi_c:>10d} {hi_c/n*100:>5.0f}% {lo_c:>10d} {lo_c/n*100:>5.0f}%")

    # ═══════════════════════════════════════════════════════════════
    # Full event list for OpEx Fri extended days
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  OpEx FRIDAY EVENT LIST (ext >= 1% above d21 EMA)")
    print("=" * 100 + "\n")

    opex_ext_sorted = opex_ext.sort_values("date")
    print(f"  {'Date':<12s} {'Ext%':>6s} {'MaxHi':>7s} {'MaxLo':>7s} {'C/O':>7s} "
          f"{'Range':>7s} {'HiTime':>7s} {'LoTime':>7s}")
    for _, r in opex_ext_sorted.iterrows():
        d = str(r["date"])[:10]
        ext = f"{r['ext_pct']:.2f}"
        mh = f"{r['max_high_pct']:+.2f}"
        ml = f"{r['max_low_pct']:+.2f}"
        co = f"{r['close_vs_open_pct']:+.2f}"
        rng = f"{r['range_pct']:.2f}"
        print(f"  {d:<12s} {ext:>6s} {mh:>7s} {ml:>7s} {co:>7s} {rng:>7s} "
              f"{r['high_time']:>7s} {r['low_time']:>7s}")

    # ═══════════════════════════════════════════════════════════════
    # Deep extension subset (4%+)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  DEEP EXTENSION (ext >= 4%) — OpEx Fri events")
    print("=" * 100 + "\n")
    deep = rdf[rdf["is_opex_friday"] & (rdf["ext_pct"] >= 4.0)].sort_values("date")
    if len(deep) > 0:
        print(f"  {'Date':<12s} {'Ext%':>6s} {'MaxHi':>7s} {'MaxLo':>7s} {'C/O':>7s} {'Range':>7s}")
        for _, r in deep.iterrows():
            d = str(r["date"])[:10]
            ext = f"{r['ext_pct']:.2f}"
            mh = f"{r['max_high_pct']:+.2f}"
            ml = f"{r['max_low_pct']:+.2f}"
            co = f"{r['close_vs_open_pct']:+.2f}"
            rng = f"{r['range_pct']:.2f}"
            print(f"  {d:<12s} {ext:>6s} {mh:>7s} {ml:>7s} {co:>7s} {rng:>7s}")
    else:
        print("  (no events)")

    rdf.to_csv(os.path.join(BASE_DIR, "opex_friday_extended_results.csv"), index=False)
    print(f"\nSaved full results to opex_friday_extended_results.csv")


if __name__ == "__main__":
    main()
