"""Corrected reruns for the two Bilbo GG satellite studies (2000-2025):
1. 10m vs 60m PO comparison (bilbo-10m.html) — both joins point-in-time-safe:
   60m PO = last fully closed 1h bar (bar-end shifted merge);
   10m PO = previous completed 10m bar (shift 1; the trigger bar's own PO is
   not knowable at touch time).
2. Continuation ladder (bilbo-continuation.html) — reach of 61.8/78.6/100/123.6
   after the 38.2 trigger, baseline vs 60m marquee buckets.
"""
import json
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, "/root/spy")
from backtest_gg_with_po import classify_po, DB_PATH

CUTOFF = pd.Timestamp("2026-01-01")

conn = sqlite3.connect(DB_PATH)
df10 = pd.read_sql_query(
    "SELECT timestamp, open, high, low, close, "
    "atr_upper_0382, atr_lower_0382, atr_upper_0618, atr_lower_0618, "
    "atr_upper_0786, atr_lower_0786, atr_upper_100, atr_lower_100, "
    "atr_upper_1236, atr_lower_1236, atr_upper_1618, atr_lower_1618, atr_upper_200, atr_lower_200, "
    "phase_oscillator, po_compression, prev_close, atr_14 "
    "FROM ind_10m ORDER BY timestamp",
    conn, parse_dates=["timestamp"])
df10 = df10[df10["timestamp"] < CUTOFF]
df10 = df10.set_index("timestamp").sort_index()
# Previous completed 10m bar's PO must be taken on the FULL frame (incl.
# overnight adjacency) before the RTH filter, mirroring how the 1h join can
# hand back yesterday's last completed bar.
df10["po_10m_prev"] = df10["phase_oscillator"].shift(1)
df10["po_10m_prev2"] = df10["phase_oscillator"].shift(2)
df10["comp_10m_prev"] = df10["po_compression"].shift(1)
df10 = df10.between_time("09:30", "15:59")
df10 = df10.dropna(subset=["prev_close", "atr_14"])

df60 = pd.read_sql_query(
    "SELECT timestamp, phase_oscillator, compression FROM ind_1h ORDER BY timestamp",
    conn, parse_dates=["timestamp"])
df60 = df60.dropna(subset=["phase_oscillator"]).copy()
df60 = df60.set_index("timestamp").sort_index()
df60["po_prev"] = df60["phase_oscillator"].shift(1)

df10_reset = df10.reset_index()
df60_reset = df60.reset_index()
df60_reset["timestamp"] = df60_reset["timestamp"] + pd.Timedelta(hours=1)
merged = pd.merge_asof(
    df10_reset[["timestamp"]],
    df60_reset[["timestamp", "phase_oscillator", "po_prev", "compression"]],
    on="timestamp", direction="backward", suffixes=("", "_60"))
df10["po_60m"] = merged["phase_oscillator_60"].values if "phase_oscillator_60" in merged else merged.iloc[:, 1].values
df10["po_prev_60m"] = merged["po_prev"].values
df10["compression_60m"] = merged["compression"].values
df10["date"] = df10.index.date

events = []
for date, group in df10.groupby("date"):
    first = group.iloc[0]
    if pd.isna(first["atr_upper_0382"]):
        continue
    for direction in ("bull", "bear"):
        side = "upper" if direction == "bull" else "lower"
        trig = first[f"atr_{side}_0382"]
        levels = {k: first[f"atr_{side}_{k}"] for k in ("0618", "0786", "100", "1236", "1618", "200")}
        if direction == "bull":
            if first["open"] >= trig:
                ti = 0
            else:
                hit = group["high"] >= trig
                ti = hit.values.argmax() if hit.any() else None
        else:
            if first["open"] <= trig:
                ti = 0
            else:
                hit = group["low"] <= trig
                ti = hit.values.argmax() if hit.any() else None
        if ti is None:
            continue
        row = group.iloc[ti]
        e = dict(direction=direction, date=str(date))
        # 60m class (last completed hour)
        if pd.notna(row["po_60m"]) and pd.notna(row["po_prev_60m"]):
            e["c60"] = classify_po(row["po_60m"], row["po_prev_60m"], row["compression_60m"])[:2]
        # 10m class (previous completed 10m bar; slope vs the bar before it)
        if pd.notna(row["po_10m_prev"]) and pd.notna(row["po_10m_prev2"]):
            comp = row["comp_10m_prev"] if pd.notna(row["comp_10m_prev"]) else 0
            e["c10"] = classify_po(row["po_10m_prev"], row["po_10m_prev2"], comp)[:2]
        remaining = group.iloc[ti:]
        for k, lvl in levels.items():
            if direction == "bull":
                e[f"hit_{k}"] = bool((remaining["high"] >= lvl).any())
            else:
                e[f"hit_{k}"] = bool((remaining["low"] <= lvl).any())
        events.append(e)

ev = pd.DataFrame(events)

def rate(sub, col="hit_0618"):
    return (round(100 * sub[col].mean(), 1), len(sub)) if len(sub) else (None, 0)

report = {}
for direction, marquee in (("bull", ("high", "rising")), ("bear", ("low", "falling"))):
    d = ev[ev.direction == direction]
    base, bn = rate(d)
    rows60, rows10 = {}, {}
    for zs in [("high", "rising"), ("high", "falling"), ("mid", "rising"),
               ("mid", "falling"), ("low", "rising"), ("low", "falling")]:
        r60, n60 = rate(d[d.c60 == zs].dropna(subset=["c60"])) if "c60" in d else (None, 0)
        sub60 = d[d["c60"].apply(lambda x: x == zs if isinstance(x, tuple) else False)]
        sub10 = d[d["c10"].apply(lambda x: x == zs if isinstance(x, tuple) else False)]
        rows60["+".join(zs)] = rate(sub60)
        rows10["+".join(zs)] = rate(sub10)
    # continuation ladder: baseline & 60m marquee
    ladder = {}
    buckets = {"baseline": d}
    for zs in [("high", "rising"), ("high", "falling"), ("mid", "rising"),
               ("mid", "falling"), ("low", "rising"), ("low", "falling")]:
        buckets["+".join(zs)] = d[d["c60"].apply(lambda x: x == zs if isinstance(x, tuple) else False)]
    for name, sub in buckets.items():
        ladder[name] = {"n": len(sub),
                        "pcts": [rate(sub, f"hit_{k}")[0] for k in ("0618", "0786", "100", "1236", "1618", "200")]}
    report[direction] = {"baseline": (base, bn), "by60": rows60, "by10": rows10, "ladder": ladder}

print(json.dumps(report, indent=1))
