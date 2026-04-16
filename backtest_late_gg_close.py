"""
Late-Day Golden Gate Reversal Study

When the bullish GG first opens (price hits upper 38.2%) during the last 2 hours
of RTH (14:00-15:59), how often does SPY close below the call trigger (upper 23.6%)?

Also examines:
- Does it matter if the GG entry is at 14:00 vs 15:00?
- How often does price close below prev_close (full reversal)?
- What about the bearish side (GG opens to downside, close above put trigger)?
- Does the GG complete (hit 61.8%) on these late entries?
- Where does the day actually close relative to ATR levels?
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

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
    df = df.dropna(subset=["prev_close", "atr_14", "atr_upper_trigger"])
    df["date"] = df.index.date
    df["hour"] = df.index.hour

    print(f"Total RTH 10m bars: {len(df):,}")

    # ──────────────────────────────────────────────
    # Accumulators
    # ──────────────────────────────────────────────

    total_days = 0

    # Bullish: GG opens upside in last 2 hours
    bull = {
        "total": 0,
        "close_below_trigger": 0,
        "close_below_prev": 0,
        "gg_completed": 0,
        # by trigger hour
        "by_hour": defaultdict(lambda: {
            "total": 0, "close_below_trigger": 0,
            "close_below_prev": 0, "gg_completed": 0,
        }),
        # where does the day close relative to levels?
        "close_zones": defaultdict(int),
        # date list for charting
        "dates": [],
    }

    # Bearish: GG opens downside in last 2 hours
    bear = {
        "total": 0,
        "close_above_trigger": 0,
        "close_above_prev": 0,
        "gg_completed": 0,
        "by_hour": defaultdict(lambda: {
            "total": 0, "close_above_trigger": 0,
            "close_above_prev": 0, "gg_completed": 0,
        }),
        "close_zones": defaultdict(int),
        "dates": [],
    }

    # Also track: GG entries in FIRST 2 hours for comparison
    bull_early = {"total": 0, "close_below_trigger": 0, "close_below_prev": 0}
    bear_early = {"total": 0, "close_above_trigger": 0, "close_above_prev": 0}

    for date, group in df.groupby("date"):
        total_days += 1
        first = group.iloc[0]
        last = group.iloc[-1]
        day_close = last["close"]

        upper_trigger = first["atr_upper_trigger"]
        lower_trigger = first["atr_lower_trigger"]
        upper_0382 = first["atr_upper_0382"]
        lower_0382 = first["atr_lower_0382"]
        upper_0618 = first["atr_upper_0618"]
        lower_0618 = first["atr_lower_0618"]
        prev_close = first["prev_close"]

        # ── BULLISH GG ──
        # Find first bar where high >= upper 38.2%
        bull_hits = group[group["high"] >= upper_0382]
        if len(bull_hits) > 0:
            first_hit_time = bull_hits.index[0]
            first_hit_hour = first_hit_time.hour

            if first_hit_hour >= 14:
                # Late-day GG entry
                bull["total"] += 1
                h = bull["by_hour"][first_hit_hour]
                h["total"] += 1

                below_trigger = day_close < upper_trigger
                below_prev = day_close < prev_close

                if below_trigger:
                    bull["close_below_trigger"] += 1
                    h["close_below_trigger"] += 1
                if below_prev:
                    bull["close_below_prev"] += 1
                    h["close_below_prev"] += 1

                # Did GG complete (hit 61.8%)?
                remaining = group[group.index >= first_hit_time]
                if (remaining["high"] >= upper_0618).any():
                    bull["gg_completed"] += 1
                    h["gg_completed"] += 1

                # Where did the day close?
                if day_close >= upper_0618:
                    bull["close_zones"]["above_0618"] += 1
                elif day_close >= upper_0382:
                    bull["close_zones"]["0382_to_0618"] += 1
                elif day_close >= upper_trigger:
                    bull["close_zones"]["trigger_to_0382"] += 1
                elif day_close >= prev_close:
                    bull["close_zones"]["prev_to_trigger"] += 1
                elif day_close >= lower_trigger:
                    bull["close_zones"]["below_prev_above_lower_trig"] += 1
                else:
                    bull["close_zones"]["below_lower_trigger"] += 1

                bull["dates"].append({
                    "d": str(date),
                    "h": first_hit_hour,
                    "below_trig": 1 if below_trigger else 0,
                })

            elif first_hit_hour <= 10:
                # Early GG for comparison
                bull_early["total"] += 1
                if day_close < upper_trigger:
                    bull_early["close_below_trigger"] += 1
                if day_close < prev_close:
                    bull_early["close_below_prev"] += 1

        # ── BEARISH GG ──
        bear_hits = group[group["low"] <= lower_0382]
        if len(bear_hits) > 0:
            first_hit_time = bear_hits.index[0]
            first_hit_hour = first_hit_time.hour

            if first_hit_hour >= 14:
                bear["total"] += 1
                h = bear["by_hour"][first_hit_hour]
                h["total"] += 1

                above_trigger = day_close > lower_trigger
                above_prev = day_close > prev_close

                if above_trigger:
                    bear["close_above_trigger"] += 1
                    h["close_above_trigger"] += 1
                if above_prev:
                    bear["close_above_prev"] += 1
                    h["close_above_prev"] += 1

                remaining = group[group.index >= first_hit_time]
                if (remaining["low"] <= lower_0618).any():
                    bear["gg_completed"] += 1
                    h["gg_completed"] += 1

                if day_close <= lower_0618:
                    bear["close_zones"]["below_0618"] += 1
                elif day_close <= lower_0382:
                    bear["close_zones"]["0382_to_0618"] += 1
                elif day_close <= lower_trigger:
                    bear["close_zones"]["trigger_to_0382"] += 1
                elif day_close <= prev_close:
                    bear["close_zones"]["prev_to_trigger"] += 1
                elif day_close <= upper_trigger:
                    bear["close_zones"]["above_prev_below_upper_trig"] += 1
                else:
                    bear["close_zones"]["above_upper_trigger"] += 1

                bear["dates"].append({
                    "d": str(date),
                    "h": first_hit_hour,
                    "above_trig": 1 if above_trigger else 0,
                })

            elif first_hit_hour <= 10:
                bear_early["total"] += 1
                if day_close > lower_trigger:
                    bear_early["close_above_trigger"] += 1
                if day_close > prev_close:
                    bear_early["close_above_prev"] += 1

    # ──────────────────────────────────────────────
    # Print Results
    # ──────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("LATE-DAY GOLDEN GATE REVERSAL STUDY")
    print("GG first opens in last 2 hours → where does the day close?")
    print("=" * 70)
    print(f"\nTotal trading days: {total_days:,}")

    # ── BULLISH ──
    print(f"\n{'─'*60}")
    print(f"BULLISH: GG opens upside (hit +38.2%) at 14:00-15:59")
    print(f"{'─'*60}")
    n = bull["total"]
    print(f"  Total qualifying days: {n:,}")
    if n > 0:
        pct_below_trig = bull["close_below_trigger"] / n * 100
        pct_below_prev = bull["close_below_prev"] / n * 100
        pct_gg_done = bull["gg_completed"] / n * 100
        print(f"\n  Close below call trigger (23.6%): {bull['close_below_trigger']:>4} / {n} = {pct_below_trig:.1f}%")
        print(f"  Close below prev close:           {bull['close_below_prev']:>4} / {n} = {pct_below_prev:.1f}%")
        print(f"  GG completed (hit 61.8%):         {bull['gg_completed']:>4} / {n} = {pct_gg_done:.1f}%")

        print(f"\n  By hour:")
        print(f"  {'Hour':<8s} {'n':>5s} {'<Trig':>7s} {'<Trig%':>8s} {'<Prev':>7s} {'<Prev%':>8s} {'GG%':>7s}")
        for hour in sorted(bull["by_hour"].keys()):
            h = bull["by_hour"][hour]
            hn = h["total"]
            bt = h["close_below_trigger"] / hn * 100 if hn else 0
            bp = h["close_below_prev"] / hn * 100 if hn else 0
            gg = h["gg_completed"] / hn * 100 if hn else 0
            print(f"  {hour:02d}:00   {hn:5d} {h['close_below_trigger']:7d} {bt:7.1f}% {h['close_below_prev']:7d} {bp:7.1f}% {gg:6.1f}%")

        print(f"\n  Where does the day close? (zone breakdown)")
        zone_order = ["above_0618", "0382_to_0618", "trigger_to_0382",
                       "prev_to_trigger", "below_prev_above_lower_trig", "below_lower_trigger"]
        zone_labels = {
            "above_0618": "Above 61.8% (GG completed, held)",
            "0382_to_0618": "38.2% to 61.8% (inside GG)",
            "trigger_to_0382": "Trigger to 38.2% (above trigger)",
            "prev_to_trigger": "Prev close to trigger (mild fade)",
            "below_prev_above_lower_trig": "Below prev, above lower trigger",
            "below_lower_trigger": "Below lower trigger (full reversal)",
        }
        for zone in zone_order:
            cnt = bull["close_zones"].get(zone, 0)
            pct = cnt / n * 100
            print(f"    {zone_labels[zone]:<48s} {cnt:4d}  {pct:5.1f}%")

    # Comparison with early entries
    if bull_early["total"] > 0:
        en = bull_early["total"]
        print(f"\n  COMPARISON — Early entries (09:30-10:59):")
        print(f"    n={en:,}, close below trigger: {bull_early['close_below_trigger']/en*100:.1f}%, close below prev: {bull_early['close_below_prev']/en*100:.1f}%")

    # ── BEARISH ──
    print(f"\n{'─'*60}")
    print(f"BEARISH: GG opens downside (hit -38.2%) at 14:00-15:59")
    print(f"{'─'*60}")
    n = bear["total"]
    print(f"  Total qualifying days: {n:,}")
    if n > 0:
        pct_above_trig = bear["close_above_trigger"] / n * 100
        pct_above_prev = bear["close_above_prev"] / n * 100
        pct_gg_done = bear["gg_completed"] / n * 100
        print(f"\n  Close above put trigger (-23.6%): {bear['close_above_trigger']:>4} / {n} = {pct_above_trig:.1f}%")
        print(f"  Close above prev close:            {bear['close_above_prev']:>4} / {n} = {pct_above_prev:.1f}%")
        print(f"  GG completed (hit -61.8%):         {bear['gg_completed']:>4} / {n} = {pct_gg_done:.1f}%")

        print(f"\n  By hour:")
        print(f"  {'Hour':<8s} {'n':>5s} {'>Trig':>7s} {'>Trig%':>8s} {'>Prev':>7s} {'>Prev%':>8s} {'GG%':>7s}")
        for hour in sorted(bear["by_hour"].keys()):
            h = bear["by_hour"][hour]
            hn = h["total"]
            at = h["close_above_trigger"] / hn * 100 if hn else 0
            ap = h["close_above_prev"] / hn * 100 if hn else 0
            gg = h["gg_completed"] / hn * 100 if hn else 0
            print(f"  {hour:02d}:00   {hn:5d} {h['close_above_trigger']:7d} {at:7.1f}% {h['close_above_prev']:7d} {ap:7.1f}% {gg:6.1f}%")

        print(f"\n  Where does the day close? (zone breakdown)")
        bear_zone_order = ["below_0618", "0382_to_0618", "trigger_to_0382",
                           "prev_to_trigger", "above_prev_below_upper_trig", "above_upper_trigger"]
        bear_zone_labels = {
            "below_0618": "Below -61.8% (GG completed, held)",
            "0382_to_0618": "-38.2% to -61.8% (inside GG)",
            "trigger_to_0382": "Put trigger to -38.2% (below trigger)",
            "prev_to_trigger": "Prev close to put trigger (mild bounce)",
            "above_prev_below_upper_trig": "Above prev, below upper trigger",
            "above_upper_trigger": "Above upper trigger (full reversal)",
        }
        for zone in bear_zone_order:
            cnt = bear["close_zones"].get(zone, 0)
            pct = cnt / n * 100
            print(f"    {zone_labels.get(zone, zone):<48s} {cnt:4d}  {pct:5.1f}%")

    if bear_early["total"] > 0:
        en = bear_early["total"]
        print(f"\n  COMPARISON — Early entries (09:30-10:59):")
        print(f"    n={en:,}, close above trigger: {bear_early['close_above_trigger']/en*100:.1f}%, close above prev: {bear_early['close_above_prev']/en*100:.1f}%")

    # ── Export dates ──
    import json
    export = {
        "bull_late": bull["dates"],
        "bear_late": bear["dates"],
    }
    with open("/root/milkman/data/late-gg-dates.json", "w") as f:
        json.dump(export, f, separators=(",", ":"))
    print(f"\nExported {len(bull['dates'])} bull + {len(bear['dates'])} bear dates to late-gg-dates.json")

    conn.close()


if __name__ == "__main__":
    main()
