"""
Tests for backtest_bilbo_box_edge_validation.

Pytest may not be installed; runnable via `python3 test_bilbo_edge_validation.py`.
"""

import math
import numpy as np
import pandas as pd

from backtest_bilbo_box_edge_validation import (
    BREAKEVEN_HIT_RATE,
    BOOTSTRAP_PATH_LEN,
    FRICTION_PER_TRADE_PTS,
    N_BOOTSTRAP,
    SENSITIVITY_STOPS,
    SENSITIVITY_TARGETS,
    WALKFWD_MIN_TRADES,
    assign_verdict,
    bootstrap_mc,
    evaluate_single_bracket_custom,
    friction_test,
    headline_block,
    max_consecutive,
    per_trade_R,
    sensitivity_grid,
    walk_forward_by_year,
)


# ───────────────────────── helpers ─────────────────────────

def _make_event(pnl_points, t2=False, stop=False, ts=None,
                box_high=500.0, box_low=499.0, direction="bull",
                entry_price=500.0):
    """Build a single evaluated-event row resembling the locked-universe output."""
    return {
        "break_bar_ts": ts if ts is not None else pd.Timestamp("2024-06-01 10:00"),
        "box_high": box_high,
        "box_low": box_low,
        "direction": direction,
        "__entry_price": entry_price,
        "__entry_ts": ts if ts is not None else pd.Timestamp("2024-06-01 10:00"),
        "strategy_pnl_points": pnl_points,
        "strategy_targets_hit": 1 if t2 else 0,
        "strategy_stop_hit": stop,
        "strategy_timeout": (not t2 and not stop),
        "strategy_resolution": "T1" if t2 else ("stop" if stop else "timeout"),
        "strategy_bars_to_resolution": 5,
        "strategy_same_bar_conflicts": 0,
        "strategy_t1_hit": t2,
        "strategy_t1_bar": 3 if t2 else None,
    }


def _build_universe(n_per_year, win_rate_per_year, R_box=1.0):
    """Create a synthetic ev DataFrame with controllable per-year win rates."""
    rows = []
    for year, n in n_per_year.items():
        wr = win_rate_per_year[year]
        n_win = int(round(n * wr))
        n_loss = n - n_win
        for k in range(n_win):
            ts = pd.Timestamp(f"{year}-06-01 10:00") + pd.Timedelta(minutes=3 * k)
            rows.append(_make_event(pnl_points=R_box, t2=True, ts=ts,
                                    box_high=500.0 + R_box, box_low=500.0))
        for k in range(n_loss):
            ts = pd.Timestamp(f"{year}-07-01 10:00") + pd.Timedelta(minutes=3 * k)
            rows.append(_make_event(pnl_points=-0.5 * R_box, stop=True, ts=ts,
                                    box_high=500.0 + R_box, box_low=500.0))
    return pd.DataFrame(rows)


def _make_bars():
    """3-min bar frame containing the entry timestamps used in custom-walker tests."""
    idx = pd.date_range("2024-06-03 09:30", periods=20, freq="3min")
    df = pd.DataFrame({
        "open":  np.full(20, 500.0),
        "high":  np.full(20, 500.2),
        "low":   np.full(20, 499.8),
        "close": np.full(20, 500.0),
    }, index=idx)
    df.index.name = "timestamp"
    return df


# ───────────────────────── per_trade_R / max_consecutive ─────────────────────────

def test_per_trade_R_divides_pnl_by_box_height():
    ev = pd.DataFrame([
        _make_event(pnl_points=2.0, box_high=502.0, box_low=500.0),  # R=2.0 → +1.0 R
        _make_event(pnl_points=-1.0, box_high=502.0, box_low=500.0), # R=2.0 → -0.5 R
    ])
    R = per_trade_R(ev)
    assert math.isclose(R[0], 1.0)
    assert math.isclose(R[1], -0.5)


def test_max_consecutive_counts_longest_run_of_ones():
    assert max_consecutive([0, 1, 1, 0, 1, 1, 1, 0, 1]) == 3
    assert max_consecutive([]) == 0
    assert max_consecutive([0, 0, 0]) == 0
    assert max_consecutive([1, 1, 1, 1]) == 4


# ───────────────────────── headline ─────────────────────────

def test_headline_block_basic_stats_match_hand_computation():
    # 10 trades: 5 wins +1R, 4 stops -0.5R, 1 timeout 0.0R
    R_arr = np.array([1.0]*5 + [-0.5]*4 + [0.0])
    ev = pd.DataFrame([_make_event(pnl_points=1.0, t2=True)]*5
                      + [_make_event(pnl_points=-0.5, stop=True)]*4
                      + [_make_event(pnl_points=0.0)])
    h = headline_block(ev, R_arr)
    assert h["n"] == 10
    assert math.isclose(h["t2_hit_rate"], 0.5)
    assert math.isclose(h["stop_rate"], 0.4)
    assert math.isclose(h["timeout_rate"], 0.1)
    # mean R = (5 - 2 + 0) / 10 = 0.3
    assert math.isclose(h["mean_R_per_trade"], 0.3, abs_tol=1e-9)
    # profit factor = 5 / 2 = 2.5
    assert math.isclose(h["profit_factor"], 2.5, abs_tol=1e-9)


# ───────────────────────── walk-forward ─────────────────────────

def test_walk_forward_year_split_correctness():
    # 60 trades in 2023 at 50% win, 60 in 2024 at 30% win, 20 in 2025 (below threshold).
    ev = _build_universe(
        n_per_year={2023: 60, 2024: 60, 2025: 20},
        win_rate_per_year={2023: 0.50, 2024: 0.30, 2025: 1.00},
        R_box=1.0,
    )
    R = per_trade_R(ev)
    rows = walk_forward_by_year(ev, R, min_n=WALKFWD_MIN_TRADES)
    by_year = {r["year"]: r for r in rows}
    assert set(by_year.keys()) == {2023, 2024, 2025}

    assert by_year[2023]["qualifying"] is True
    assert by_year[2023]["n"] == 60
    assert math.isclose(by_year[2023]["win_pct"], 0.50)
    assert by_year[2023]["clears_breakeven"] is True   # 0.50 > 0.333

    assert by_year[2024]["qualifying"] is True
    assert by_year[2024]["n"] == 60
    assert math.isclose(by_year[2024]["win_pct"], 0.30)
    assert by_year[2024]["clears_breakeven"] is False  # 0.30 < 0.333

    assert by_year[2025]["qualifying"] is False        # below n threshold
    assert by_year[2025]["clears_breakeven"] is None


# ───────────────────────── bootstrap shape ─────────────────────────

def test_bootstrap_shape_and_keys():
    # Tiny resample so test runs fast.
    R_arr = np.array([1.0, 1.0, -0.5, -0.5, 0.0, 1.0, -0.5])
    out = bootstrap_mc(R_arr, n_paths=200, path_len=50, seed=7)
    assert isinstance(out, dict)
    for key in ("n_paths", "path_len", "seed",
                "median_final_R", "p10_final_R", "p90_final_R",
                "pct_positive", "pct_dd_worse_than_neg50R"):
        assert key in out
    assert out["n_paths"] == 200
    assert out["path_len"] == 50
    # Percentile invariants
    assert out["p10_final_R"] <= out["median_final_R"] <= out["p90_final_R"]
    assert 0.0 <= out["pct_positive"] <= 1.0
    assert 0.0 <= out["pct_dd_worse_than_neg50R"] <= 1.0


def test_bootstrap_is_deterministic_given_seed():
    R_arr = np.array([1.0, -0.5, 0.0, 1.0, -0.5, 1.0, -0.5, 0.0])
    a = bootstrap_mc(R_arr, n_paths=100, path_len=40, seed=123)
    b = bootstrap_mc(R_arr, n_paths=100, path_len=40, seed=123)
    assert a == b


# ───────────────────────── sensitivity grid ─────────────────────────

def test_sensitivity_grid_size_matches_cross_product():
    # Sensitivity does an actual bar walk, so use real bars + one synthetic event
    # whose entry maps to a real bar timestamp. The exact outcome doesn't matter
    # for the size assertion.
    bars = _make_bars()
    ev = pd.DataFrame([{
        "__entry_ts": pd.Timestamp("2024-06-03 09:30"),
        "__entry_price": 500.0,
        "box_high": 500.0,
        "box_low": 499.0,
        "direction": "bull",
    }])
    rows = sensitivity_grid(ev, bars,
                            stops=SENSITIVITY_STOPS, targets=SENSITIVITY_TARGETS)
    assert len(rows) == len(SENSITIVITY_STOPS) * len(SENSITIVITY_TARGETS)
    keys = {(r["stop_R"], r["target_R"]) for r in rows}
    expected = {(s, t) for s in SENSITIVITY_STOPS for t in SENSITIVITY_TARGETS}
    assert keys == expected
    for r in rows:
        for k in ("n", "win_pct", "avg_R", "ev_per_1000"):
            assert k in r


def test_evaluate_single_bracket_custom_records_target_hit():
    bars = _make_bars()
    # Make the next bar after entry a strong bullish breakout that touches the +1R target.
    bars.loc[pd.Timestamp("2024-06-03 09:33"),
             ["open", "high", "low", "close"]] = [500.1, 501.5, 500.05, 501.4]
    ev = pd.DataFrame([{
        "__entry_ts": pd.Timestamp("2024-06-03 09:30"),
        "__entry_price": 500.0,
        "box_high": 500.0,
        "box_low": 499.0,
        "direction": "bull",
    }])
    out = evaluate_single_bracket_custom(ev, bars, stop_R=0.5, target_R=1.0)
    assert len(out) == 1
    assert math.isclose(out[0], 1.0)


def test_evaluate_single_bracket_custom_records_stop_hit():
    bars = _make_bars()
    # Drop into the stop on the very next bar.
    bars.loc[pd.Timestamp("2024-06-03 09:33"),
             ["open", "high", "low", "close"]] = [500.0, 500.1, 499.4, 499.45]
    ev = pd.DataFrame([{
        "__entry_ts": pd.Timestamp("2024-06-03 09:30"),
        "__entry_price": 500.0,
        "box_high": 500.0,
        "box_low": 499.0,
        "direction": "bull",
    }])
    out = evaluate_single_bracket_custom(ev, bars, stop_R=0.5, target_R=1.0)
    assert math.isclose(out[0], -0.5)


# ───────────────────────── friction monotonicity ─────────────────────────

def test_friction_monotonicity_reduces_mean_R_and_pf():
    # Mixed wins/losses so PF is finite both before and after.
    R_arr = np.array([1.0, 1.0, 1.0, 1.0, -0.5, -0.5, -0.5, -0.5, 0.0])
    ev = pd.DataFrame([_make_event(pnl_points=1.0, box_high=502.0, box_low=500.0)
                       for _ in range(len(R_arr))])
    f_low = friction_test(ev, R_arr, friction_pts=0.0)
    f_mid = friction_test(ev, R_arr, friction_pts=FRICTION_PER_TRADE_PTS)
    f_hi = friction_test(ev, R_arr, friction_pts=FRICTION_PER_TRADE_PTS * 4)
    # Mean R must decrease as friction grows.
    assert f_low["mean_R_after_friction"] > f_mid["mean_R_after_friction"]
    assert f_mid["mean_R_after_friction"] > f_hi["mean_R_after_friction"]
    # EV per 1k must decrease in lockstep.
    assert (f_low["ev_per_1000_after_friction"]
            > f_mid["ev_per_1000_after_friction"]
            > f_hi["ev_per_1000_after_friction"])
    # PF must decrease too because numerator shrinks and denominator grows.
    assert f_low["profit_factor_after_friction"] >= f_mid["profit_factor_after_friction"]
    assert f_mid["profit_factor_after_friction"] >= f_hi["profit_factor_after_friction"]
    # Zero-friction R == raw R.
    assert math.isclose(f_low["mean_R_after_friction"], R_arr.mean(), abs_tol=1e-9)


# ───────────────────────── verdict ─────────────────────────

def test_verdict_publishable_when_all_four_criteria_met():
    headline = {"t2_hit_rate": 0.45}
    walk = [{"qualifying": True, "clears_breakeven": True} for _ in range(5)]
    walk += [{"qualifying": True, "clears_breakeven": False}]   # 5/6 ~ 83% pass
    mc = {"p10_final_R": 12.0}
    fric = {"ev_per_1000_after_friction": 80.0}
    v, c = assign_verdict(headline, walk, mc, fric)
    assert v == "publishable"
    assert c["n_criteria_met"] == 4


def test_verdict_borderline_when_three_of_four_met():
    headline = {"t2_hit_rate": 0.45}
    walk = [{"qualifying": True, "clears_breakeven": True} for _ in range(5)]
    walk += [{"qualifying": True, "clears_breakeven": False}]
    mc = {"p10_final_R": -5.0}                        # FAIL
    fric = {"ev_per_1000_after_friction": 50.0}
    v, c = assign_verdict(headline, walk, mc, fric)
    assert v == "borderline"
    assert c["n_criteria_met"] == 3


def test_verdict_not_publishable_when_two_or_fewer_met():
    headline = {"t2_hit_rate": 0.20}                  # FAIL
    walk = [{"qualifying": True, "clears_breakeven": False} for _ in range(5)]  # FAIL
    mc = {"p10_final_R": -10.0}                       # FAIL
    fric = {"ev_per_1000_after_friction": 30.0}
    v, c = assign_verdict(headline, walk, mc, fric)
    assert v == "not_publishable"
    assert c["n_criteria_met"] == 1


# ───────────────────────── manual harness ─────────────────────────

def _run_all():
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS {f.__name__}")
        except AssertionError as e:
            failed.append((f.__name__, repr(e)))
            print(f"FAIL {f.__name__}: {e!r}")
        except Exception as e:
            failed.append((f.__name__, repr(e)))
            print(f"ERROR {f.__name__}: {e!r}")
    print(f"\n{len(funcs) - len(failed)} passed, {len(failed)} failed/errored")
    return len(failed)


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
