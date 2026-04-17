"""
4H PO Rollover Confluence Study

Base signal: V2 — 4H PO peak ≥80, cross below 80 (N≈118)
Target: ≥1.0% intraday drop within 5 days (V2 baseline ~51%)

Confluence factors tested at signal time:
  F1: Daily PO zone × direction (high/mid/low × rising/falling)
  F2: Weekly PO zone
  F3: 1H PO compression active / recently ended
  F4: 1H PO zone at signal
  F5: 4H signal bar time-of-day
  F6: 4H signal bar day-of-week
  F7: Daily ATR position (intraday context)
  F8: Daily candle: close above/below daily EMA21 at signal
  F9: 4H EMA trend (EMA8 vs EMA21) — trend state

Each factor reported with hit rate + sample size. Then top combos tested.
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")


def classify_po(po_value):
    """Zone classification: high (>61.8), mid (-61.8 to 61.8), low (<-61.8)."""
    if pd.isna(po_value):
        return "unk"
    if po_value > 61.8:
        return "high"
    if po_value < -61.8:
        return "low"
    return "mid"


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading data...")
    df4h = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_8, ema_21, "
        "phase_oscillator, phase_zone, po_compression "
        "FROM ind_4h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp").dropna(subset=["phase_oscillator"])

    df1d = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, ema_21, phase_oscillator, "
        "phase_zone, atr_14, prev_close "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")

    df1w = pd.read_sql_query(
        "SELECT timestamp, close, phase_oscillator, phase_zone "
        "FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")

    df1h = pd.read_sql_query(
        "SELECT timestamp, phase_oscillator, po_compression "
        "FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    ).set_index("timestamp")

    conn.close()

    # ─── Find V2 signals ───
    po = df4h["phase_oscillator"]
    was_above = False
    peak = 0
    signals = []
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
            signals.append({
                "signal_time": df4h.index[i],
                "signal_idx_4h": i,
                "peak_po": peak,
                "signal_po": cur,
                "signal_close": df4h.iloc[i]["close"],
                "prev_4h_po": prev,
            })
            was_above = False
            peak = 0

    print(f"V2 signals: {len(signals)}")

    # ─── For each signal, collect confluence factors + forward outcome ───
    df1d_sorted = df1d.sort_index()
    df1w_sorted = df1w.sort_index()
    df1h_sorted = df1h.sort_index()

    results = []
    for sig in signals:
        sig_time = sig["signal_time"]
        sig_date = sig_time.normalize()
        sig_close = sig["signal_close"]
        idx_4h = sig["signal_idx_4h"]

        # Daily context: daily bar for signal date
        dloc = df1d_sorted.index.searchsorted(sig_date)
        if dloc >= len(df1d_sorted):
            continue
        if df1d_sorted.index[dloc] < sig_date:
            dloc += 1
        if dloc >= len(df1d_sorted):
            continue
        drow = df1d_sorted.iloc[dloc]

        # Daily PO state (using prev day's daily PO since current day isn't closed yet)
        prev_drow = df1d_sorted.iloc[dloc - 1] if dloc > 0 else None
        d_po_zone = classify_po(prev_drow["phase_oscillator"]) if prev_drow is not None else "unk"
        # PO direction: compare current day's intra-day PO vs prev day? We don't have that.
        # Use prev 2 daily PO readings for direction
        prev_prev_drow = df1d_sorted.iloc[dloc - 2] if dloc > 1 else None
        if prev_drow is not None and prev_prev_drow is not None:
            d_po_rising = prev_drow["phase_oscillator"] > prev_prev_drow["phase_oscillator"]
        else:
            d_po_rising = None

        # Weekly PO state: most recent weekly bar ending before sig_date
        wloc = df1w_sorted.index.searchsorted(sig_date)
        if wloc > 0:
            wrow = df1w_sorted.iloc[wloc - 1]
            w_po_zone = classify_po(wrow["phase_oscillator"])
        else:
            w_po_zone = "unk"

        # 1H PO state at signal time
        hloc = df1h_sorted.index.searchsorted(sig_time)
        if hloc > 0:
            hrow = df1h_sorted.iloc[hloc - 1]
            h_po_zone = classify_po(hrow["phase_oscillator"])
            h_compression = bool(hrow["po_compression"]) if pd.notna(hrow["po_compression"]) else False
        else:
            h_po_zone = "unk"
            h_compression = False

        # 1H PO compression that recently ended (within last 4 hours)
        h_recent_compression = False
        if hloc >= 4:
            recent_hrs = df1h_sorted.iloc[hloc - 4:hloc]
            if "po_compression" in recent_hrs.columns:
                h_recent_compression = recent_hrs["po_compression"].any()

        # 4H signal bar time-of-day and day-of-week
        hour_of_day = sig_time.hour
        day_of_week = sig_time.dayofweek  # 0=Mon

        # Daily ATR position (signal close vs prev day close in daily ATR units)
        d_atr_pos = None
        if prev_drow is not None and pd.notna(drow.get("atr_14")) and drow["atr_14"] > 0:
            d_atr_pos = (sig_close - prev_drow["close"]) / drow["atr_14"]

        # Daily EMA21 position
        d_above_ema21 = None
        if pd.notna(drow.get("ema_21")):
            d_above_ema21 = sig_close > drow["ema_21"]

        # 4H EMA trend (EMA8 vs EMA21)
        sig_4h = df4h.iloc[idx_4h]
        ema8_above_21 = None
        if pd.notna(sig_4h.get("ema_8")) and pd.notna(sig_4h.get("ema_21")):
            ema8_above_21 = sig_4h["ema_8"] > sig_4h["ema_21"]

        # ─── Forward outcome: max intraday drop over 3d/5d ───
        # Track from daily bar forward
        end_idx = min(dloc + 6, len(df1d_sorted))
        future = df1d_sorted.iloc[dloc + 1:end_idx]
        max_drop_5d = None
        hit_05 = hit_10 = hit_15 = hit_20 = False
        if len(future) > 0:
            min_low = future["low"].min()
            max_drop_5d = (min_low - sig_close) / sig_close * 100
            hit_05 = (future["low"] <= sig_close * 0.995).any()
            hit_10 = (future["low"] <= sig_close * 0.990).any()
            hit_15 = (future["low"] <= sig_close * 0.985).any()
            hit_20 = (future["low"] <= sig_close * 0.980).any()

        results.append({
            "signal_date": sig_date,
            "sig_time": sig_time,
            "peak_po": sig["peak_po"],
            "d_po_zone": d_po_zone,
            "d_po_rising": d_po_rising,
            "w_po_zone": w_po_zone,
            "h_po_zone": h_po_zone,
            "h_compression": h_compression,
            "h_recent_compression": h_recent_compression,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "d_atr_pos": d_atr_pos,
            "d_above_ema21": d_above_ema21,
            "ema8_above_21": ema8_above_21,
            "max_drop_5d": max_drop_5d,
            "hit_05_5d": hit_05,
            "hit_10_5d": hit_10,
            "hit_15_5d": hit_15,
            "hit_20_5d": hit_20,
        })

    rdf = pd.DataFrame(results).dropna(subset=["max_drop_5d"])
    n_total = len(rdf)
    baseline = rdf["hit_10_5d"].sum() / n_total * 100
    baseline_15 = rdf["hit_15_5d"].sum() / n_total * 100
    print(f"\nValid events: {n_total}")
    print(f"Baseline ≥1.0% 5d hit rate: {baseline:.1f}%")
    print(f"Baseline ≥1.5% 5d hit rate: {baseline_15:.1f}%")
    print(f"Baseline median 5d max drop: {rdf['max_drop_5d'].median():.2f}%")

    def show(title, groups):
        print(f"\n{'─' * 70}")
        print(f"  {title}")
        print(f"{'─' * 70}")
        print(f"  {'Group':<35s} {'N':>4s} {'≥0.5%':>7s} {'≥1.0%':>7s} {'≥1.5%':>7s} {'Med5d':>8s}")
        for gname, gdf in groups:
            n = len(gdf)
            if n < 4:
                print(f"  {gname:<35s} {n:>4d}   (too small)")
                continue
            h05 = gdf["hit_05_5d"].sum() / n * 100
            h10 = gdf["hit_10_5d"].sum() / n * 100
            h15 = gdf["hit_15_5d"].sum() / n * 100
            med = gdf["max_drop_5d"].median()
            delta = h10 - baseline
            tag = " ←" if abs(delta) >= 10 else ""
            print(f"  {gname:<35s} {n:>4d} {h05:>6.0f}% {h10:>6.0f}% {h15:>6.0f}% {med:>7.2f}%{tag}")

    # ═══════════════════════════════════════════════════════════════
    # F1: Daily PO Zone × Direction
    # ═══════════════════════════════════════════════════════════════
    groups = []
    for zone in ["high", "mid", "low"]:
        for d in [True, False]:
            subset = rdf[(rdf["d_po_zone"] == zone) & (rdf["d_po_rising"] == d)]
            groups.append((f"Daily PO {zone} + {'rising' if d else 'falling'}", subset))
    show("F1: DAILY PO ZONE × DIRECTION", groups)

    # Simpler: just daily zone
    show("F1b: DAILY PO ZONE (any direction)", [
        (f"Daily PO {zone}", rdf[rdf["d_po_zone"] == zone]) for zone in ["high", "mid", "low"]
    ])

    # ═══════════════════════════════════════════════════════════════
    # F2: Weekly PO Zone
    # ═══════════════════════════════════════════════════════════════
    show("F2: WEEKLY PO ZONE", [
        (f"Weekly PO {zone}", rdf[rdf["w_po_zone"] == zone]) for zone in ["high", "mid", "low"]
    ])

    # ═══════════════════════════════════════════════════════════════
    # F3: 1H PO Compression
    # ═══════════════════════════════════════════════════════════════
    show("F3: 1H PO COMPRESSION STATE AT SIGNAL", [
        ("1H in compression", rdf[rdf["h_compression"] == True]),
        ("1H NOT in compression", rdf[rdf["h_compression"] == False]),
        ("1H recent compression (4h)", rdf[rdf["h_recent_compression"] == True]),
        ("1H no recent compression", rdf[rdf["h_recent_compression"] == False]),
    ])

    # ═══════════════════════════════════════════════════════════════
    # F4: 1H PO Zone
    # ═══════════════════════════════════════════════════════════════
    show("F4: 1H PO ZONE AT SIGNAL", [
        (f"1H PO {zone}", rdf[rdf["h_po_zone"] == zone]) for zone in ["high", "mid", "low"]
    ])

    # ═══════════════════════════════════════════════════════════════
    # F5: Time of Day of 4H Signal
    # ═══════════════════════════════════════════════════════════════
    show("F5: 4H SIGNAL BAR TIME-OF-DAY", [
        (f"{hr:02d}:00 signal bar", rdf[rdf["hour_of_day"] == hr])
        for hr in sorted(rdf["hour_of_day"].unique())
    ])

    # ═══════════════════════════════════════════════════════════════
    # F6: Day of Week
    # ═══════════════════════════════════════════════════════════════
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    show("F6: 4H SIGNAL DAY-OF-WEEK", [
        (dow_names[d], rdf[rdf["day_of_week"] == d]) for d in range(5)
    ])

    # ═══════════════════════════════════════════════════════════════
    # F7: Daily ATR position
    # ═══════════════════════════════════════════════════════════════
    show("F7: DAILY ATR POSITION AT SIGNAL", [
        ("Below -trigger (-0.236)", rdf[rdf["d_atr_pos"] < -0.236]),
        ("Bear trigger box (-0.236 to 0)", rdf[(rdf["d_atr_pos"] >= -0.236) & (rdf["d_atr_pos"] < 0)]),
        ("Bull trigger box (0 to 0.236)", rdf[(rdf["d_atr_pos"] >= 0) & (rdf["d_atr_pos"] < 0.236)]),
        ("Above trigger (0.236 to 0.618)", rdf[(rdf["d_atr_pos"] >= 0.236) & (rdf["d_atr_pos"] < 0.618)]),
        ("Past 61.8% (>=0.618)", rdf[rdf["d_atr_pos"] >= 0.618]),
    ])

    # ═══════════════════════════════════════════════════════════════
    # F8: Daily EMA21 position
    # ═══════════════════════════════════════════════════════════════
    show("F8: PRICE vs DAILY EMA21", [
        ("Above daily EMA21", rdf[rdf["d_above_ema21"] == True]),
        ("Below daily EMA21", rdf[rdf["d_above_ema21"] == False]),
    ])

    # ═══════════════════════════════════════════════════════════════
    # F9: 4H EMA trend
    # ═══════════════════════════════════════════════════════════════
    show("F9: 4H EMA8 vs EMA21 AT SIGNAL", [
        ("4H EMA8 > EMA21 (bullish trend)", rdf[rdf["ema8_above_21"] == True]),
        ("4H EMA8 < EMA21 (bearish trend)", rdf[rdf["ema8_above_21"] == False]),
    ])

    # ═══════════════════════════════════════════════════════════════
    # COMBINATIONS: The promising confluences
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'═' * 70}")
    print(f"  TOP COMBINATIONS")
    print(f"{'═' * 70}")

    combos = [
        ("Weekly PO mid + Daily PO high",
         rdf[(rdf["w_po_zone"] == "mid") & (rdf["d_po_zone"] == "high")]),
        ("Weekly PO high + Daily PO high",
         rdf[(rdf["w_po_zone"] == "high") & (rdf["d_po_zone"] == "high")]),
        ("Daily PO high + falling",
         rdf[(rdf["d_po_zone"] == "high") & (rdf["d_po_rising"] == False)]),
        ("Daily PO high + falling + Weekly high",
         rdf[(rdf["d_po_zone"] == "high") & (rdf["d_po_rising"] == False) &
             (rdf["w_po_zone"] == "high")]),
        ("1H in compression + Daily PO high",
         rdf[(rdf["h_compression"] == True) & (rdf["d_po_zone"] == "high")]),
        ("1H recent compression + Daily PO high",
         rdf[(rdf["h_recent_compression"] == True) & (rdf["d_po_zone"] == "high")]),
        ("Daily PO high + 4H EMA bearish (rollover confirmed)",
         rdf[(rdf["d_po_zone"] == "high") & (rdf["ema8_above_21"] == False)]),
        ("4H EMA bearish cross at signal",
         rdf[rdf["ema8_above_21"] == False]),
        ("Daily ATR >= 0.618 + Daily PO high",
         rdf[(rdf["d_atr_pos"] >= 0.618) & (rdf["d_po_zone"] == "high")]),
        ("Daily ATR in trigger box + Weekly high",
         rdf[(rdf["d_atr_pos"].abs() < 0.236) & (rdf["w_po_zone"] == "high")]),
    ]
    show("Combinations", combos)

    # Save
    rdf.to_csv(os.path.join(BASE_DIR, "confluence_results.csv"), index=False)
    print("\nSaved to confluence_results.csv")


if __name__ == "__main__":
    main()
