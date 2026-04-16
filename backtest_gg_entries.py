"""
Golden Gate Entry Optimization Study

Question: After a Golden Gate opens (38.2% hit), what's the best entry
to maximize completion probability and profit?

Tests entering at various pullback levels (ATR levels + EMAs) after the
38.2% is first hit. For each entry strategy, measures:
- How often the entry opportunity appears
- Completion rate (does 61.8% get hit after entry?)
- Average reward in ATR% terms (distance from entry to 61.8%)
- Average risk (distance from entry back to stop/invalidation level)
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/root/spy/spy.db"


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 10m data...", flush=True)
    df10 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "atr_upper_050, atr_lower_050, "
        "prev_close, atr_14, "
        "ema_8, ema_21, ema_48 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df10 = df10.set_index("timestamp").sort_index()
    df10 = df10.between_time("09:30", "15:59")
    df10 = df10.dropna(subset=["prev_close", "atr_14"])
    df10["date"] = df10.index.date

    # Load 1h EMAs
    print("Loading 1h EMAs...", flush=True)
    df1h = pd.read_sql_query(
        "SELECT timestamp, ema_21 as ema_21_1h, ema_48 as ema_48_1h FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df1h = df1h.set_index("timestamp").sort_index()
    merged = pd.merge_asof(df10.reset_index()[["timestamp"]], df1h.reset_index(), on="timestamp", direction="backward")
    df10["ema_21_1h"] = merged["ema_21_1h"].values
    df10["ema_48_1h"] = merged["ema_48_1h"].values

    print("Computing entry stats...\n", flush=True)

    # Entry strategies: after 38.2% is hit, wait for price to pull back to a level,
    # then enter on the NEXT bar after a 10m close touches/bounces off that level.
    #
    # For bullish: "entry when 10m close pulls back to X and then closes above X"
    # We simplify: entry = the close price of the first bar that touches the level from above

    for direction, entry_col, target_col, label in [
        ("bull", "atr_upper_0382", "atr_upper_0618", "BULLISH"),
        ("bear", "atr_lower_0382", "atr_lower_0618", "BEARISH"),
    ]:
        # Define entry levels
        if direction == "bull":
            entry_levels = [
                ("Immediate (at 38.2%)",       lambda first, bar: True,                                          lambda first, bar: first["atr_upper_0382"]),
                ("Pullback to 50% midpoint",   lambda first, bar: bar["low"] <= first["atr_upper_050"],          lambda first, bar: first["atr_upper_050"]),
                ("Pullback to EMA 8 (10m)",    lambda first, bar: bar["low"] <= bar["ema_8"],                    lambda first, bar: bar["ema_8"]),
                ("Pullback to EMA 21 (10m)",   lambda first, bar: bar["low"] <= bar["ema_21"],                   lambda first, bar: bar["ema_21"]),
                ("Pullback to EMA 48 (10m)",   lambda first, bar: bar["low"] <= bar["ema_48"],                   lambda first, bar: bar["ema_48"]),
                ("Pullback to EMA 21 (1h)",    lambda first, bar: bar["low"] <= bar["ema_21_1h"],                lambda first, bar: bar["ema_21_1h"]),
                ("Pullback to EMA 48 (1h)",    lambda first, bar: bar["low"] <= bar["ema_48_1h"],                lambda first, bar: bar["ema_48_1h"]),
                ("Pullback to Call Trigger",   lambda first, bar: bar["low"] <= first["atr_upper_trigger"],      lambda first, bar: first["atr_upper_trigger"]),
                ("Pullback to Prev Close",     lambda first, bar: bar["low"] <= first["prev_close"],             lambda first, bar: first["prev_close"]),
            ]
        else:
            entry_levels = [
                ("Immediate (at 38.2%)",       lambda first, bar: True,                                          lambda first, bar: first["atr_lower_0382"]),
                ("Pullback to 50% midpoint",   lambda first, bar: bar["high"] >= first["atr_lower_050"],         lambda first, bar: first["atr_lower_050"]),
                ("Pullback to EMA 8 (10m)",    lambda first, bar: bar["high"] >= bar["ema_8"],                   lambda first, bar: bar["ema_8"]),
                ("Pullback to EMA 21 (10m)",   lambda first, bar: bar["high"] >= bar["ema_21"],                  lambda first, bar: bar["ema_21"]),
                ("Pullback to EMA 48 (10m)",   lambda first, bar: bar["high"] >= bar["ema_48"],                  lambda first, bar: bar["ema_48"]),
                ("Pullback to EMA 21 (1h)",    lambda first, bar: bar["high"] >= bar["ema_21_1h"],               lambda first, bar: bar["ema_21_1h"]),
                ("Pullback to EMA 48 (1h)",    lambda first, bar: bar["high"] >= bar["ema_48_1h"],               lambda first, bar: bar["ema_48_1h"]),
                ("Pullback to Put Trigger",    lambda first, bar: bar["high"] >= first["atr_lower_trigger"],     lambda first, bar: first["atr_lower_trigger"]),
                ("Pullback to Prev Close",     lambda first, bar: bar["high"] >= first["prev_close"],            lambda first, bar: first["prev_close"]),
            ]

        stats = {name: {"total_gg": 0, "entry_appeared": 0, "completed": 0,
                         "rewards": [], "risks": []}
                 for name, _, _ in entry_levels}

        for date, group in df10.groupby("date"):
            first = group.iloc[0]
            entry_level = first[entry_col]
            target_level = first[target_col]
            atr_val = first["atr_14"]
            if pd.isna(entry_level) or pd.isna(atr_val) or atr_val == 0:
                continue

            # Find GG entry (38.2% hit)
            if direction == "bull":
                if first["open"] >= entry_level:
                    tidx = 0
                else:
                    hit = group["high"] >= entry_level
                    if hit.any():
                        tidx = hit.values.argmax()
                    else:
                        continue
            else:
                if first["open"] <= entry_level:
                    tidx = 0
                else:
                    hit = group["low"] <= entry_level
                    if hit.any():
                        tidx = hit.values.argmax()
                    else:
                        continue

            remaining = group.iloc[tidx:]

            for name, check_fn, price_fn in entry_levels:
                stats[name]["total_gg"] += 1

                if name.startswith("Immediate"):
                    # Enter at 38.2% level on the trigger bar
                    entry_price = price_fn(first, remaining.iloc[0])
                    entry_idx = 0
                    entered = True
                else:
                    # Look for pullback to the level after GG entry
                    entered = False
                    entry_price = None
                    entry_idx = None
                    for i, (ts, bar) in enumerate(remaining.iterrows()):
                        try:
                            if check_fn(first, bar):
                                entry_price = price_fn(first, bar)
                                entry_idx = i
                                entered = True
                                break
                        except:
                            continue

                if not entered or entry_price is None or pd.isna(entry_price):
                    continue

                stats[name]["entry_appeared"] += 1

                # Check if target is reached after entry
                after_entry = remaining.iloc[entry_idx:]
                if direction == "bull":
                    completed = (after_entry["high"] >= target_level).any()
                    reward = (target_level - entry_price) / atr_val * 100  # in ATR%
                    # Risk = distance from entry back to trigger (natural stop)
                    stop = first["atr_upper_trigger"]
                    risk = (entry_price - stop) / atr_val * 100
                else:
                    completed = (after_entry["low"] <= target_level).any()
                    reward = (entry_price - target_level) / atr_val * 100
                    stop = first["atr_lower_trigger"]
                    risk = (stop - entry_price) / atr_val * 100

                if completed:
                    stats[name]["completed"] += 1

                if reward > 0:
                    stats[name]["rewards"].append(reward)
                if risk > 0:
                    stats[name]["risks"].append(risk)

        # Print results
        print(f"{'=' * 100}")
        print(f"{label} GOLDEN GATE ENTRY OPTIMIZATION")
        print(f"{'=' * 100}")
        print(f"\n{'Entry Strategy':<30s} {'GG Days':>7s} {'Entry%':>7s} {'GG%':>7s} {'Avg Reward':>11s} {'Avg Risk':>9s} {'R:R':>6s}")
        print("-" * 85)

        for name, _, _ in entry_levels:
            s = stats[name]
            total = s["total_gg"]
            appeared = s["entry_appeared"]
            completed = s["completed"]
            entry_pct = appeared / total * 100 if total > 0 else 0
            gg_pct = completed / appeared * 100 if appeared > 0 else 0
            avg_reward = np.mean(s["rewards"]) if s["rewards"] else 0
            avg_risk = np.mean(s["risks"]) if s["risks"] else 0
            rr = avg_reward / avg_risk if avg_risk > 0 else 0

            print(f"  {name:<28s} {total:7d} {entry_pct:6.1f}% {gg_pct:6.1f}% {avg_reward:9.1f}% ATR {avg_risk:7.1f}% {rr:5.1f}x")

        # Expected value calculation
        print(f"\n  {'--- Expected Value (per trade) ---':}")
        print(f"  {'Entry Strategy':<30s} {'EV (ATR%)':>10s}  {'Rationale':}")
        print(f"  {'-'*75}")
        for name, _, _ in entry_levels:
            s = stats[name]
            appeared = s["entry_appeared"]
            completed = s["completed"]
            if appeared == 0:
                continue
            gg_pct = completed / appeared
            avg_reward = np.mean(s["rewards"]) if s["rewards"] else 0
            avg_risk = np.mean(s["risks"]) if s["risks"] else 0
            # EV = P(win) * reward - P(loss) * risk
            ev = gg_pct * avg_reward - (1 - gg_pct) * avg_risk
            entry_pct = appeared / s["total_gg"] * 100
            print(f"  {name:<28s} {ev:+9.1f}%    win={gg_pct*100:.0f}% x {avg_reward:.1f} - lose={100-gg_pct*100:.0f}% x {avg_risk:.1f}, appears {entry_pct:.0f}%")

        print()

    conn.close()


if __name__ == "__main__":
    main()
