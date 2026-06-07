"""
Bilbo Box Breakout × Higher-TF PO — Bracket-Exit Study (revised)
================================================================

WHAT THIS STUDIES
-----------------
Replaces the prior R-mark-to-market view of Bilbo×HTF-PO with a target-
before-stop bracket study. For each immediate-entry break:

  R unit = box HEIGHT (price range) = box_high - box_low
           (NOT "box width" — width is the time/x-axis dimension; the
            existing column `box_width_pts` is a misnomer.)

  Stop   = opposite box side (touch resolves)
  T1     = entry ± 0.5 × R
  T2     = entry ± 1.0 × R
  T3     = entry ± 2.0 × R
  Time   = 15 bars after entry, intraday RTH truncation honored

  Same-bar stop/target conflict: if stop and a target both fall inside the
  same OHLC bar, do NOT auto-count the trade out. Wait for that candle close:
  close beyond a target records the target; close beyond the stop records the
  stop; otherwise keep walking subsequent bars.

GAP-THROUGH NOTE
----------------
Entry can gap beyond the break boundary; in that case the actual entry-to-
stop distance exceeds R (=box height). We keep R = box height as Pedro
specified and report the realized stop loss in R-units (actual_stop_R)
separately. Expectancy uses the actual realized R-loss for stop outcomes.

LOOKAHEAD SAFETY
----------------
HTF PO timestamps shifted forward by one full HTF bar duration before
merge_asof, so only fully-closed HTF bars are visible at break time.

INPUT
-----
analyst/bilbo_box_events.csv (produced by backtest_bilbo_box.py)
spy.db (ind_3m, ind_10m, ind_1h)

OUTPUT
------
- analyst/bilbo_box_htf_po_exits_run.log
- analyst/bilbo_box_htf_po_exits_summary.json
"""

import os
import json
import sqlite3
from contextlib import redirect_stdout
from dataclasses import dataclass
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
ANALYST_DIR = os.path.join(BASE_DIR, "analyst")
EVENTS_CSV = os.path.join(ANALYST_DIR, "bilbo_box_events.csv")
LOG_PATH = os.path.join(ANALYST_DIR, "bilbo_box_htf_po_exits_run.log")
JSON_PATH = os.path.join(ANALYST_DIR, "bilbo_box_htf_po_exits_summary.json")

MAX_BARS = 15
TARGETS = [("T1", 0.5), ("T2", 1.0), ("T3", 2.0)]
MIN_REPORT = 20
FLAG_SAMPLE = 50


@dataclass(frozen=True)
class StrategyParams:
    """Parametrized 3-contract partial-profit Bilbo strategy."""
    targets_R: tuple = (0.5, 1.0, 2.0)
    position_size: int = 3
    max_bars: int = 15
    initial_stop: str = "opposite_box"
    stop_after_t1: str = "no_move"
    stop_after_t2: str = "box_break_side"
    stop_after_t3: str = "box_break_side"


STRATEGY_PARAMS = StrategyParams(
    targets_R=tuple(v for _, v in TARGETS),
    position_size=3,
    max_bars=MAX_BARS,
    initial_stop="opposite_box",
    stop_after_t1="no_move",
    stop_after_t2="box_break_side",
    stop_after_t3="box_break_side",
)


# ───────────────────────── classification ─────────────────────────

def classify(po, po_prev, compression):
    if compression == 1:
        state = "compression"
    elif po >= 0:
        state = "bull_exp"
    else:
        state = "bear_exp"
    sign = "PO>=0" if po >= 0 else "PO<0"
    if po > 61.8:
        zone = "high"
    elif po < -61.8:
        zone = "low"
    else:
        zone = "mid"
    slope = "rising" if (pd.notna(po_prev) and po > po_prev) else "falling"
    return state, sign, zone, slope


# ───────────────────────── data plumbing ─────────────────────────

def load_bars(conn, table, intraday_rth):
    df = pd.read_sql_query(
        f"SELECT timestamp, open, high, low, close FROM {table} ORDER BY timestamp",
        conn, parse_dates=["timestamp"],
    )
    df = df.set_index("timestamp").sort_index()
    if intraday_rth:
        df = df.between_time("09:30", "15:59")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def load_higher_tf_po(conn, table, bar_minutes):
    df = pd.read_sql_query(
        f"SELECT timestamp, phase_oscillator, compression FROM {table} ORDER BY timestamp",
        conn, parse_dates=["timestamp"],
    )
    df = df.dropna(subset=["phase_oscillator"]).copy()
    df["po_prev"] = df["phase_oscillator"].shift(1)
    df["timestamp"] = df["timestamp"] + pd.Timedelta(minutes=bar_minutes)
    return df.sort_values("timestamp").reset_index(drop=True)


def attach_po(events, po_df, suffix):
    ev = events.copy()
    ev["break_bar_ts"] = pd.to_datetime(ev["break_bar_ts"])
    ev = ev.sort_values("break_bar_ts").reset_index(drop=True)
    merged = pd.merge_asof(
        ev[["break_bar_ts"]],
        po_df.rename(columns={"timestamp": "break_bar_ts"}),
        on="break_bar_ts",
        direction="backward",
    )
    ev[f"po_{suffix}"] = merged["phase_oscillator"].values
    ev[f"po_prev_{suffix}"] = merged["po_prev"].values
    ev[f"comp_{suffix}"] = merged["compression"].values

    cls = [classify(p, pp, c) for p, pp, c in zip(
        ev[f"po_{suffix}"], ev[f"po_prev_{suffix}"], ev[f"comp_{suffix}"]
    )]
    ev[f"state_{suffix}"] = [c[0] for c in cls]
    ev[f"sign_{suffix}"] = [c[1] for c in cls]
    ev[f"zone_{suffix}"] = [c[2] for c in cls]
    ev[f"slope_{suffix}"] = [c[3] for c in cls]
    ev[f"state_slope_{suffix}"] = ev[f"state_{suffix}"] + "+" + ev[f"slope_{suffix}"]
    return ev


# ───────────────────────── bracket eval ─────────────────────────

def evaluate_event_bracket(bars_index_array, highs, lows, closes, dates,
                           entry_idx, entry_price, direction, box_high, box_low,
                           intraday_rth):
    """
    Walk bars after the entry bar applying the T1/T2/T3-vs-stop bracket.
    Returns a dict of resolution flags + per-target hit info.
    """
    R = box_high - box_low
    if R <= 0:
        return None
    if direction == "bull":
        t1, t2, t3 = entry_price + 0.5 * R, entry_price + 1.0 * R, entry_price + 2.0 * R
        stop = box_low
        actual_stop_R = (entry_price - stop) / R
    else:
        t1, t2, t3 = entry_price - 0.5 * R, entry_price - 1.0 * R, entry_price - 2.0 * R
        stop = box_high
        actual_stop_R = (stop - entry_price) / R

    entry_date = dates[entry_idx]
    n = len(highs)

    t1_hit = t2_hit = t3_hit = stop_hit = False
    t1_bar = t2_bar = t3_bar = stop_bar = None
    same_bar_conflicts = 0
    last_walked = 0
    last_close_in_R = np.nan  # MTM at end-of-window if timeout

    for step in range(1, MAX_BARS + 1):
        idx = entry_idx + step
        if idx >= n:
            break
        if intraday_rth and dates[idx] != entry_date:
            break
        h = highs[idx]
        l = lows[idx]
        c = closes[idx]
        last_walked = step
        last_close_in_R = (c - entry_price) / R if direction == "bull" \
            else (entry_price - c) / R

        if direction == "bull":
            stop_in_bar = l <= stop
            t1_in_bar = h >= t1
            t2_in_bar = h >= t2
            t3_in_bar = h >= t3
            close_stops = c <= stop
            close_t1 = c >= t1
            close_t2 = c >= t2
            close_t3 = c >= t3
        else:
            stop_in_bar = h >= stop
            t1_in_bar = l <= t1
            t2_in_bar = l <= t2
            t3_in_bar = l <= t3
            close_stops = c >= stop
            close_t1 = c <= t1
            close_t2 = c <= t2
            close_t3 = c <= t3

        target_in_bar = t1_in_bar or t2_in_bar or t3_in_bar

        # If stop and target are both touched in the same OHLC bar, the bar is
        # ambiguous intrabar. Per Pedro: wait for the candle close instead of
        # auto-counting a stop or target from the wick sequence.
        if stop_in_bar and target_in_bar:
            same_bar_conflicts += 1
            if close_stops:
                stop_hit = True
                stop_bar = step
                break
            if close_t1 and not t1_hit:
                t1_hit = True
                t1_bar = step
            if close_t2 and not t2_hit:
                t2_hit = True
                t2_bar = step
            if close_t3 and not t3_hit:
                t3_hit = True
                t3_bar = step
                break
            # Close did not resolve the ambiguous candle: continue walking.
            continue

        if stop_in_bar:
            stop_hit = True
            stop_bar = step
            break

        if t1_in_bar and not t1_hit:
            t1_hit = True
            t1_bar = step
        if t2_in_bar and not t2_hit:
            t2_hit = True
            t2_bar = step
        if t3_in_bar and not t3_hit:
            t3_hit = True
            t3_bar = step
            break  # T3 is final target

    if stop_hit:
        resolution = "stop"
        bars_to_res = stop_bar
    elif t3_hit:
        resolution = "T3"
        bars_to_res = t3_bar
    else:
        resolution = "timeout"
        bars_to_res = last_walked if last_walked > 0 else 0

    return {
        "R_pts": float(R),
        "actual_stop_R": float(actual_stop_R),
        "t1_hit": bool(t1_hit), "t2_hit": bool(t2_hit), "t3_hit": bool(t3_hit),
        "stop_hit": bool(stop_hit),
        "timeout": (resolution == "timeout"),
        "t1_bar": t1_bar, "t2_bar": t2_bar, "t3_bar": t3_bar, "stop_bar": stop_bar,
        "same_bar_conflicts": int(same_bar_conflicts),
        "bars_to_resolution": int(bars_to_res),
        "resolution": resolution,
        "last_close_R": float(last_close_in_R) if last_walked > 0 else np.nan,
    }


def _directional_point(exit_price, entry_price, direction):
    return (exit_price - entry_price) if direction == "bull" else (entry_price - exit_price)


def _level_from_name(name, entry_price, direction, box_high, box_low, targets):
    R = box_high - box_low
    if name == "opposite_box":
        return box_low if direction == "bull" else box_high
    if name == "box_midpoint":
        return (box_high + box_low) / 2.0
    if name == "box_top":
        return box_high
    if name == "box_bottom":
        return box_low
    if name == "box_break_side":
        # Break-side edge: top for bull breaks, bottom for bear breaks.
        return box_high if direction == "bull" else box_low
    if name == "entry":
        return entry_price
    if name == "tight_half_R":
        # Symmetric tight stop: 0.5R against direction from entry.
        return entry_price - 0.5 * R if direction == "bull" else entry_price + 0.5 * R
    if name.startswith("T"):
        idx = int(name[1:]) - 1
        r_mult = targets[idx]
        return entry_price + r_mult * R if direction == "bull" else entry_price - r_mult * R
    raise ValueError(f"Unknown stop level name: {name}")


def evaluate_event_strategy_pnl(bars_index_array, highs, lows, closes, dates,
                                entry_idx, entry_price, direction, box_high, box_low,
                                params=STRATEGY_PARAMS, intraday_rth=True):
    """
    Simulate the partial-profit strategy in SPY points.

    Default: 3 contracts, one contract exits at each of T1/T2/T3. Stop starts
    at the opposite box side, does not move after T1, then moves to the
    break-side edge of the Bilbo box after T2 and stays there. Remaining
    contracts close on stop, full target, or timeout after max_bars.
    Same-bar stop/target ambiguity waits for candle close.
    """
    R = box_high - box_low
    if R <= 0:
        return None
    targets = tuple(float(x) for x in params.targets_R)
    if params.position_size != len(targets):
        raise ValueError("position_size must match number of target levels for one-contract partials")

    target_prices = [entry_price + r * R if direction == "bull" else entry_price - r * R
                     for r in targets]
    stop_names = [params.stop_after_t1, params.stop_after_t2, params.stop_after_t3]
    current_stop = _level_from_name(params.initial_stop, entry_price, direction, box_high, box_low, targets)
    entry_date = dates[entry_idx]
    n = len(highs)

    exits = []
    hit_bars = [None] * len(targets)
    stop_hit = False
    stop_bar = None
    timeout = False
    same_bar_conflicts = 0
    last_walked = 0
    last_close = np.nan
    remaining = params.position_size
    next_target_idx = 0

    def target_touched(i, h, l):
        return h >= target_prices[i] if direction == "bull" else l <= target_prices[i]

    def stop_touched(h, l):
        return l <= current_stop if direction == "bull" else h >= current_stop

    def close_beyond_stop(c):
        return c <= current_stop if direction == "bull" else c >= current_stop

    def close_beyond_target(i, c):
        return c >= target_prices[i] if direction == "bull" else c <= target_prices[i]

    for step in range(1, params.max_bars + 1):
        idx = entry_idx + step
        if idx >= n:
            break
        if intraday_rth and dates[idx] != entry_date:
            break
        h = highs[idx]
        l = lows[idx]
        c = closes[idx]
        last_walked = step
        last_close = c

        pending = list(range(next_target_idx, len(targets)))
        targets_in_bar = [i for i in pending if target_touched(i, h, l)]
        stop_in_bar = remaining > 0 and stop_touched(h, l)

        if stop_in_bar and targets_in_bar:
            same_bar_conflicts += 1
            if close_beyond_stop(c):
                stop_hit = True
                stop_bar = step
                exits.extend([current_stop] * remaining)
                remaining = 0
                break
            close_targets = [i for i in pending if close_beyond_target(i, c)]
            if not close_targets:
                continue
            targets_to_take = list(range(next_target_idx, max(close_targets) + 1))
        else:
            if stop_in_bar:
                stop_hit = True
                stop_bar = step
                exits.extend([current_stop] * remaining)
                remaining = 0
                break
            targets_to_take = targets_in_bar

        for i in targets_to_take:
            if remaining <= 0 or i != next_target_idx:
                continue
            exits.append(target_prices[i])
            hit_bars[i] = step
            remaining -= 1
            next_target_idx += 1
            if remaining > 0:
                stop_name = stop_names[i]
                if stop_name not in ("no_move", "none", "unchanged"):
                    current_stop = _level_from_name(stop_name, entry_price, direction, box_high, box_low, targets)
        if remaining == 0:
            break

    if remaining > 0 and not stop_hit:
        timeout = True
        timeout_price = last_close if last_walked > 0 and pd.notna(last_close) else entry_price
        exits.extend([timeout_price] * remaining)
        remaining = 0

    pnl_points = sum(_directional_point(x, entry_price, direction) for x in exits)
    t_hits = len([b for b in hit_bars if b is not None])
    if stop_hit:
        resolution = "stop"
        bars_to_res = stop_bar
    elif t_hits == len(targets):
        resolution = f"T{len(targets)}"
        bars_to_res = hit_bars[-1]
    else:
        resolution = "timeout"
        bars_to_res = last_walked if last_walked > 0 else 0

    out = {
        "strategy_pnl_points": float(pnl_points),
        "strategy_targets_hit": int(t_hits),
        "strategy_stop_hit": bool(stop_hit),
        "strategy_timeout": bool(timeout),
        "strategy_resolution": resolution,
        "strategy_bars_to_resolution": int(bars_to_res) if bars_to_res is not None else 0,
        "strategy_same_bar_conflicts": int(same_bar_conflicts),
    }
    for i in range(len(targets)):
        out[f"strategy_t{i+1}_hit"] = hit_bars[i] is not None
        out[f"strategy_t{i+1}_bar"] = hit_bars[i]
    # Test-friendly aliases.
    out.update({
        "pnl_points": out["strategy_pnl_points"],
        "targets_hit": out["strategy_targets_hit"],
        "stop_hit": out["strategy_stop_hit"],
        "timeout": out["strategy_timeout"],
        "resolution": out["strategy_resolution"],
        "stop_bar": stop_bar,
        "t1_hit": out.get("strategy_t1_hit", False),
        "t2_hit": out.get("strategy_t2_hit", False),
        "t3_hit": out.get("strategy_t3_hit", False),
    })
    return out


def evaluate_all(events_df, bars_df, intraday_rth):
    """Vectorize bar lookup; loop per event for bracket walk."""
    if len(events_df) == 0:
        return events_df.copy()

    bars = bars_df.reset_index()
    bars_ts = bars["timestamp"].values.astype("datetime64[ns]")
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    # date-of-bar for intraday RTH day-boundary check
    dates = bars["timestamp"].dt.date.values

    # Index events by entry timestamp into bars_ts
    ev = events_df.reset_index(drop=True).copy()
    ev["immediate_entry_ts"] = pd.to_datetime(ev["immediate_entry_ts"])
    entry_ts_arr = ev["immediate_entry_ts"].values.astype("datetime64[ns]")
    entry_idx = np.searchsorted(bars_ts, entry_ts_arr)

    # Confirm exact match for each event; mark missing
    ok = (entry_idx < len(bars_ts)) & (bars_ts[np.minimum(entry_idx, len(bars_ts) - 1)] == entry_ts_arr)
    ev["bar_match"] = ok

    out_rows = []
    strategy_rows = []
    entry_prices = ev["immediate_entry_price"].astype(float).values
    box_highs = ev["box_high"].astype(float).values
    box_lows = ev["box_low"].astype(float).values
    directions = ev["direction"].values

    for i in range(len(ev)):
        if not ok[i]:
            out_rows.append(None)
            strategy_rows.append(None)
            continue
        res = evaluate_event_bracket(
            bars_ts, highs, lows, closes, dates,
            int(entry_idx[i]), entry_prices[i], directions[i],
            box_highs[i], box_lows[i], intraday_rth,
        )
        strategy_res = evaluate_event_strategy_pnl(
            bars_ts, highs, lows, closes, dates,
            int(entry_idx[i]), entry_prices[i], directions[i],
            box_highs[i], box_lows[i], STRATEGY_PARAMS, intraday_rth,
        )
        out_rows.append(res)
        strategy_rows.append(strategy_res)

    # Expand into columns
    keys = ["R_pts", "actual_stop_R", "t1_hit", "t2_hit", "t3_hit",
            "stop_hit", "timeout", "t1_bar", "t2_bar", "t3_bar", "stop_bar",
            "same_bar_conflicts", "bars_to_resolution", "resolution", "last_close_R"]
    for k in keys:
        ev[k] = [r[k] if r is not None else np.nan for r in out_rows]
    strategy_keys = ["strategy_pnl_points", "strategy_targets_hit", "strategy_stop_hit", "strategy_timeout",
                     "strategy_resolution", "strategy_bars_to_resolution", "strategy_same_bar_conflicts",
                     "strategy_t1_hit", "strategy_t2_hit", "strategy_t3_hit",
                     "strategy_t1_bar", "strategy_t2_bar", "strategy_t3_bar"]
    for k in strategy_keys:
        ev[k] = [r[k] if r is not None else np.nan for r in strategy_rows]
    ev = ev[ev["resolution"].notna()].copy()
    return ev


# ───────────────────────── stats ─────────────────────────

def stats_for(ev):
    n = len(ev)
    if n == 0:
        return {"n": 0}
    t1 = ev["t1_hit"].astype(bool)
    t2 = ev["t2_hit"].astype(bool)
    t3 = ev["t3_hit"].astype(bool)
    stop = ev["stop_hit"].astype(bool)
    timeout = ev["timeout"].astype(bool)
    actual_stop_R = ev["actual_stop_R"].astype(float)
    last_close_R = ev["last_close_R"].astype(float)
    bars_to_res = ev["bars_to_resolution"].astype(float)
    same_bar_conflicts = ev["same_bar_conflicts"].astype(float) if "same_bar_conflicts" in ev else pd.Series(0, index=ev.index, dtype=float)

    # Single-target expectancy models (in R units)
    # T_k model: exit at +k*R if Tk_hit, else exit at -actual_stop_R if stop_hit,
    #            else mark to last close (in R) at timeout.
    def exp_for(target_R, tk_hit):
        outcome = np.where(tk_hit, target_R,
                  np.where(stop, -actual_stop_R, last_close_R.fillna(0.0)))
        return float(np.nanmean(outcome))

    return {
        "n": int(n),
        "t1_pct": float(t1.mean()),
        "t2_pct": float(t2.mean()),
        "t3_pct": float(t3.mean()),
        "stop_only_pct": float((stop & ~t1).mean()),     # stopped before any target
        "stop_after_partial_pct": float((stop & t1 & ~t3).mean()),
        "stop_pct": float(stop.mean()),                   # any stop (incl after partial)
        "timeout_pct": float(timeout.mean()),
        "median_bars_to_resolution": float(bars_to_res.median()),
        "same_bar_conflict_pct": float((same_bar_conflicts > 0).mean()),
        "same_bar_conflict_count": int((same_bar_conflicts > 0).sum()),
        "actual_stop_R_median": float(actual_stop_R.median()),
        "expectancy_T1_R": exp_for(0.5, t1),
        "expectancy_T2_R": exp_for(1.0, t2),
        "expectancy_T3_R": exp_for(2.0, t3),
    }


def strategy_stats_for(ev):
    n = len(ev)
    if n == 0:
        return {"n": 0}
    pnl = ev["strategy_pnl_points"].astype(float)
    stop = ev["strategy_stop_hit"].astype(bool)
    timeout = ev["strategy_timeout"].astype(bool)
    targets_hit = ev["strategy_targets_hit"].astype(int)
    bars_to_res = ev["strategy_bars_to_resolution"].astype(float)
    return {
        "n": int(n),
        "t1_count": int((targets_hit >= 1).sum()),
        "t2_count": int((targets_hit >= 2).sum()),
        "t3_count": int((targets_hit >= 3).sum()),
        "stop_count": int(stop.sum()),
        "timeout_count": int(timeout.sum()),
        "t1_pct": float((targets_hit >= 1).mean()),
        "t2_pct": float((targets_hit >= 2).mean()),
        "t3_pct": float((targets_hit >= 3).mean()),
        "stop_pct": float(stop.mean()),
        "timeout_pct": float(timeout.mean()),
        "median_bars_to_resolution": float(bars_to_res.median()),
        "pnl_points_total": float(pnl.sum()),
        "pnl_points_avg_per_trade": float(pnl.mean()),
        "pnl_points_median_per_trade": float(pnl.median()),
        "win_pct": float((pnl > 0).mean()),
        "loss_pct": float((pnl < 0).mean()),
        "flat_pct": float((pnl == 0).mean()),
        "best_trade_points": float(pnl.max()),
        "worst_trade_points": float(pnl.min()),
    }


def fmt_strategy_row(label, s, indent="  "):
    if s["n"] < MIN_REPORT:
        print(f"{indent}{label:28s} n={s['n']:>5d}   — insufficient sample —")
        return
    flag = " *" if s["n"] < FLAG_SAMPLE else ""
    print(f"{indent}{label:28s} n={s['n']:>5d}  "
          f"T1={s['t1_pct']*100:5.1f}%  T2={s['t2_pct']*100:5.1f}%  "
          f"T3={s['t3_pct']*100:5.1f}%  Stop={s['stop_pct']*100:5.1f}%  "
          f"Tout={s['timeout_pct']*100:5.1f}%  Win={s['win_pct']*100:5.1f}%  "
          f"PnL={s['pnl_points_total']:+.1f} pts  Avg={s['pnl_points_avg_per_trade']:+.3f}{flag}")


def same_direction_confirmation(ev, suffix, direction):
    if direction == "bull":
        return ev[f"state_slope_{suffix}"] == "bull_exp+rising"
    if direction == "bear":
        return ev[f"state_slope_{suffix}"] == "bear_exp+falling"
    raise ValueError(f"unknown direction: {direction}")


def run_same_direction_strategy(ev, suffix, htf_label, direction, label):
    print_header(f"3-CONTRACT SAME-DIRECTION PO-CONFIRMED STRATEGY — {label}")
    have_po = ev[f"po_{suffix}"].notna()
    ev = ev[have_po].copy()
    confirmed = ev[same_direction_confirmation(ev, suffix, direction)]
    bucket = f"{direction}_exp+{'rising' if direction == 'bull' else 'falling'}"
    overall = strategy_stats_for(confirmed)
    fmt_strategy_row(f"{bucket}", overall)

    by_state_slope = {}
    for st in ["bull_exp", "bear_exp", "compression"]:
        for sl in ["rising", "falling"]:
            key = f"{st}+{sl}"
            s = strategy_stats_for(ev[ev[f"state_slope_{suffix}"] == key])
            by_state_slope[key] = s
    by_state = {st: strategy_stats_for(ev[ev[f"state_{suffix}"] == st])
                for st in ["bull_exp", "bear_exp", "compression"]}
    by_slope = {sl: strategy_stats_for(ev[ev[f"slope_{suffix}"] == sl])
                for sl in ["rising", "falling"]}
    return {
        "strategy": "same_direction_po_confirmation",
        "direction": direction,
        "htf": htf_label,
        "confirmation_bucket": bucket,
        "confirmed": overall,
        "by_state": by_state,
        "by_slope": by_slope,
        "by_state_slope": by_state_slope,
    }


def fmt_row(label, s, indent="  "):
    if s["n"] < MIN_REPORT:
        print(f"{indent}{label:28s} n={s['n']:>5d}   — insufficient sample —")
        return
    flag = " *" if s["n"] < FLAG_SAMPLE else ""
    print(f"{indent}{label:28s} n={s['n']:>5d}  "
          f"T1={s['t1_pct']*100:5.1f}%  T2={s['t2_pct']*100:5.1f}%  "
          f"T3={s['t3_pct']*100:5.1f}%  Stop={s['stop_pct']*100:5.1f}%  "
          f"Tout={s['timeout_pct']*100:5.1f}%  "
          f"medBars={s['median_bars_to_resolution']:>4.1f}  "
          f"E[T2]={s['expectancy_T2_R']:+.3f}R{flag}")


def print_header(title):
    print(f"\n  {title}")
    print(f"  {'-' * 110}")


# ───────────────────────── per-cut report ─────────────────────────

def run_cut(ev, suffix, htf_label, direction_label):
    print("\n" + "=" * 110)
    print(f"  {direction_label}  ×  {htf_label} Phase Oscillator  (T1=0.5R, T2=1R, T3=2R, time 15 bars)")
    print("=" * 110)

    have_po = ev[f"po_{suffix}"].notna()
    n_drop = int((~have_po).sum())
    if n_drop:
        print(f"  Dropped {n_drop} events with no fully-closed {htf_label} PO at break time")
    ev = ev[have_po].copy()

    summary = {"htf": htf_label, "direction": direction_label,
               "n_total": int(len(ev))}

    # Baseline
    print_header(f"BASELINE — all {direction_label}")
    base = stats_for(ev)
    fmt_row("baseline", base)
    summary["baseline"] = base

    # By state
    print_header(f"BY STATE ({htf_label} PO)")
    state_summary = {}
    for st in ["bull_exp", "bear_exp", "compression"]:
        sub = ev[ev[f"state_{suffix}"] == st]
        s = stats_for(sub)
        fmt_row(st, s)
        state_summary[st] = s
    summary["by_state"] = state_summary

    # By zone
    print_header(f"BY ZONE ({htf_label} PO)")
    zone_summary = {}
    for z in ["high", "mid", "low"]:
        sub = ev[ev[f"zone_{suffix}"] == z]
        s = stats_for(sub)
        fmt_row(z, s)
        zone_summary[z] = s
    summary["by_zone"] = zone_summary

    # By slope
    print_header(f"BY SLOPE ({htf_label} PO)")
    slope_summary = {}
    for sl in ["rising", "falling"]:
        sub = ev[ev[f"slope_{suffix}"] == sl]
        s = stats_for(sub)
        fmt_row(sl, s)
        slope_summary[sl] = s
    summary["by_slope"] = slope_summary

    # State × slope
    print_header(f"BY STATE × SLOPE ({htf_label} PO)")
    combo_summary = {}
    for st in ["bull_exp", "bear_exp", "compression"]:
        for sl in ["rising", "falling"]:
            key = f"{st}+{sl}"
            sub = ev[ev[f"state_slope_{suffix}"] == key]
            s = stats_for(sub)
            fmt_row(key, s)
            combo_summary[key] = s
    summary["by_state_slope"] = combo_summary

    # Compression highlight (most impactful bucket from prior study)
    print_header(f"COMPRESSION HIGHLIGHT ({htf_label} PO)")
    sub_comp = ev[ev[f"state_{suffix}"] == "compression"]
    comp_overall = stats_for(sub_comp)
    fmt_row("compression (any slope)", comp_overall)
    comp_rising = ev[(ev[f"state_{suffix}"] == "compression") & (ev[f"slope_{suffix}"] == "rising")]
    fmt_row("compression+rising", stats_for(comp_rising))
    comp_falling = ev[(ev[f"state_{suffix}"] == "compression") & (ev[f"slope_{suffix}"] == "falling")]
    fmt_row("compression+falling", stats_for(comp_falling))
    summary["compression_highlight"] = {
        "overall": comp_overall,
        "rising": stats_for(comp_rising),
        "falling": stats_for(comp_falling),
    }

    # Direction-aware anti-filter cells from prior study
    if "bull" in direction_label.lower():
        print_header(f"ANTI-FILTER CHECK — 10m PO low zone (skip suspect)")
        anti = ev[ev[f"zone_{suffix}"] == "low"]
        fmt_row("low zone (avoid)", stats_for(anti))
    else:
        print_header(f"ANTI-FILTER CHECK — 1h PO bull_exp+rising (skip suspect)")
        anti = ev[ev[f"state_slope_{suffix}"] == "bull_exp+rising"]
        fmt_row("bull_exp+rising (avoid)", stats_for(anti))

    return summary


# ───────────────────────── driver ─────────────────────────

def main():
    if not os.path.exists(EVENTS_CSV):
        raise SystemExit(f"Missing events CSV: {EVENTS_CSV}.")
    print(f"Loading events from {EVENTS_CSV}...")
    ev_all = pd.read_csv(EVENTS_CSV, parse_dates=["break_bar_ts", "immediate_entry_ts"],
                        low_memory=False)
    print(f"  {len(ev_all):,} total events across all timeframes")

    conn = sqlite3.connect(DB_PATH)

    # Cut 1 universe
    ev_3m_bull = ev_all[(ev_all["timeframe"] == "3m")
                        & (ev_all["direction"] == "bull")
                        & (~ev_all["ambiguous_outside"].astype(bool))
                        & (ev_all["immediate_fired"].astype(bool))].copy()
    print(f"\nCut 1 universe: {len(ev_3m_bull):,} clean 3m bull immediate-entry breaks")

    # Cut 2 universe
    ev_10m_bear = ev_all[(ev_all["timeframe"] == "10m")
                         & (ev_all["direction"] == "bear")
                         & (~ev_all["ambiguous_outside"].astype(bool))
                         & (ev_all["immediate_fired"].astype(bool))].copy()
    print(f"Cut 2 universe: {len(ev_10m_bear):,} clean 10m bear immediate-entry breaks")

    # Load 3m bars and 10m bars (intraday RTH)
    print("\nLoading 3m bars...", flush=True)
    bars_3m = load_bars(conn, "ind_3m", intraday_rth=True)
    print(f"  {len(bars_3m):,} bars (RTH)")
    print("Loading 10m bars...", flush=True)
    bars_10m = load_bars(conn, "ind_10m", intraday_rth=True)
    print(f"  {len(bars_10m):,} bars (RTH)")

    # Evaluate brackets per event
    print("\nEvaluating Cut 1 brackets (3m bull)...", flush=True)
    ev_3m_bull = evaluate_all(ev_3m_bull, bars_3m, intraday_rth=True)
    print(f"  {len(ev_3m_bull):,} resolved")
    print("Evaluating Cut 2 brackets (10m bear)...", flush=True)
    ev_10m_bear = evaluate_all(ev_10m_bear, bars_10m, intraday_rth=True)
    print(f"  {len(ev_10m_bear):,} resolved")

    # HTF PO joins
    print("\nLoading 10m PO (shifted +10m for lookahead safety)...", flush=True)
    po_10m = load_higher_tf_po(conn, "ind_10m", bar_minutes=10)
    print("Loading 1h PO (shifted +60m for lookahead safety)...", flush=True)
    po_1h = load_higher_tf_po(conn, "ind_1h", bar_minutes=60)

    ev_3m_bull = attach_po(ev_3m_bull, po_10m, suffix="10m")
    ev_10m_bear = attach_po(ev_10m_bear, po_1h, suffix="1h")

    conn.close()

    summary_1 = run_cut(ev_3m_bull, "10m", "10m", "3m BULL Bilbo breaks")
    summary_2 = run_cut(ev_10m_bear, "1h", "1h", "10m BEAR Bilbo breaks")
    strategy_1 = run_same_direction_strategy(ev_3m_bull, "10m", "10m", "bull", "3m BULL × 10m PO bull_exp+rising")
    strategy_2 = run_same_direction_strategy(ev_10m_bear, "1h", "1h", "bear", "10m BEAR × 1h PO bear_exp+falling")

    # Compact takeaway
    print("\n" + "=" * 110)
    print("  COMPACT TAKEAWAY (target-before-stop %, T1=0.5R, T2=1R, T3=2R, 15-bar timeout)")
    print("=" * 110)
    for name, strat in [("3m bull × 10m PO bull_exp+rising", strategy_1),
                        ("10m bear × 1h PO bear_exp+falling", strategy_2)]:
        s = strat["confirmed"]
        if s["n"] >= MIN_REPORT:
            print(f"  {name:36s} n={s['n']:>5d}  "
                  f"T1={s['t1_pct']*100:5.1f}%  T2={s['t2_pct']*100:5.1f}%  "
                  f"T3={s['t3_pct']*100:5.1f}%  Stop={s['stop_pct']*100:5.1f}%  "
                  f"Tout={s['timeout_pct']*100:5.1f}%  "
                  f"PnL={s['pnl_points_total']:+.1f} pts  Avg={s['pnl_points_avg_per_trade']:+.3f}")

    out = {
        "study": "bilbo_box_htf_po_exits",
        "params": {
            "max_bars": MAX_BARS,
            "targets_R": {"T1": 0.5, "T2": 1.0, "T3": 2.0},
            "strategy": {
                "position_size_contracts": STRATEGY_PARAMS.position_size,
                "targets_R": list(STRATEGY_PARAMS.targets_R),
                "initial_stop": STRATEGY_PARAMS.initial_stop,
                "stop_after_t1": STRATEGY_PARAMS.stop_after_t1,
                "stop_after_t2": STRATEGY_PARAMS.stop_after_t2,
                "stop_after_t3": STRATEGY_PARAMS.stop_after_t3,
                "pnl_unit": "SPY points summed across contracts; multiply by contract multiplier separately if needed",
                "confirmation": "same-direction PO expansion with matching slope: bull_exp+rising for bull breaks, bear_exp+falling for bear breaks",
            },
            "stop": "opposite box side (touch)",
            "R_definition": "box_height = box_high - box_low",
            "same_bar_resolution": "if stop and target touch same OHLC bar, wait for candle close: close beyond target counts target, close beyond stop counts stop, otherwise continue",
            "min_report": MIN_REPORT,
            "flag_sample": FLAG_SAMPLE,
        },
        "strategy_pnl": {
            "3m_bull_x_10m_po_bull_exp_rising": strategy_1,
            "10m_bear_x_1h_po_bear_exp_falling": strategy_2,
        },
        "cuts": {
            "3m_bull_x_10m_po": summary_1,
            "10m_bear_x_1h_po": summary_2,
        },
    }
    with open(JSON_PATH, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved summary → {JSON_PATH}")
    print("\nDone.")


if __name__ == "__main__":
    import sys
    logf = open(LOG_PATH, "w")
    class Tee:
        def __init__(self, *streams): self.streams = streams
        def write(self, s):
            for st in self.streams:
                try: st.write(s)
                except ValueError: pass
        def flush(self):
            for st in self.streams:
                try: st.flush()
                except ValueError: pass
    sys.stdout = Tee(sys.__stdout__, logf)
    try:
        main()
    finally:
        sys.stdout = sys.__stdout__
        logf.close()
