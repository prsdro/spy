#!/usr/bin/env python3
"""SPX ATR Markov State Explorer v1.

Semantics:
  - Opening zone cohort: sessions whose 09:30 RTH open ATR offset falls in
    [lower_atr, upper_atr). Denominator includes every such session regardless
    of whether any boundary was touched.
  - Two boundary levels per zone: lower rung L and upper rung U.
  - Scan 3-minute RTH bars 09:30..15:57 in order.
  - Same-bar ambiguity: a bar whose range spans both L and U terminates
    scanning with outcome='ambiguous'.
  - Touch: bar range spans a single boundary (high >= rung >= low).
  - Primary boundary = whichever is touched FIRST on a given day.
  - Attempt counting: attempt increments only when the current bar is NOT
    contiguous with the previous touch bar for this boundary (bar index gap > 1).
    Contiguous bars touching the same level count as one attempt.
  - Post-touch close-side classification (touch bar):
      upper boundary: close >= U_price -> 'above' (accepted); close < U_price -> 'below' (rejected)
      lower boundary: close <= L_price -> 'below' (accepted); close > L_price -> 'above' (rejected)
  - Primary outcome partition per day (sums to zone cohort n):
      accepted_on_1, accepted_on_2, accepted_on_3plus
      opposite_boundary_terminated  (opposite boundary first touched before primary accepted)
      ambiguous
      untouched                     (no boundary touched by 15:57)
      touched_unresolved_by_close   (primary touched/rejected but not accepted by 15:57)
  - Secondary outcome: close-side on the bar that fires opposite_boundary_terminated.
  - "Acceptance" means the touch bar's close landed on the through-side. This is
    a single-bar definition; sustained acceptance is not modelled in v1.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_atr_cascade import (
    HIDDEN_MEASUREMENT_LABELS,
    LADDER,
    LEVEL_NAMES,
)
from backtest_atr_cascade_spx_firstrate import load_spx

BASE_DIR = Path(__file__).resolve().parent
JSON_OUT = BASE_DIR / "site" / "data" / "spx-atr-markov.json"
JSON_OUT.parent.mkdir(parents=True, exist_ok=True)

EPS = 1e-9

# Public ladder: drop hidden +/- 2.236 sentinel rungs.
PUBLIC = [(lab, col, mult) for lab, col, mult in LADDER if lab not in HIDDEN_MEASUREMENT_LABELS]
PUBLIC_LABELS = [r[0] for r in PUBLIC]
PUBLIC_COLS = [r[1] for r in PUBLIC]
PUBLIC_MULTS = [r[2] for r in PUBLIC]
N_PUBLIC = len(PUBLIC_LABELS)
PUBLIC_PDC_IDX = PUBLIC_LABELS.index("PDC")

OUTCOME_BUCKETS = [
    "accepted_on_1",
    "accepted_on_2",
    "accepted_on_3plus",
    "opposite_boundary_terminated",
    "ambiguous",
    "untouched",
    "touched_unresolved_by_close",
]

STATE_HOURS_ET = [10, 11, 12, 13, 14, 15]
SNAPSHOT_STATE_BUCKETS = ["residing", "touching_upper", "touching_lower", "touching_both"]
NEXT_STATE_BUCKETS = [
    "upper_accepted",
    "upper_rejected",
    "lower_accepted",
    "lower_rejected",
    "ambiguous_both",
    "no_next_change",
]

# v3 compact window dataset: residence-zone -> within-window upper/lower
# test and acceptance rates over a fixed time window. Denominator is the
# starting-zone cohort: window 1 uses the 09:30 open price's zone; later
# windows use the close of the first 3-min bar at/after the window start.
WINDOWS = [
    {"key": "0930_1000", "label": "Open → 10am",
     "start_h": 9, "start_m": 30, "end_h": 10, "end_m": 0, "use_open_zone": True},
    {"key": "1000_1100", "label": "10am → 11am",
     "start_h": 10, "start_m": 0, "end_h": 11, "end_m": 0, "use_open_zone": False},
    {"key": "1100_1200", "label": "11am → 12pm",
     "start_h": 11, "start_m": 0, "end_h": 12, "end_m": 0, "use_open_zone": False},
    {"key": "1200_1300", "label": "12pm → 1pm",
     "start_h": 12, "start_m": 0, "end_h": 13, "end_m": 0, "use_open_zone": False},
    {"key": "1300_1400", "label": "1pm → 2pm",
     "start_h": 13, "start_m": 0, "end_h": 14, "end_m": 0, "use_open_zone": False},
    {"key": "1400_1500", "label": "2pm → 3pm",
     "start_h": 14, "start_m": 0, "end_h": 15, "end_m": 0, "use_open_zone": False},
    {"key": "1500_1600", "label": "3pm → 4pm",
     "start_h": 15, "start_m": 0, "end_h": 16, "end_m": 0, "use_open_zone": False},
]


def _build_zones() -> list[dict]:
    zones = []
    for i in range(N_PUBLIC - 1):
        lo_lab = PUBLIC_LABELS[i]
        hi_lab = PUBLIC_LABELS[i + 1]
        lo_mult = PUBLIC_MULTS[i]
        hi_mult = PUBLIC_MULTS[i + 1]
        zones.append({
            "index": i,
            "lower_label": lo_lab,
            "upper_label": hi_lab,
            "lower_atr": lo_mult,
            "upper_atr": hi_mult,
            "lower_name": LEVEL_NAMES.get(lo_lab, lo_lab),
            "upper_name": LEVEL_NAMES.get(hi_lab, hi_lab),
        })
    return zones


ZONES = _build_zones()
N_ZONES = len(ZONES)


def find_zone_index(open_atr: float) -> int | None:
    """Return zone index such that lower_atr <= open_atr < upper_atr."""
    if not np.isfinite(open_atr):
        return None
    for z in ZONES:
        if z["lower_atr"] <= open_atr < z["upper_atr"]:
            return z["index"]
    return None


def _accepted_outcome(attempts: int) -> str:
    if attempts == 1:
        return "accepted_on_1"
    if attempts == 2:
        return "accepted_on_2"
    return "accepted_on_3plus"


def scan_day(
    ts_arr: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    open_price: float,
    zone_idx: int,
    rung_prices: list[float],
) -> dict:
    """Scan one RTH day and return per-day Markov state record."""
    n = len(ts_arr)
    start_ts = ts_arr[0]

    U_price = rung_prices[zone_idx + 1]
    L_price = rung_prices[zone_idx]

    # If open equals lower rung exactly, require strict cross for first bar.
    open_on_lower = abs(open_price - L_price) < EPS

    primary: str | None = None  # 'upper' | 'lower'
    upper_attempts = 0
    upper_last_bar = -2
    lower_attempts = 0
    lower_last_bar = -2

    primary_outcome: str | None = None
    primary_minutes: float | None = None
    secondary_close_side: str | None = None
    secondary_minutes: float | None = None
    events: list[dict] = []

    def _minutes(bar_idx: int) -> float:
        return float(
            (ts_arr[bar_idx] - start_ts).astype("timedelta64[s]").astype(np.int64)
        ) / 60.0

    for i in range(n):
        hi = highs[i]
        lo = lows[i]
        cl = closes[i]

        up_hit = (hi >= U_price) and (lo <= U_price)
        if open_on_lower:
            lo_hit = (lo < L_price - EPS) and (hi >= L_price)
        else:
            lo_hit = (lo <= L_price) and (hi >= L_price)

        if not (up_hit or lo_hit):
            continue

        m = round(_minutes(i), 3)

        # Same-bar ambiguity terminates the day.
        if up_hit and lo_hit:
            events.append({"m": m, "side": "ambiguous", "attempt": None, "close_side": None, "resolution": "ambiguous"})
            primary_outcome = "ambiguous"
            if primary is None:
                primary = "ambiguous"
            break

        if up_hit:
            if primary is None:
                # First boundary touch: upper becomes primary.
                primary = "upper"
                upper_attempts = 1
            elif primary == "lower":
                # Opposite boundary (upper) touched for the first time.
                cs = "above" if cl >= U_price else "below"
                secondary_close_side = cs
                secondary_minutes = m
                events.append({"m": m, "side": "upper", "attempt": 1, "close_side": cs, "resolution": "secondary_first_touch"})
                primary_outcome = "opposite_boundary_terminated"
                primary_minutes = m
                break
            else:
                # Continuing upper primary track.
                if i != upper_last_bar + 1:
                    upper_attempts += 1
            upper_last_bar = i

            cs = "above" if cl >= U_price else "below"
            if cs == "above":
                events.append({"m": m, "side": "upper", "attempt": upper_attempts, "close_side": cs, "resolution": "accepted"})
                primary_outcome = _accepted_outcome(upper_attempts)
                primary_minutes = m
                break
            else:
                events.append({"m": m, "side": "upper", "attempt": upper_attempts, "close_side": cs, "resolution": "rejected"})

        elif lo_hit:
            if primary is None:
                primary = "lower"
                lower_attempts = 1
            elif primary == "upper":
                # Opposite boundary (lower) touched for the first time.
                cs = "below" if cl <= L_price else "above"
                secondary_close_side = cs
                secondary_minutes = m
                events.append({"m": m, "side": "lower", "attempt": 1, "close_side": cs, "resolution": "secondary_first_touch"})
                primary_outcome = "opposite_boundary_terminated"
                primary_minutes = m
                break
            else:
                if i != lower_last_bar + 1:
                    lower_attempts += 1
            lower_last_bar = i

            cs = "below" if cl <= L_price else "above"
            if cs == "below":
                events.append({"m": m, "side": "lower", "attempt": lower_attempts, "close_side": cs, "resolution": "accepted"})
                primary_outcome = _accepted_outcome(lower_attempts)
                primary_minutes = m
                break
            else:
                events.append({"m": m, "side": "lower", "attempt": lower_attempts, "close_side": cs, "resolution": "rejected"})

    # Session-close resolution.
    if primary is None:
        primary_outcome = "untouched"
        primary = "none"
    elif primary_outcome is None:
        primary_outcome = "touched_unresolved_by_close"

    attempts = (
        upper_attempts if primary == "upper"
        else lower_attempts if primary == "lower"
        else 0
    )

    return {
        "primary_first_test": primary,
        "events": events,
        "primary_outcome": primary_outcome,
        "primary_attempts": attempts,
        "primary_minutes": primary_minutes,
        "secondary_close_side": secondary_close_side,
        "secondary_minutes": secondary_minutes,
    }


def _median_or_none(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(statistics.median(vals), 1)


def find_zone_for_atr(x: float) -> int | None:
    """Return residence zone for an ATR-offset price/close."""
    return find_zone_index(x)


def _snapshot_state_for_bar(hi: float, lo: float, cl: float, zone_idx: int, rung_prices: list[float]) -> str:
    """Classify whether the snapshot bar is touching an adjacent boundary level."""
    L = rung_prices[zone_idx]
    U = rung_prices[zone_idx + 1]
    up_hit = (hi >= U) and (lo <= U)
    lo_hit = (lo <= L) and (hi >= L)
    if up_hit and lo_hit:
        return "touching_both"
    if up_hit:
        return "touching_upper"
    if lo_hit:
        return "touching_lower"
    return "residing"


def _next_state_change_from(start_idx: int, ts_arr: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, zone_idx: int, rung_prices: list[float]) -> dict:
    """Find the next adjacent boundary event after a current-state snapshot."""
    start_ts = ts_arr[start_idx]
    L = rung_prices[zone_idx]
    U = rung_prices[zone_idx + 1]
    for j in range(start_idx + 1, len(ts_arr)):
        hi = highs[j]
        lo = lows[j]
        cl = closes[j]
        up_hit = (hi >= U) and (lo <= U)
        lo_hit = (lo <= L) and (hi >= L)
        if not (up_hit or lo_hit):
            continue
        m = float((ts_arr[j] - start_ts).astype("timedelta64[s]").astype(np.int64)) / 60.0
        if up_hit and lo_hit:
            return {"outcome": "ambiguous_both", "side": "ambiguous", "minutes": round(m, 3)}
        if up_hit:
            return {"outcome": "upper_accepted" if cl >= U else "upper_rejected", "side": "upper", "minutes": round(m, 3)}
        return {"outcome": "lower_accepted" if cl <= L else "lower_rejected", "side": "lower", "minutes": round(m, 3)}
    return {"outcome": "no_next_change", "side": "none", "minutes": None}


def _scan_window(
    ts_arr: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    zone_idx: int,
    rung_prices: list[float],
    bar_idxs: np.ndarray,
) -> dict:
    """Within a given set of bar indices, determine:
      1. Whether the upper and lower adjacent ATR boundary levels were tested,
         and whether the FIRST test of each was accepted (independent rates).
      2. The first-resolution bucket — a mutually exclusive partition over the
         starting-zone cohort that sums to n. Categories: first_upper_accept,
         first_upper_reject, first_lower_accept, first_lower_reject,
         first_both_same_bar, no_touch.

    Test (touch): bar range spans the boundary (high >= boundary >= low).
    Accepted (upper): first-up-test bar close > upper boundary.
    Accepted (lower): first-dn-test bar close < lower boundary.
    First-resolution is determined by the FIRST bar in the window that touches
    either boundary. If that bar touches both rungs simultaneously the day is
    classified as first_both_same_bar.
    """
    U = rung_prices[zone_idx + 1]
    L = rung_prices[zone_idx]
    tested_up = False
    accepted_up = False
    tested_dn = False
    accepted_dn = False
    first_up_m: float | None = None
    first_dn_m: float | None = None
    first_resolution: str = "no_touch"
    first_resolution_m: float | None = None
    if len(bar_idxs) == 0:
        return {
            "tested_up": False, "accepted_up": False, "first_up_m": None,
            "tested_dn": False, "accepted_dn": False, "first_dn_m": None,
            "first_resolution": "no_touch", "first_resolution_m": None,
        }
    start_ts = ts_arr[bar_idxs[0]]
    seen_first = False
    for i in bar_idxs:
        hi = highs[i]
        lo = lows[i]
        cl = closes[i]
        up_hit = (hi >= U) and (lo <= U)
        lo_hit = (hi >= L) and (lo <= L)
        if not seen_first and (up_hit or lo_hit):
            seen_first = True
            first_resolution_m = float((ts_arr[i] - start_ts).astype("timedelta64[s]").astype(np.int64)) / 60.0
            if up_hit and lo_hit:
                first_resolution = "first_both_same_bar"
            elif up_hit:
                first_resolution = "first_upper_accept" if cl > U else "first_upper_reject"
            else:
                first_resolution = "first_lower_accept" if cl < L else "first_lower_reject"
        if not tested_up and up_hit:
            tested_up = True
            accepted_up = bool(cl > U)
            first_up_m = float((ts_arr[i] - start_ts).astype("timedelta64[s]").astype(np.int64)) / 60.0
        if not tested_dn and lo_hit:
            tested_dn = True
            accepted_dn = bool(cl < L)
            first_dn_m = float((ts_arr[i] - start_ts).astype("timedelta64[s]").astype(np.int64)) / 60.0
        if tested_up and tested_dn:
            break
    return {
        "tested_up": tested_up, "accepted_up": accepted_up,
        "first_up_m": None if first_up_m is None else round(first_up_m, 1),
        "tested_dn": tested_dn, "accepted_dn": accepted_dn,
        "first_dn_m": None if first_dn_m is None else round(first_dn_m, 1),
        "first_resolution": first_resolution,
        "first_resolution_m": None if first_resolution_m is None else round(first_resolution_m, 1),
    }


FIRST_RES_BUCKETS = [
    "first_upper_accept",
    "first_upper_reject",
    "first_lower_accept",
    "first_lower_reject",
    "first_both_same_bar",
    "no_touch",
]


def _aggregate_windows(window_rows: list[dict]) -> dict:
    """Group per-session window observations by (window_key, zone_index)."""
    by_key: dict[tuple, list[dict]] = {}
    for r in window_rows:
        by_key.setdefault((r["wk"], r["zi"]), []).append(r)

    windows_out = []
    for w in WINDOWS:
        zones_out = {}
        for zi in range(N_ZONES):
            rows = by_key.get((w["key"], zi), [])
            n = len(rows)
            if n == 0:
                continue
            tu = sum(1 for r in rows if r["tu"])
            au = sum(1 for r in rows if r["au"])
            td = sum(1 for r in rows if r["td"])
            ad = sum(1 for r in rows if r["ad"])
            up_times = [r["um"] for r in rows if r["tu"] and r["um"] is not None]
            dn_times = [r["dm"] for r in rows if r["td"] and r["dm"] is not None]
            tested_either = sum(1 for r in rows if r["tu"] or r["td"])
            tested_both = sum(1 for r in rows if r["tu"] and r["td"])
            first_res = {b: 0 for b in FIRST_RES_BUCKETS}
            for r in rows:
                first_res[r["fr"]] = first_res.get(r["fr"], 0) + 1
            assert sum(first_res.values()) == n, (
                f"first-resolution partition does not sum to n for {w['key']}:{zi}: "
                f"sum={sum(first_res.values())} n={n}"
            )
            zones_out[str(zi)] = {
                "n": n,
                "tested_up": tu,
                "accepted_up": au,
                "tested_down": td,
                "accepted_down": ad,
                "tested_either": tested_either,
                "tested_both": tested_both,
                "rejected_up": tu - au,
                "rejected_down": td - ad,
                "median_up_m": _median_or_none(up_times),
                "median_down_m": _median_or_none(dn_times),
                "first_resolution": first_res,
            }
        windows_out.append({
            "key": w["key"],
            "label": w["label"],
            "start_et": f"{w['start_h']:02d}:{w['start_m']:02d}",
            "end_et": f"{w['end_h']:02d}:{w['end_m']:02d}",
            "use_open_zone": w["use_open_zone"],
            "by_zone": zones_out,
        })

    return {
        "windows": windows_out,
        "definitions": {
            "denominator": "All historical sessions whose starting price is in the selected ATR residence zone at the start of the window. Window 1 (Open → 10am) uses the 09:30 RTH open price's zone to match the existing opening-zone cohort; windows 2-7 use the close of the first 3-min bar at/after the window start. Each session contributes at most one snapshot per window.",
            "tested": "A 3-min bar within the window has a range that touches/spans the adjacent ATR boundary level (bar high >= level AND bar low <= level).",
            "accepted_up": "The FIRST 3-min bar within the window that tests the upper adjacent boundary closes above that boundary (close > upper level price).",
            "accepted_down": "The FIRST 3-min bar within the window that tests the lower adjacent boundary closes below that boundary (close < lower level price).",
            "independent_rates": "The four displayed rates (tested up, tested down, accepted up, accepted down) are INDEPENDENT rates over the same starting-zone denominator. A single session can test BOTH boundaries, so tested_up + tested_down typically exceeds n. accepted_up + accepted_down does NOT equal 'sessions that left the zone'.",
            "rejected_up": "tested_up - accepted_up. A session whose first up-test bar's close landed BACK INSIDE the zone (close <= upper level).",
            "rejected_down": "tested_down - accepted_down. A session whose first down-test bar's close landed back inside the zone (close >= lower level).",
            "tested_either": "Sessions where at least one boundary was tested in the window.",
            "tested_both": "Sessions where BOTH boundaries were tested at some point in the window.",
            "first_resolution": "Mutually exclusive partition over n. For each session, the FIRST bar in the window that touches either boundary determines the bucket: first_upper_accept (touched upper only, close > U), first_upper_reject (touched upper only, close <= U), first_lower_accept (touched lower only, close < L), first_lower_reject (touched lower only, close >= L), first_both_same_bar (single bar touched both rungs), no_touch (no boundary touched in window). Buckets sum to n.",
            "scope": "Within-window only. Bars at or after the window end are ignored. Acceptance/rejection refer to single-bar close polarity at the first test; sustained acceptance is deliberately not modelled here.",
        },
    }


def _aggregate_current_state(snapshot_rows: list[dict]) -> dict:
    """Aggregate hourly current-state snapshots into next-state probabilities."""
    groups: dict[str, list[dict]] = {}
    for r in snapshot_rows:
        key = f"{r['hour']}|{r['zi']}|{r['ls']}"
        groups.setdefault(key, []).append(r)
    states = []
    for key, rows in sorted(groups.items(), key=lambda kv: (int(kv[0].split('|')[0]), int(kv[0].split('|')[1]), kv[0].split('|')[2])):
        hour_s, zi_s, ls = key.split('|')
        outcomes = {}
        for b in NEXT_STATE_BUCKETS:
            br = [r for r in rows if r["nx"] == b]
            times = [r["nm"] for r in br if r.get("nm") is not None]
            outcomes[b] = {"n": len(br), "median_m": _median_or_none(times)}
        states.append({
            "hour": int(hour_s),
            "zone_index": int(zi_s),
            "level_state": ls,
            "n": len(rows),
            "outcomes": outcomes,
            "examples": [r["d"] for r in rows[:8]],
        })
    return {
        "snapshot_hours_et": STATE_HOURS_ET,
        "level_states": SNAPSHOT_STATE_BUCKETS,
        "outcome_buckets": NEXT_STATE_BUCKETS,
        "states": states,
        "definitions": {
            "current_state_denominator": "All historical hourly snapshots matching the selected hour, current ATR residence zone, and current adjacent-level interaction state. Each session contributes at most one snapshot for that hour.",
            "current_zone": "The ATR zone containing the snapshot bar close. Price resides in zones between adjacent public Saty ATR levels.",
            "level_state": "Whether the snapshot bar is merely residing inside the zone or is touching the upper boundary, lower boundary, or both boundaries. Levels are boundary events, not residence states.",
            "next_state_change": "First adjacent boundary-level touch after the snapshot. Upper/lower accepted means the touch-bar close landed through the level; rejected means the touch-bar close landed back inside the current zone.",
        },
    }


def _aggregate_zone(zone_days: list[dict]) -> dict:
    """Pre-compute zone-level aggregate buckets from per-day records."""
    n = len(zone_days)

    def _buckets(side: str) -> dict:
        """Aggregate the primary-first-test track for one boundary side.

        These buckets are intentionally a day-level primary partition, not two
        independent per-boundary denominators. Percentages should normally be
        rendered against the full opening-zone cohort, with the side's `n`
        shown as the subset where that boundary was the first tested level.
        """
        subset = [d for d in zone_days if d["primary_first_test"] == side]
        ns = len(subset)
        out: dict = {"n": ns}
        for bkt in OUTCOME_BUCKETS:
            days_bkt = [d for d in subset if d["primary_outcome"] == bkt]
            times = [d["primary_minutes"] for d in days_bkt if d["primary_minutes"] is not None]
            out[bkt] = {"n": len(days_bkt), "median_m": _median_or_none(times)}
        # Secondary outcome breakdown for opposite_boundary_terminated.
        opp = [d for d in subset if d["primary_outcome"] == "opposite_boundary_terminated"]
        sec_acc = sum(1 for d in opp if d["secondary_close_side"] == ("below" if side == "upper" else "above"))
        sec_rej = len(opp) - sec_acc
        sec_times = [d["secondary_minutes"] for d in opp if d["secondary_minutes"] is not None]
        out["opposite_secondary"] = {
            "secondary_accepted": sec_acc,
            "secondary_rejected": sec_rej,
            "median_m": _median_or_none(sec_times),
        }
        return out

    untouched_n = sum(1 for d in zone_days if d["primary_first_test"] == "none")
    initial_ambiguous_n = sum(1 for d in zone_days if d["primary_first_test"] == "ambiguous")
    all_ambiguous_n = sum(1 for d in zone_days if d["primary_outcome"] == "ambiguous")
    amb_times = [d["primary_minutes"] for d in zone_days if d["primary_first_test"] == "ambiguous" and d["primary_minutes"] is not None]
    primary_upper = _buckets("upper")
    primary_lower = _buckets("lower")

    return {
        "n": n,
        "primary_upper": primary_upper,
        "primary_lower": primary_lower,
        "primary_first_test_counts": {
            "upper": primary_upper["n"],
            "lower": primary_lower["n"],
            "ambiguous": initial_ambiguous_n,
            "none": untouched_n,
        },
        "untouched_n": untouched_n,
        "initial_ambiguous_n": initial_ambiguous_n,
        "all_ambiguous_n": all_ambiguous_n,
        "ambiguous_n": initial_ambiguous_n,
        "ambiguous_median_m": _median_or_none(amb_times),
        "low_sample": n < 100,
    }


def build_payload(df: pd.DataFrame, diag: dict) -> dict:
    days_out: list[dict] = []
    snapshot_rows: list[dict] = []
    window_rows: list[dict] = []
    zone_day_map: dict[int, list[dict]] = {i: [] for i in range(N_ZONES)}
    skipped_outside = 0
    skipped_no_open = 0
    n_total_days = 0

    for date, group in df.groupby("date", sort=True):
        n_total_days += 1
        group = group.sort_index()
        first_ts = group.index[0]
        if first_ts.hour != 9 or first_ts.minute != 30:
            skipped_no_open += 1
            continue
        prev_close = float(group["prev_close"].iloc[0])
        atr14 = float(group["atr_14"].iloc[0])
        if not (np.isfinite(prev_close) and np.isfinite(atr14) and atr14 > 0):
            skipped_no_open += 1
            continue

        open_price = float(group["open"].iloc[0])
        open_atr = (open_price - prev_close) / atr14
        zone_idx = find_zone_index(open_atr)
        if zone_idx is None:
            skipped_outside += 1
            continue

        rung_prices = [prev_close + m * atr14 for m in PUBLIC_MULTS]

        ts_arr = group.index.values
        highs = group["high"].to_numpy(dtype=float)
        lows = group["low"].to_numpy(dtype=float)
        closes = group["close"].to_numpy(dtype=float)

        rec = scan_day(ts_arr, highs, lows, closes, open_price, zone_idx, rung_prices)

        # v2 hourly current-state snapshots: hour + current ATR residence zone
        # + current level-interaction state -> next adjacent boundary event.
        for hour in STATE_HOURS_ET:
            idxs = np.where((group.index.hour == hour) & (group.index.minute == 0))[0]
            if len(idxs) == 0:
                continue
            si = int(idxs[0])
            close_atr = (float(closes[si]) - prev_close) / atr14
            cur_zi = find_zone_for_atr(close_atr)
            if cur_zi is None:
                continue
            level_state = _snapshot_state_for_bar(float(highs[si]), float(lows[si]), float(closes[si]), cur_zi, rung_prices)
            nxt = _next_state_change_from(si, ts_arr, highs, lows, closes, cur_zi, rung_prices)
            snapshot_rows.append({
                "d": str(date),
                "hour": hour,
                "zi": cur_zi,
                "ls": level_state,
                "ca": round(close_atr, 4),
                "nx": nxt["outcome"],
                "ns": nxt["side"],
                "nm": nxt["minutes"],
            })

        # v3 compact window dataset: for each fixed time window, find
        # starting-zone cohort and within-window upper/lower test/accept rates.
        bar_hours = group.index.hour.to_numpy()
        bar_mins = group.index.minute.to_numpy()
        bar_min_of_day = bar_hours * 60 + bar_mins
        for w in WINDOWS:
            w_start = w["start_h"] * 60 + w["start_m"]
            w_end = w["end_h"] * 60 + w["end_m"]
            mask = (bar_min_of_day >= w_start) & (bar_min_of_day < w_end)
            idxs = np.where(mask)[0]
            if len(idxs) == 0:
                continue
            if w["use_open_zone"]:
                w_zone_idx = zone_idx
            else:
                first_close_atr = (float(closes[idxs[0]]) - prev_close) / atr14
                w_zone_idx = find_zone_for_atr(first_close_atr)
                if w_zone_idx is None:
                    continue
            scan = _scan_window(ts_arr, highs, lows, closes, w_zone_idx, rung_prices, idxs)
            window_rows.append({
                "wk": w["key"],
                "zi": w_zone_idx,
                "tu": scan["tested_up"],
                "au": scan["accepted_up"],
                "um": scan["first_up_m"],
                "td": scan["tested_dn"],
                "ad": scan["accepted_dn"],
                "dm": scan["first_dn_m"],
                "fr": scan["first_resolution"],
                "frm": scan["first_resolution_m"],
            })

        date_s = str(date)
        day_rec = {
            "d": date_s,
            "y": int(date_s[:4]),
            "oa": round(open_atr, 4),
            "zi": zone_idx,
            "pft": rec["primary_first_test"],
            "po": rec["primary_outcome"],
            "pa": rec["primary_attempts"],
            "pm": rec["primary_minutes"],
            "scs": rec["secondary_close_side"],
            "sm": rec["secondary_minutes"],
            "ev": rec["events"],
        }
        days_out.append(day_rec)
        zone_day_map[zone_idx].append(rec)

    # Build zone aggregates.
    zone_aggregates = []
    for zi in range(N_ZONES):
        agg = _aggregate_zone(zone_day_map[zi])
        zone_aggregates.append({**ZONES[zi], **agg})

    metadata = {
        "symbol": "SPX",
        "source": diag.get("source"),
        "source_vendor": diag.get("source_vendor"),
        "timezone": diag.get("timezone"),
        "timestamp_convention": diag.get("timestamp_convention"),
        "bar_minutes": diag.get("bar_minutes"),
        "canonical_source_timeframe": diag.get("canonical_source_timeframe"),
        "rth_3m_days": diag.get("rth_3m_days"),
        "intraday_start": diag.get("rth_3m_first"),
        "intraday_end": diag.get("rth_3m_last"),
        "n_total_days": n_total_days,
        "n_days_in_zones": len(days_out),
        "n_skipped_outside_public_ladder": skipped_outside,
        "n_skipped_no_open_or_atr": skipped_no_open,
        "year_range": [int(days_out[0]["y"]), int(days_out[-1]["y"])] if days_out else None,
        "available_years": sorted({d["y"] for d in days_out}),
        "version": "atrmarkov-v3-windows",
        "generated_at": "deterministic-source-build",
        "definitions": {
            "opening_zone_cohort": "Days whose 09:30 RTH open price, expressed as ATR offset from previous close, falls in [lower_atr, upper_atr). Denominator includes all such sessions.",
            "primary_boundary": "The first boundary (upper or lower rung of the opening zone) whose price is spanned by a 3-minute bar's range.",
            "primary_first_test_view": "v1 is a day-level primary-first-test explorer. Upper/lower cards show sessions where that adjacent boundary was the first tested level. Percentages are rendered against the full opening-zone cohort unless explicitly labeled as subset percentages.",
            "attempt": "A contiguous-touch sequence counts as one attempt. A new attempt begins when a non-touching bar precedes the next touch.",
            "close_side_upper": "Touch-bar close >= U_price -> above (accepted). close < U_price -> below (rejected).",
            "close_side_lower": "Touch-bar close <= L_price -> below (accepted). close > L_price -> above (rejected).",
            "acceptance_caveat": "Acceptance is defined as the touch bar's own close landing on the through-side. Sustained acceptance (held for multiple bars) is NOT modelled in v1.",
            "opposite_boundary_terminated": "Primary boundary had >=0 rejections; opposite boundary was touched for the first time before primary was accepted.",
            "ambiguous": "A single 3-minute bar's range spans both the upper and lower rung simultaneously.",
            "untouched": "Neither boundary was touched by the 15:57 close.",
            "touched_unresolved_by_close": "Primary boundary was touched and rejected but not accepted before the 15:57 session close.",
            "outcome_partition": "For each zone, the 7 buckets (accepted_on_1, accepted_on_2, accepted_on_3plus, opposite_boundary_terminated, ambiguous, untouched, touched_unresolved_by_close) sum to n.",
            "current_state_v2": "Current-state mode goes beyond the open: choose hour of day, current ATR residence zone, and current level-interaction state, then see the next adjacent boundary event probabilities. This is an hourly snapshot model, not a trade recommendation.",
        },
    }

    return {
        "metadata": metadata,
        "zones": zone_aggregates,
        "ladder": [{"label": PUBLIC_LABELS[i], "atr": PUBLIC_MULTS[i]} for i in range(N_PUBLIC)],
        "current_state": _aggregate_current_state(snapshot_rows),
        "windows_by_zone": _aggregate_windows(window_rows),
        "days": days_out,
    }


def run() -> dict:
    print("Loading FirstRateData SPX 1-minute + daily data ...")
    df, diag = load_spx()
    print(f"  {diag['rth_3m_days']:,} RTH days, {diag['rth_3m_rows']:,} 3-min bars")
    payload = build_payload(df, diag)
    with JSON_OUT.open("w") as f:
        json.dump(payload, f, separators=(",", ":"))
    size_kb = JSON_OUT.stat().st_size / 1024.0
    print(f"Wrote {JSON_OUT} ({size_kb:.1f} KB)")
    md = payload["metadata"]
    print(f"  days_in_zones={md['n_days_in_zones']:,}  outside={md['n_skipped_outside_public_ladder']:,}  skipped={md['n_skipped_no_open_or_atr']:,}")
    print(f"  current_state_groups={len(payload.get('current_state', {}).get('states', [])):,}")
    # Quick integrity check: each zone's bucket counts sum to n.
    for z in payload["zones"]:
        zi = z["index"]
        n = z["n"]
        up_n = z["primary_upper"].get("n", 0)
        lo_n = z["primary_lower"].get("n", 0)
        unt = z["untouched_n"]
        amb = z["ambiguous_n"]
        total = up_n + lo_n + unt + amb
        assert total == n, f"Zone {zi} bucket sum {total} != n={n}"
    print("  Zone bucket integrity: OK")

    # v3 windows contract check: each zone bucket's tested/accepted counts must
    # not exceed n, and accepted <= tested. Window count must match WINDOWS.
    wbz = payload.get("windows_by_zone", {})
    assert len(wbz.get("windows", [])) == len(WINDOWS), "windows count mismatch"
    for w in wbz["windows"]:
        for zk, zr in w["by_zone"].items():
            n = zr["n"]
            assert zr["tested_up"] <= n and zr["tested_down"] <= n, f"tested > n in {w['key']}:{zk}"
            assert zr["accepted_up"] <= zr["tested_up"], f"accepted_up > tested_up in {w['key']}:{zk}"
            assert zr["accepted_down"] <= zr["tested_down"], f"accepted_down > tested_down in {w['key']}:{zk}"
            fr_sum = sum(zr["first_resolution"].values())
            assert fr_sum == n, f"first_resolution sum {fr_sum} != n {n} in {w['key']}:{zk}"
            # tested_either >= max(tested_up, tested_down); tested_both <= min
            assert zr["tested_either"] >= max(zr["tested_up"], zr["tested_down"]), f"tested_either invariant in {w['key']}:{zk}"
            assert zr["tested_both"] <= min(zr["tested_up"], zr["tested_down"]), f"tested_both invariant in {w['key']}:{zk}"
            # Inclusion-exclusion: tested_either = tested_up + tested_down - tested_both
            assert zr["tested_either"] == zr["tested_up"] + zr["tested_down"] - zr["tested_both"], f"incl-excl in {w['key']}:{zk}"
    total_window_sessions = sum(zr["n"] for w in wbz["windows"] for zr in w["by_zone"].values())
    print(f"  Windows: {len(wbz['windows'])}, total session-window observations={total_window_sessions:,}")
    print("  Window bucket integrity: OK")
    return payload


def main() -> None:
    run()


if __name__ == "__main__":
    main()
