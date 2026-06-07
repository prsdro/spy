"""
ATR Level Cascade — when SPY first hits an ATR level during RTH, what's the
next ATR level it reaches? Continuation (one level beyond, away from PDC),
retrace (one level behind, toward PDC), or last (no further adjacent move)?

Filter dimension: hour-of-day bucket of the first hit.

Levels covered (low → high), full Saty ladder from -2 ATR to +2 ATR:
    -2.00, -1.786, -1.618, -1.50, -1.382, -1.236, -1.00, -0.786, -0.618,
    -0.50, -0.382, -0.236, PDC,
    +0.236, +0.382, +0.50, +0.618, +0.786, +1.00, +1.236, +1.382, +1.50,
    +1.618, +1.786, +2.00

Outcomes per (level, hour bucket):
    - p_beyond = next adjacent first-touch was the level further from PDC
    - p_behind = next adjacent first-touch was the level closer to PDC
    - p_last   = neither adjacent level reached again before RTH close
    - p_ambig  = beyond and behind were first reached in the same bar
    - avg time-to-beyond and avg time-to-behind (minutes)

A "first hit" of a level uses the directional touch rule:
    upper-side level L (above PDC): high >= L
    lower-side level L (below PDC): low  <= L
    PDC:                              low <= PDC <= high

After the origin level's first-hit bar, scan forward (inclusive of the same bar):
    upper-side beyond  = first bar with high >= L_{i+1}
    upper-side behind  = first bar with low  <= L_{i-1}
    lower-side beyond  = first bar with low  <= L_{i-1}
    lower-side behind  = first bar with high >= L_{i+1}

Bars are 3-minute, RTH (09:30-15:59 ET).
"""

import json
import os
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
OUT_DIR = os.path.join(BASE_DIR, "analyst")
os.makedirs(OUT_DIR, exist_ok=True)

# Measurement ladder (low → high). The ±2.236 rungs are hidden sentinels: they
# exist only so ±2.00 can measure whether price continued one rung farther.
# They are intentionally excluded from the public report/table.
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
N = len(LADDER)
PDC_IDX = LABELS.index("PDC")
HIDDEN_MEASUREMENT_LABELS = {"-2.236", "+2.236"}
REPORT_LABELS = [lab for lab in LABELS if lab not in HIDDEN_MEASUREMENT_LABELS]

# Canonical Saty/Milkman names for ATR rungs that have trading vocabulary.
# These are public display labels only; hidden measurement rungs stay unnamed.
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


def load_data():
    conn = sqlite3.connect(DB_PATH)
    cols = ["timestamp", "high", "low"] + COLUMNS
    sql = f"SELECT {','.join(cols)} FROM ind_3m ORDER BY timestamp"
    df = pd.read_sql_query(sql, conn, parse_dates=["timestamp"])
    conn.close()
    df = df.set_index("timestamp").sort_index()
    # RTH 3-minute bars; the final timestamp in this left-labeled series is 15:57.
    df = df.between_time("09:30", "15:57")
    df = df.dropna(subset=["prev_close"])
    df["date"] = df.index.date
    return df


def first_hit_bar(highs, lows, L, idx, opens=None):
    """Return the first intraday bar that reaches a ladder level.

    Levels already passed at the RTH open are not counted as "reached" for
    first-hit/conditional-path purposes. Example: if the day opens above +0.382,
    a later +0.50 hit counts, but +0.236 and +0.382 are excluded from that day's
    +0.236→+0.382 conditional cohort.
    """
    if opens is not None and len(opens):
        day_open = opens[0]
        if idx > PDC_IDX and day_open >= L:
            return None
        if idx < PDC_IDX and day_open <= L:
            return None

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
    opens = group["open"].values if "open" in group.columns else None
    ts = group.index

    first_hits = [first_hit_bar(highs, lows, level_prices[i], i, opens) for i in range(N)]

    # Chronological sequence of first-hit level indices (incl. PDC)
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
            else:  # 'down'
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
    """Chronological adjacent-level walk, including revisits, for path explorer.

    Unlike first-hit paths, this walk starts with the day's first touched public rung
    and then records the next adjacent rung touched from the current rung. That makes
    retraces to the immediately prior ATR level visible (e.g. +1.00 -> +0.786),
    instead of requiring a new low frontier beyond PDC.
    """
    row0 = group.iloc[0]
    level_prices = [row0[c] for c in COLUMNS]
    if any(pd.isna(p) for p in level_prices):
        return []

    public_idx = [LABELS.index(lab) for lab in REPORT_LABELS]
    public_set = set(public_idx)
    to_public = {LABELS.index(lab): REPORT_LABELS.index(lab) for lab in REPORT_LABELS}
    highs = group["high"].values
    lows = group["low"].values
    opens = group["open"].values if "open" in group.columns else None

    first_hits = [first_hit_bar(highs, lows, level_prices[i], i, opens) if i in public_set else None for i in range(N)]
    seq_pairs = sorted((first_hits[i], i) for i in public_idx if first_hits[i] is not None)
    if not seq_pairs:
        return []

    # When several rungs are first touched in the same OHLC bar, their order is
    # unknowable. Start from PDC when available; otherwise choose the tied rung
    # closest to PDC. This avoids a systematic low-index/downside bias.
    first_bar = seq_pairs[0][0]
    tied_first = [i for bar, i in seq_pairs if bar == first_bar]
    current_idx = min(tied_first, key=lambda i: (abs(i - PDC_IDX), i))
    current_bar = first_bar
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
        first_candidate_bar = candidates[0][0]
        same_bar = [c for c in candidates if c[0] == first_candidate_bar]
        if len(same_bar) > 1:
            # Both adjacent rungs were crossed inside the same OHLC bar, so the
            # true sequence is unknowable. Stop the walk rather than choosing a
            # direction and biasing continuation/retrace stats.
            break
        current_bar, current_idx = candidates[0]
        walk.append(to_public[current_idx])
    return walk


def analyse_gg_retrace_case(group, direction):
    """Measure GG completion after GG opens, split by whether price retraces to trigger first."""
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
    opens = group["open"].values if "open" in group.columns else None
    ts = group.index

    trigger_idx = LABELS.index(trigger_lab)
    open_idx = LABELS.index(open_lab)
    complete_idx = LABELS.index(complete_lab)
    first_hits = [first_hit_bar(highs, lows, level_prices[i], i, opens) for i in range(N)]
    trigger_bar = first_hits[trigger_idx]
    open_bar = first_hits[open_idx]

    # For GG completion baseline/retest stats, include sessions where RTH opens
    # with the Golden Gate already open but not completed. The generic
    # first-hit path logic intentionally excludes gap-open-passed rungs, so we
    # seed the GG-open bar at 09:30 here instead of dropping those cases.
    day_open = opens[0] if opens is not None and len(opens) else None
    if day_open is not None:
        open_price = level_prices[open_idx]
        complete_price = level_prices[complete_idx]
        if target_dir == "up":
            gap_open_gg_open = day_open >= open_price and day_open < complete_price
        else:
            gap_open_gg_open = day_open <= open_price and day_open > complete_price
        if gap_open_gg_open and open_bar is None:
            open_bar = 0
            trigger_bar = 0

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

    # Once GG opens, it remains open for the rest of the RTH session. A trigger
    # retest inside the GG-open bar does not invalidate the setup; if completion
    # happens later, it belongs in the trigger-retest-first cohort. Only a bar
    # that contains both trigger retest and completion is truly unsequenceable.
    if complete_same_bar and retrace_same_bar:
        return {
            "direction": direction,
            "bucket": "ambiguous_open_bar_both",
            "completed": True,
            "minutes_to_completion": 0.0,
        }
    if complete_same_bar:
        return {
            "direction": direction,
            "bucket": "completed_before_trigger_retrace",
            "completed": True,
            "minutes_to_completion": 0.0,
        }

    scan_start = open_bar + 1
    complete_bar = forward_hit_from(scan_start, complete_idx, target_dir) if scan_start < len(group) else None
    retrace_bar = forward_hit_from(scan_start, trigger_idx, retrace_dir) if scan_start < len(group) else None
    if retrace_same_bar:
        retrace_bar = open_bar
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
        "retraced_to_trigger_first": "Trigger retested before GG completion",
        "completed_before_trigger_retrace": "Completed GG before trigger retest",
        "no_decision": "Neither completion nor trigger retest before close",
        "ambiguous_same_bar": "Completion and trigger retest in same later 3-min bar",
        "ambiguous_open_bar_both": "GG-open bar hit both trigger retest and completion",
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


# Histogram bins for time-to-next-level (minutes)
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
    # Per (level, hour_bucket): counts and average minutes for beyond/behind
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

    # 1) per-level overall (no time filter)
    for lab in levels_for_report:
        subset = [e for e in events if e["level"] == lab]
        s = stats_for(subset)
        if s is None:
            continue
        rows.append({"level": lab, "hour_bucket": "ALL", **s})

    # 2) per-level per-hour-bucket
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
    print("ATR LEVEL CASCADE — overall (all hours)")
    print("=" * 90)
    o = df[df["hour_bucket"] == "ALL"].copy()
    print(f"{'Level':>7s} {'N':>6s} {'%Beyond':>9s} {'%Behind':>9s} {'%Last':>7s} {'%Ambig':>8s} "
          f"{'Avg min→Beyond':>15s} {'Avg min→Behind':>15s}")
    # display in order from low to high
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


def print_by_hour_for_level(df, level):
    print()
    print("-" * 90)
    print(f"Level {level} — by hour-of-day of first hit")
    print("-" * 90)
    sub = df[(df["level"] == level) & (df["hour_bucket"] != "ALL")].copy()
    print(f"{'Hour':>13s} {'N':>5s} {'%Beyond':>9s} {'%Behind':>9s} {'%Last':>7s} "
          f"{'%Ambig':>8s} {'AvgMinB+':>9s} {'AvgMinB-':>9s}")
    for hb_label, *_ in HOUR_BUCKETS:
        r = sub[sub["hour_bucket"] == hb_label]
        if len(r) == 0:
            continue
        r = r.iloc[0]
        if r["n"] == 0:
            print(f"{hb_label:>13s} {0:5d}      --        --      --       --        --        --")
            continue
        ab = f"{r['avg_min_to_beyond']:7.0f}" if pd.notna(r['avg_min_to_beyond']) else "     --"
        ah = f"{r['avg_min_to_behind']:7.0f}" if pd.notna(r['avg_min_to_behind']) else "     --"
        flag = "  *" if r["n"] < 50 else ""
        print(f"{hb_label:>13s} {int(r['n']):5d} "
              f"{r['p_beyond']*100:8.1f}% {r['p_behind']*100:8.1f}% "
              f"{r['p_last']*100:6.1f}% {r['p_ambig']*100:7.1f}% "
              f"{ab:>9s} {ah:>9s}{flag}")


def build_json_payload(all_events, all_paths, out_df, n_days, gg_retrace=None, adjacent_walks=None):
    """Build a compact JSON dataset consumed by the study page."""

    # Per-cell summary (level x hour-bucket including "ALL")
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

    # Time-to-next histograms per (level, hour_bucket including ALL) and per outcome
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

    # Public path explorer uses the public ladder, so strip hidden sentinel
    # rungs from paths and remap measurement-ladder indices to report-ladder indices.
    public_idx = {LABELS.index(lab): REPORT_LABELS.index(lab) for lab in REPORT_LABELS}
    public_paths = []
    for path in all_paths:
        remapped = [public_idx[i] for i in path if i in public_idx]
        if remapped:
            public_paths.append(remapped)

    n_events_public = sum(int(c["n"]) for c in cells if c["hour_bucket"] == "ALL")
    public_event_set = set(REPORT_LABELS) - {"PDC"}
    public_events = [e for e in all_events if e.get("level") in public_event_set]
    n_beyond = sum(1 for e in public_events if e.get("outcome") == "beyond")
    n_behind = sum(1 for e in public_events if e.get("outcome") == "behind")
    n_last = sum(1 for e in public_events if e.get("outcome") == "last")
    n_ambig = sum(1 for e in public_events if e.get("outcome") == "ambiguous")
    next_times = [e.get("time_to_min") for e in public_events if e.get("outcome") in ("beyond", "behind") and e.get("time_to_min") is not None]
    outcome_summary = {
        "n": len(public_events),
        "n_beyond": n_beyond,
        "n_behind": n_behind,
        "n_last": n_last,
        "n_ambig": n_ambig,
        "p_beyond": round(n_beyond / len(public_events), 4) if public_events else None,
        "p_behind": round(n_behind / len(public_events), 4) if public_events else None,
        "p_last": round(n_last / len(public_events), 4) if public_events else None,
        "p_ambig": round(n_ambig / len(public_events), 4) if public_events else None,
        "med_min_to_next": round(float(np.median(next_times)), 1) if next_times else None,
        "avg_min_to_next": round(float(np.mean(next_times)), 1) if next_times else None,
    }

    return {
        "metadata": {
            "n_days": n_days,
            "n_events": n_events_public,
            "outcome_summary": outcome_summary,
            "n_events_public": n_events_public,
            "n_events_with_hidden": len(all_events),
            "n_paths": len(public_paths),
            "n_adjacent_walks": len(adjacent_walks or []),
            "ladder": REPORT_LABELS,
            "level_names": {lab: LEVEL_NAMES[lab] for lab in REPORT_LABELS if lab in LEVEL_NAMES},
            "measurement_ladder": LABELS,
            "hidden_measurement_rungs": sorted(HIDDEN_MEASUREMENT_LABELS),
            "hour_buckets": [hb[0] for hb in HOUR_BUCKETS],
            "hist_labels": HIST_LABELS,
            "hist_edges": HIST_EDGES[:-1],
        },
        "cells": cells,
        "hist": hist_payload,
        "paths": public_paths,
        "adjacent_walks": adjacent_walks or [],
        "gg_retrace": gg_retrace or [],
    }


def main():
    print("Loading 3-minute data...")
    df = load_data()
    n_days = df["date"].nunique()
    print(f"  {len(df):,} bars across {n_days:,} trading days")

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
    csv_path = os.path.join(OUT_DIR, "atr_cascade_table.csv")
    out.to_csv(csv_path, index=False)
    print(f"\nWrote {csv_path}")

    gg_retrace = aggregate_gg_retrace(gg_cases)
    json_payload = build_json_payload(all_events, all_paths, out, n_days, gg_retrace=gg_retrace, adjacent_walks=adjacent_walks)
    json_path = os.path.join(BASE_DIR, "site", "data", "atr-cascade.json")
    with open(json_path, "w") as f:
        json.dump(json_payload, f, separators=(",", ":"))
    print(f"Wrote {json_path}  ({os.path.getsize(json_path)/1024:.1f} KB)")

    # Top-line summary (n=ALL)
    print_overall(out)

    # Per-level breakdown by hour-bucket
    for lab in [l for l in REPORT_LABELS if l != "PDC"]:
        # only print if at least some hour-bucket has n>=20 to keep output tractable
        sub = out[(out["level"] == lab) & (out["hour_bucket"] != "ALL")]
        if sub["n"].max() < 20:
            continue
        print_by_hour_for_level(out, lab)

    print("\n* = n < 50 (treat as low-confidence)")


if __name__ == "__main__":
    main()
