"""
Golden Gate Subway Stats conditioned on 60-minute Phase Oscillator snapshots.

PO Snapshot = (zone, slope, state)
- Zone: High (>61.8), Mid (-61.8 to 61.8), Low (<-61.8)
- Slope: Rising (PO > PO_prev), Falling
- State: Compression, Bull Expansion (PO>=0 + no compression), Bear Expansion (PO<0 + no compression)
"""

import os
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def classify_po(po_val, po_prev, compression):
    """Classify a Phase Oscillator reading into (zone, slope, state)."""
    # Zone
    if po_val > 61.8:
        zone = "high"
    elif po_val < -61.8:
        zone = "low"
    else:
        zone = "mid"

    # Slope
    slope = "rising" if po_val > po_prev else "falling"

    # State
    if compression == 1:
        state = "compression"
    elif po_val >= 0:
        state = "bull_exp"
    else:
        state = "bear_exp"

    return zone, slope, state


def main():
    conn = sqlite3.connect(DB_PATH)

    # Load 10-minute data for trigger/completion detection (RTH only)
    print("Loading 10m data...", flush=True)
    df10 = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "prev_close, atr_14 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df10 = df10.set_index("timestamp").sort_index()
    df10 = df10.between_time("09:30", "15:59")
    df10 = df10.dropna(subset=["prev_close", "atr_14"])

    # Load 60-minute Phase Oscillator data
    print("Loading 60m Phase Oscillator...", flush=True)
    df60 = pd.read_sql_query(
        "SELECT timestamp, phase_oscillator, compression "
        "FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df60 = df60.set_index("timestamp").sort_index()

    # Pre-compute PO slope (current vs previous bar)
    df60["po_prev"] = df60["phase_oscillator"].shift(1)

    # For fast lookup: for a given 10m timestamp, find the most recent 60m bar
    # Build a mapping: each 10m bar -> nearest prior 60m PO reading
    print("Mapping 10m bars to 60m PO snapshots...", flush=True)
    po_vals = df60["phase_oscillator"]
    po_prevs = df60["po_prev"]
    po_comp = df60["compression"]

    # Use merge_asof for efficient time-based join
    df10_reset = df10.reset_index()
    df60_reset = df60.reset_index()
    merged = pd.merge_asof(
        df10_reset[["timestamp"]],
        df60_reset[["timestamp", "phase_oscillator", "po_prev", "compression"]],
        on="timestamp",
        direction="backward",
        suffixes=("", "_60m")
    )
    df10["po_60m"] = merged["phase_oscillator"].values
    df10["po_prev_60m"] = merged["po_prev"].values
    df10["compression_60m"] = merged["compression"].values

    df10["date"] = df10.index.date

    # --- Compute Golden Gate stats conditioned on PO snapshot ---
    print("Computing conditioned Golden Gate stats...\n")

    # Results structure: snapshot_key -> {direction -> {trigger_cat -> {total, completed}}}
    results = {}

    for date, group in df10.groupby("date"):
        first = group.iloc[0]
        upper_trigger = first["atr_upper_0382"]   # GG entry at 38.2%
        lower_trigger = first["atr_lower_0382"]
        upper_gate = first["atr_upper_0618"]     # GG completion at 61.8%
        lower_gate = first["atr_lower_0618"]

        if pd.isna(upper_trigger):
            continue

        # --- BULLISH ---
        if first["open"] >= upper_trigger:
            trigger_cat = "open"
            trigger_idx = 0
        else:
            hit = group["high"] >= upper_trigger
            if hit.any():
                trigger_idx = hit.values.argmax()
                trigger_cat = group.index[trigger_idx].hour
            else:
                trigger_cat = None

        if trigger_cat is not None:
            row = group.iloc[trigger_idx]
            po_val = row.get("po_60m", np.nan)
            po_prev = row.get("po_prev_60m", np.nan)
            comp = row.get("compression_60m", 0)

            if pd.notna(po_val) and pd.notna(po_prev):
                zone, slope, state = classify_po(po_val, po_prev, comp)
                key = (zone, slope, state)

                if key not in results:
                    results[key] = {"bull": {"total": 0, "completed": 0},
                                    "bear": {"total": 0, "completed": 0}}

                results[key]["bull"]["total"] += 1

                # Check completion
                remaining = group.iloc[trigger_idx:]
                if (remaining["high"] >= upper_gate).any():
                    results[key]["bull"]["completed"] += 1

        # --- BEARISH ---
        if first["open"] <= lower_trigger:
            trigger_cat = "open"
            trigger_idx = 0
        else:
            hit = group["low"] <= lower_trigger
            if hit.any():
                trigger_idx = hit.values.argmax()
                trigger_cat = group.index[trigger_idx].hour
            else:
                trigger_cat = None

        if trigger_cat is not None:
            row = group.iloc[trigger_idx]
            po_val = row.get("po_60m", np.nan)
            po_prev = row.get("po_prev_60m", np.nan)
            comp = row.get("compression_60m", 0)

            if pd.notna(po_val) and pd.notna(po_prev):
                zone, slope, state = classify_po(po_val, po_prev, comp)
                key = (zone, slope, state)

                if key not in results:
                    results[key] = {"bull": {"total": 0, "completed": 0},
                                    "bear": {"total": 0, "completed": 0}}

                results[key]["bear"]["total"] += 1

                remaining = group.iloc[trigger_idx:]
                if (remaining["low"] <= lower_gate).any():
                    results[key]["bear"]["completed"] += 1

    # --- Print Results ---
    print("=" * 80)
    print("GOLDEN GATE COMPLETION RATES BY 60m PHASE OSCILLATOR SNAPSHOT")
    print("=" * 80)

    # Overall baseline
    total_bull = sum(v["bull"]["total"] for v in results.values())
    total_bull_done = sum(v["bull"]["completed"] for v in results.values())
    total_bear = sum(v["bear"]["total"] for v in results.values())
    total_bear_done = sum(v["bear"]["completed"] for v in results.values())
    print(f"\nBaseline: Bull GG {total_bull_done}/{total_bull} = {total_bull_done/total_bull*100:.1f}%"
          f"   Bear GG {total_bear_done}/{total_bear} = {total_bear_done/total_bear*100:.1f}%")

    # Sort by total count descending
    sorted_keys = sorted(results.keys(),
                         key=lambda k: results[k]["bull"]["total"] + results[k]["bear"]["total"],
                         reverse=True)

    print(f"\n{'PO Snapshot':<35s} {'Bull N':>7s} {'Bull%':>7s} {'Bear N':>7s} {'Bear%':>7s} {'Total N':>8s}")
    print("-" * 80)

    for key in sorted_keys:
        zone, slope, state = key
        label = f"({zone}, {slope}, {state})"
        v = results[key]
        bn = v["bull"]["total"]
        bd = v["bull"]["completed"]
        bpct = bd / bn * 100 if bn > 0 else 0
        an = v["bear"]["total"]
        ad = v["bear"]["completed"]
        apct = ad / an * 100 if an > 0 else 0
        total_n = bn + an
        if total_n < 20:  # skip tiny samples
            continue
        print(f"  {label:<33s} {bn:7d} {bpct:6.1f}% {an:7d} {apct:6.1f}% {total_n:8d}")

    # Grouped summaries
    print(f"\n{'--- By Zone ---'}")
    for zone in ["high", "mid", "low"]:
        bn = sum(v["bull"]["total"] for k, v in results.items() if k[0] == zone)
        bd = sum(v["bull"]["completed"] for k, v in results.items() if k[0] == zone)
        an = sum(v["bear"]["total"] for k, v in results.items() if k[0] == zone)
        ad = sum(v["bear"]["completed"] for k, v in results.items() if k[0] == zone)
        bpct = bd / bn * 100 if bn > 0 else 0
        apct = ad / an * 100 if an > 0 else 0
        print(f"  {zone:<10s}  Bull: {bd:>4d}/{bn:<4d} = {bpct:5.1f}%   Bear: {ad:>4d}/{an:<4d} = {apct:5.1f}%")

    print(f"\n{'--- By Slope ---'}")
    for slope in ["rising", "falling"]:
        bn = sum(v["bull"]["total"] for k, v in results.items() if k[1] == slope)
        bd = sum(v["bull"]["completed"] for k, v in results.items() if k[1] == slope)
        an = sum(v["bear"]["total"] for k, v in results.items() if k[1] == slope)
        ad = sum(v["bear"]["completed"] for k, v in results.items() if k[1] == slope)
        bpct = bd / bn * 100 if bn > 0 else 0
        apct = ad / an * 100 if an > 0 else 0
        print(f"  {slope:<10s}  Bull: {bd:>4d}/{bn:<4d} = {bpct:5.1f}%   Bear: {ad:>4d}/{an:<4d} = {apct:5.1f}%")

    print(f"\n{'--- By State ---'}")
    for state in ["bull_exp", "bear_exp", "compression"]:
        bn = sum(v["bull"]["total"] for k, v in results.items() if k[2] == state)
        bd = sum(v["bull"]["completed"] for k, v in results.items() if k[2] == state)
        an = sum(v["bear"]["total"] for k, v in results.items() if k[2] == state)
        ad = sum(v["bear"]["completed"] for k, v in results.items() if k[2] == state)
        bpct = bd / bn * 100 if bn > 0 else 0
        apct = ad / an * 100 if an > 0 else 0
        print(f"  {state:<13s}  Bull: {bd:>4d}/{bn:<4d} = {bpct:5.1f}%   Bear: {ad:>4d}/{an:<4d} = {apct:5.1f}%")

    # Top/bottom performing snapshots
    print(f"\n{'--- Best & Worst Snapshots (min 50 triggers) ---'}")
    for direction in ["bull", "bear"]:
        print(f"\n  {direction.upper()}ISH Golden Gate:")
        valid = [(k, v[direction]["completed"]/v[direction]["total"]*100, v[direction]["total"])
                 for k, v in results.items() if v[direction]["total"] >= 50]
        valid.sort(key=lambda x: x[1], reverse=True)
        print(f"    {'Best:':<8s}", end="")
        for k, pct, n in valid[:3]:
            print(f"  ({k[0]},{k[1]},{k[2]}) {pct:.1f}% (n={n})", end="")
        print()
        print(f"    {'Worst:':<8s}", end="")
        for k, pct, n in valid[-3:]:
            print(f"  ({k[0]},{k[1]},{k[2]}) {pct:.1f}% (n={n})", end="")
        print()

    conn.close()


if __name__ == "__main__":
    main()
