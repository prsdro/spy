#!/usr/bin/env python3
"""Scratch ATR-anchor survey for published Milkman studies.

This does not modify live backtests or HTML. It reproduces selected study
metrics with either stored level columns or corrected period_index=1 ATR levels.
"""

import os
import sqlite3
import sys
from collections import defaultdict

os.environ.setdefault("PANDAS_USE_NUMEXPR", "0")
os.environ.setdefault("PANDAS_USE_BOTTLENECK", "0")
sys.modules.setdefault("numexpr", None)
sys.modules.setdefault("bottleneck", None)

import numpy as np
import pandas as pd


BASE_DIR = "/root/spy"
DB_PATH = os.path.join(BASE_DIR, "spy.db")

TRIGGER = 0.236
FIBS = {
    "trigger": TRIGGER,
    "0382": 0.382,
    "050": 0.500,
    "0618": 0.618,
    "0786": 0.786,
    "100": 1.000,
}


def pct(num, den):
    return num / den * 100 if den else np.nan


def add_levels(df, prefix=""):
    prev_close = df[f"{prefix}prev_close"]
    atr = df[f"{prefix}atr_14"]
    for label, fib in FIBS.items():
        if label == "trigger":
            upper_col = f"{prefix}atr_upper_trigger"
            lower_col = f"{prefix}atr_lower_trigger"
        else:
            upper_col = f"{prefix}atr_upper_{label}"
            lower_col = f"{prefix}atr_lower_{label}"
        df[upper_col] = prev_close + fib * atr
        df[lower_col] = prev_close - fib * atr
    return df


def attach_corrected_daily_levels(conn, intraday, needed_labels):
    daily = pd.read_sql_query(
        "SELECT timestamp, close, atr_14 FROM ind_1d ORDER BY timestamp",
        conn,
        parse_dates=["timestamp"],
    ).set_index("timestamp").sort_index()
    levels = pd.DataFrame(index=daily.index)
    levels["prev_close"] = daily["close"].shift(1)
    levels["atr_14"] = daily["atr_14"].shift(1)
    levels = add_levels(levels)
    levels["date"] = levels.index.date
    levels = levels.set_index("date")

    mapped = levels.reindex(intraday.index.date)
    intraday = intraday.copy()
    for col in ["prev_close", "atr_14"]:
        intraday[col] = mapped[col].values
    for label in needed_labels:
        if label == "trigger":
            cols = ["atr_upper_trigger", "atr_lower_trigger"]
        else:
            cols = [f"atr_upper_{label}", f"atr_lower_{label}"]
        for col in cols:
            intraday[col] = mapped[col].values
    return intraday


def multiday_gg(conn, corrected):
    if corrected:
        weekly = pd.read_sql_query(
            "SELECT timestamp, close, atr_14 FROM ind_1w ORDER BY timestamp",
            conn,
            parse_dates=["timestamp"],
        ).set_index("timestamp").sort_index()
        weekly["prev_close"] = weekly["close"].shift(1)
        weekly["atr_14"] = weekly["atr_14"].shift(1)
        weekly = add_levels(weekly)
        weekly = weekly.dropna(subset=["prev_close", "atr_14"])
    else:
        weekly = pd.read_sql_query(
            "SELECT timestamp, close, atr_14, prev_close, "
            "atr_upper_0382, atr_lower_0382, atr_upper_0618, atr_lower_0618, "
            "atr_upper_100, atr_lower_100, atr_upper_trigger, atr_lower_trigger "
            "FROM ind_1w ORDER BY timestamp",
            conn,
            parse_dates=["timestamp"],
        ).set_index("timestamp").sort_index()
        weekly = weekly.dropna(subset=["prev_close", "atr_14"])

    daily = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, phase_oscillator, compression "
        "FROM ind_1d ORDER BY timestamp",
        conn,
        parse_dates=["timestamp"],
    ).set_index("timestamp").sort_index()
    daily["po_yesterday"] = daily["phase_oscillator"].shift(1)
    daily["po_day_before"] = daily["phase_oscillator"].shift(2)

    daily_reset = daily.reset_index()
    weekly_reset = weekly.reset_index()
    merged = pd.merge_asof(
        daily_reset[["timestamp"]],
        weekly_reset,
        on="timestamp",
        direction="backward",
    )
    level_cols = [
        "prev_close",
        "atr_14",
        "atr_upper_0382",
        "atr_lower_0382",
        "atr_upper_0618",
        "atr_lower_0618",
        "atr_upper_100",
        "atr_lower_100",
        "atr_upper_trigger",
        "atr_lower_trigger",
    ]
    for col in level_cols:
        daily[f"wk_{col}"] = merged[col].values

    def classify_po(po, po_prev):
        if pd.isna(po) or pd.isna(po_prev):
            return None
        zone = "high" if po > 61.8 else ("low" if po < -61.8 else "mid")
        slope = "rising" if po > po_prev else "falling"
        return f"{zone}|{slope}"

    horizons = [1, 2, 3, 4, 5]
    out = {}
    dates = daily.index.tolist()

    for direction in ["bull", "bear"]:
        results = defaultdict(lambda: {"total": 0, **{f"complete_{h}d": 0 for h in horizons},
                                       **{f"full_atr_{h}d": 0 for h in horizons}})
        for i in range(len(daily)):
            row = daily.iloc[i]
            if direction == "bull":
                entry_level = row["wk_atr_upper_0382"]
                exit_level = row["wk_atr_upper_0618"]
                full_atr = row["wk_atr_upper_100"]
                entry_hit = row["high"] >= entry_level
            else:
                entry_level = row["wk_atr_lower_0382"]
                exit_level = row["wk_atr_lower_0618"]
                full_atr = row["wk_atr_lower_100"]
                entry_hit = row["low"] <= entry_level

            if pd.isna(entry_level) or pd.isna(exit_level) or not entry_hit:
                continue

            if i > 0:
                prev_row = daily.iloc[i - 1]
                if direction == "bull":
                    already_hit = prev_row["high"] >= entry_level
                else:
                    already_hit = prev_row["low"] <= entry_level
                same_week = (
                    dates[i].isocalendar()[1] == dates[i - 1].isocalendar()[1]
                    and dates[i].year == dates[i - 1].year
                )
                if same_week and already_hit:
                    continue

            po_key = classify_po(row["po_yesterday"], row["po_day_before"])
            if po_key is None:
                continue

            results[po_key]["total"] += 1
            for h in horizons:
                end_idx = min(i + h, len(daily) - 1)
                future_slice = daily.iloc[i : end_idx + 1]
                if direction == "bull":
                    if (future_slice["high"] >= exit_level).any():
                        results[po_key][f"complete_{h}d"] += 1
                    if (future_slice["high"] >= full_atr).any():
                        results[po_key][f"full_atr_{h}d"] += 1
                else:
                    if (future_slice["low"] <= exit_level).any():
                        results[po_key][f"complete_{h}d"] += 1
                    if (future_slice["low"] <= full_atr).any():
                        results[po_key][f"full_atr_{h}d"] += 1

        total = sum(v["total"] for v in results.values())
        complete_1d = sum(v["complete_1d"] for v in results.values())
        out[f"{direction}_baseline_1d"] = {
            "n": total,
            "hits": complete_1d,
            "pct": pct(complete_1d, total),
        }
        bilbo_key = "high|rising" if direction == "bull" else "low|falling"
        bv = results.get(bilbo_key, {"total": 0, "complete_1d": 0, "full_atr_1d": 0})
        out[f"{direction}_bilbo_1d"] = {
            "n": bv["total"],
            "hits": bv["complete_1d"],
            "pct": pct(bv["complete_1d"], bv["total"]),
            "full_hits": bv["full_atr_1d"],
            "full_pct": pct(bv["full_atr_1d"], bv["total"]),
        }
    return out


def call_trigger(conn, corrected):
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, atr_upper_0382, atr_lower_0382, "
        "prev_close, atr_14 "
        "FROM ind_3m ORDER BY timestamp",
        conn,
        parse_dates=["timestamp"],
    ).set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    if corrected:
        df = attach_corrected_daily_levels(conn, df, ["trigger", "0382"])
    df = df.dropna(subset=["prev_close", "atr_14", "atr_upper_trigger"])
    df["date"] = df.index.date

    total_days = 0
    box_days = 0
    trigger_days = 0
    hit_0382 = 0
    invalidated = 0
    invalidated_hit = 0
    clean_hit = 0
    clean_total = 0

    for _date, group in df.groupby("date"):
        total_days += 1
        first = group.iloc[0]
        upper_trigger = first["atr_upper_trigger"]
        lower_trigger = first["atr_lower_trigger"]
        target_0382 = first["atr_upper_0382"]
        day_open = first["open"]

        if not (lower_trigger <= day_open <= upper_trigger):
            continue
        box_days += 1

        trigger_bars = group[group["close"] > upper_trigger]
        if len(trigger_bars) == 0:
            continue

        trigger_days += 1
        trigger_time = trigger_bars.index[0]
        remaining = group[group.index > trigger_time]

        hit_target = False
        target_hit_time = None
        if len(remaining) > 0:
            target_hits = remaining[remaining["high"] >= target_0382]
            if len(target_hits) > 0:
                hit_target = True
                target_hit_time = target_hits.index[0]

        invalid = False
        invalid_time = None
        if len(remaining) > 0:
            inv_bars = remaining[remaining["close"] < upper_trigger]
            if len(inv_bars) > 0:
                invalid = True
                invalid_time = inv_bars.index[0]

        invalid_before_target = False
        if invalid and hit_target:
            invalid_before_target = target_hit_time is not None and invalid_time < target_hit_time
        elif invalid and not hit_target:
            invalid_before_target = True

        if hit_target:
            hit_0382 += 1

        if invalid_before_target or (invalid and not hit_target):
            invalidated += 1
            if hit_target:
                invalidated_hit += 1
        else:
            clean_total += 1
            if hit_target:
                clean_hit += 1

    return {
        "total_days": total_days,
        "box_days": box_days,
        "trigger_days": trigger_days,
        "hit_0382": hit_0382,
        "hit_pct": pct(hit_0382, trigger_days),
        "invalidated": invalidated,
        "invalidated_hit": invalidated_hit,
        "invalidated_hit_pct": pct(invalidated_hit, invalidated),
        "clean_total": clean_total,
        "clean_hit": clean_hit,
        "clean_hit_pct": pct(clean_hit, clean_total),
    }


def gg_entries_immediate(conn, corrected):
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, "
        "atr_upper_trigger, atr_lower_trigger, "
        "atr_upper_0382, atr_lower_0382, "
        "atr_upper_0618, atr_lower_0618, "
        "prev_close, atr_14 "
        "FROM ind_10m ORDER BY timestamp",
        conn,
        parse_dates=["timestamp"],
    ).set_index("timestamp").sort_index()
    df = df.between_time("09:30", "15:59")
    if corrected:
        df = attach_corrected_daily_levels(conn, df, ["trigger", "0382", "0618"])
    df = df.dropna(subset=["prev_close", "atr_14"])
    df["date"] = df.index.date

    out = {}
    for direction in ["bull", "bear"]:
        total = 0
        completed = 0
        for _date, group in df.groupby("date"):
            first = group.iloc[0]
            if direction == "bull":
                entry_level = first["atr_upper_0382"]
                target_level = first["atr_upper_0618"]
                if pd.isna(entry_level):
                    continue
                if first["open"] >= entry_level:
                    tidx = 0
                else:
                    hit = group["high"] >= entry_level
                    if not hit.any():
                        continue
                    tidx = int(hit.values.argmax())
                after_entry = group.iloc[tidx + 1 :]
                did_complete = len(after_entry) > 0 and (after_entry["high"] >= target_level).any()
            else:
                entry_level = first["atr_lower_0382"]
                target_level = first["atr_lower_0618"]
                if pd.isna(entry_level):
                    continue
                if first["open"] <= entry_level:
                    tidx = 0
                else:
                    hit = group["low"] <= entry_level
                    if not hit.any():
                        continue
                    tidx = int(hit.values.argmax())
                after_entry = group.iloc[tidx + 1 :]
                did_complete = len(after_entry) > 0 and (after_entry["low"] <= target_level).any()

            total += 1
            completed += int(did_complete)

        win_pct = pct(completed, total)
        win = win_pct / 100
        ev = win * 23.6 - (1 - win) * 14.6 if total else np.nan
        out[direction] = {"n": total, "hits": completed, "pct": win_pct, "ev": ev}

    total_n = out["bull"]["n"] + out["bear"]["n"]
    total_hits = out["bull"]["hits"] + out["bear"]["hits"]
    combined_pct = pct(total_hits, total_n)
    win = combined_pct / 100
    combined_ev = win * 23.6 - (1 - win) * 14.6
    out["combined"] = {
        "n": total_n,
        "hits": total_hits,
        "pct": combined_pct,
        "ev": combined_ev,
    }
    return out


def emit(name, current, corrected):
    print(f"\n## {name}")
    print("current_buggy:", current)
    print("corrected:", corrected)


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        emit("multiday_gg", multiday_gg(conn, corrected=False), multiday_gg(conn, corrected=True))
        emit("call_trigger", call_trigger(conn, corrected=False), call_trigger(conn, corrected=True))
        emit("gg_entries_immediate", gg_entries_immediate(conn, corrected=False), gg_entries_immediate(conn, corrected=True))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
