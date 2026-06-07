#!/usr/bin/env python3
"""Contract tests for backtest_atr_markov.

Covers the 9 directives from the corrected implementation plan:
  1. Cohort parity per zone with backtest_open_band_path (same denominator).
  2. Per-boundary bucket counts sum to zone cohort n (denominator integrity).
  3. Close-above on touch bar -> accepted; close-below -> rejected (and mirror for lower).
  4. Contiguous touch bars collapse into one attempt; gap > 1 bar starts new attempt.
  5. Three rejections then acceptance -> accepted_on_3plus (attempt=4 bucket).
  6. Same-bar ambiguity terminates the day.
  7. Open exactly on lower rung does not count as touch (parity with open-band-path).
  8. Per-day events list is monotonically increasing in m.
  9. Generator is deterministic (two build_payload calls produce identical output).

Run: python3 test_atr_markov.py
"""

from __future__ import annotations

import copy
import sys
import json
from datetime import datetime

import numpy as np
import pandas as pd

from backtest_atr_markov import (
    ZONES,
    N_ZONES,
    PUBLIC_LABELS,
    PUBLIC_MULTS,
    N_PUBLIC,
    find_zone_index,
    scan_day,
    build_payload,
    OUTCOME_BUCKETS,
)
from backtest_open_band_path import (
    BANDS,
    find_band_index,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _ts_grid(n: int = 130) -> np.ndarray:
    base = np.datetime64("2025-01-02T09:30:00")
    return np.array([base + np.timedelta64(3 * i, "m") for i in range(n)], dtype="datetime64[ns]")


def _rung_prices(prev_close: float, atr: float) -> list[float]:
    return [prev_close + m * atr for m in PUBLIC_MULTS]


def _zone(lower_label: str) -> dict:
    for z in ZONES:
        if z["lower_label"] == lower_label:
            return z
    raise KeyError(lower_label)


def _make_arrays(n: int, hi: float, lo: float, cl: float):
    return (
        np.full(n, hi, dtype=float),
        np.full(n, lo, dtype=float),
        np.full(n, cl, dtype=float),
    )


def _run(ts, highs, lows, closes, open_price, zone_idx, rung_prices):
    return scan_day(ts, highs, lows, closes, open_price, zone_idx, rung_prices)


# ── test 1: cohort parity with open-band-path ─────────────────────────────────

def test_cohort_parity_zone_indices():
    """Zone index from find_zone_index must match band index from find_band_index
    for the same open_atr, over a representative sweep of midpoints."""
    mismatches = 0
    for zi in range(N_ZONES):
        z = ZONES[zi]
        mid = (z["lower_atr"] + z["upper_atr"]) / 2
        zi_result = find_zone_index(mid)
        bi_result = find_band_index(mid)
        if zi_result != bi_result:
            mismatches += 1
            print(f"    MISMATCH zone {zi}: markov={zi_result} obp={bi_result}")
    assert mismatches == 0, f"{mismatches} zone index mismatches vs open-band-path"


def test_cohort_parity_boundaries():
    """Lower boundary inclusive, upper exclusive — same as open-band-path."""
    z = _zone("+0.236")
    assert find_zone_index(z["lower_atr"]) == z["index"]
    assert find_zone_index(z["upper_atr"]) != z["index"]
    assert find_zone_index(-2.5) is None
    assert find_zone_index(2.5) is None


# ── test 2: denominator integrity ─────────────────────────────────────────────

def test_denominator_integrity():
    """Build a synthetic payload and verify per-zone bucket sums == n."""
    pdc = 100.0
    atr = 10.0
    rung = _rung_prices(pdc, atr)
    z = _zone("+0.236")
    zi = z["index"]
    open_price = pdc + 0.30 * atr
    open_atr = (open_price - pdc) / atr

    U_price = rung[zi + 1]
    L_price = rung[zi]
    n_bars = 130
    ts = _ts_grid(n_bars)

    def _make_df(event_spec):
        """event_spec: list of (bar_idx, 'up'|'lo'|'both'|None, close_override)"""
        hi_arr = np.full(n_bars, open_price + 0.01)
        lo_arr = np.full(n_bars, open_price - 0.01)
        cl_arr = np.full(n_bars, open_price)
        for bi, which, cl_val in event_spec:
            if which == "up":
                hi_arr[bi] = U_price + 0.05
                lo_arr[bi] = open_price - 0.01
            elif which == "lo":
                lo_arr[bi] = L_price - 0.05
                hi_arr[bi] = open_price + 0.01
            elif which == "both":
                hi_arr[bi] = U_price + 0.05
                lo_arr[bi] = L_price - 0.05
            if cl_val is not None:
                cl_arr[bi] = cl_val
        return hi_arr, lo_arr, cl_arr

    day_specs = [
        # accepted_on_1 upper
        [(2, "up", U_price + 0.01)],
        [(3, "up", U_price + 0.01)],
        # accepted_on_2 upper
        [(2, "up", open_price), (5, "up", U_price + 0.01)],
        # accepted_on_3plus upper
        [(2, "up", open_price), (5, "up", open_price), (8, "up", U_price + 0.01)],
        # opposite_boundary_terminated (upper primary, then lower hit)
        [(2, "up", open_price), (8, "lo", L_price - 0.01)],
        # ambiguous
        [(2, "both", open_price)],
        # untouched
        [],
        # touched_unresolved_by_close (upper rejected all day)
        [(2, "up", open_price)],
    ]

    results = []
    for spec in day_specs:
        hi, lo, cl = _make_df(spec)
        r = _run(ts, hi, lo, cl, open_price, zi, rung)
        results.append(r)

    # Build fake payload-like zone data.
    from backtest_atr_markov import _aggregate_zone
    agg = _aggregate_zone(results)

    up_n = agg["primary_upper"]["n"]
    lo_n = agg["primary_lower"]["n"]
    unt = agg["untouched_n"]
    amb = agg["ambiguous_n"]
    total = up_n + lo_n + unt + amb
    assert total == len(results), f"Bucket sum {total} != n={len(results)}"


# ── test 3: close-side classification ─────────────────────────────────────────

def test_close_above_upper_accepted():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    # bar 2: high touches upper, close above -> accepted
    hi[2] = U_price + 0.05
    lo[2] = open_price - 0.01
    cl[2] = U_price + 0.01
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_first_test"] == "upper"
    assert r["primary_outcome"] == "accepted_on_1"
    assert r["primary_minutes"] == 6.0
    assert r["events"][0]["close_side"] == "above"
    assert r["events"][0]["resolution"] == "accepted"


def test_close_below_upper_rejected():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    hi[2] = U_price + 0.05
    lo[2] = open_price - 0.01
    cl[2] = open_price  # close below U_price
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_first_test"] == "upper"
    assert r["primary_outcome"] == "touched_unresolved_by_close"
    assert r["events"][0]["close_side"] == "below"
    assert r["events"][0]["resolution"] == "rejected"


def test_close_below_lower_accepted():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    L_price = rung[zi]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    lo[3] = L_price - 0.05
    hi[3] = open_price + 0.01
    cl[3] = L_price - 0.01  # close below L_price -> accepted
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_first_test"] == "lower"
    assert r["primary_outcome"] == "accepted_on_1"
    assert r["events"][0]["close_side"] == "below"
    assert r["events"][0]["resolution"] == "accepted"


def test_close_above_lower_rejected():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    L_price = rung[zi]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    lo[3] = L_price - 0.05
    hi[3] = open_price + 0.01
    cl[3] = open_price  # close above L_price -> rejected
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_first_test"] == "lower"
    assert r["primary_outcome"] == "touched_unresolved_by_close"
    assert r["events"][0]["close_side"] == "above"
    assert r["events"][0]["resolution"] == "rejected"


# ── test 4: contiguous bars collapse, gap starts new attempt ──────────────────

def test_contiguous_bars_same_attempt():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    # bars 2 and 3 both touch upper (contiguous), both reject
    hi[2] = U_price + 0.05; lo[2] = open_price - 0.01; cl[2] = open_price
    hi[3] = U_price + 0.05; lo[3] = open_price - 0.01; cl[3] = open_price
    # bar 10: accept
    hi[10] = U_price + 0.05; lo[10] = open_price - 0.01; cl[10] = U_price + 0.01
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    # bars 2&3 = attempt 1 (contiguous), bar 10 = attempt 2
    assert r["primary_outcome"] == "accepted_on_2", r["primary_outcome"]
    assert r["primary_attempts"] == 2


def test_gap_bar_new_attempt():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    # bar 2: reject (attempt 1)
    hi[2] = U_price + 0.05; lo[2] = open_price - 0.01; cl[2] = open_price
    # bar 4: reject (attempt 2, gap bar 3 is quiet)
    hi[4] = U_price + 0.05; lo[4] = open_price - 0.01; cl[4] = open_price
    # bar 6: accept (attempt 3)
    hi[6] = U_price + 0.05; lo[6] = open_price - 0.01; cl[6] = U_price + 0.01
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_outcome"] == "accepted_on_3plus", r["primary_outcome"]
    assert r["primary_attempts"] == 3


# ── test 5: 3 rejections then acceptance = accepted_on_3plus ──────────────────

def test_four_attempts_accepted_on_3plus():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    for bar_i in [2, 5, 8]:
        hi[bar_i] = U_price + 0.05; lo[bar_i] = open_price - 0.01; cl[bar_i] = open_price
    hi[11] = U_price + 0.05; lo[11] = open_price - 0.01; cl[11] = U_price + 0.01
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_outcome"] == "accepted_on_3plus"
    assert r["primary_attempts"] == 4


# ── test 6: same-bar ambiguity terminates ─────────────────────────────────────

def test_ambiguity_terminates():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    L_price = rung[zi]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    hi[5] = U_price + 0.05
    lo[5] = L_price - 0.05
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_outcome"] == "ambiguous"
    assert len(r["events"]) == 1
    assert r["events"][0]["resolution"] == "ambiguous"
    assert r["primary_minutes"] is None  # no minutes for ambiguous


def test_ambiguity_after_rejection_terminates():
    """Ambiguity can fire after a prior rejection of the primary boundary."""
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    L_price = rung[zi]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    # bar 2: upper reject
    hi[2] = U_price + 0.05; lo[2] = open_price - 0.01; cl[2] = open_price
    # bar 6: ambiguous
    hi[6] = U_price + 0.05; lo[6] = L_price - 0.05
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_outcome"] == "ambiguous"
    assert r["events"][-1]["resolution"] == "ambiguous"


# ── test 7: open on lower rung not a touch ────────────────────────────────────

def test_open_on_lower_rung_not_a_touch():
    """When open == lower rung, lo == L_price never counts as a touch (strict
    criterion applies for all bars, matching open-band-path semantics)."""
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    L_price = rung[zi]
    U_price = rung[zi + 1]
    open_price = L_price  # exactly at lower boundary
    ts = _ts_grid(130)
    # All bars: lo == L_price (touching but not strictly crossing) -> not a touch
    hi = np.full(130, open_price + 0.01)
    lo = np.full(130, open_price)
    cl = np.full(130, open_price)
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_outcome"] == "untouched", f"got {r['primary_outcome']}"
    # Strict cross below L_price on bar 1 -> accepted_on_1
    lo2 = lo.copy()
    lo2[1] = L_price - 0.001  # strictly below L_price - EPS
    cl2 = cl.copy()
    cl2[1] = L_price - 0.001
    r2 = _run(ts, hi, lo2, cl2, open_price, zi, rung)
    assert r2["primary_outcome"] == "accepted_on_1", f"got {r2['primary_outcome']}"
    assert r2["primary_minutes"] == 3.0


# ── test 8: events monotonic in m ─────────────────────────────────────────────

def test_events_monotonic():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    for bar_i in [2, 5, 8, 11]:
        hi[bar_i] = U_price + 0.05; lo[bar_i] = open_price - 0.01; cl[bar_i] = open_price
    hi[14] = U_price + 0.05; lo[14] = open_price - 0.01; cl[14] = U_price + 0.01
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    times = [e["m"] for e in r["events"]]
    assert times == sorted(times), f"Events not monotonic: {times}"
    assert len(times) >= 2


# ── test 9: generator determinism ─────────────────────────────────────────────

def test_generator_determinism():
    """Two build_payload calls on the same DataFrame produce identical JSON."""
    from backtest_atr_cascade_spx_firstrate import load_spx
    df, diag = load_spx()
    # Use only the first 300 days to keep the test fast.
    dates = df["date"].unique()[:300]
    df_small = df[df["date"].isin(dates)].copy()
    diag_small = dict(diag)

    p1 = build_payload(df_small, diag_small)
    p2 = build_payload(df_small, diag_small)

    j1 = json.dumps(p1, separators=(",", ":"), sort_keys=True)
    j2 = json.dumps(p2, separators=(",", ":"), sort_keys=True)
    assert j1 == j2, "Two runs produced different JSON"


# ── test: opposite_boundary_terminated ────────────────────────────────────────

def test_opposite_boundary_terminated():
    z = _zone("+0.236")
    zi = z["index"]
    pdc, atr = 100.0, 10.0
    rung = _rung_prices(pdc, atr)
    U_price = rung[zi + 1]
    L_price = rung[zi]
    open_price = pdc + 0.30 * atr
    ts = _ts_grid(130)
    hi, lo, cl = _make_arrays(130, open_price + 0.01, open_price - 0.01, open_price)
    # bar 2: upper rejected (upper is primary)
    hi[2] = U_price + 0.05; lo[2] = open_price - 0.01; cl[2] = open_price
    # bar 8: lower touched first time -> terminates upper track
    lo[8] = L_price - 0.05; hi[8] = open_price + 0.01; cl[8] = L_price - 0.01  # secondary accepted
    r = _run(ts, hi, lo, cl, open_price, zi, rung)
    assert r["primary_first_test"] == "upper"
    assert r["primary_outcome"] == "opposite_boundary_terminated"
    assert r["secondary_close_side"] == "below"  # lower accepted
    assert r["secondary_minutes"] == 24.0  # bar 8 * 3 min


# ── runner ────────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        test_cohort_parity_zone_indices,
        test_cohort_parity_boundaries,
        test_denominator_integrity,
        test_close_above_upper_accepted,
        test_close_below_upper_rejected,
        test_close_below_lower_accepted,
        test_close_above_lower_rejected,
        test_contiguous_bars_same_attempt,
        test_gap_bar_new_attempt,
        test_four_attempts_accepted_on_3plus,
        test_ambiguity_terminates,
        test_ambiguity_after_rejection_terminates,
        test_open_on_lower_rung_not_a_touch,
        test_events_monotonic,
        test_opposite_boundary_terminated,
        test_generator_determinism,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
