"""
Trigger Box Study

When price opens in the bearish trigger box (below PDC but above put trigger):
1. How often does a bearish Golden Gate open (price reaches -38.2%)?
2. If 10m candles never close above PDC in first 30min / 1hr, how does GG% change?
3. When price DOES close above PDC in the first hour, how often does it reach the call trigger?

Mirror for bullish: opens above PDC but below call trigger.
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
        "prev_close, atr_14 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date
    df["time"] = df.index.time

    print("Computing trigger box stats...\n")

    for direction, label in [("bear", "BEARISH"), ("bull", "BULLISH")]:
        stats = {
            "total_in_box": 0,
            "gg_opened": 0,
            "gg_completed": 0,
            # Never closed above/below PDC in first 30 min
            "held_30m": 0,
            "held_30m_gg": 0,
            "held_30m_gg_complete": 0,
            # Never closed above/below PDC in first 1 hour
            "held_1h": 0,
            "held_1h_gg": 0,
            "held_1h_gg_complete": 0,
            # DID close above/below PDC in first 1 hour
            "reclaimed_1h": 0,
            "reclaimed_1h_reached_opp_trigger": 0,
            "reclaimed_1h_reached_opp_gg": 0,
        }

        for date, group in df.groupby("date"):
            first = group.iloc[0]
            day_open = first["open"]
            pdc = first["prev_close"]
            put_trigger = first["atr_lower_trigger"]
            call_trigger = first["atr_upper_trigger"]
            bear_gg_entry = first["atr_lower_0382"]
            bear_gg_exit = first["atr_lower_0618"]
            bull_gg_entry = first["atr_upper_0382"]
            bull_gg_exit = first["atr_upper_0618"]

            if pd.isna(pdc) or pd.isna(put_trigger):
                continue

            # Check if open is in the trigger box
            if direction == "bear":
                # Bearish box: open below PDC but above put trigger
                in_box = day_open < pdc and day_open > put_trigger
            else:
                # Bullish box: open above PDC but below call trigger
                in_box = day_open > pdc and day_open < call_trigger

            if not in_box:
                continue

            stats["total_in_box"] += 1

            # Did a GG open (reach 38.2%) and complete (reach 61.8%)?
            if direction == "bear":
                gg_opened = (group["low"] <= bear_gg_entry).any()
                gg_completed = (group["low"] <= bear_gg_exit).any()
            else:
                gg_opened = (group["high"] >= bull_gg_entry).any()
                gg_completed = (group["high"] >= bull_gg_exit).any()

            if gg_opened:
                stats["gg_opened"] += 1
            if gg_completed:
                stats["gg_completed"] += 1

            # First 30 minutes: bars from 09:30 to 09:59
            first_30m = group[group.index.time < pd.Timestamp("10:00").time()]
            # First 1 hour: bars from 09:30 to 10:29
            first_1h = group[group.index.time < pd.Timestamp("10:30").time()]

            if direction == "bear":
                # "Held" = no 10m candle closed ABOVE PDC
                held_30m = not (first_30m["close"] > pdc).any()
                held_1h = not (first_1h["close"] > pdc).any()
                # "Reclaimed" = at least one 10m candle closed ABOVE PDC in first hour
                reclaimed_1h = (first_1h["close"] > pdc).any()
            else:
                # "Held" = no 10m candle closed BELOW PDC
                held_30m = not (first_30m["close"] < pdc).any()
                held_1h = not (first_1h["close"] < pdc).any()
                # "Reclaimed" = at least one 10m candle closed BELOW PDC
                reclaimed_1h = (first_1h["close"] < pdc).any()

            if held_30m:
                stats["held_30m"] += 1
                if gg_opened:
                    stats["held_30m_gg"] += 1
                if gg_completed:
                    stats["held_30m_gg_complete"] += 1

            if held_1h:
                stats["held_1h"] += 1
                if gg_opened:
                    stats["held_1h_gg"] += 1
                if gg_completed:
                    stats["held_1h_gg_complete"] += 1

            if reclaimed_1h:
                stats["reclaimed_1h"] += 1
                if direction == "bear":
                    # Price reclaimed PDC — did it reach the CALL trigger?
                    reached_call = (group["high"] >= call_trigger).any()
                    reached_bull_gg = (group["high"] >= bull_gg_entry).any()
                    if reached_call:
                        stats["reclaimed_1h_reached_opp_trigger"] += 1
                    if reached_bull_gg:
                        stats["reclaimed_1h_reached_opp_gg"] += 1
                else:
                    # Price fell back below PDC — did it reach the PUT trigger?
                    reached_put = (group["low"] <= put_trigger).any()
                    reached_bear_gg = (group["low"] <= bear_gg_entry).any()
                    if reached_put:
                        stats["reclaimed_1h_reached_opp_trigger"] += 1
                    if reached_bear_gg:
                        stats["reclaimed_1h_reached_opp_gg"] += 1

        # Print
        s = stats
        pct = lambda n, d: f"{n/d*100:.1f}%" if d > 0 else "n/a"

        if direction == "bear":
            box_desc = "Open below PDC but above put trigger"
            held_desc = "No 10m close above PDC"
            reclaim_desc = "10m close above PDC in first hour"
            opp_trigger = "call trigger"
            opp_gg = "bullish GG (38.2%)"
        else:
            box_desc = "Open above PDC but below call trigger"
            held_desc = "No 10m close below PDC"
            reclaim_desc = "10m close below PDC in first hour"
            opp_trigger = "put trigger"
            opp_gg = "bearish GG (38.2%)"

        print(f"{'='*70}")
        print(f"{label} TRIGGER BOX")
        print(f"{'='*70}")
        print(f"  {box_desc}")
        print(f"  Days in trigger box: {s['total_in_box']:,}")
        print()

        print(f"  --- Baseline (all trigger box days) ---")
        print(f"  GG opened (reached 38.2%):    {pct(s['gg_opened'], s['total_in_box'])}  ({s['gg_opened']}/{s['total_in_box']})")
        print(f"  GG completed (reached 61.8%): {pct(s['gg_completed'], s['total_in_box'])}  ({s['gg_completed']}/{s['total_in_box']})")
        print()

        print(f"  --- {held_desc} in first 30 min ---")
        print(f"  Days:                         {s['held_30m']:,}  ({pct(s['held_30m'], s['total_in_box'])} of box days)")
        print(f"  GG opened:                    {pct(s['held_30m_gg'], s['held_30m'])}  ({s['held_30m_gg']}/{s['held_30m']})")
        print(f"  GG completed:                 {pct(s['held_30m_gg_complete'], s['held_30m'])}  ({s['held_30m_gg_complete']}/{s['held_30m']})")
        print()

        print(f"  --- {held_desc} in first 1 hour ---")
        print(f"  Days:                         {s['held_1h']:,}  ({pct(s['held_1h'], s['total_in_box'])} of box days)")
        print(f"  GG opened:                    {pct(s['held_1h_gg'], s['held_1h'])}  ({s['held_1h_gg']}/{s['held_1h']})")
        print(f"  GG completed:                 {pct(s['held_1h_gg_complete'], s['held_1h'])}  ({s['held_1h_gg_complete']}/{s['held_1h']})")
        print()

        print(f"  --- {reclaim_desc} ---")
        print(f"  Days:                         {s['reclaimed_1h']:,}  ({pct(s['reclaimed_1h'], s['total_in_box'])} of box days)")
        print(f"  Reached {opp_trigger}:       {pct(s['reclaimed_1h_reached_opp_trigger'], s['reclaimed_1h'])}  ({s['reclaimed_1h_reached_opp_trigger']}/{s['reclaimed_1h']})")
        print(f"  Reached {opp_gg}: {pct(s['reclaimed_1h_reached_opp_gg'], s['reclaimed_1h'])}  ({s['reclaimed_1h_reached_opp_gg']}/{s['reclaimed_1h']})")
        print()

    conn.close()


if __name__ == "__main__":
    main()
