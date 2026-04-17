"""
Validate Saty ATR Levels level-to-level probabilities and Golden Gate subway stats
against 25 years of SPY daily data.

Reference claims from validated-backtests/:
- Level-to-level probabilities (within same period)
- Golden Gate timing statistics (trigger to 38.2% completion by hour)
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def load_daily_indicators(conn):
    """Load daily indicator data."""
    df = pd.read_sql_query(
        "SELECT * FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    return df


def load_intraday_with_daily_levels(conn, table="ind_10m"):
    """Load intraday data that has daily ATR levels."""
    df = pd.read_sql_query(
        f"SELECT * FROM {table} ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    return df


# ──────────────────────────────────────────────
# 1. Level-to-Level Probabilities (Daily)
# ──────────────────────────────────────────────

def compute_level_to_level_probabilities(conn):
    """For each trading day, check if price reached each ATR level.
    Uses daily ATR levels with intraday data to check actual price action."""

    print("=" * 60)
    print("ATR LEVEL-TO-LEVEL PROBABILITIES (Day Mode)")
    print("=" * 60)

    # Load 10-minute data with daily ATR levels
    df = load_intraday_with_daily_levels(conn, "ind_10m")

    # Filter to RTH only (9:30-16:00) for day trading mode
    df = df.between_time("09:30", "15:59")

    # Drop rows without ATR levels (first day, etc.)
    df = df.dropna(subset=["prev_close", "atr_14"])

    # Group by date
    df["date"] = df.index.date
    dates = df.groupby("date")

    results = {
        "total_days": 0,
        # Upside levels reached
        "upper_trigger": 0,   # 23.6%
        "upper_0382": 0,      # 38.2% (Golden Gate)
        "upper_0618": 0,      # 61.8% (Midrange)
        "upper_0786": 0,      # 78.6%
        "upper_100": 0,       # 100% (Full ATR)
        # Downside levels reached
        "lower_trigger": 0,
        "lower_0382": 0,
        "lower_0618": 0,
        "lower_0786": 0,
        "lower_100": 0,
        # Either direction
        "trigger_either": 0,
        "0382_either": 0,
        "0618_either": 0,
        "0786_either": 0,
        "100_either": 0,
        # Conditional: given trigger hit, did 38.2% also hit?
        "upper_trigger_then_0382": 0,
        "lower_trigger_then_0382": 0,
        # Conditional: given 38.2%, did 61.8%?
        "upper_0382_then_0618": 0,
        "lower_0382_then_0618": 0,
        # Given 61.8%, did 78.6%?
        "upper_0618_then_0786": 0,
        "lower_0618_then_0786": 0,
        # Given 78.6%, did 100%?
        "upper_0786_then_100": 0,
        "lower_0786_then_100": 0,
        # Close to full ATR (cumulative)
        "close_to_upper_100": 0,
        "close_to_lower_100": 0,
    }

    for date, group in dates:
        day_high = group["high"].max()
        day_low = group["low"].min()

        # Use the first bar's ATR levels (they're the same for the whole day)
        first = group.iloc[0]
        prev_close = first["prev_close"]
        if pd.isna(prev_close):
            continue

        results["total_days"] += 1

        # Check which levels were reached
        hit_upper = {}
        hit_lower = {}

        for level_name, col in [
            ("trigger", "atr_upper_trigger"),
            ("0382", "atr_upper_0382"),
            ("0618", "atr_upper_0618"),
            ("0786", "atr_upper_0786"),
            ("100", "atr_upper_100"),
        ]:
            hit_upper[level_name] = day_high >= first[col]
            if hit_upper[level_name]:
                results[f"upper_{level_name}"] += 1

        for level_name, col in [
            ("trigger", "atr_lower_trigger"),
            ("0382", "atr_lower_0382"),
            ("0618", "atr_lower_0618"),
            ("0786", "atr_lower_0786"),
            ("100", "atr_lower_100"),
        ]:
            hit_lower[level_name] = day_low <= first[col]
            if hit_lower[level_name]:
                results[f"lower_{level_name}"] += 1

        # Either direction
        for level in ["trigger", "0382", "0618", "0786", "100"]:
            if hit_upper[level] or hit_lower[level]:
                results[f"{level}_either"] += 1

        # Conditional probabilities
        if hit_upper["trigger"]:
            results["upper_trigger_then_0382"] += int(hit_upper["0382"])
        if hit_lower["trigger"]:
            results["lower_trigger_then_0382"] += int(hit_lower["0382"])

        if hit_upper["0382"]:
            results["upper_0382_then_0618"] += int(hit_upper["0618"])
        if hit_lower["0382"]:
            results["lower_0382_then_0618"] += int(hit_lower["0618"])

        if hit_upper["0618"]:
            results["upper_0618_then_0786"] += int(hit_upper["0786"])
        if hit_lower["0618"]:
            results["lower_0618_then_0786"] += int(hit_lower["0786"])

        if hit_upper["0786"]:
            results["upper_0786_then_100"] += int(hit_upper["100"])
        if hit_lower["0786"]:
            results["lower_0786_then_100"] += int(hit_lower["100"])

        # Cumulative: close to full ATR
        results["close_to_upper_100"] += int(hit_upper["100"])
        results["close_to_lower_100"] += int(hit_lower["100"])

    # Print results
    n = results["total_days"]
    print(f"\nTotal trading days: {n:,}\n")

    print("--- Absolute: % of days each level was reached ---")
    print(f"{'Level':<25s} {'Up':>8s} {'Down':>8s} {'Either':>8s}")
    for level, label in [("trigger", "±23.6% Trigger"), ("0382", "±38.2% Golden Gate"),
                          ("0618", "±61.8% Midrange"), ("0786", "±78.6%"), ("100", "±100% Full ATR")]:
        up_pct = results[f"upper_{level}"] / n * 100
        dn_pct = results[f"lower_{level}"] / n * 100
        ei_pct = results[f"{level}_either"] / n * 100
        print(f"  {label:<23s} {up_pct:7.1f}% {dn_pct:7.1f}% {ei_pct:7.1f}%")

    print(f"\n--- Conditional: level-to-level (given previous level hit) ---")
    print(f"{'Transition':<35s} {'Up':>8s} {'Down':>8s} {'Claim':>8s}")

    transitions = [
        ("Trigger → 38.2%", "upper_trigger_then_0382", "lower_trigger_then_0382",
         results["upper_trigger"], results["lower_trigger"], "80%"),
        ("38.2% → 61.8%", "upper_0382_then_0618", "lower_0382_then_0618",
         results["upper_0382"], results["lower_0382"], "69%"),
        ("61.8% → 78.6%", "upper_0618_then_0786", "lower_0618_then_0786",
         results["upper_0618"], results["lower_0618"], "60%"),
        ("78.6% → 100%", "upper_0786_then_100", "lower_0786_then_100",
         results["upper_0786"], results["lower_0786"], "55%"),
    ]

    for label, up_key, dn_key, up_base, dn_base, claim in transitions:
        up_pct = results[up_key] / up_base * 100 if up_base > 0 else 0
        dn_pct = results[dn_key] / dn_base * 100 if dn_base > 0 else 0
        print(f"  {label:<33s} {up_pct:7.1f}% {dn_pct:7.1f}% {claim:>8s}")

    cum_up = results["close_to_upper_100"] / n * 100
    cum_dn = results["close_to_lower_100"] / n * 100
    print(f"\n  {'Close → ±1 ATR (cumulative)':<33s} {cum_up:7.1f}% {cum_dn:7.1f}% {'14%':>8s}")


# ──────────────────────────────────────────────
# 2. Golden Gate Subway Stats
# ──────────────────────────────────────────────

def compute_golden_gate_subway_stats(conn):
    """For each day, find when the trigger is first hit during RTH and when 38.2% completes.
    Matches the reference subway stats format:
    - 'Open' = trigger already breached at market open (gap through trigger)
    - Hour rows = trigger first hit during that hour
    - Only counts RTH triggers and completions (9:30-15:59)
    """

    print("\n" + "=" * 60)
    print("GOLDEN GATE SUBWAY STATS (Trigger → 38.2%, RTH Only)")
    print("=" * 60)

    df = load_intraday_with_daily_levels(conn, "ind_10m")
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date
    df["hour"] = df.index.hour

    # Trigger categories: "open" + hours 9-15
    trigger_cats = ["open"] + list(range(9, 16))
    comp_hours = list(range(9, 16))

    def make_stats():
        return {cat: {"completions": {h: 0 for h in comp_hours}, "total": 0} for cat in trigger_cats}

    bullish_stats = make_stats()
    bearish_stats = make_stats()

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        upper_trigger = first["atr_upper_trigger"]
        lower_trigger = first["atr_lower_trigger"]
        upper_gate = first["atr_upper_0382"]
        lower_gate = first["atr_lower_0382"]

        if pd.isna(upper_trigger):
            continue

        # --- BULLISH ---
        # Check if open price already above trigger (gap through)
        if first["open"] >= upper_trigger:
            trigger_cat = "open"
            trigger_time = group.index[0]
        else:
            # Find first RTH bar where high >= upper_trigger
            hit = group[group["high"] >= upper_trigger]
            if len(hit) > 0:
                trigger_time = hit.index[0]
                trigger_cat = trigger_time.hour
            else:
                trigger_cat = None

        if trigger_cat is not None and trigger_cat in bullish_stats:
            bullish_stats[trigger_cat]["total"] += 1
            if trigger_cat == "open":
                remaining = group[group.index >= trigger_time]
            else:
                remaining = group[group.index > trigger_time]
            completion = remaining[remaining["high"] >= upper_gate]
            if len(completion) > 0:
                comp_hour = completion.index[0].hour
                if comp_hour in bullish_stats[trigger_cat]["completions"]:
                    bullish_stats[trigger_cat]["completions"][comp_hour] += 1

        # --- BEARISH ---
        if first["open"] <= lower_trigger:
            trigger_cat = "open"
            trigger_time = group.index[0]
        else:
            hit = group[group["low"] <= lower_trigger]
            if len(hit) > 0:
                trigger_time = hit.index[0]
                trigger_cat = trigger_time.hour
            else:
                trigger_cat = None

        if trigger_cat is not None and trigger_cat in bearish_stats:
            bearish_stats[trigger_cat]["total"] += 1
            if trigger_cat == "open":
                remaining = group[group.index >= trigger_time]
            else:
                remaining = group[group.index > trigger_time]
            completion = remaining[remaining["low"] <= lower_gate]
            if len(completion) > 0:
                comp_hour = completion.index[0].hour
                if comp_hour in bearish_stats[trigger_cat]["completions"]:
                    bearish_stats[trigger_cat]["completions"][comp_hour] += 1

    # Print results
    bull_claims = {"open": "90.9%", 9: "70.2%", 10: "55.0%", 11: "49.6%",
                   12: "46.8%", 13: "50.0%", 14: "40.9%", 15: "9.1%"}
    bear_claims = {"open": "91.1%", 9: "69.7%", 10: "58.8%", 11: "58.9%",
                   12: "55.6%", 13: "48.4%", 14: "48.6%", 15: "36.6%"}

    for direction, stats, label, claims in [
        ("BULLISH", bullish_stats, "Trigger → +38.2%", bull_claims),
        ("BEARISH", bearish_stats, "Trigger → -38.2%", bear_claims),
    ]:
        print(f"\n--- {direction} Golden Gate ({label}) ---")
        print(f"{'Trigger':>8s} {'Total':>6s}", end="")
        for h in comp_hours:
            print(f" {h:02d}:00", end="")
        print(f" {'Done%':>7s} {'Claim':>7s}")

        for trigger_cat in trigger_cats:
            total = stats[trigger_cat]["total"]
            if total == 0:
                continue
            completions = stats[trigger_cat]["completions"]
            total_completed = sum(completions.values())
            pct_done = total_completed / total * 100

            cat_label = "  Open" if trigger_cat == "open" else f"  {trigger_cat:02d}:00"
            print(f"{cat_label:>8s} {total:6d}", end="")
            for h in comp_hours:
                cpct = completions[h] / total * 100
                print(f" {cpct:5.1f}", end="")
            claim = claims.get(trigger_cat, "")
            print(f" {pct_done:6.1f}% {claim:>7s}")


# ──────────────────────────────────────────────
# 3. Gap Fill Probabilities
# ──────────────────────────────────────────────

def compute_gap_fill_probabilities(conn):
    """Compute how often gaps fill within the same trading day."""

    print("\n" + "=" * 60)
    print("GAP FILL PROBABILITIES (Same Day)")
    print("=" * 60)

    df = load_intraday_with_daily_levels(conn, "ind_10m")
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close"])
    df["date"] = df.index.date

    gap_buckets = [
        (0, 0.001, "< 0.1%"),
        (0.001, 0.0025, "0.1-0.25%"),
        (0.0025, 0.005, "0.25-0.5%"),
        (0.005, 0.0075, "0.5-0.75%"),
        (0.0075, 0.01, "0.75-1.0%"),
        (0.01, 0.015, "1.0-1.5%"),
        (0.015, 0.02, "1.5-2.0%"),
        (0.02, 0.03, "2.0-3.0%"),
        (0.03, 1.0, "3.0%+"),
    ]

    results = {label: {"gap_up": 0, "gap_up_fill": 0, "gap_down": 0, "gap_down_fill": 0}
               for _, _, label in gap_buckets}

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        prev_close = first["prev_close"]
        if pd.isna(prev_close) or prev_close == 0:
            continue

        day_open = first["open"]
        gap_pct = (day_open - prev_close) / prev_close
        gap_abs = abs(gap_pct)

        day_high = group["high"].max()
        day_low = group["low"].min()

        for lo, hi, label in gap_buckets:
            if lo <= gap_abs < hi:
                if gap_pct > 0:
                    results[label]["gap_up"] += 1
                    if day_low <= prev_close:
                        results[label]["gap_up_fill"] += 1
                elif gap_pct < 0:
                    results[label]["gap_down"] += 1
                    if day_high >= prev_close:
                        results[label]["gap_down_fill"] += 1
                break

    print(f"\n{'Gap Size':<15s} {'Up N':>6s} {'Up Fill%':>9s} {'Claim':>7s} {'Dn N':>6s} {'Dn Fill%':>9s} {'Claim':>7s}")

    claims_up = {"< 0.1%": "92.0%", "0.1-0.25%": "76.5%", "0.25-0.5%": "58.6%",
                 "0.5-0.75%": "44.6%", "0.75-1.0%": "40.2%", "1.0-1.5%": "28.3%",
                 "1.5-2.0%": "20.0%", "2.0-3.0%": "27.5%", "3.0%+": "43.8%"}
    claims_dn = {"< 0.1%": "92.9%", "0.1-0.25%": "78.9%", "0.25-0.5%": "62.9%",
                 "0.5-0.75%": "47.7%", "0.75-1.0%": "34.2%", "1.0-1.5%": "36.7%",
                 "1.5-2.0%": "31.1%", "2.0-3.0%": "41.5%", "3.0%+": "15.0%"}

    for _, _, label in gap_buckets:
        r = results[label]
        up_pct = r["gap_up_fill"] / r["gap_up"] * 100 if r["gap_up"] > 0 else 0
        dn_pct = r["gap_down_fill"] / r["gap_down"] * 100 if r["gap_down"] > 0 else 0
        print(f"  {label:<13s} {r['gap_up']:6d} {up_pct:8.1f}% {claims_up[label]:>7s} {r['gap_down']:6d} {dn_pct:8.1f}% {claims_dn[label]:>7s}")


def main():
    conn = sqlite3.connect(DB_PATH)
    compute_level_to_level_probabilities(conn)
    compute_golden_gate_subway_stats(conn)
    compute_gap_fill_probabilities(conn)
    conn.close()


if __name__ == "__main__":
    main()
