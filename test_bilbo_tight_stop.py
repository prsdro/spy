"""
Tests for the tight-stop study helpers.

Pytest may not be installed in this environment, so each test function is
also runnable through the manual harness at the bottom (python3 test_bilbo_tight_stop.py).
"""

import math
from datetime import date

import numpy as np
import pandas as pd

from backtest_bilbo_box_tight_stop import (
    apply_variant_filter,
    evaluate_universe,
    filter_entry_mode,
    is_publishable,
    is_strong,
    split_metrics,
    stats_for,
    TIGHT_STRATEGY,
    TIGHT_ATR_QUANTILE,
    GAP_FILTER_MAX,
)


# ───────────────────────── helpers ─────────────────────────

def _make_bars():
    """Build a tiny 3m bar frame that contains the entry timestamps used in tests."""
    idx = pd.date_range("2024-01-02 09:30", periods=20, freq="3min")
    df = pd.DataFrame({
        "open":   np.full(20, 500.0),
        "high":   np.full(20, 500.2),
        "low":    np.full(20, 499.8),
        "close":  np.full(20, 500.0),
    }, index=idx)
    df.index.name = "timestamp"
    return df


def _evaluated_event(strategy_pnl=1.5, t2_hit=True, stop_hit=False, ts=None,
                     box_high=500.0, box_low=499.0, direction="bull",
                     entry_price=500.0, box_bars=3, box_width_atr=0.10):
    """Return a dict shaped like a row of the evaluated dataframe."""
    return {
        "break_bar_ts": ts if ts is not None else pd.Timestamp("2024-01-02 09:30"),
        "box_high": box_high,
        "box_low": box_low,
        "direction": direction,
        "box_bars": box_bars,
        "box_width_atr": box_width_atr,
        "__entry_price": entry_price,
        "strategy_pnl_points": strategy_pnl,
        "strategy_targets_hit": 2 if t2_hit else 0,
        "strategy_stop_hit": stop_hit,
        "strategy_timeout": (not t2_hit and not stop_hit),
        "strategy_resolution": "T3" if t2_hit else ("stop" if stop_hit else "timeout"),
        "strategy_bars_to_resolution": 5,
        "strategy_same_bar_conflicts": 0,
        "strategy_t1_hit": t2_hit,
        "strategy_t2_hit": t2_hit,
        "strategy_t3_hit": False,
        "strategy_t1_bar": 1 if t2_hit else None,
        "strategy_t2_bar": 2 if t2_hit else None,
        "strategy_t3_bar": None,
    }


# ───────────────────────── filter_entry_mode ─────────────────────────

def test_filter_entry_mode_close_confirm_requires_break_bar_match():
    # Two events: one whose close confirmed on the break bar, one whose close
    # confirmed only on a later bar. close_confirm should keep only the first.
    ev = pd.DataFrame([
        # break-bar close confirmed: close_outside_entry_ts == break_bar_ts
        {"break_bar_ts": pd.Timestamp("2024-01-02 09:30"),
         "immediate_fired": True,
         "immediate_entry_ts": pd.Timestamp("2024-01-02 09:30"),
         "immediate_entry_price": 500.0,
         "close_outside_fired": True,
         "close_outside_entry_ts": pd.Timestamp("2024-01-02 09:30"),
         "close_outside_entry_price": 500.2,
         "retest_fired": False,
         "retest_entry_ts": pd.NaT, "retest_entry_price": np.nan,
         "direction": "bull"},
        # confirmed only later → close_confirm must drop this
        {"break_bar_ts": pd.Timestamp("2024-01-02 10:00"),
         "immediate_fired": True,
         "immediate_entry_ts": pd.Timestamp("2024-01-02 10:00"),
         "immediate_entry_price": 500.0,
         "close_outside_fired": True,
         "close_outside_entry_ts": pd.Timestamp("2024-01-02 10:03"),
         "close_outside_entry_price": 500.4,
         "retest_fired": False,
         "retest_entry_ts": pd.NaT, "retest_entry_price": np.nan,
         "direction": "bull"},
    ])
    sub, ts_col, price_col = filter_entry_mode(ev, "close_confirm")
    assert len(sub) == 1
    assert sub.iloc[0]["break_bar_ts"] == pd.Timestamp("2024-01-02 09:30")
    assert ts_col == "close_outside_entry_ts"
    assert price_col == "close_outside_entry_price"


def test_filter_entry_mode_immediate_keeps_only_immediate_fired():
    ev = pd.DataFrame([
        {"immediate_fired": True,
         "immediate_entry_ts": pd.Timestamp("2024-01-02 09:30"),
         "immediate_entry_price": 500.0},
        {"immediate_fired": False,
         "immediate_entry_ts": pd.NaT, "immediate_entry_price": np.nan},
    ])
    sub, ts_col, price_col = filter_entry_mode(ev, "immediate_touch")
    assert len(sub) == 1
    assert ts_col == "immediate_entry_ts"
    assert price_col == "immediate_entry_price"


def test_filter_entry_mode_retest_keeps_only_retest_fired():
    ev = pd.DataFrame([
        {"retest_fired": True,
         "retest_entry_ts": pd.Timestamp("2024-01-02 09:33"),
         "retest_entry_price": 500.0},
        {"retest_fired": False,
         "retest_entry_ts": pd.NaT, "retest_entry_price": np.nan},
    ])
    sub, ts_col, price_col = filter_entry_mode(ev, "retest")
    assert len(sub) == 1
    assert ts_col == "retest_entry_ts"
    assert price_col == "retest_entry_price"


# ───────────────────────── apply_variant_filter ─────────────────────────

def test_variant_filters_basic_inclusion_exclusion():
    rows = [
        # short box, low atr, on-edge entry
        _evaluated_event(box_bars=2, box_width_atr=0.05, entry_price=500.0),
        # long box, low atr, on-edge entry
        _evaluated_event(box_bars=5, box_width_atr=0.05, entry_price=500.0),
        # short box, high atr, on-edge entry
        _evaluated_event(box_bars=2, box_width_atr=0.50, entry_price=500.0),
        # short box, low atr, gapped entry (overshoot 0.5R) → fails gap filter
        _evaluated_event(box_bars=2, box_width_atr=0.05, entry_price=500.5),
    ]
    df = pd.DataFrame(rows)
    atr_threshold = 0.10  # quartile-style threshold

    base, _ = apply_variant_filter(df, "base", atr_threshold)
    assert len(base) == 4

    short, _ = apply_variant_filter(df, "short_box", atr_threshold)
    assert len(short) == 3

    tight, _ = apply_variant_filter(df, "tight_atr", atr_threshold)
    assert len(tight) == 3  # everyone with atr <= 0.10

    short_tight, _ = apply_variant_filter(df, "short_box_tight_atr", atr_threshold)
    assert len(short_tight) == 2

    gap, _ = apply_variant_filter(df, "gap_filter", atr_threshold)
    # overshoot 0.5R > 0.25 only for the gapped row; rest pass.
    assert len(gap) == 3

    triple, _ = apply_variant_filter(df, "short_box_tight_atr_gap", atr_threshold)
    assert len(triple) == 1


def test_variant_filter_tight_atr_returns_empty_when_threshold_missing():
    rows = [_evaluated_event()]
    df = pd.DataFrame(rows)
    sub, status = apply_variant_filter(df, "tight_atr", None)
    assert len(sub) == 0
    assert status == "no_atr_threshold"


# ───────────────────────── stats_for / split_metrics ─────────────────────────

def test_stats_reports_constant_initial_risk_and_rr_for_tight_stop():
    ev = pd.DataFrame([
        _evaluated_event(strategy_pnl=1.5, t2_hit=True),
        _evaluated_event(strategy_pnl=-1.5, t2_hit=False, stop_hit=True),
    ])
    s = stats_for(ev)
    assert s["n"] == 2
    assert math.isclose(s["t2_pct"], 0.5)
    assert math.isclose(s["stop_pct"], 0.5)
    # By construction with tight_half_R: every row's stop is 0.5R against
    # direction, so realized risk and R:R are constants.
    assert math.isclose(s["median_initial_risk_box_R"], 0.5)
    assert math.isclose(s["median_rr_to_t2"], 2.0)


def test_split_metrics_partitions_train_holdout_correctly():
    ev = pd.DataFrame([
        _evaluated_event(strategy_pnl=1.5, t2_hit=True,
                         ts=pd.Timestamp("2024-06-01 10:00")),  # train
        _evaluated_event(strategy_pnl=-1.5, t2_hit=False, stop_hit=True,
                         ts=pd.Timestamp("2025-09-29 10:00")),  # train (boundary)
        _evaluated_event(strategy_pnl=1.5, t2_hit=True,
                         ts=pd.Timestamp("2025-10-15 10:00")),  # holdout
    ])
    splits = split_metrics(ev)
    assert splits["train_n"] == 2
    assert splits["holdout_n"] == 1
    assert math.isclose(splits["train_t2_pct"], 0.5)
    assert math.isclose(splits["holdout_t2_pct"], 1.0)


# ───────────────────────── publishable / strong flags ─────────────────────────

def test_publishable_requires_n_and_rr():
    base = stats_for(pd.DataFrame([_evaluated_event() for _ in range(250)]))
    assert is_publishable(base)
    small = stats_for(pd.DataFrame([_evaluated_event() for _ in range(50)]))
    assert not is_publishable(small)


def test_strong_candidate_needs_holdout_durability():
    rows_train = [_evaluated_event(strategy_pnl=1.5, t2_hit=True,
                                   ts=pd.Timestamp("2024-06-01 10:00")) for _ in range(150)]
    rows_train += [_evaluated_event(strategy_pnl=-1.5, stop_hit=True, t2_hit=False,
                                    ts=pd.Timestamp("2024-06-02 10:00")) for _ in range(50)]
    # Holdout 60% T2 (above 0.7 × 0.75 = 0.525 → strong)
    rows_hold = [_evaluated_event(strategy_pnl=1.5, t2_hit=True,
                                  ts=pd.Timestamp("2025-11-01 10:00")) for _ in range(30)]
    rows_hold += [_evaluated_event(strategy_pnl=-1.5, stop_hit=True, t2_hit=False,
                                   ts=pd.Timestamp("2025-11-02 10:00")) for _ in range(20)]
    df = pd.DataFrame(rows_train + rows_hold)
    stats = stats_for(df)
    splits = split_metrics(df)
    assert stats["t2_pct"] > 0.5
    assert is_strong(stats, splits)

    # If holdout collapses to 20%, strong should fail.
    rows_hold_bad = [_evaluated_event(strategy_pnl=1.5, t2_hit=True,
                                      ts=pd.Timestamp("2025-11-01 10:00")) for _ in range(10)]
    rows_hold_bad += [_evaluated_event(strategy_pnl=-1.5, stop_hit=True, t2_hit=False,
                                       ts=pd.Timestamp("2025-11-02 10:00")) for _ in range(40)]
    df_bad = pd.DataFrame(rows_train + rows_hold_bad)
    stats_bad = stats_for(df_bad)
    splits_bad = split_metrics(df_bad)
    assert is_publishable(stats_bad)
    assert not is_strong(stats_bad, splits_bad)


# ───────────────────────── evaluate_universe (integration with shared evaluator) ─────────────────────────

def test_evaluate_universe_uses_chosen_entry_columns_and_records_strategy_outcome():
    bars = _make_bars()
    # Place a winning T1+T2 trajectory after the entry timestamp.
    bars.loc[pd.Timestamp("2024-01-02 09:33"), ["open", "high", "low", "close"]] = [500.1, 500.6, 500.05, 500.55]
    bars.loc[pd.Timestamp("2024-01-02 09:36"), ["open", "high", "low", "close"]] = [500.55, 501.1, 500.5, 501.05]
    bars.loc[pd.Timestamp("2024-01-02 09:39"), ["open", "high", "low", "close"]] = [501.0, 501.5, 500.95, 501.2]
    ev_in = pd.DataFrame([{
        "break_bar_ts": pd.Timestamp("2024-01-02 09:30"),
        "direction": "bull",
        "box_high": 500.0,
        "box_low": 499.0,
        "box_bars": 3,
        "box_width_atr": 0.1,
        "immediate_fired": True,
        "immediate_entry_ts": pd.Timestamp("2024-01-02 09:30"),
        "immediate_entry_price": 500.0,
    }])
    ev_eval = evaluate_universe(
        ev_in, bars,
        entry_ts_col="immediate_entry_ts",
        entry_price_col="immediate_entry_price",
        intraday_rth=True,
    )
    assert len(ev_eval) == 1
    assert ev_eval.iloc[0]["strategy_targets_hit"] >= 2
    assert math.isclose(ev_eval.iloc[0]["__entry_price"], 500.0)


# ───────────────────────── manual harness ─────────────────────────

def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
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
