"""
Trigger Box Credit Spread Study

When price opens in the trigger box and holds for 30min/1hr:
- How often does price NOT reach the opposing 61.8% level? (win rate for selling spreads there)
- How often does price NOT reach the opposing 38.2%? (tighter spread, higher win rate)
- How does win rate improve if price stays in one HALF of the trigger box?
- Use passing 38.2% in the trade direction as a stop

Example: Bearish trigger box (open below PDC, above put trigger)
- Sell CALL credit spread at +61.8% ATR level
- Stop/invalidation: price reaches +38.2%
- Win: price NEVER reaches +61.8% by end of day
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 10m data...", flush=True)
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "atr_upper_050, atr_lower_050, "
        "atr_upper_100, atr_lower_100, "
        "prev_close, atr_14 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date

    print("Computing credit spread stats...\n")

    for direction, label in [("bear", "BEARISH TRIGGER BOX — Sell CALL spreads"), ("bull", "BULLISH TRIGGER BOX — Sell PUT spreads")]:
        print(f"{'='*80}")
        print(f"  {label}")
        print(f"{'='*80}")

        # Levels to test "price does NOT reach X"
        if direction == "bear":
            # Open below PDC, above put trigger
            # Selling calls — want price to NOT go up
            strike_levels = [
                ("PDC (0%)",                "prev_close",        "up"),
                ("Call Trigger (+23.6%)",    "atr_upper_trigger", "up"),
                ("+38.2% (GG entry)",       "atr_upper_0382",    "up"),
                ("+50%",                    "atr_upper_050",     "up"),
                ("+61.8% (GG exit)",        "atr_upper_0618",    "up"),
                ("+100% (full ATR)",        "atr_upper_100",     "up"),
            ]
            stop_col = "atr_upper_0382"  # stop if price reaches +38.2%
        else:
            # Open above PDC, below call trigger
            # Selling puts — want price to NOT go down
            strike_levels = [
                ("PDC (0%)",                "prev_close",        "down"),
                ("Put Trigger (-23.6%)",    "atr_lower_trigger", "down"),
                ("-38.2% (GG entry)",       "atr_lower_0382",    "down"),
                ("-50%",                    "atr_lower_050",     "down"),
                ("-61.8% (GG exit)",        "atr_lower_0618",    "down"),
                ("-100% (full ATR)",        "atr_lower_100",     "down"),
            ]
            stop_col = "atr_lower_0382"

        # Conditions
        conditions = [
            ("All trigger box days", "all"),
            ("Held 30 min", "held_30m"),
            ("Held 1 hour", "held_1h"),
            ("Held 30m + top half of box", "held_30m_top"),
            ("Held 30m + bottom half of box", "held_30m_bottom"),
            ("Held 1h + top half of box", "held_1h_top"),
            ("Held 1h + bottom half of box", "held_1h_bottom"),
        ]

        results = {}
        for cond_name, _ in conditions:
            results[cond_name] = {"n": 0}
            for strike_name, _, _ in strike_levels:
                results[cond_name][strike_name] = 0  # count of days price DID NOT reach

        for date, group in df.groupby("date"):
            first = group.iloc[0]
            day_open = first["open"]
            pdc = first["prev_close"]
            if pd.isna(pdc):
                continue

            if direction == "bear":
                put_trig = first["atr_lower_trigger"]
                in_box = day_open < pdc and day_open > put_trig
                box_mid = (pdc + put_trig) / 2
                in_top_half = day_open >= box_mid  # closer to PDC
                in_bottom_half = day_open < box_mid  # closer to put trigger
            else:
                call_trig = first["atr_upper_trigger"]
                in_box = day_open > pdc and day_open < call_trig
                box_mid = (pdc + call_trig) / 2
                in_top_half = day_open >= box_mid  # closer to call trigger
                in_bottom_half = day_open < box_mid  # closer to PDC

            if not in_box:
                continue

            first_30m = group[group.index.time < pd.Timestamp("10:00").time()]
            first_1h = group[group.index.time < pd.Timestamp("10:30").time()]

            if direction == "bear":
                held_30m = not (first_30m["close"] > pdc).any()
                held_1h = not (first_1h["close"] > pdc).any()
            else:
                held_30m = not (first_30m["close"] < pdc).any()
                held_1h = not (first_1h["close"] < pdc).any()

            # Determine which conditions this day matches
            day_conds = ["all"]
            if held_30m:
                day_conds.append("held_30m")
                if direction == "bear":
                    if in_top_half:
                        day_conds.append("held_30m_top")
                    else:
                        day_conds.append("held_30m_bottom")
                else:
                    if in_top_half:
                        day_conds.append("held_30m_top")
                    else:
                        day_conds.append("held_30m_bottom")
            if held_1h:
                day_conds.append("held_1h")
                if direction == "bear":
                    if in_top_half:
                        day_conds.append("held_1h_top")
                    else:
                        day_conds.append("held_1h_bottom")
                else:
                    if in_top_half:
                        day_conds.append("held_1h_top")
                    else:
                        day_conds.append("held_1h_bottom")

            # Check each strike level
            day_high = group["high"].max()
            day_low = group["low"].min()

            for cond_name, cond_key in conditions:
                if cond_key not in day_conds:
                    continue
                results[cond_name]["n"] += 1

                for strike_name, strike_col, strike_dir in strike_levels:
                    strike_val = first[strike_col]
                    if pd.isna(strike_val):
                        continue
                    if strike_dir == "up":
                        did_not_reach = day_high < strike_val
                    else:
                        did_not_reach = day_low > strike_val

                    if did_not_reach:
                        results[cond_name][strike_name] += 1

        # Print results
        pct = lambda n, d: f"{n/d*100:.1f}%" if d > 0 else "n/a"

        # Header
        print(f"\n  {'Condition':<35s} {'N':>5s}", end="")
        for strike_name, _, _ in strike_levels:
            short = strike_name.split("(")[0].strip()[:12]
            print(f" {short:>12s}", end="")
        print()
        print(f"  {'-'*35} {'-----':>5s}", end="")
        for _ in strike_levels:
            print(f" {'------------':>12s}", end="")
        print()

        for cond_name, _ in conditions:
            n = results[cond_name]["n"]
            if n == 0:
                continue
            print(f"  {cond_name:<35s} {n:5d}", end="")
            for strike_name, _, _ in strike_levels:
                safe = results[cond_name][strike_name]
                print(f" {pct(safe, n):>12s}", end="")
            print()

        print()
        if direction == "bear":
            print("  Reading: '85%' at '+61.8%' means price did NOT reach +61.8% on 85% of days")
            print("  = 85% win rate if you sold a call spread with short strike at +61.8%")
        else:
            print("  Reading: '85%' at '-61.8%' means price did NOT reach -61.8% on 85% of days")
            print("  = 85% win rate if you sold a put spread with short strike at -61.8%")
        print()

    conn.close()


if __name__ == "__main__":
    main()
