import math
from datetime import date

import numpy as np
import pandas as pd

from backtest_bilbo_box_htf_po_exits import StrategyParams, evaluate_event_strategy_pnl


def _arrays(rows):
    idx = pd.date_range("2024-01-02 09:30", periods=len(rows), freq="3min")
    highs = np.array([r[0] for r in rows], dtype=float)
    lows = np.array([r[1] for r in rows], dtype=float)
    closes = np.array([r[2] for r in rows], dtype=float)
    dates = np.array([date(2024, 1, 2)] * len(rows))
    return idx.values.astype("datetime64[ns]"), highs, lows, closes, dates


def test_bull_three_contract_partials_hold_initial_stop_until_t2_and_full_t3_profit_points():
    # Entry at 500, box 499-500, R=1.
    # T1=500.5 exits first contract and leaves stop at the opposite box side.
    # T2=501 exits second contract, then moves final contract stop to the box top.
    # T3=502 exits final contract. Total points = 0.5 + 1.0 + 2.0 = 3.5.
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.6, 500.1, 500.55),
        (501.1, 500.6, 501.05),
        (502.1, 501.2, 502.0),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        entry_idx=0,
        entry_price=500.0,
        direction="bull",
        box_high=500.0,
        box_low=499.0,
        params=StrategyParams(),
        intraday_rth=True,
    )
    assert res["targets_hit"] == 3
    assert res["t1_hit"] and res["t2_hit"] and res["t3_hit"]
    assert not res["stop_hit"]
    assert not res["timeout"]
    assert res["resolution"] == "T3"
    assert math.isclose(res["pnl_points"], 3.5)


def test_bull_after_t1_stop_does_not_move_for_remaining_contracts():
    # T1 hit exits one at +0.5. Remaining two still use initial stop at box low 499.
    # A midpoint touch at 499.4 should not stop the trade.
    # Final timeout at 499.45 gives P&L = +0.5 + 2*(-0.55) = -0.6 points.
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.6, 500.1, 500.55),
        (500.4, 499.4, 499.45),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bull", 500.0, 499.0, StrategyParams(), True,
    )
    assert res["targets_hit"] == 1
    assert not res["stop_hit"]
    assert res["timeout"]
    assert math.isclose(res["pnl_points"], -0.6)


def test_bull_after_t2_stop_moves_to_box_top_and_stays_there():
    # T1 and T2 exit two contracts. Stop then moves to the box top, not T1.
    # Final contract stops at 500.0, so P&L = 0.5 + 1.0 + 0.0 = 1.5.
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.6, 500.1, 500.55),
        (501.1, 500.6, 501.05),
        (500.4, 499.95, 500.1),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bull", 500.0, 499.0, StrategyParams(), True,
    )
    assert res["targets_hit"] == 2
    assert res["stop_hit"]
    assert res["stop_bar"] == 3
    assert math.isclose(res["pnl_points"], 1.5)


def test_bear_after_t2_stop_moves_to_box_bottom_symmetrically():
    # For a bear break, the break-side edge is the box bottom. After T2, final
    # contract stop should be 500.0, not T1 at 499.5 or box high at 501.0.
    bars, highs, lows, closes, dates = _arrays([
        (500.2, 499.9, 500.0),
        (499.8, 499.4, 499.45),
        (499.4, 498.9, 498.95),
        (500.05, 499.2, 499.9),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bear", 501.0, 500.0, StrategyParams(), True,
    )
    assert res["targets_hit"] == 2
    assert res["stop_hit"]
    assert res["stop_bar"] == 3
    assert math.isclose(res["pnl_points"], 1.5)


def test_bear_three_contract_partials_and_timeout_points_are_directional():
    # Bear entry 500, box 500-501, R=1. T1=499.5 exits one, T2=499 exits one.
    # Final times out at close 498.8 for +1.2. Total = 0.5 + 1.0 + 1.2 = 2.7.
    bars, highs, lows, closes, dates = _arrays([
        (500.2, 499.9, 500.0),
        (499.8, 499.4, 499.45),
        (499.4, 498.9, 498.95),
        (499.2, 498.7, 498.8),
    ])
    params = StrategyParams(max_bars=3)
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bear", 501.0, 500.0, params, True,
    )
    assert res["targets_hit"] == 2
    assert not res["stop_hit"]
    assert res["timeout"]
    assert math.isclose(res["pnl_points"], 2.7)


def test_tight_half_R_stop_bull_stops_all_three_before_t1():
    # Tight stop at entry - 0.5R = 499.5. First bar dips to 499.4 → all three
    # contracts exit at 499.5 → -0.5 each → -1.5 total.
    params = StrategyParams(initial_stop="tight_half_R")
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.2, 499.4, 499.45),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bull", 500.0, 499.0, params, True,
    )
    assert res["targets_hit"] == 0
    assert res["stop_hit"]
    assert res["stop_bar"] == 1
    assert math.isclose(res["pnl_points"], -1.5)


def test_tight_half_R_stop_bull_after_t1_holds_at_tight_stop():
    # T1 at 500.5 hits, stop stays at 499.5 (no_move). Next bar dips to 499.4
    # → remaining two stop at 499.5 for -0.5 each. Total = +0.5 - 1.0 = -0.5.
    params = StrategyParams(initial_stop="tight_half_R")
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.6, 500.1, 500.55),
        (500.4, 499.4, 499.45),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bull", 500.0, 499.0, params, True,
    )
    assert res["targets_hit"] == 1
    assert res["stop_hit"]
    assert res["stop_bar"] == 2
    assert math.isclose(res["pnl_points"], -0.5)


def test_tight_half_R_stop_bull_after_t2_moves_to_box_break_side():
    # T1 + T2 hit. After T2, final stop moves to box_high (500). Final contract
    # times out at close 500.0 with box_high stop never violated → +0.0.
    # Total = +0.5 + 1.0 + 0.0 = 1.5.
    params = StrategyParams(initial_stop="tight_half_R")
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.6, 500.1, 500.55),
        (501.1, 500.6, 501.05),
        (500.4, 499.95, 500.1),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bull", 500.0, 499.0, params, True,
    )
    assert res["targets_hit"] == 2
    assert res["stop_hit"]
    assert math.isclose(res["pnl_points"], 1.5)


def test_tight_half_R_stop_bear_symmetric():
    # Bear entry 500, R=1, tight stop at 500.5. First bar pokes to 500.6 → all
    # three contracts exit at 500.5 → -0.5 each → -1.5 total.
    params = StrategyParams(initial_stop="tight_half_R")
    bars, highs, lows, closes, dates = _arrays([
        (500.2, 499.9, 500.0),
        (500.6, 499.8, 499.9),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bear", 501.0, 500.0, params, True,
    )
    assert res["targets_hit"] == 0
    assert res["stop_hit"]
    assert math.isclose(res["pnl_points"], -1.5)


def test_tight_half_R_close_confirm_with_overshoot_entry_loses_on_final_after_t2():
    # Bull close-confirm: entry above box_high. Box 499-500, R=1, entry=500.2.
    # tight stop = 499.7, T1 = 500.7, T2 = 501.2. After T2, stop = box_high =
    # 500.0 → final contract loses 0.2. Total = +0.5 + 1.0 - 0.2 = 1.3.
    params = StrategyParams(initial_stop="tight_half_R")
    bars, highs, lows, closes, dates = _arrays([
        (500.3, 500.1, 500.2),     # entry bar
        (500.8, 500.15, 500.75),   # T1 hit
        (501.3, 500.7, 501.25),    # T2 hit, stop moves to box_high (500)
        (500.5, 499.95, 500.05),   # box_high touched → final exits at 500.0
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.2, "bull", 500.0, 499.0, params, True,
    )
    assert res["targets_hit"] == 2
    assert res["stop_hit"]
    assert math.isclose(res["pnl_points"], 1.3)


def test_strategy_params_can_change_targets_and_stop_moves():
    params = StrategyParams(
        targets_R=(0.25, 0.75, 1.5),
        stop_after_t1="entry",
        stop_after_t2="T1",
        stop_after_t3="T2",
        max_bars=5,
    )
    bars, highs, lows, closes, dates = _arrays([
        (500.0, 499.8, 500.0),
        (500.3, 500.1, 500.25),
        (500.1, 499.9, 499.95),
    ])
    res = evaluate_event_strategy_pnl(
        bars, highs, lows, closes, dates,
        0, 500.0, "bull", 500.0, 499.0, params, True,
    )
    # First target is +0.25, then remaining two stop at entry, so total +0.25.
    assert res["targets_hit"] == 1
    assert res["stop_hit"]
    assert math.isclose(res["pnl_points"], 0.25)
