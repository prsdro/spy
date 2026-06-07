#!/usr/bin/env python3
"""Contract tests for backtest_open_band_path.

Covers:
  1. Band inclusion at the lower/upper boundaries (lower inclusive, upper exclusive).
  2. Upside continuation, upside retracement.
  3. Downside continuation, downside retracement.
  4. Same-bar ambiguous (terminates path).
  5. No-first-touch (terminates path).
  6. Cumulative curves use the original cohort denominator (amb + none stay visible).
  7. Path conditioning after the first event narrows the cohort to the chosen step
     and recomputes from the new band.

Run: python3 test_open_band_path.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from backtest_open_band_path import (
    BANDS,
    N_PUBLIC,
    PUBLIC_LABELS,
    PUBLIC_MULTS,
    PUBLIC_PDC_IDX,
    band_side,
    find_band_index,
    walk_path,
)


def _ts_grid(n: int = 130) -> np.ndarray:
    base = np.datetime64("2025-01-02T09:30:00")
    return np.array([base + np.timedelta64(3 * i, "m") for i in range(n)], dtype="datetime64[ns]")


def _bar_arrays(n: int, default_high: float, default_low: float):
    return np.full(n, default_high, dtype=float), np.full(n, default_low, dtype=float)


def _rung_prices(prev_close: float, atr: float) -> list[float]:
    return [prev_close + m * atr for m in PUBLIC_MULTS]


def _band(label_low: str) -> dict:
    for b in BANDS:
        if b["lower_label"] == label_low:
            return b
    raise KeyError(label_low)


def test_band_inclusion_boundaries():
    # +0.236 .. +0.382 band: lower inclusive, upper exclusive
    b = _band("+0.236")
    assert find_band_index(b["lower_atr"]) == b["index"], "lower bound must be inclusive"
    assert find_band_index(b["upper_atr"]) != b["index"], "upper bound must be exclusive"
    next_b = _band("+0.382")
    assert find_band_index(b["upper_atr"]) == next_b["index"], "upper bound must roll into next band"
    # Interior
    mid = (b["lower_atr"] + b["upper_atr"]) / 2
    assert find_band_index(mid) == b["index"]
    # Outside public ladder
    assert find_band_index(-2.5) is None
    assert find_band_index(2.5) is None
    assert find_band_index(2.0) is None  # +2.00 is the top boundary; no band above
    # Bottom boundary -2.00 IS a band lower-bound (band [-2.00, -1.786))
    assert find_band_index(-2.0) == _band("-2.00")["index"]


def test_upside_continuation():
    # open in [+0.236, +0.382): cont = touch +0.382 first
    b = _band("+0.236")
    pdc = 100.0
    atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr  # interior
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    # 09:30 bar quiet, 09:33 bar reaches +0.382 only
    upper_p = rung[b["index"] + 1]
    highs[1] = upper_p + 0.01  # touch upper
    lows[1] = open_price        # didn't touch lower
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[0]["o"] == "cont", path
    assert path[0]["m"] == 3.0
    assert path[0]["side"] == "up"


def test_upside_retracement():
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    lower_p = rung[b["index"]]
    lows[2] = lower_p - 0.01  # touch lower at 09:36
    highs[2] = open_price + 0.01
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[0]["o"] == "retr", path
    assert path[0]["m"] == 6.0


def test_downside_continuation():
    # open in [-0.382, -0.236): cont = touch -0.382 (lower rung, away from PDC)
    b = _band("-0.382")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc - 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    lower_p = rung[b["index"]]
    lows[3] = lower_p - 0.01
    highs[3] = open_price + 0.01
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[0]["o"] == "cont"
    assert path[0]["side"] == "down"
    assert path[0]["m"] == 9.0


def test_downside_retracement():
    b = _band("-0.382")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc - 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    upper_p = rung[b["index"] + 1]
    highs[4] = upper_p + 0.01  # touch upper rung -0.236 = retr toward PDC
    lows[4] = open_price - 0.01
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[0]["o"] == "retr"
    assert path[0]["side"] == "down"
    assert path[0]["m"] == 12.0


def test_same_bar_ambiguous_terminates():
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    upper_p = rung[b["index"] + 1]
    lower_p = rung[b["index"]]
    # bar 5 hits both boundaries simultaneously
    highs[5] = upper_p + 0.05
    lows[5] = lower_p - 0.05
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[-1]["o"] == "amb"
    assert len(path) == 1, "ambiguous must terminate the path"
    assert path[0]["m"] == 15.0


def test_no_first_touch_terminates():
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    # bars never touch either boundary
    highs = np.full(n, open_price + 0.01)
    lows = np.full(n, open_price - 0.01)
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[-1]["o"] == "none"
    assert "m" not in path[-1]
    assert len(path) == 1


def test_path_conditioning_after_cont():
    """After a cont event, the new band is shifted one rung in the cont direction
    and the next event's outcome should reflect that band's labels."""
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    upper_p = rung[b["index"] + 1]      # +0.382 price
    next_upper_p = rung[b["index"] + 2] # +0.50 price
    lower_p = rung[b["index"]]          # +0.236 price
    # bar 1: cont (touch +0.382, not +0.50)
    highs[1] = upper_p + 0.01
    lows[1] = open_price
    # bar 10: cont again (touch +0.50)
    highs[10] = next_upper_p + 0.01
    lows[10] = upper_p + 0.05
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert len(path) >= 2
    assert path[0]["o"] == "cont"
    assert path[0]["lo"] == "+0.236" and path[0]["hi"] == "+0.382"
    assert path[1]["lo"] == "+0.382" and path[1]["hi"] == "+0.50"
    assert path[1]["o"] == "cont"
    assert path[1]["m"] == 30.0


def test_path_conditioning_after_retr_can_cross_pdc():
    """Open in [PDC, +0.236) (upside-by-rule); after retr to PDC, the new
    band is [-0.236, PDC), which is downside, so the side label must flip."""
    b = _band("PDC")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.10 * atr  # in [PDC, +0.236)
    n = 130
    ts = _ts_grid(n)
    highs, lows = _bar_arrays(n, default_high=open_price + 0.01, default_low=open_price - 0.01)
    pdc_p = rung[b["index"]]                # PDC price
    minus_236 = rung[b["index"] - 1]        # -0.236 price
    # bar 2: retr (touch PDC)
    highs[2] = open_price + 0.01
    lows[2] = pdc_p - 0.001                 # crosses through PDC
    # bar 12: cont in new band (touch -0.236)
    highs[12] = pdc_p - 0.001
    lows[12] = minus_236 - 0.01
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[0]["o"] == "retr"
    assert path[0]["side"] == "up"
    assert path[1]["lo"] == "-0.236" and path[1]["hi"] == "PDC"
    assert path[1]["side"] == "down"
    # touching -0.236 from a downside band = cont
    assert path[1]["o"] == "cont"


def test_open_at_lower_rung_does_not_count_as_touch():
    """If the 09:30 open price equals the lower rung exactly, the bar.low
    being == lower rung must not trigger a touch (open itself is not a touch)."""
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    lower_p = rung[b["index"]]
    open_price = lower_p  # exactly at boundary
    n = 130
    ts = _ts_grid(n)
    highs = np.full(n, open_price + 0.01)
    lows = np.full(n, open_price)            # bar lows == open price == lower rung
    # No movement; no touch should ever register
    path = walk_path(ts, highs, lows, open_price, b["index"], rung)
    assert path[-1]["o"] == "none"
    # Now make bar 1's low strictly below the lower rung -> should count
    lows2 = lows.copy()
    lows2[1] = lower_p - 0.001
    highs2 = highs.copy()
    path2 = walk_path(ts, highs2, lows2, open_price, b["index"], rung)
    assert path2[0]["o"] == "retr"
    assert path2[0]["m"] == 3.0


def _cumulative(days_paths: list[list[dict]], step: int, target_outcome: str, denom: int, grid: range) -> list[float]:
    """Cumulative numerator / original-cohort denominator for path[step]==target_outcome."""
    out = []
    for t in grid:
        c = 0
        for path in days_paths:
            if step >= len(path):
                continue
            ev = path[step]
            if ev["o"] != target_outcome:
                continue
            if ev.get("m") is None:
                continue
            if ev["m"] <= t:
                c += 1
        out.append(c / denom if denom else 0.0)
    return out


def test_cumulative_uses_original_denominator():
    """Build a tiny synthetic cohort with mixed outcomes and verify that
    cumulative curves divide by the cohort size, not the survivor count."""
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    upper_p = rung[b["index"] + 1]
    lower_p = rung[b["index"]]

    paths = []
    # 10 cohort days
    # 4 cont at minute 6
    for _ in range(4):
        highs, lows = _bar_arrays(n, open_price + 0.01, open_price - 0.01)
        highs[2] = upper_p + 0.01
        paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))
    # 3 retr at minute 9
    for _ in range(3):
        highs, lows = _bar_arrays(n, open_price + 0.01, open_price - 0.01)
        lows[3] = lower_p - 0.01
        paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))
    # 2 amb at minute 12
    for _ in range(2):
        highs, lows = _bar_arrays(n, open_price + 0.01, open_price - 0.01)
        highs[4] = upper_p + 0.05
        lows[4] = lower_p - 0.05
        paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))
    # 1 none
    highs = np.full(n, open_price + 0.01); lows = np.full(n, open_price - 0.01)
    paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))

    denom = len(paths)  # 10
    grid = range(0, 391, 3)
    cont_curve = _cumulative(paths, 0, "cont", denom, grid)
    retr_curve = _cumulative(paths, 0, "retr", denom, grid)
    amb_curve = _cumulative(paths, 0, "amb", denom, grid)
    # at t=6 minutes: 4 cont have happened
    assert cont_curve[grid.index(6) if hasattr(grid, "index") else list(grid).index(6)] == 0.4
    grid_list = list(grid)
    assert cont_curve[grid_list.index(6)] == 0.4
    assert retr_curve[grid_list.index(9)] == 0.3
    assert amb_curve[grid_list.index(12)] == 0.2
    # Final values should be the full proportions out of 10
    assert cont_curve[-1] == 0.4
    assert retr_curve[-1] == 0.3
    assert amb_curve[-1] == 0.2
    # 1 "none" + 0.4+0.3+0.2 = 0.9 with rounding. (none stays visible as denom leakage.)
    assert abs((cont_curve[-1] + retr_curve[-1] + amb_curve[-1]) - 0.9) < 1e-9


def test_path_conditioning_narrows_cohort():
    """Cohort denominator for step-2 must be the count of days whose step-1
    outcome was the chosen one (cont here), not the original cohort size."""
    b = _band("+0.236")
    pdc = 100.0; atr = 10.0
    rung = _rung_prices(pdc, atr)
    open_price = pdc + 0.30 * atr
    n = 130
    ts = _ts_grid(n)
    upper_p = rung[b["index"] + 1]
    next_upper_p = rung[b["index"] + 2]
    lower_p = rung[b["index"]]

    paths = []
    # 5 days: cont then cont
    for _ in range(5):
        highs, lows = _bar_arrays(n, open_price + 0.01, open_price - 0.01)
        highs[2] = upper_p + 0.01
        highs[8] = next_upper_p + 0.01
        lows[8] = upper_p + 0.001
        paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))
    # 3 days: cont then retr (back to lower of new band = +0.236)
    for _ in range(3):
        highs, lows = _bar_arrays(n, open_price + 0.01, open_price - 0.01)
        highs[2] = upper_p + 0.01
        lows[8] = upper_p - 0.001
        highs[8] = upper_p + 0.001
        # NB: the cont touch at bar 2 reuses bar 2 in next-band scan; but bar 2's
        # values won't trigger further events because we set them above. The new
        # band is [+0.236, +0.382] (upper now +0.382). Wait, after touching upper
        # from band [+0.236,+0.382] we move to [+0.382,+0.50]. So lower is now
        # +0.382 (=upper_p) and upper is +0.50 (=next_upper_p). Touching +0.382
        # again is "retr" (toward PDC) on the new upside band.
        paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))
    # 2 days: retr first (no cont path)
    for _ in range(2):
        highs, lows = _bar_arrays(n, open_price + 0.01, open_price - 0.01)
        lows[3] = lower_p - 0.01
        paths.append(walk_path(ts, highs, lows, open_price, b["index"], rung))

    cohort_size = len(paths)  # 10
    cont_first_paths = [p for p in paths if p and p[0]["o"] == "cont"]
    assert len(cont_first_paths) == 8
    # Step 2: of the 8 with cont first, 5 had cont second, 3 had retr second
    step2_cont = sum(1 for p in cont_first_paths if len(p) > 1 and p[1]["o"] == "cont")
    step2_retr = sum(1 for p in cont_first_paths if len(p) > 1 and p[1]["o"] == "retr")
    assert step2_cont == 5
    assert step2_retr == 3
    # Conditional probability after step 1 = cont
    assert step2_cont / len(cont_first_paths) == 0.625
    assert step2_retr / len(cont_first_paths) == 0.375
    # Original cohort denominator would have been 10 -> 0.5 / 0.3 (different)
    assert step2_cont / cohort_size == 0.5


def main() -> int:
    tests = [
        test_band_inclusion_boundaries,
        test_upside_continuation,
        test_upside_retracement,
        test_downside_continuation,
        test_downside_retracement,
        test_same_bar_ambiguous_terminates,
        test_no_first_touch_terminates,
        test_path_conditioning_after_cont,
        test_path_conditioning_after_retr_can_cross_pdc,
        test_open_at_lower_rung_does_not_count_as_touch,
        test_cumulative_uses_original_denominator,
        test_path_conditioning_narrows_cohort,
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
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
