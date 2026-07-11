"""Rerun the FIXED Bilbo GG pipeline (point-in-time-safe 1h PO join) on the
published 2000-2025 window, and emit everything the bilbo-golden-gate.html
page needs: pooled zone+slope rows w/ within-1h rates, speed curves,
same-bar shares, and the per-event drill-down dates JSON.

Sanity gate: the (zone,slope,state) bucket counts must reproduce
audit-reruns/postfix-stats_2026-04-26 exactly (e.g. bear low+falling 120/141).
"""
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/spy")
from backtest_gg_with_po import classify_po, DB_PATH

CUTOFF = pd.Timestamp("2026-01-01")

conn = sqlite3.connect(DB_PATH)
df10 = pd.read_sql_query(
    "SELECT timestamp, open, high, low, close, "
    "atr_upper_0382, atr_lower_0382, atr_upper_0618, atr_lower_0618, "
    "prev_close, atr_14 FROM ind_10m ORDER BY timestamp",
    conn, parse_dates=["timestamp"])
df10 = df10[df10["timestamp"] < CUTOFF]
df10 = df10.set_index("timestamp").sort_index()
df10 = df10.between_time("09:30", "15:59")
df10 = df10.dropna(subset=["prev_close", "atr_14"])

df60 = pd.read_sql_query(
    "SELECT timestamp, phase_oscillator, compression FROM ind_1h ORDER BY timestamp",
    conn, parse_dates=["timestamp"])
df60 = df60.dropna(subset=["phase_oscillator"]).copy()
df60 = df60.set_index("timestamp").sort_index()
df60["po_prev"] = df60["phase_oscillator"].shift(1)

# Point-in-time-safe join: shift left-labeled 1h bars to bar-end.
df10_reset = df10.reset_index()
df60_reset = df60.reset_index()
df60_reset["timestamp"] = df60_reset["timestamp"] + pd.Timedelta(hours=1)
merged = pd.merge_asof(
    df10_reset[["timestamp"]],
    df60_reset[["timestamp", "phase_oscillator", "po_prev", "compression"]],
    on="timestamp", direction="backward")
df10["po_60m"] = merged["phase_oscillator"].values
df10["po_prev_60m"] = merged["po_prev"].values
df10["compression_60m"] = merged["compression"].values
df10["date"] = df10.index.date

events = []  # dicts: dir, date, zone, slope, state, completed, mins (None if not completed)

for date, group in df10.groupby("date"):
    first = group.iloc[0]
    if pd.isna(first["atr_upper_0382"]):
        continue
    for direction in ("bull", "bear"):
        if direction == "bull":
            trig_lvl, gate_lvl = first["atr_upper_0382"], first["atr_upper_0618"]
            if first["open"] >= trig_lvl:
                trigger_idx = 0
            else:
                hit = group["high"] >= trig_lvl
                trigger_idx = hit.values.argmax() if hit.any() else None
        else:
            trig_lvl, gate_lvl = first["atr_lower_0382"], first["atr_lower_0618"]
            if first["open"] <= trig_lvl:
                trigger_idx = 0
            else:
                hit = group["low"] <= trig_lvl
                trigger_idx = hit.values.argmax() if hit.any() else None
        if trigger_idx is None:
            continue
        row = group.iloc[trigger_idx]
        po_val, po_prev = row["po_60m"], row["po_prev_60m"]
        if pd.isna(po_val) or pd.isna(po_prev):
            continue
        zone, slope, state = classify_po(po_val, po_prev, row["compression_60m"])
        remaining = group.iloc[trigger_idx:]
        if direction == "bull":
            done_mask = (remaining["high"] >= gate_lvl).values
        else:
            done_mask = (remaining["low"] <= gate_lvl).values
        completed = bool(done_mask.any())
        mins = None
        if completed:
            done_idx = int(done_mask.argmax())  # bars after trigger bar (0 = same bar)
            t_trig = remaining.index[0]
            t_done = remaining.index[done_idx]
            mins = (t_done - t_trig).total_seconds() / 60.0
        events.append(dict(direction=direction, date=str(date), zone=zone,
                           slope=slope, state=state, completed=completed,
                           mins=mins))

ev = pd.DataFrame(events)

# ── Sanity gate vs audited postfix artifacts ──
audit = pd.read_csv("/root/spy/audit-reruns/postfix-stats_2026-04-26/gg_po_bucket_comparison_2026-04-26.csv")
mismatch = 0
for _, a in audit.iterrows():
    sub = ev[(ev.direction == ("bull" if a["direction"] == "bull" else "bear"))
             & (ev.zone == a["zone"]) & (ev.slope == a["slope"]) & (ev.state == a["state"])]
    if len(sub) != a["total_fixed"] or int(sub.completed.sum()) != a["completed_fixed"]:
        mismatch += 1
        print(f"MISMATCH {a['direction']} {a['zone']}/{a['slope']}/{a['state']}: "
              f"rerun {int(sub.completed.sum())}/{len(sub)} vs audit {a['completed_fixed']}/{a['total_fixed']}")
print("SANITY:", "PASS — reproduces audited postfix counts" if mismatch == 0 else f"{mismatch} bucket mismatches")

# ── Page rows: pooled zone+slope ──
def row_stats(sub):
    n = len(sub)
    done = sub[sub.completed]
    overall = 100 * len(done) / n if n else float("nan")
    h1 = 100 * (done.mins <= 60).sum() / n if n else float("nan")
    return overall, h1, n

label_map = {("high", "rising"): "PO High + Rising", ("high", "falling"): "PO High + Falling",
             ("mid", "rising"): "PO Mid + Rising", ("mid", "falling"): "PO Mid + Falling",
             ("low", "rising"): "PO Low + Rising", ("low", "falling"): "PO Low + Falling"}

out = {"bull": [], "bear": []}
for direction in ("bull", "bear"):
    d = ev[ev.direction == direction]
    zones = [("high", "rising"), ("high", "falling"), ("mid", "rising"), ("mid", "falling")] \
        if direction == "bull" else [("low", "falling"), ("low", "rising"), ("mid", "falling"), ("mid", "rising")]
    for z, s in zones:
        sub = d[(d.zone == z) & (d.slope == s)]
        o, h1, n = row_stats(sub)
        out[direction].append(dict(label=label_map[(z, s)], overall=round(o, 1), h1=round(h1, 1), n=n))
    o, h1, n = row_stats(d)
    out[direction].append(dict(label="Baseline (all)", overall=round(o, 1), h1=round(h1, 1), n=n, baseline=True))

# ── Speed curves ──
def speed(sub):
    done = sub[sub.completed]
    if not len(done):
        return None
    cum = {c: round(100 * (done.mins <= t).sum() / len(done), 1)
           for c, t in [("0 min", 0), ("≤10 min", 10), ("≤20 min", 20), ("≤30 min", 30), ("≤60 min", 60)]}
    return dict(n_completed=len(done), mean=round(done.mins.mean(), 1), cum=cum)

speed_out = {
    "bull_marquee": speed(ev[(ev.direction == "bull") & (ev.zone == "high") & (ev.slope == "rising")]),
    "bull_base": speed(ev[ev.direction == "bull"]),
    "bear_marquee": speed(ev[(ev.direction == "bear") & (ev.zone == "low") & (ev.slope == "falling")]),
    "bear_base": speed(ev[ev.direction == "bear"]),
}

# ── Drill-down dates JSON (page rowKey format) ──
dates = {}
for direction in ("bull", "bear"):
    d = ev[ev.direction == direction]
    for (z, s), label in label_map.items():
        sub = d[(d.zone == z) & (d.slope == s)]
        if not len(sub):
            continue
        dates[f"{direction}_{label}"] = [
            {"d": r.date, "h": int(r.completed)} for r in sub.itertuples()]

with open("/root/spy/site/data/bilbo-gg-dates.json", "w") as f:
    json.dump(dates, f, separators=(",", ":"))

print(json.dumps({"rows": out, "speed": speed_out}, indent=1))
