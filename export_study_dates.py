"""
Export date lists for ALL study pages.
Each study gets a JSON file in /root/milkman/data/ keyed by row label,
with entries [{d:"2024-01-15", h:1}, ...] where h=1 means "yes" (outcome happened).
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import json
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
OUT_DIR = "/root/milkman/data"


def load_10m(conn):
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "atr_upper_0786, atr_lower_0786, "
        "atr_upper_100, atr_lower_100, "
        "prev_close, atr_14, "
        "ema_8, ema_13, ema_21, ema_48 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date
    df["hour"] = df.index.hour
    return df


def load_60m_po(conn):
    df60 = pd.read_sql_query(
        "SELECT timestamp, phase_oscillator, compression "
        "FROM ind_1h ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df60 = df60.set_index("timestamp").sort_index()
    df60["po_prev"] = df60["phase_oscillator"].shift(1)
    return df60


def classify_po(po_val, po_prev, compression):
    if po_val > 61.8:
        zone = "high"
    elif po_val < -61.8:
        zone = "low"
    else:
        zone = "mid"
    slope = "rising" if po_val > po_prev else "falling"
    if compression == 1:
        state = "compression"
    elif po_val >= 0:
        state = "bull_exp"
    else:
        state = "bear_exp"
    return zone, slope, state


def po_label(zone, slope):
    return f"PO {zone.title()} + {slope.title()}"


# ═══════════════════════════════════════════════
# 1. Golden Gate Subway Stats
# ═══════════════════════════════════════════════
def export_golden_gate(df):
    """For each day, find when trigger fires and whether GG completes.
    Row key = trigger time category (open, 09, 10, ... 15).
    h=1 if GG completed (hit 61.8%) by EOD."""
    dates = defaultdict(list)

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        for direction, trig_col, gate_col, comp_fn, prefix in [
            ("bull", "atr_upper_0382", "atr_upper_0618", lambda row, lvl: row["high"] >= lvl, "bull"),
            ("bear", "atr_lower_0382", "atr_lower_0618", lambda row, lvl: row["low"] <= lvl, "bear"),
        ]:
            trigger_lvl = first[trig_col]
            gate_lvl = first[gate_col]
            if pd.isna(trigger_lvl):
                continue

            if direction == "bull":
                hit_bars = group[group["high"] >= trigger_lvl]
                if first["open"] >= trigger_lvl:
                    cat = "open"
                    trigger_idx = 0
                elif len(hit_bars) > 0:
                    trigger_idx = hit_bars.index[0]
                    h = group.loc[trigger_idx].hour if not isinstance(trigger_idx, int) else group.index[trigger_idx].hour
                    cat = f"{h:02d}00"
                else:
                    continue
            else:
                hit_bars = group[group["low"] <= trigger_lvl]
                if first["open"] <= trigger_lvl:
                    cat = "open"
                    trigger_idx = 0
                elif len(hit_bars) > 0:
                    trigger_idx = hit_bars.index[0]
                    h = group.loc[trigger_idx].hour if not isinstance(trigger_idx, int) else group.index[trigger_idx].hour
                    cat = f"{h:02d}00"
                else:
                    continue

            # Did GG complete?
            if isinstance(trigger_idx, int):
                remaining = group.iloc[trigger_idx:]
            else:
                remaining = group[group.index >= trigger_idx]

            if direction == "bull":
                completed = (remaining["high"] >= gate_lvl).any()
            else:
                completed = (remaining["low"] <= gate_lvl).any()

            key = f"{prefix}_{cat}"
            dates[key].append({"d": str(date), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# 2. Bilbo Golden Gate (GG + 60m PO)
# ═══════════════════════════════════════════════
def export_bilbo_gg(df, df60):
    """Row key = PO state at trigger time. h=1 if GG completed."""
    # Merge 60m PO onto 10m data
    df_reset = df.reset_index()
    df60_reset = df60.reset_index()
    merged = pd.merge_asof(
        df_reset[["timestamp"]],
        df60_reset[["timestamp", "phase_oscillator", "po_prev", "compression"]],
        on="timestamp", direction="backward"
    )
    df["po_60m"] = merged["phase_oscillator"].values
    df["po_prev_60m"] = merged["po_prev"].values
    df["compression_60m"] = merged["compression"].values

    dates = defaultdict(list)

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        for direction, trig_col, gate_col, prefix in [
            ("bull", "atr_upper_0382", "atr_upper_0618", "bull"),
            ("bear", "atr_lower_0382", "atr_lower_0618", "bear"),
        ]:
            trigger_lvl = first[trig_col]
            gate_lvl = first[gate_col]
            if pd.isna(trigger_lvl):
                continue

            if direction == "bull":
                hit = group["high"] >= trigger_lvl
            else:
                hit = group["low"] <= trigger_lvl

            if first["open"] >= trigger_lvl if direction == "bull" else first["open"] <= trigger_lvl:
                trigger_idx = 0
            elif hit.any():
                trigger_idx = hit.values.argmax()
            else:
                continue

            row = group.iloc[trigger_idx]
            po_val = row.get("po_60m", np.nan)
            po_prev = row.get("po_prev_60m", np.nan)
            comp = row.get("compression_60m", 0)

            if pd.isna(po_val) or pd.isna(po_prev):
                continue

            zone, slope, state = classify_po(po_val, po_prev, comp)
            label = po_label(zone, slope)

            remaining = group.iloc[trigger_idx:]
            if direction == "bull":
                completed = (remaining["high"] >= gate_lvl).any()
            else:
                completed = (remaining["low"] <= gate_lvl).any()

            key = f"{prefix}_{label}"
            dates[key].append({"d": str(date), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# 3. GG Invalidation (Pullback Waterfall)
# ═══════════════════════════════════════════════
def export_gg_invalidation(df):
    """Row key = deepest pullback level. h=1 if GG still completed."""
    dates = defaultdict(list)

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        for direction, prefix in [("bull", "bull"), ("bear", "bear")]:
            if direction == "bull":
                trig = first["atr_upper_0382"]
                gate = first["atr_upper_0618"]
                if pd.isna(trig):
                    continue
                hit = group["high"] >= trig
            else:
                trig = first["atr_lower_0382"]
                gate = first["atr_lower_0618"]
                if pd.isna(trig):
                    continue
                hit = group["low"] <= trig

            if not hit.any() and not (
                (first["open"] >= trig) if direction == "bull" else (first["open"] <= trig)
            ):
                continue

            if direction == "bull":
                if first["open"] >= trig:
                    trigger_idx = 0
                else:
                    trigger_idx = hit.values.argmax()
                remaining = group.iloc[trigger_idx:]
                completed = (remaining["high"] >= gate).any()
                # Deepest pullback from trigger
                worst = remaining["low"].min()
                levels = [
                    ("held_0382", first["atr_upper_0382"]),
                    ("pulled_ema8", None),  # handled separately
                    ("pulled_ema21", None),
                    ("pulled_trigger", first["atr_upper_trigger"]),
                    ("broke_trigger", None),
                ]
                if worst >= first["atr_upper_0382"]:
                    pb = "held_0382"
                elif worst >= first.get("ema_8", 0):
                    pb = "pulled_ema8"
                elif worst >= first.get("ema_21", 0):
                    pb = "pulled_ema21"
                elif worst >= first["atr_upper_trigger"]:
                    pb = "pulled_trigger"
                else:
                    pb = "broke_trigger"
            else:
                if first["open"] <= trig:
                    trigger_idx = 0
                else:
                    trigger_idx = hit.values.argmax()
                remaining = group.iloc[trigger_idx:]
                completed = (remaining["low"] <= gate).any()
                worst = remaining["high"].max()
                if worst <= first["atr_lower_0382"]:
                    pb = "held_0382"
                elif worst <= first.get("ema_8", 9999):
                    pb = "pulled_ema8"
                elif worst <= first.get("ema_21", 9999):
                    pb = "pulled_ema21"
                elif worst <= first["atr_lower_trigger"]:
                    pb = "pulled_trigger"
                else:
                    pb = "broke_trigger"

            key = f"{prefix}_{pb}"
            dates[key].append({"d": str(date), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# 4. GG Entries
# ═══════════════════════════════════════════════
def export_gg_entries(df):
    """Row key = entry type. h=1 if GG completed from that entry."""
    dates = defaultdict(list)

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        for direction, prefix in [("bull", "bull"), ("bear", "bear")]:
            if direction == "bull":
                trig = first["atr_upper_0382"]
                gate = first["atr_upper_0618"]
                if pd.isna(trig):
                    continue
                hit = group["high"] >= trig
                if not hit.any() and first["open"] < trig:
                    continue
                trigger_idx = 0 if first["open"] >= trig else hit.values.argmax()
                remaining = group.iloc[trigger_idx:]
                completed = (remaining["high"] >= gate).any()

                # Check which entries appeared
                # Immediate entry at 38.2%
                dates[f"{prefix}_immediate"].append({"d": str(date), "h": 1 if completed else 0})

                # EMA 8 pullback
                ema8_touch = (remaining["low"] <= remaining["ema_8"]).any() if "ema_8" in remaining.columns else False
                if ema8_touch:
                    dates[f"{prefix}_ema8"].append({"d": str(date), "h": 1 if completed else 0})

                # EMA 21 pullback
                ema21_touch = (remaining["low"] <= remaining["ema_21"]).any() if "ema_21" in remaining.columns else False
                if ema21_touch:
                    dates[f"{prefix}_ema21"].append({"d": str(date), "h": 1 if completed else 0})

            else:
                trig = first["atr_lower_0382"]
                gate = first["atr_lower_0618"]
                if pd.isna(trig):
                    continue
                hit = group["low"] <= trig
                if not hit.any() and first["open"] > trig:
                    continue
                trigger_idx = 0 if first["open"] <= trig else hit.values.argmax()
                remaining = group.iloc[trigger_idx:]
                completed = (remaining["low"] <= gate).any()

                dates[f"{prefix}_immediate"].append({"d": str(date), "h": 1 if completed else 0})

                ema8_touch = (remaining["high"] >= remaining["ema_8"]).any() if "ema_8" in remaining.columns else False
                if ema8_touch:
                    dates[f"{prefix}_ema8"].append({"d": str(date), "h": 1 if completed else 0})

                ema21_touch = (remaining["high"] >= remaining["ema_21"]).any() if "ema_21" in remaining.columns else False
                if ema21_touch:
                    dates[f"{prefix}_ema21"].append({"d": str(date), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# 5. Trigger Box
# ═══════════════════════════════════════════════
def export_trigger_box(df):
    """Row key = box direction + hold duration. h=1 if GG completed."""
    dates = defaultdict(list)

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        prev_close = first["prev_close"]
        upper_trigger = first["atr_upper_trigger"]
        lower_trigger = first["atr_lower_trigger"]
        upper_0382 = first["atr_upper_0382"]
        lower_0382 = first["atr_lower_0382"]
        upper_0618 = first["atr_upper_0618"]
        lower_0618 = first["atr_lower_0618"]
        if pd.isna(prev_close):
            continue

        day_open = first["open"]

        # Bullish box: open between prev_close and upper_trigger
        if prev_close <= day_open <= upper_trigger:
            # Check hold durations
            for mins, label in [(30, "30min"), (60, "1hr"), (120, "2hr")]:
                bars = mins // 10
                if len(group) >= bars:
                    hold_slice = group.iloc[:bars]
                    held = (hold_slice["low"] >= prev_close).all()
                    if held:
                        # Did GG fire and complete?
                        triggered = (group["high"] >= upper_0382).any()
                        completed = triggered and (group["high"] >= upper_0618).any()
                        dates[f"bull_held_{label}"].append({"d": str(date), "h": 1 if completed else 0})

            # All bull box days
            triggered = (group["high"] >= upper_0382).any()
            completed = triggered and (group["high"] >= upper_0618).any()
            dates["bull_all"].append({"d": str(date), "h": 1 if completed else 0})

        # Bearish box: open between lower_trigger and prev_close
        if lower_trigger <= day_open <= prev_close:
            for mins, label in [(30, "30min"), (60, "1hr"), (120, "2hr")]:
                bars = mins // 10
                if len(group) >= bars:
                    hold_slice = group.iloc[:bars]
                    held = (hold_slice["high"] <= prev_close).all()
                    if held:
                        triggered = (group["low"] <= lower_0382).any()
                        completed = triggered and (group["low"] <= lower_0618).any()
                        dates[f"bear_held_{label}"].append({"d": str(date), "h": 1 if completed else 0})

            triggered = (group["low"] <= lower_0382).any()
            completed = triggered and (group["low"] <= lower_0618).any()
            dates["bear_all"].append({"d": str(date), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# 6. Trigger Box Spreads
# ═══════════════════════════════════════════════
def export_trigger_box_spreads(df):
    """Row key = direction + hold + strike level. h=1 if spread wins (price didn't reach strike)."""
    dates = defaultdict(list)

    for date, group in df.groupby("date"):
        first = group.iloc[0]
        prev_close = first["prev_close"]
        upper_trigger = first["atr_upper_trigger"]
        lower_trigger = first["atr_lower_trigger"]
        if pd.isna(prev_close):
            continue

        day_open = first["open"]
        day_high = group["high"].max()
        day_low = group["low"].min()

        strike_levels = {
            "0382": (first["atr_upper_0382"], first["atr_lower_0382"]),
            "050": (first.get("atr_upper_050", np.nan), first.get("atr_lower_050", np.nan)),
            "0618": (first["atr_upper_0618"], first["atr_lower_0618"]),
            "100": (first.get("atr_upper_100", np.nan), first.get("atr_lower_100", np.nan)),
        }

        # Bear box → sell call spreads (above)
        if lower_trigger <= day_open <= prev_close:
            for strike_key, (upper_strike, _) in strike_levels.items():
                if pd.isna(upper_strike):
                    continue
                win = day_high < upper_strike
                dates[f"bear_call_{strike_key}"].append({"d": str(date), "h": 1 if win else 0})

        # Bull box → sell put spreads (below)
        if prev_close <= day_open <= upper_trigger:
            for strike_key, (_, lower_strike) in strike_levels.items():
                if pd.isna(lower_strike):
                    continue
                win = day_low > lower_strike
                dates[f"bull_put_{strike_key}"].append({"d": str(date), "h": 1 if win else 0})

    return dates


# ═══════════════════════════════════════════════
# 7. Gap Fills
# ═══════════════════════════════════════════════
def export_gap_fills(conn):
    """Row key = direction + gap size bucket. h=1 if gap filled same day."""
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, prev_close, atr_14 "
        "FROM ind_10m ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["prev_close"])
    df["date"] = df.index.date

    buckets = [
        (0, 0.0025, "lt025"),
        (0.0025, 0.005, "025_05"),
        (0.005, 0.01, "05_1"),
        (0.01, 0.02, "1_2"),
        (0.02, 1.0, "2plus"),
    ]

    dates = defaultdict(list)

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

        for lo, hi, label in buckets:
            if lo <= gap_abs < hi:
                if gap_pct > 0:
                    filled = day_low <= prev_close
                    dates[f"up_{label}"].append({"d": str(date), "h": 1 if filled else 0})
                elif gap_pct < 0:
                    filled = day_high >= prev_close
                    dates[f"down_{label}"].append({"d": str(date), "h": 1 if filled else 0})
                break

    return dates


# ═══════════════════════════════════════════════
# 8. Multi-Day GG (Weekly ATR)
# ═══════════════════════════════════════════════
def export_multiday_gg(conn):
    """Row key = direction + PO label. h=1 if GG completed within 5 days."""
    weekly = pd.read_sql_query(
        "SELECT timestamp, close, atr_14, prev_close, "
        "atr_upper_0382, atr_lower_0382, atr_upper_0618, atr_lower_0618, "
        "atr_upper_100, atr_lower_100 "
        "FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    weekly = weekly.set_index("timestamp").sort_index().dropna(subset=["prev_close", "atr_14"])

    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, phase_oscillator, compression "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()
    daily["po_yesterday"] = daily["phase_oscillator"].shift(1)
    daily["po_day_before"] = daily["phase_oscillator"].shift(2)

    dr = daily.reset_index()
    wr = weekly.reset_index()
    merged = pd.merge_asof(dr[["timestamp"]], wr, on="timestamp", direction="backward", suffixes=("", "_wk"))
    for col in ["prev_close", "atr_upper_0382", "atr_lower_0382",
                "atr_upper_0618", "atr_lower_0618", "atr_upper_100", "atr_lower_100"]:
        daily[f"wk_{col}"] = merged[col].values

    idx = daily.index.tolist()
    n = len(idx)
    dates = defaultdict(list)

    for direction in ["bull", "bear"]:
        for i in range(n):
            row = daily.iloc[i]
            if direction == "bull":
                entry = row.get("wk_atr_upper_0382")
                exit_lvl = row.get("wk_atr_upper_0618")
                hit = row["high"] >= entry if pd.notna(entry) else False
            else:
                entry = row.get("wk_atr_lower_0382")
                exit_lvl = row.get("wk_atr_lower_0618")
                hit = row["low"] <= entry if pd.notna(entry) else False

            if not hit or pd.isna(entry) or pd.isna(exit_lvl):
                continue

            # Dedup within week
            if i > 0:
                prev = daily.iloc[i - 1]
                same_wk = (idx[i].isocalendar()[1] == idx[i-1].isocalendar()[1] and
                           idx[i].year == idx[i-1].year)
                if same_wk:
                    if direction == "bull" and prev["high"] >= entry:
                        continue
                    if direction == "bear" and prev["low"] <= entry:
                        continue

            po = row["po_yesterday"]
            po_prev = row["po_day_before"]
            if pd.isna(po) or pd.isna(po_prev):
                continue
            zone = "High" if po > 61.8 else ("Low" if po < -61.8 else "Mid")
            slope = "Rising" if po > po_prev else "Falling"
            po_label_str = f"{zone} + {slope}"

            # Check completion within 5 days
            end_idx = min(i + 5, n - 1)
            future = daily.iloc[i:end_idx + 1]
            if direction == "bull":
                completed = (future["high"] >= exit_lvl).any()
            else:
                completed = (future["low"] <= exit_lvl).any()

            key = f"{direction}_{po_label_str}"
            dates[key].append({"d": str(idx[i].date()), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# 9. Swing GG (Monthly ATR)
# ═══════════════════════════════════════════════
def rma(series, period):
    result = np.empty_like(series, dtype=float)
    result[0] = series.iloc[0]
    alpha = 1.0 / period
    for i in range(1, len(series)):
        result[i] = alpha * series.iloc[i] + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=series.index)


def export_swing_gg(conn):
    """Row key = direction + weekly PO label. h=1 if GG completed within 20 days."""
    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, phase_oscillator "
        "FROM ind_1d ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    daily = daily.set_index("timestamp").sort_index()

    weekly = pd.read_sql_query(
        "SELECT timestamp, phase_oscillator as weekly_po "
        "FROM ind_1w ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    weekly = weekly.set_index("timestamp").sort_index()
    weekly["wk_po_prev"] = weekly["weekly_po"].shift(1)
    weekly["wk_po_prev2"] = weekly["weekly_po"].shift(2)

    dr = daily.reset_index()
    wr = weekly.reset_index()
    m = pd.merge_asof(dr[["timestamp"]], wr[["timestamp", "wk_po_prev", "wk_po_prev2"]],
                       on="timestamp", direction="backward")
    daily["wk_po"] = m["wk_po_prev"].values
    daily["wk_po_prev"] = m["wk_po_prev2"].values

    # Monthly candles + ATR
    daily["month"] = daily.index.to_period("M")
    monthly = daily.groupby("month").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    )
    prev_close = monthly["close"].shift(1)
    tr = pd.concat([
        monthly["high"] - monthly["low"],
        (monthly["high"] - prev_close).abs(),
        (monthly["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    monthly["atr_14"] = rma(tr, 14)
    monthly["prev_close"] = prev_close
    for name, fib in [("0382", 0.382), ("0618", 0.618), ("100", 1.0)]:
        monthly[f"upper_{name}"] = monthly["prev_close"] + fib * monthly["atr_14"]
        monthly[f"lower_{name}"] = monthly["prev_close"] - fib * monthly["atr_14"]

    monthly_lookup = monthly.copy()
    monthly_lookup.index = monthly_lookup.index.to_timestamp()
    mr = monthly_lookup.reset_index().rename(columns={"month": "timestamp"})
    m2 = pd.merge_asof(dr[["timestamp"]], mr, on="timestamp", direction="backward", suffixes=("", "_mo"))
    for col in ["upper_0382", "lower_0382", "upper_0618", "lower_0618", "upper_100", "lower_100"]:
        if col in m2.columns:
            daily[f"mo_{col}"] = m2[col].values

    idx = daily.index.tolist()
    n = len(idx)
    dates = defaultdict(list)

    for direction in ["bull", "bear"]:
        for i in range(n):
            row = daily.iloc[i]
            if direction == "bull":
                entry = row.get("mo_upper_0382")
                exit_lvl = row.get("mo_upper_0618")
                hit = row["high"] >= entry if pd.notna(entry) else False
            else:
                entry = row.get("mo_lower_0382")
                exit_lvl = row.get("mo_lower_0618")
                hit = row["low"] <= entry if pd.notna(entry) else False

            if not hit or pd.isna(entry) or pd.isna(exit_lvl):
                continue

            # Dedup within month
            if i > 0:
                same_mo = idx[i].month == idx[i-1].month and idx[i].year == idx[i-1].year
                if same_mo:
                    prev = daily.iloc[i - 1]
                    if direction == "bull" and prev["high"] >= entry:
                        continue
                    if direction == "bear" and prev["low"] <= entry:
                        continue

            po = row["wk_po"]
            po_prev = row["wk_po_prev"]
            if pd.isna(po) or pd.isna(po_prev):
                continue
            zone = "High" if po > 61.8 else ("Low" if po < -61.8 else "Mid")
            slope = "Rising" if po > po_prev else "Falling"
            po_label_str = f"{zone} + {slope}"

            end_idx = min(i + 20, n - 1)
            future = daily.iloc[i:end_idx + 1]
            if direction == "bull":
                completed = (future["high"] >= exit_lvl).any()
            else:
                completed = (future["low"] <= exit_lvl).any()

            key = f"{direction}_{po_label_str}"
            dates[key].append({"d": str(idx[i].date()), "h": 1 if completed else 0})

    return dates


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════
def save(name, data):
    path = f"{OUT_DIR}/{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    total = sum(len(v) for v in data.values())
    print(f"  {name}: {len(data)} keys, {total} total dates → {path}")


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading 10m data...", flush=True)
    df = load_10m(conn)
    print(f"  {len(df):,} RTH 10m bars")

    print("Loading 60m PO...", flush=True)
    df60 = load_60m_po(conn)

    print("\nExporting study dates...", flush=True)

    print("1. Golden Gate Subway Stats")
    save("golden-gate-dates", export_golden_gate(df))

    print("2. Bilbo Golden Gate")
    save("bilbo-gg-dates", export_bilbo_gg(df.copy(), df60))

    print("3. GG Invalidation")
    save("gg-invalidation-dates", export_gg_invalidation(df))

    print("4. GG Entries")
    save("gg-entries-dates", export_gg_entries(df))

    print("5. Trigger Box")
    save("trigger-box-dates", export_trigger_box(df))

    print("6. Trigger Box Spreads")
    save("trigger-box-spreads-dates", export_trigger_box_spreads(df))

    print("7. Gap Fills")
    save("gap-fills-dates", export_gap_fills(conn))

    print("8. Multi-Day GG (Weekly ATR)")
    save("multiday-gg-dates", export_multiday_gg(conn))

    print("9. Swing GG (Monthly ATR)")
    save("swing-gg-dates", export_swing_gg(conn))

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
