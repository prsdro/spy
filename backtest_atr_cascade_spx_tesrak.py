"""
SPX ATR Level Cascade — same logic as backtest_atr_cascade.py but for SPX
10-minute bars sourced from the Tesrak upload at
/root/spy/incoming/tesrak/2026-05-02/SPX_intraday_10min.csv.gz.

The Tesrak SPX file mixes:
  - daily SPX bars (timestamp at 00:00:00) covering 2008-05-05 .. 2025-10-20
  - 10-minute SPX bars covering 2025-10-21 .. 2026-03-20 (RTH 09:30-15:50 ET)

Outputs are written to clearly-named SPX-specific files so they cannot collide
with the published SPY study:
    site/data/atr-cascade-spx.json
    analyst/atr_cascade_spx_table.csv
    agent_reports/atr_cascade_spx_run.log (when run with tee)
"""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_GZ = os.path.join(
    BASE_DIR, "incoming", "tesrak", "2026-05-02", "SPX_intraday_10min.csv.gz"
)
OUT_DIR = os.path.join(BASE_DIR, "analyst")
JSON_OUT = os.path.join(BASE_DIR, "site", "data", "atr-cascade-spx.json")
CSV_OUT = os.path.join(OUT_DIR, "atr_cascade_spx_table.csv")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)


# ─── Saty ATR ladder definition (mirrors backtest_atr_cascade.py) ────────────

LADDER = [
    ("-2.236", "atr_lower_2236",    -2.236),
    ("-2.00",  "atr_lower_200",     -2.000),
    ("-1.786", "atr_lower_1786",    -1.786),
    ("-1.618", "atr_lower_1618",    -1.618),
    ("-1.50",  "atr_lower_150",     -1.500),
    ("-1.382", "atr_lower_1382",    -1.382),
    ("-1.236", "atr_lower_1236",    -1.236),
    ("-1.00",  "atr_lower_100",     -1.000),
    ("-0.786", "atr_lower_0786",    -0.786),
    ("-0.618", "atr_lower_0618",    -0.618),
    ("-0.50",  "atr_lower_050",     -0.500),
    ("-0.382", "atr_lower_0382",    -0.382),
    ("-0.236", "atr_lower_trigger", -0.236),
    ("PDC",    "prev_close",         0.000),
    ("+0.236", "atr_upper_trigger",  0.236),
    ("+0.382", "atr_upper_0382",     0.382),
    ("+0.50",  "atr_upper_050",      0.500),
    ("+0.618", "atr_upper_0618",     0.618),
    ("+0.786", "atr_upper_0786",     0.786),
    ("+1.00",  "atr_upper_100",      1.000),
    ("+1.236", "atr_upper_1236",     1.236),
    ("+1.382", "atr_upper_1382",     1.382),
    ("+1.50",  "atr_upper_150",      1.500),
    ("+1.618", "atr_upper_1618",     1.618),
    ("+1.786", "atr_upper_1786",     1.786),
    ("+2.00",  "atr_upper_200",      2.000),
    ("+2.236", "atr_upper_2236",     2.236),
]
LABELS = [r[0] for r in LADDER]
COLUMNS = [r[1] for r in LADDER]
MULTIPLES = [r[2] for r in LADDER]
N = len(LADDER)
PDC_IDX = LABELS.index("PDC")
HIDDEN_MEASUREMENT_LABELS = {"-2.236", "+2.236"}
REPORT_LABELS = [lab for lab in LABELS if lab not in HIDDEN_MEASUREMENT_LABELS]

LEVEL_NAMES = {
    "-2.00": "-2 ATR",
    "-1.786": "Momo Put 78.6",
    "-1.618": "Momo Put GG Closed",
    "-1.50": "Momo Put Midrange",
    "-1.382": "Momo Put GG Open",
    "-1.236": "Momo Put Trigger",
    "-1.00": "-1 ATR",
    "-0.786": "Put 78.6",
    "-0.618": "Put GG Closed",
    "-0.50": "Put Midrange",
    "-0.382": "Put GG Open",
    "-0.236": "Put Trigger",
    "PDC": "Previous Close / Central Pivot",
    "+0.236": "Call Trigger",
    "+0.382": "Call GG Open",
    "+0.50": "Call Midrange",
    "+0.618": "Call GG Closed",
    "+0.786": "Call 78.6",
    "+1.00": "+1 ATR",
    "+1.236": "Momo Call Trigger",
    "+1.382": "Momo Call GG Open",
    "+1.50": "Momo Call Midrange",
    "+1.618": "Momo Call GG Closed",
    "+1.786": "Momo Call 78.6",
    "+2.00": "+2 ATR",
}

HOUR_BUCKETS = [
    ("09:30-10:00",  9, 30, 10,  0),
    ("10:00-11:00", 10,  0, 11,  0),
    ("11:00-12:00", 11,  0, 12,  0),
    ("12:00-13:00", 12,  0, 13,  0),
    ("13:00-14:00", 13,  0, 14,  0),
    ("14:00-15:00", 14,  0, 15,  0),
    ("15:00-16:00", 15,  0, 16,  0),
]


def time_bucket(ts):
    tt = ts.hour * 60 + ts.minute
    for label, h1, m1, h2, m2 in HOUR_BUCKETS:
        if h1 * 60 + m1 <= tt < h2 * 60 + m2:
            return label
    return None


# ─── Wilder ATR ──────────────────────────────────────────────────────────────

def rma(series, period):
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def atr_series(daily_df, period=14):
    high = daily_df["high"]
    low = daily_df["low"]
    prev_close = daily_df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return rma(tr, period)


# ─── Tesrak SPX loader ───────────────────────────────────────────────────────

def load_spx():
    """Load the SPX gz file and return:
        intraday_df  — 10-minute RTH bars (DatetimeIndex), with the full
                       Saty ATR ladder (and prev_close, atr_14) per row
        diagnostics  — dict with row counts, date ranges, etc.
    """
    with gzip.open(SRC_GZ, "rt") as fh:
        raw = pd.read_csv(fh, parse_dates=["Date"])
    raw = raw.rename(columns={
        "Date": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })
    raw = raw.sort_values("timestamp").reset_index(drop=True)

    # Split daily (00:00:00) and intraday (anything else)
    is_daily_row = (raw["timestamp"].dt.time == pd.Timestamp("00:00:00").time())
    daily_rows = raw[is_daily_row].copy()
    intraday_rows = raw[~is_daily_row].copy()

    # Build full daily OHLC series:
    #   - daily file rows up to (and including) the day before the first intraday day
    #   - intraday-derived OHLC from the first intraday day onward
    #
    # This guarantees no gap when computing ATR(14) Wilder across the boundary.
    intraday_rows["date"] = intraday_rows["timestamp"].dt.date
    intraday_daily = (
        intraday_rows.groupby("date")
        .agg(open=("open", "first"),
             high=("high", "max"),
             low=("low", "min"),
             close=("close", "last"))
        .reset_index()
    )
    intraday_daily["timestamp"] = pd.to_datetime(intraday_daily["date"])
    intraday_daily = intraday_daily.drop(columns=["date"])

    daily_rows["date"] = daily_rows["timestamp"].dt.date

    first_intraday_date = intraday_rows["date"].min()
    daily_pre = daily_rows[daily_rows["date"] < first_intraday_date]
    daily_pre = daily_pre[["timestamp", "open", "high", "low", "close"]]
    intraday_daily = intraday_daily[["timestamp", "open", "high", "low", "close"]]
    full_daily = pd.concat([daily_pre, intraday_daily], ignore_index=True)
    full_daily = full_daily.sort_values("timestamp").reset_index(drop=True)

    # Saty period_index=1: today's level uses YESTERDAY's close & ATR.
    full_daily["atr_14_prev"] = atr_series(full_daily, 14).shift(1)
    full_daily["prev_close"] = full_daily["close"].shift(1)
    full_daily["date"] = full_daily["timestamp"].dt.date

    daily_lookup = (
        full_daily.set_index("date")[["prev_close", "atr_14_prev"]]
        .rename(columns={"atr_14_prev": "atr_14"})
    )

    # Build the intraday RTH dataframe with ATR ladder
    intra = intraday_rows.set_index("timestamp").sort_index()
    intra = intra.between_time("09:30", "15:59")
    intra["date"] = intra.index.date
    intra = intra.join(daily_lookup, on="date")
    intra = intra.dropna(subset=["prev_close", "atr_14"])

    pc = intra["prev_close"]
    atr14 = intra["atr_14"]
    for label, col, mult in LADDER:
        if col == "prev_close":
            continue  # already present
        intra[col] = pc + mult * atr14

    # Final column order matches what analyse_day expects
    keep = ["high", "low", "prev_close", "atr_14"] + [
        c for _, c, _ in LADDER if c != "prev_close"
    ] + ["date"]
    intra = intra[keep]

    diagnostics = {
        "src_file": SRC_GZ,
        "raw_rows": int(len(raw)),
        "daily_file_rows": int(len(daily_rows)),
        "intraday_rows": int(len(intraday_rows)),
        "intraday_first_date": str(intraday_rows["date"].min()),
        "intraday_last_date": str(intraday_rows["date"].max()),
        "intraday_trading_days": int(intraday_rows["date"].nunique()),
        "daily_first_date": str(daily_rows["date"].min()) if len(daily_rows) else None,
        "daily_last_date": str(daily_rows["date"].max()) if len(daily_rows) else None,
        "daily_series_rows": int(len(full_daily)),
        "rth_bars_used": int(len(intra)),
        "rth_days_used": int(intra["date"].nunique()),
    }
    return intra, diagnostics


# ─── Cascade analysis (mirrors backtest_atr_cascade.py) ──────────────────────

def first_hit_bar(highs, lows, L, idx):
    if idx == PDC_IDX:
        m = (lows <= L) & (highs >= L)
    elif idx > PDC_IDX:
        m = highs >= L
    else:
        m = lows <= L
    if m.any():
        return int(np.argmax(m))
    return None


def analyse_day(group):
    row0 = group.iloc[0]
    level_prices = [row0[c] for c in COLUMNS]
    if any(pd.isna(p) for p in level_prices):
        return [], []

    highs = group["high"].values
    lows = group["low"].values
    ts = group.index

    first_hits = [first_hit_bar(highs, lows, level_prices[i], i) for i in range(N)]

    seq_pairs = sorted(
        [(first_hits[i], i) for i in range(N) if first_hits[i] is not None]
    )
    sequence = [i for (_, i) in seq_pairs]

    events = []
    for i in range(N):
        if i == PDC_IDX:
            continue
        if first_hits[i] is None:
            continue
        T_bar = first_hits[i]
        T_ts = ts[T_bar]

        if i > PDC_IDX:
            beyond_idx, behind_idx = i + 1, i - 1
            beyond_dir, behind_dir = "up", "down"
        else:
            beyond_idx, behind_idx = i - 1, i + 1
            beyond_dir, behind_dir = "down", "up"

        def forward_hit(target_idx, direction):
            if not (0 <= target_idx < N):
                return None
            L_t = level_prices[target_idx]
            if pd.isna(L_t):
                return None
            fh = highs[T_bar:]
            fl = lows[T_bar:]
            if direction == "up":
                m = fh >= L_t
            else:
                m = fl <= L_t
            if m.any():
                return T_bar + int(np.argmax(m))
            return None

        b_bar = forward_hit(beyond_idx, beyond_dir)
        h_bar = forward_hit(behind_idx, behind_dir)

        if b_bar is None and h_bar is None:
            outcome, t_min = "last", None
        elif b_bar is None:
            outcome = "behind"
            t_min = (ts[h_bar] - T_ts).total_seconds() / 60
        elif h_bar is None:
            outcome = "beyond"
            t_min = (ts[b_bar] - T_ts).total_seconds() / 60
        else:
            if b_bar < h_bar:
                outcome = "beyond"
                t_min = (ts[b_bar] - T_ts).total_seconds() / 60
            elif h_bar < b_bar:
                outcome = "behind"
                t_min = (ts[h_bar] - T_ts).total_seconds() / 60
            else:
                outcome = "ambiguous"
                t_min = (ts[b_bar] - T_ts).total_seconds() / 60

        events.append({
            "level": LABELS[i],
            "hour_bucket": time_bucket(T_ts),
            "outcome": outcome,
            "time_to_min": t_min,
            "first_hit_ts": T_ts,
        })
    return events, sequence


def analyse_adjacent_walk(group):
    row0 = group.iloc[0]
    level_prices = [row0[c] for c in COLUMNS]
    if any(pd.isna(p) for p in level_prices):
        return []

    public_idx = [LABELS.index(lab) for lab in REPORT_LABELS]
    public_set = set(public_idx)
    to_public = {LABELS.index(lab): REPORT_LABELS.index(lab) for lab in REPORT_LABELS}
    highs = group["high"].values
    lows = group["low"].values

    first_hits = [first_hit_bar(highs, lows, level_prices[i], i) if i in public_set else None for i in range(N)]
    seq_pairs = sorted((first_hits[i], i) for i in public_idx if first_hits[i] is not None)
    if not seq_pairs:
        return []

    current_bar, current_idx = seq_pairs[0]
    walk = [to_public[current_idx]]
    max_steps = 240

    for _ in range(max_steps):
        candidates = []
        for next_idx, direction in ((current_idx + 1, "up"), (current_idx - 1, "down")):
            if next_idx not in public_set:
                continue
            L_t = level_prices[next_idx]
            fh = highs[current_bar + 1:]
            fl = lows[current_bar + 1:]
            if len(fh) == 0:
                continue
            m = fh >= L_t if direction == "up" else fl <= L_t
            if m.any():
                candidates.append((current_bar + 1 + int(np.argmax(m)), next_idx))
        if not candidates:
            break
        candidates.sort()
        current_bar, current_idx = candidates[0]
        walk.append(to_public[current_idx])
    return walk


def analyse_gg_retrace_case(group, direction):
    if direction == "call":
        trigger_lab, open_lab, complete_lab = "+0.236", "+0.382", "+0.618"
        target_dir = "up"
        retrace_dir = "down"
    elif direction == "put":
        trigger_lab, open_lab, complete_lab = "-0.236", "-0.382", "-0.618"
        target_dir = "down"
        retrace_dir = "up"
    else:
        raise ValueError(direction)

    row0 = group.iloc[0]
    level_prices = [row0[c] for c in COLUMNS]
    if any(pd.isna(p) for p in level_prices):
        return None

    highs = group["high"].values
    lows = group["low"].values
    ts = group.index

    trigger_idx = LABELS.index(trigger_lab)
    open_idx = LABELS.index(open_lab)
    complete_idx = LABELS.index(complete_lab)
    first_hits = [first_hit_bar(highs, lows, level_prices[i], i) for i in range(N)]
    trigger_bar = first_hits[trigger_idx]
    open_bar = first_hits[open_idx]
    if trigger_bar is None or open_bar is None or trigger_bar > open_bar:
        return None

    def forward_hit_from(start_bar, target_idx, direction_):
        L_t = level_prices[target_idx]
        fh = highs[start_bar:]
        fl = lows[start_bar:]
        m = fh >= L_t if direction_ == "up" else fl <= L_t
        if m.any():
            return start_bar + int(np.argmax(m))
        return None

    complete_same_bar = (highs[open_bar] >= level_prices[complete_idx]) if target_dir == "up" else (lows[open_bar] <= level_prices[complete_idx])
    retrace_same_bar = (lows[open_bar] <= level_prices[trigger_idx]) if retrace_dir == "down" else (highs[open_bar] >= level_prices[trigger_idx])
    if complete_same_bar or retrace_same_bar:
        return {
            "direction": direction,
            "bucket": "ambiguous_open_bar",
            "completed": bool(complete_same_bar),
            "minutes_to_completion": 0.0 if complete_same_bar else None,
        }

    scan_start = open_bar + 1
    if scan_start >= len(group):
        return {"direction": direction, "bucket": "no_decision", "completed": False, "minutes_to_completion": None}

    complete_bar = forward_hit_from(scan_start, complete_idx, target_dir)
    retrace_bar = forward_hit_from(scan_start, trigger_idx, retrace_dir)
    completed = complete_bar is not None
    minutes_to_completion = (ts[complete_bar] - ts[open_bar]).total_seconds() / 60 if completed else None

    if retrace_bar is not None and (complete_bar is None or retrace_bar < complete_bar):
        bucket = "retraced_to_trigger_first"
    elif complete_bar is not None and (retrace_bar is None or complete_bar < retrace_bar):
        bucket = "completed_before_trigger_retrace"
    elif complete_bar is not None and retrace_bar is not None and complete_bar == retrace_bar:
        bucket = "ambiguous_same_bar"
    else:
        bucket = "no_decision"

    return {
        "direction": direction,
        "bucket": bucket,
        "completed": completed,
        "minutes_to_completion": minutes_to_completion,
    }


def aggregate_gg_retrace(cases):
    rows = []
    bucket_labels = {
        "retraced_to_trigger_first": "Retraced to trigger before GG completion",
        "completed_before_trigger_retrace": "Completed GG before trigger retrace",
        "no_decision": "Neither completion nor trigger retrace before close",
        "ambiguous_same_bar": "Completion and trigger retrace in same 10-min bar",
        "ambiguous_open_bar": "GG-open bar also touched completion or trigger",
    }
    for direction in ["call", "put"]:
        sub = [c for c in cases if c and c["direction"] == direction]
        denom = len(sub)
        for bucket, label in bucket_labels.items():
            bsub = [c for c in sub if c["bucket"] == bucket]
            n = len(bsub)
            completed = sum(1 for c in bsub if c["completed"])
            times = [c["minutes_to_completion"] for c in bsub if c["minutes_to_completion"] is not None]
            rows.append({
                "direction": direction,
                "bucket": bucket,
                "label": label,
                "n": n,
                "share_of_gg_opens": round(n / denom, 4) if denom else None,
                "completion_rate": round(completed / n, 4) if n else None,
                "completed": completed,
                "avg_min_to_completion": round(float(np.mean(times)), 1) if times else None,
                "med_min_to_completion": round(float(np.median(times)), 1) if times else None,
            })
    return rows


HIST_EDGES = [0, 3, 6, 12, 24, 45, 90, 180, 360, 10_000]
HIST_LABELS = ["0-3", "3-6", "6-12", "12-24", "24-45", "45-90", "90-180", "180-360", "360+"]


def hist_bin(t_min):
    if t_min is None:
        return None
    for i in range(len(HIST_EDGES) - 1):
        if HIST_EDGES[i] <= t_min < HIST_EDGES[i + 1]:
            return i
    return None


def aggregate(events):
    rows = []

    def stats_for(subset):
        n = len(subset)
        if n == 0:
            return None
        n_beyond = sum(1 for e in subset if e["outcome"] == "beyond")
        n_behind = sum(1 for e in subset if e["outcome"] == "behind")
        n_last = sum(1 for e in subset if e["outcome"] == "last")
        n_ambig = sum(1 for e in subset if e["outcome"] == "ambiguous")
        beyond_times = [e["time_to_min"] for e in subset if e["outcome"] == "beyond"]
        behind_times = [e["time_to_min"] for e in subset if e["outcome"] == "behind"]
        return {
            "n": n,
            "p_beyond": n_beyond / n,
            "p_behind": n_behind / n,
            "p_last": n_last / n,
            "p_ambig": n_ambig / n,
            "avg_min_to_beyond": float(np.mean(beyond_times)) if beyond_times else None,
            "med_min_to_beyond": float(np.median(beyond_times)) if beyond_times else None,
            "avg_min_to_behind": float(np.mean(behind_times)) if behind_times else None,
            "med_min_to_behind": float(np.median(behind_times)) if behind_times else None,
        }

    levels_for_report = [lab for lab in REPORT_LABELS if lab != "PDC"]

    for lab in levels_for_report:
        subset = [e for e in events if e["level"] == lab]
        s = stats_for(subset)
        if s is None:
            continue
        rows.append({"level": lab, "hour_bucket": "ALL", **s})

    for lab in levels_for_report:
        for b in [hb[0] for hb in HOUR_BUCKETS]:
            subset = [e for e in events if e["level"] == lab and e["hour_bucket"] == b]
            s = stats_for(subset)
            if s is None:
                rows.append({"level": lab, "hour_bucket": b, "n": 0,
                             "p_beyond": None, "p_behind": None, "p_last": None, "p_ambig": None,
                             "avg_min_to_beyond": None, "med_min_to_beyond": None,
                             "avg_min_to_behind": None, "med_min_to_behind": None})
            else:
                rows.append({"level": lab, "hour_bucket": b, **s})

    return pd.DataFrame(rows)


def print_overall(df):
    print("=" * 90)
    print("SPX ATR LEVEL CASCADE — overall (all hours)")
    print("=" * 90)
    o = df[df["hour_bucket"] == "ALL"].copy()
    print(f"{'Level':>7s} {'N':>6s} {'%Beyond':>9s} {'%Behind':>9s} {'%Last':>7s} {'%Ambig':>8s} "
          f"{'Avg min→Beyond':>15s} {'Avg min→Behind':>15s}")
    order = [lab for lab in REPORT_LABELS if lab != "PDC"]
    for lab in order:
        r = o[o["level"] == lab]
        if len(r) == 0:
            continue
        r = r.iloc[0]
        ab = f"{r['avg_min_to_beyond']:6.0f}" if pd.notna(r['avg_min_to_beyond']) else "    --"
        ah = f"{r['avg_min_to_behind']:6.0f}" if pd.notna(r['avg_min_to_behind']) else "    --"
        print(f"{lab:>7s} {int(r['n']):6d} "
              f"{r['p_beyond']*100:8.1f}% {r['p_behind']*100:8.1f}% "
              f"{r['p_last']*100:6.1f}% {r['p_ambig']*100:7.1f}% "
              f"{ab:>15s} {ah:>15s}")


def build_json_payload(all_events, all_paths, out_df, n_days, gg_retrace, adjacent_walks, diagnostics):
    cells = []
    for _, r in out_df.iterrows():
        cells.append({
            "level": r["level"],
            "hour_bucket": r["hour_bucket"],
            "n": int(r["n"]),
            "p_beyond": None if pd.isna(r["p_beyond"]) else round(float(r["p_beyond"]), 4),
            "p_behind": None if pd.isna(r["p_behind"]) else round(float(r["p_behind"]), 4),
            "p_last":   None if pd.isna(r["p_last"])   else round(float(r["p_last"]), 4),
            "p_ambig":  None if pd.isna(r["p_ambig"])  else round(float(r["p_ambig"]), 4),
            "avg_min_to_beyond": None if pd.isna(r["avg_min_to_beyond"]) else round(float(r["avg_min_to_beyond"]), 1),
            "med_min_to_beyond": None if pd.isna(r["med_min_to_beyond"]) else round(float(r["med_min_to_beyond"]), 1),
            "avg_min_to_behind": None if pd.isna(r["avg_min_to_behind"]) else round(float(r["avg_min_to_behind"]), 1),
            "med_min_to_behind": None if pd.isna(r["med_min_to_behind"]) else round(float(r["med_min_to_behind"]), 1),
        })

    hist = defaultdict(lambda: defaultdict(lambda: {"beyond": [0]*len(HIST_LABELS), "behind": [0]*len(HIST_LABELS)}))
    for e in all_events:
        if e["outcome"] not in ("beyond", "behind"):
            continue
        b = hist_bin(e["time_to_min"])
        if b is None:
            continue
        hist[e["level"]][e["hour_bucket"]][e["outcome"]][b] += 1
        hist[e["level"]]["ALL"][e["outcome"]][b] += 1

    hist_payload = {}
    report_label_set = set(REPORT_LABELS)
    for level, by_hour in hist.items():
        if level not in report_label_set:
            continue
        hist_payload[level] = {hb: dict(d) for hb, d in by_hour.items()}

    public_idx = {LABELS.index(lab): REPORT_LABELS.index(lab) for lab in REPORT_LABELS}
    public_paths = []
    for path in all_paths:
        remapped = [public_idx[i] for i in path if i in public_idx]
        if remapped:
            public_paths.append(remapped)

    return {
        "metadata": {
            "symbol": "SPX",
            "source": "Tesrak SPX_intraday_10min.csv.gz (uploaded 2026-05-02)",
            "bar_minutes": 10,
            "n_days": n_days,
            "n_events": len(all_events),
            "n_paths": len(public_paths),
            "n_adjacent_walks": len(adjacent_walks or []),
            "ladder": REPORT_LABELS,
            "level_names": {lab: LEVEL_NAMES[lab] for lab in REPORT_LABELS if lab in LEVEL_NAMES},
            "measurement_ladder": LABELS,
            "hidden_measurement_rungs": sorted(HIDDEN_MEASUREMENT_LABELS),
            "hour_buckets": [hb[0] for hb in HOUR_BUCKETS],
            "hist_labels": HIST_LABELS,
            "hist_edges": HIST_EDGES[:-1],
            "diagnostics": diagnostics,
        },
        "cells": cells,
        "hist": hist_payload,
        "paths": public_paths,
        "adjacent_walks": adjacent_walks or [],
        "gg_retrace": gg_retrace or [],
    }


def main():
    print(f"Loading SPX 10-min data from {SRC_GZ} ...")
    df, diag = load_spx()
    print("  diagnostics:")
    for k, v in diag.items():
        print(f"    {k}: {v}")

    print("\nProcessing days...")
    all_events = []
    all_paths = []
    adjacent_walks = []
    gg_cases = []
    for date, group in df.groupby("date", sort=True):
        ev, seq = analyse_day(group)
        all_events.extend(ev)
        if seq:
            all_paths.append(seq)
        walk = analyse_adjacent_walk(group)
        if walk:
            adjacent_walks.append(walk)
        for direction in ("call", "put"):
            case = analyse_gg_retrace_case(group, direction)
            if case is not None:
                gg_cases.append(case)
    print(f"  {len(all_events):,} level first-hit events recorded")
    print(f"  {len(all_paths):,} day-sequences captured")
    print(f"  {len(adjacent_walks):,} adjacent walk sequences captured")
    print(f"  {len(gg_cases):,} GG-open retrace/completion cases captured")

    out = aggregate(all_events)
    out.to_csv(CSV_OUT, index=False)
    print(f"\nWrote {CSV_OUT}")

    gg_retrace = aggregate_gg_retrace(gg_cases)
    payload = build_json_payload(
        all_events, all_paths, out, diag["rth_days_used"],
        gg_retrace=gg_retrace, adjacent_walks=adjacent_walks, diagnostics=diag,
    )
    with open(JSON_OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {JSON_OUT}  ({os.path.getsize(JSON_OUT)/1024:.1f} KB)")

    print_overall(out)


if __name__ == "__main__":
    main()
