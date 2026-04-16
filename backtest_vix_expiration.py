"""
VIX Expiration Day Pattern Study

VIX expiration = the Wednesday that is 30 calendar days before the 3rd Friday
of the following month. If that Wednesday is a market holiday, it shifts to
the preceding Tuesday (standard CBOE convention).

This study analyzes SPY behavior on VIX expiration days vs normal days across
all Saty indicators: ATR levels, Pivot Ribbon, and Phase Oscillator.
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import date, timedelta
from collections import defaultdict

DB_PATH = "/root/spy/spy.db"

# ─────────────────────────────────────────────────────────────
# 1. Compute VIX Expiration Dates
# ─────────────────────────────────────────────────────────────

def third_friday(year, month):
    """Return the 3rd Friday of the given month/year."""
    # First day of month
    d = date(year, month, 1)
    # Find first Friday: weekday 4 = Friday
    days_until_friday = (4 - d.weekday()) % 7
    first_friday = d + timedelta(days=days_until_friday)
    # Third Friday = first + 14
    return first_friday + timedelta(days=14)


def compute_vix_expiration_dates(start_year=2004, end_year=2025):
    """
    Compute VIX expiration dates.
    VIX expiration = 30 calendar days before the 3rd Friday of the FOLLOWING month.
    If it falls on a weekend or holiday, use the preceding business day.
    """
    dates_list = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # "Following month" means: for a Jan VIX expiration cycle,
            # we look at the 3rd Friday of February
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month = 1
                next_year = year + 1

            fri3 = third_friday(next_year, next_month)
            vix_exp = fri3 - timedelta(days=30)

            # VIX expiration should land on a Wednesday (weekday 2)
            # If not (due to calendar math), adjust to nearest Wednesday
            # In practice, 30 days before a Friday = a Monday most of the time
            # Actually, let me reconsider: the rule is more nuanced.
            # The CBOE rule: VIX settlement is on the Wednesday that is 30 days
            # before the S&P 500 options expiration (3rd Friday).
            # 30 days before Friday = the Wednesday 30 days prior
            # Friday - 30 days:
            #   If Friday is day X, then X-30... let's compute day of week.
            #   Friday=4. 30 mod 7 = 2. So 4-2=2 = Wednesday.
            # So 30 days before any Friday IS always a Wednesday!

            # But if that Wednesday is a holiday, CBOE moves to Tuesday before
            # We don't have a full holiday calendar, but we can check if the
            # date exists in our trading data

            dates_list.append(vix_exp)

    return dates_list


# Known US market holidays that fall on Wednesdays (for adjustment)
# We'll also validate against actual trading days in our database
def get_vix_expiration_trading_days(conn, start_year=2004, end_year=2025):
    """Get VIX expiration dates, adjusted to actual trading days."""
    raw_dates = compute_vix_expiration_dates(start_year, end_year)

    # Get all trading days from our database
    trading_days = pd.read_sql_query(
        "SELECT DISTINCT date(timestamp) as trade_date FROM candles_1d ORDER BY trade_date",
        conn
    )
    trading_days_set = set(trading_days["trade_date"].values)

    adjusted = []
    for d in raw_dates:
        d_str = d.isoformat()
        if d_str in trading_days_set:
            adjusted.append(d)
        else:
            # Try Tuesday before (holiday adjustment)
            tuesday = d - timedelta(days=1)
            t_str = tuesday.isoformat()
            if t_str in trading_days_set:
                adjusted.append(tuesday)
            else:
                # Skip — likely before our data range or other issue
                pass

    return adjusted


# ─────────────────────────────────────────────────────────────
# 2. Analysis Functions
# ─────────────────────────────────────────────────────────────

def analyze_daily_patterns(conn, vix_dates):
    """Compare daily bar characteristics: VIX expiration vs normal days."""
    print("=" * 70)
    print("SECTION 1: DAILY BAR CHARACTERISTICS")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date

    vix_set = set(vix_dates)
    df["is_vix_exp"] = df["date"].apply(lambda d: d in vix_set)

    # Compute daily metrics
    df["daily_return"] = (df["close"] - df["open"]) / df["open"] * 100
    df["daily_range"] = (df["high"] - df["low"]) / df["open"] * 100
    df["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["open"] * 100
    df["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["open"] * 100
    df["body_size"] = abs(df["daily_return"])
    df["is_green"] = (df["close"] > df["open"]).astype(int)
    df["close_vs_prev"] = df["close"].pct_change() * 100

    # ATR-normalized range
    df["range_vs_atr"] = np.where(df["atr_14"] > 0,
                                   (df["high"] - df["low"]) / df["atr_14"] * 100, np.nan)

    vix = df[df["is_vix_exp"]]
    normal = df[~df["is_vix_exp"]]

    print(f"\nVIX expiration days: {len(vix)}")
    print(f"Normal days: {len(normal)}")

    metrics = [
        ("Open-to-Close Return (%)", "daily_return"),
        ("Abs Return (%)", "body_size"),
        ("Daily Range (%)", "daily_range"),
        ("Range as % of ATR", "range_vs_atr"),
        ("Upper Wick (%)", "upper_wick"),
        ("Lower Wick (%)", "lower_wick"),
        ("Close vs Prev Close (%)", "close_vs_prev"),
    ]

    print(f"\n{'Metric':<30s} {'VIX Exp':>12s} {'Normal':>12s} {'Diff':>10s}")
    print("-" * 70)
    for label, col in metrics:
        v_mean = vix[col].mean()
        n_mean = normal[col].mean()
        diff = v_mean - n_mean
        print(f"  {label:<28s} {v_mean:11.3f}% {n_mean:11.3f}% {diff:+9.3f}%")

    # Green candle %
    v_green = vix["is_green"].mean() * 100
    n_green = normal["is_green"].mean() * 100
    print(f"  {'Green Candle %':<28s} {v_green:11.1f}% {n_green:11.1f}% {v_green - n_green:+9.1f}%")

    # Median absolute return
    v_med = vix["body_size"].median()
    n_med = normal["body_size"].median()
    print(f"  {'Median Abs Return (%)':<28s} {v_med:11.3f}% {n_med:11.3f}% {v_med - n_med:+9.3f}%")

    # Volume comparison
    if "volume" in df.columns:
        v_vol = vix["volume"].mean()
        n_vol = normal["volume"].mean()
        print(f"  {'Avg Volume':<28s} {v_vol:11.0f}  {n_vol:11.0f}  {(v_vol/n_vol - 1)*100:+8.1f}%")

    return df


def analyze_atr_levels(conn, vix_dates):
    """Compare ATR level hit rates on VIX expiration days vs normal days."""
    print("\n" + "=" * 70)
    print("SECTION 2: ATR LEVEL COMPLETION RATES")
    print("=" * 70)

    df = pd.read_sql_query(
        "SELECT * FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date

    vix_set = set(vix_dates)

    levels = [
        ("trigger", "atr_upper_trigger", "atr_lower_trigger", "±23.6% Trigger"),
        ("0382", "atr_upper_0382", "atr_lower_0382", "±38.2% Golden Gate"),
        ("0618", "atr_upper_0618", "atr_lower_0618", "±61.8% Midrange"),
        ("0786", "atr_upper_0786", "atr_lower_0786", "±78.6%"),
        ("100", "atr_upper_100", "atr_lower_100", "±100% Full ATR"),
    ]

    results = {"vix": defaultdict(int), "normal": defaultdict(int)}
    results["vix"]["total"] = 0
    results["normal"]["total"] = 0

    # Conditional level-to-level
    cond_results = {"vix": defaultdict(lambda: [0, 0]), "normal": defaultdict(lambda: [0, 0])}

    for dt, group in df.groupby("date"):
        day_high = group["high"].max()
        day_low = group["low"].min()
        first = group.iloc[0]
        if pd.isna(first["prev_close"]):
            continue

        category = "vix" if dt in vix_set else "normal"
        results[category]["total"] += 1

        hit_up = {}
        hit_dn = {}
        for key, up_col, dn_col, _ in levels:
            hit_up[key] = day_high >= first[up_col]
            hit_dn[key] = day_low <= first[dn_col]
            if hit_up[key] or hit_dn[key]:
                results[category][f"{key}_either"] += 1
            if hit_up[key]:
                results[category][f"{key}_up"] += 1
            if hit_dn[key]:
                results[category][f"{key}_dn"] += 1

        # Conditional: trigger -> 0382
        for direction, hits in [("up", hit_up), ("dn", hit_dn)]:
            if hits["trigger"]:
                cond_results[category][f"trigger_to_0382_{direction}"][0] += 1
                if hits["0382"]:
                    cond_results[category][f"trigger_to_0382_{direction}"][1] += 1
            if hits["0382"]:
                cond_results[category][f"0382_to_0618_{direction}"][0] += 1
                if hits["0618"]:
                    cond_results[category][f"0382_to_0618_{direction}"][1] += 1

    # Print absolute hit rates
    print(f"\n{'Level':<25s} {'VIX Exp':>10s} {'Normal':>10s} {'Diff':>10s}  {'VIX n':>6s} {'Norm n':>7s}")
    print("-" * 70)
    for key, _, _, label in levels:
        vn = results["vix"]["total"]
        nn = results["normal"]["total"]
        v_pct = results["vix"].get(f"{key}_either", 0) / vn * 100 if vn else 0
        n_pct = results["normal"].get(f"{key}_either", 0) / nn * 100 if nn else 0
        v_count = results["vix"].get(f"{key}_either", 0)
        n_count = results["normal"].get(f"{key}_either", 0)
        print(f"  {label:<23s} {v_pct:9.1f}% {n_pct:9.1f}% {v_pct - n_pct:+9.1f}%  {v_count:6d} {n_count:7d}")

    # Directional breakdown
    print(f"\n  {'--- Directional ---'}")
    print(f"  {'Level':<23s} {'VIX Up%':>8s} {'VIX Dn%':>8s} {'Norm Up%':>9s} {'Norm Dn%':>9s}")
    print("  " + "-" * 60)
    for key, _, _, label in levels:
        vn = results["vix"]["total"]
        nn = results["normal"]["total"]
        vu = results["vix"].get(f"{key}_up", 0) / vn * 100 if vn else 0
        vd = results["vix"].get(f"{key}_dn", 0) / vn * 100 if vn else 0
        nu = results["normal"].get(f"{key}_up", 0) / nn * 100 if nn else 0
        nd = results["normal"].get(f"{key}_dn", 0) / nn * 100 if nn else 0
        print(f"  {label:<23s} {vu:7.1f}% {vd:7.1f}% {nu:8.1f}% {nd:8.1f}%")

    # Conditional level-to-level
    print(f"\n  {'--- Conditional (level-to-level) ---'}")
    print(f"  {'Transition':<30s} {'VIX Exp':>10s} {'Normal':>10s} {'Diff':>10s}")
    print("  " + "-" * 62)
    for trans_label, key_prefix in [
        ("Trigger → 38.2% (up)", "trigger_to_0382_up"),
        ("Trigger → 38.2% (down)", "trigger_to_0382_dn"),
        ("38.2% → 61.8% (up)", "0382_to_0618_up"),
        ("38.2% → 61.8% (down)", "0382_to_0618_dn"),
    ]:
        vb, vh = cond_results["vix"][key_prefix]
        nb, nh = cond_results["normal"][key_prefix]
        v_pct = vh / vb * 100 if vb > 0 else 0
        n_pct = nh / nb * 100 if nb > 0 else 0
        print(f"  {trans_label:<28s} {v_pct:9.1f}% {n_pct:9.1f}% {v_pct - n_pct:+9.1f}%"
              f"   (n={vb}/{nb})")


def analyze_phase_oscillator(conn, vix_dates):
    """Analyze Phase Oscillator readings on VIX expiration days."""
    print("\n" + "=" * 70)
    print("SECTION 3: PHASE OSCILLATOR ANALYSIS (Daily)")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date

    vix_set = set(vix_dates)
    df["is_vix_exp"] = df["date"].apply(lambda d: d in vix_set)

    vix = df[df["is_vix_exp"]]
    normal = df[~df["is_vix_exp"]]

    # PO zone distribution
    print(f"\n  Phase Oscillator Zone Distribution:")
    print(f"  {'Zone':<20s} {'VIX Exp %':>12s} {'Normal %':>12s} {'Diff':>10s}")
    print("  " + "-" * 56)
    zones = ["extended_up", "distribution", "neutral_up", "neutral",
             "neutral_down", "accumulation", "extended_down"]
    for zone in zones:
        v_pct = (vix["phase_zone"] == zone).sum() / len(vix) * 100 if len(vix) else 0
        n_pct = (normal["phase_zone"] == zone).sum() / len(normal) * 100 if len(normal) else 0
        print(f"  {zone:<20s} {v_pct:11.1f}% {n_pct:11.1f}% {v_pct - n_pct:+9.1f}%")

    # Average PO value
    v_po = vix["phase_oscillator"].mean()
    n_po = normal["phase_oscillator"].mean()
    print(f"\n  Mean Phase Oscillator:  VIX={v_po:.2f}  Normal={n_po:.2f}  Diff={v_po - n_po:+.2f}")

    v_po_med = vix["phase_oscillator"].median()
    n_po_med = normal["phase_oscillator"].median()
    print(f"  Median Phase Oscillator: VIX={v_po_med:.2f}  Normal={n_po_med:.2f}  Diff={v_po_med - n_po_med:+.2f}")

    # Compression frequency
    v_comp = vix["compression"].mean() * 100 if "compression" in vix.columns else 0
    n_comp = normal["compression"].mean() * 100 if "compression" in normal.columns else 0
    print(f"\n  Compression active:  VIX={v_comp:.1f}%  Normal={n_comp:.1f}%  Diff={v_comp - n_comp:+.1f}%")


def analyze_pivot_ribbon(conn, vix_dates):
    """Analyze Pivot Ribbon state on VIX expiration days."""
    print("\n" + "=" * 70)
    print("SECTION 4: PIVOT RIBBON STATE")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date

    vix_set = set(vix_dates)
    df["is_vix_exp"] = df["date"].apply(lambda d: d in vix_set)

    vix = df[df["is_vix_exp"]]
    normal = df[~df["is_vix_exp"]]

    # Candle bias distribution
    print(f"\n  Candle Bias Distribution:")
    bias_labels = {1: "Bull Up (green)", 2: "Bear Up (orange)", 3: "Bull Down (blue)",
                   4: "Bear Down (red)", 5: "Compress Up", 6: "Compress Down"}
    print(f"  {'Candle Bias':<25s} {'VIX Exp %':>12s} {'Normal %':>12s} {'Diff':>10s}")
    print("  " + "-" * 60)
    for val, label in bias_labels.items():
        v_pct = (vix["candle_bias"] == val).sum() / len(vix) * 100 if len(vix) else 0
        n_pct = (normal["candle_bias"] == val).sum() / len(normal) * 100 if len(normal) else 0
        print(f"  {label:<25s} {v_pct:11.1f}% {n_pct:11.1f}% {v_pct - n_pct:+9.1f}%")

    # Fast/slow cloud state
    for col, label in [("fast_cloud_bullish", "Fast Cloud Bullish"),
                        ("slow_cloud_bullish", "Slow Cloud Bullish"),
                        ("longterm_bias_bullish", "Long-term Bias Bullish (EMA21>200)")]:
        v_pct = vix[col].mean() * 100 if len(vix) else 0
        n_pct = normal[col].mean() * 100 if len(normal) else 0
        print(f"\n  {label}: VIX={v_pct:.1f}%  Normal={n_pct:.1f}%  Diff={v_pct - n_pct:+.1f}%")

    # Conviction signals on VIX exp days
    v_bull_conv = vix["conviction_bull"].sum()
    v_bear_conv = vix["conviction_bear"].sum()
    n_bull_conv = normal["conviction_bull"].sum() / len(normal) * len(vix)  # normalized
    n_bear_conv = normal["conviction_bear"].sum() / len(normal) * len(vix)
    print(f"\n  Conviction arrows on VIX exp days: Bull={v_bull_conv:.0f} Bear={v_bear_conv:.0f}"
          f" (expected: Bull={n_bull_conv:.1f} Bear={n_bear_conv:.1f})")


def analyze_intraday_behavior(conn, vix_dates):
    """Analyze intraday behavior: when do moves happen, reversal patterns, etc."""
    print("\n" + "=" * 70)
    print("SECTION 5: INTRADAY BEHAVIOR (10m bars)")
    print("=" * 70)

    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume, prev_close, atr_14 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date
    df["hour"] = df.index.hour

    vix_set = set(vix_dates)

    # Compute hourly returns and reversal metrics by day
    vix_hourly = defaultdict(list)
    norm_hourly = defaultdict(list)
    vix_reversals = []
    norm_reversals = []

    for dt, group in df.groupby("date"):
        is_vix = dt in vix_set
        pc = group.iloc[0]["prev_close"]
        if pd.isna(pc) or pc == 0:
            continue

        # Track cumulative return through the day
        first_half_high = group[group.index.hour < 12]["high"].max() if len(group[group.index.hour < 12]) > 0 else np.nan
        first_half_low = group[group.index.hour < 12]["low"].min() if len(group[group.index.hour < 12]) > 0 else np.nan
        second_half_high = group[group.index.hour >= 12]["high"].max() if len(group[group.index.hour >= 12]) > 0 else np.nan
        second_half_low = group[group.index.hour >= 12]["low"].min() if len(group[group.index.hour >= 12]) > 0 else np.nan

        day_open = group.iloc[0]["open"]
        day_close = group.iloc[-1]["close"]
        day_high = group["high"].max()
        day_low = group["low"].min()

        # Reversal: did the day reverse from first half direction?
        first_half_return = (group[group.index.hour < 12].iloc[-1]["close"] - day_open) / day_open * 100 if len(group[group.index.hour < 12]) > 0 else 0
        full_day_return = (day_close - day_open) / day_open * 100

        reversed_direction = (first_half_return > 0.1 and full_day_return < -0.1) or \
                              (first_half_return < -0.1 and full_day_return > 0.1)

        if is_vix:
            vix_reversals.append(reversed_direction)
        else:
            norm_reversals.append(reversed_direction)

        # Hourly contribution to range
        for hour in range(9, 16):
            hour_bars = group[group["hour"] == hour]
            if len(hour_bars) == 0:
                continue
            hour_range = (hour_bars["high"].max() - hour_bars["low"].min()) / pc * 100
            hour_return = (hour_bars.iloc[-1]["close"] - hour_bars.iloc[0]["open"]) / pc * 100
            if is_vix:
                vix_hourly[hour].append((hour_range, hour_return))
            else:
                norm_hourly[hour].append((hour_range, hour_return))

    # Print hourly breakdown
    print(f"\n  Hourly Range (% of price):")
    print(f"  {'Hour':<8s} {'VIX Range':>12s} {'Norm Range':>12s} {'Diff':>10s}  {'VIX Ret':>10s} {'Norm Ret':>10s}")
    print("  " + "-" * 60)
    for hour in range(9, 16):
        if hour in vix_hourly and hour in norm_hourly:
            vr = np.mean([x[0] for x in vix_hourly[hour]])
            nr = np.mean([x[0] for x in norm_hourly[hour]])
            v_ret = np.mean([x[1] for x in vix_hourly[hour]])
            n_ret = np.mean([x[1] for x in norm_hourly[hour]])
            print(f"  {hour:02d}:00   {vr:11.4f}% {nr:11.4f}% {vr - nr:+9.4f}%"
                  f"  {v_ret:+9.4f}% {n_ret:+9.4f}%")

    # Reversal rate
    v_rev = np.mean(vix_reversals) * 100 if vix_reversals else 0
    n_rev = np.mean(norm_reversals) * 100 if norm_reversals else 0
    print(f"\n  Intraday Reversal Rate (AM direction flips by close):")
    print(f"    VIX exp: {v_rev:.1f}%  Normal: {n_rev:.1f}%  Diff: {v_rev - n_rev:+.1f}%")


def analyze_gap_behavior(conn, vix_dates):
    """Analyze gap behavior on VIX expiration days."""
    print("\n" + "=" * 70)
    print("SECTION 6: GAP BEHAVIOR")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date

    vix_set = set(vix_dates)
    df["is_vix_exp"] = df["date"].apply(lambda d: d in vix_set)
    df["gap_pct"] = (df["open"] - df["prev_close"]) / df["prev_close"] * 100
    df["gap_abs"] = df["gap_pct"].abs()

    vix = df[df["is_vix_exp"]].dropna(subset=["gap_pct"])
    normal = df[~df["is_vix_exp"]].dropna(subset=["gap_pct"])

    print(f"\n  {'Metric':<30s} {'VIX Exp':>12s} {'Normal':>12s}")
    print("  " + "-" * 56)
    print(f"  {'Mean Gap %':<30s} {vix['gap_pct'].mean():+11.3f}% {normal['gap_pct'].mean():+11.3f}%")
    print(f"  {'Mean |Gap| %':<30s} {vix['gap_abs'].mean():11.3f}% {normal['gap_abs'].mean():11.3f}%")
    print(f"  {'Median |Gap| %':<30s} {vix['gap_abs'].median():11.3f}% {normal['gap_abs'].median():11.3f}%")
    print(f"  {'Gap Up %':<30s} {(vix['gap_pct'] > 0).mean()*100:11.1f}% {(normal['gap_pct'] > 0).mean()*100:11.1f}%")
    print(f"  {'Gap > 0.5% (big gap up)':<30s} {(vix['gap_pct'] > 0.5).mean()*100:11.1f}% {(normal['gap_pct'] > 0.5).mean()*100:11.1f}%")
    print(f"  {'Gap < -0.5% (big gap down)':<30s} {(vix['gap_pct'] < -0.5).mean()*100:11.1f}% {(normal['gap_pct'] < -0.5).mean()*100:11.1f}%")


def analyze_next_day(conn, vix_dates):
    """Analyze the day AFTER VIX expiration (Thursday) for follow-through."""
    print("\n" + "=" * 70)
    print("SECTION 7: NEXT-DAY FOLLOW-THROUGH (Day After VIX Exp)")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date
    df["daily_return"] = (df["close"] - df["open"]) / df["open"] * 100
    df["close_vs_prev"] = df["close"].pct_change() * 100

    vix_set = set(vix_dates)

    # Find the trading day after each VIX expiration
    all_dates = sorted(df["date"].unique())
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    next_day_returns = []
    vix_day_direction = []

    for vd in vix_dates:
        if vd not in date_to_idx:
            continue
        idx = date_to_idx[vd]
        if idx + 1 >= len(all_dates):
            continue
        next_date = all_dates[idx + 1]

        vix_row = df[df["date"] == vd]
        next_row = df[df["date"] == next_date]
        if len(vix_row) == 0 or len(next_row) == 0:
            continue

        vix_ret = vix_row.iloc[0]["daily_return"]
        next_ret = next_row.iloc[0]["daily_return"]
        next_day_returns.append(next_ret)
        vix_day_direction.append("up" if vix_ret > 0 else "down")

    # Compare with general "next day after any day" stats
    df["next_day_return"] = df["daily_return"].shift(-1)
    all_next = df["next_day_return"].dropna()

    next_arr = np.array(next_day_returns)
    print(f"\n  Next-day returns after VIX expiration:")
    print(f"    Mean:   {next_arr.mean():+.3f}%  (all days: {all_next.mean():+.3f}%)")
    print(f"    Median: {np.median(next_arr):+.3f}%  (all days: {all_next.median():+.3f}%)")
    print(f"    Green:  {(next_arr > 0).mean()*100:.1f}%  (all days: {(all_next > 0).mean()*100:.1f}%)")
    print(f"    n = {len(next_arr)}")

    # Does VIX exp day direction predict next day?
    dirs = np.array(vix_day_direction)
    up_follow = next_arr[dirs == "up"]
    dn_follow = next_arr[dirs == "down"]
    if len(up_follow) > 10 and len(dn_follow) > 10:
        print(f"\n  After VIX exp UP day:   next day mean={up_follow.mean():+.3f}%  green={((up_follow > 0).mean()*100):.1f}%  (n={len(up_follow)})")
        print(f"  After VIX exp DOWN day: next day mean={dn_follow.mean():+.3f}%  green={((dn_follow > 0).mean()*100):.1f}%  (n={len(dn_follow)})")


def analyze_return_distribution(conn, vix_dates):
    """Deeper look at return distribution: tail behavior, volatility clustering."""
    print("\n" + "=" * 70)
    print("SECTION 8: RETURN DISTRIBUTION & TAIL BEHAVIOR")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date
    df["daily_return"] = (df["close"] - df["open"]) / df["open"] * 100

    vix_set = set(vix_dates)
    df["is_vix_exp"] = df["date"].apply(lambda d: d in vix_set)

    vix = df[df["is_vix_exp"]]["daily_return"].dropna()
    normal = df[~df["is_vix_exp"]]["daily_return"].dropna()

    # Percentile comparison
    print(f"\n  Return Percentiles:")
    print(f"  {'Percentile':<15s} {'VIX Exp':>10s} {'Normal':>10s}")
    print("  " + "-" * 37)
    for pct in [5, 10, 25, 50, 75, 90, 95]:
        v_p = np.percentile(vix, pct)
        n_p = np.percentile(normal, pct)
        print(f"  {pct:>5d}th        {v_p:+9.3f}% {n_p:+9.3f}%")

    # Large move frequency
    print(f"\n  Large Move Frequency:")
    for threshold in [0.5, 1.0, 1.5, 2.0]:
        v_pct = (vix.abs() > threshold).mean() * 100
        n_pct = (normal.abs() > threshold).mean() * 100
        print(f"    |Return| > {threshold:.1f}%:  VIX={v_pct:.1f}%  Normal={n_pct:.1f}%  Diff={v_pct - n_pct:+.1f}%")

    # Standard deviation
    print(f"\n  Volatility:")
    print(f"    Std Dev:  VIX={vix.std():.3f}%  Normal={normal.std():.3f}%")
    print(f"    MAD:      VIX={vix.abs().mean():.3f}%  Normal={normal.abs().mean():.3f}%")


def analyze_by_year(conn, vix_dates):
    """Break down VIX exp day returns by year to look for regime changes."""
    print("\n" + "=" * 70)
    print("SECTION 9: VIX EXPIRATION DAY RETURNS BY YEAR")
    print("=" * 70)

    df = pd.read_sql_query("SELECT * FROM ind_1d ORDER BY timestamp", conn, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df["date"] = df.index.date
    df["year"] = df.index.year
    df["daily_return"] = (df["close"] - df["open"]) / df["open"] * 100

    vix_set = set(vix_dates)
    df["is_vix_exp"] = df["date"].apply(lambda d: d in vix_set)

    vix_df = df[df["is_vix_exp"]]

    print(f"\n  {'Year':<6s} {'n':>4s} {'Mean Ret':>10s} {'Med Ret':>10s} {'Green%':>8s} {'Mean |Ret|':>12s} {'Std':>8s}")
    print("  " + "-" * 62)

    for year in sorted(vix_df["year"].unique()):
        yr = vix_df[vix_df["year"] == year]["daily_return"]
        if len(yr) == 0:
            continue
        print(f"  {year:<6d} {len(yr):4d} {yr.mean():+9.3f}% {yr.median():+9.3f}% "
              f"{(yr > 0).mean()*100:7.1f}% {yr.abs().mean():11.3f}% {yr.std():7.3f}%")


def analyze_day_of_week_context(conn, vix_dates):
    """Verify VIX exp dates are Wednesdays and analyze surrounding week context."""
    print("\n" + "=" * 70)
    print("SECTION 10: DAY-OF-WEEK VERIFICATION & WEEK CONTEXT")
    print("=" * 70)

    # Verify day of week distribution
    dow_counts = defaultdict(int)
    dow_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
    for d in vix_dates:
        dow_counts[d.weekday()] += 1

    print(f"\n  VIX Expiration Day-of-Week Distribution:")
    for dow in sorted(dow_counts.keys()):
        print(f"    {dow_names.get(dow, f'Day {dow}')}: {dow_counts[dow]} ({dow_counts[dow]/len(vix_dates)*100:.1f}%)")

    print(f"\n  Total VIX expiration dates in database range: {len(vix_dates)}")
    print(f"  Date range: {min(vix_dates)} to {max(vix_dates)}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)

    print("Computing VIX expiration dates...")
    vix_dates = get_vix_expiration_trading_days(conn, start_year=2004, end_year=2025)
    print(f"Found {len(vix_dates)} VIX expiration dates in database range\n")

    # Print first/last few for verification
    print("First 10 VIX expiration dates:")
    for d in vix_dates[:10]:
        dow_name = ["Mon", "Tue", "Wed", "Thu", "Fri"][d.weekday()]
        print(f"  {d} ({dow_name})")
    print(f"  ...")
    print("Last 5:")
    for d in vix_dates[-5:]:
        dow_name = ["Mon", "Tue", "Wed", "Thu", "Fri"][d.weekday()]
        print(f"  {d} ({dow_name})")

    # Run all analyses
    analyze_day_of_week_context(conn, vix_dates)
    analyze_daily_patterns(conn, vix_dates)
    analyze_return_distribution(conn, vix_dates)
    analyze_atr_levels(conn, vix_dates)
    analyze_phase_oscillator(conn, vix_dates)
    analyze_pivot_ribbon(conn, vix_dates)
    analyze_intraday_behavior(conn, vix_dates)
    analyze_gap_behavior(conn, vix_dates)
    analyze_next_day(conn, vix_dates)
    analyze_by_year(conn, vix_dates)

    conn.close()
    print("\n" + "=" * 70)
    print("STUDY COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
