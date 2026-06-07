"""
Bilbo Box Edge Validation Study
===============================

Validates ONE locked Bilbo Box setup over the full SPY history.

LOCKED SETUP
------------
Cut             : 3-minute bull Bilbo Box × 10-minute bullish PO (bull_exp+rising)
Entry           : immediate_touch
Filter          : short_box_tight_atr_gap   (box_bars <= 4 AND box_width_atr in
                  lowest within-cut quartile AND |entry - break_side_edge|/R <= 0.25)
Initial stop    : tight_half_R              (entry - 0.5R for bulls)
Target          : T2 = 1.0R                 (single-contract, single-target bracket)
Same-bar rule  : existing close-arbitration

R UNIT
------
R = box_high - box_low (box HEIGHT in price points). Per-trade R outcome =
strategy_pnl_points / R_pts. Stop loss rounds to -0.5R, win to +1.0R, timeout
marks-to-close at last bar in R.

WHAT THIS PRODUCES
------------------
- Headline block on the full sample (n, hit rate, profit factor, etc.)
- Walk-forward by calendar year (years with n >= 50)
- Bootstrap Monte Carlo: 5,000 paths × 1,000 trades drawn with replacement
- Sensitivity 3×3 grid: stop ∈ {0.45,0.50,0.55}, target ∈ {0.95,1.00,1.05}
- Friction test: 0.02pt slippage + 0.01pt commission per side
- Verdict: publishable / borderline / not_publishable

OUTPUTS
-------
- analyst/bilbo_box_edge_validation_run.log
- analyst/bilbo_box_edge_validation_summary.json
- analyst/bilbo_box_edge_validation_table.csv

REUSED HELPERS
--------------
load_bars, load_higher_tf_po, attach_po, evaluate_event_strategy_pnl,
StrategyParams from backtest_bilbo_box_htf_po_exits.
filter_cut_universe, filter_po_confirmed, filter_entry_mode,
evaluate_universe, apply_variant_filter, TIGHT_ATR_QUANTILE
from backtest_bilbo_box_tight_stop.
"""

import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd

from backtest_bilbo_box_htf_po_exits import (
    StrategyParams,
    load_bars,
    load_higher_tf_po,
    attach_po,
    evaluate_event_strategy_pnl,
)
from backtest_bilbo_box_tight_stop import (
    filter_cut_universe,
    filter_po_confirmed,
    filter_entry_mode,
    apply_variant_filter,
    TIGHT_ATR_QUANTILE,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
ANALYST_DIR = os.path.join(BASE_DIR, "analyst")
EVENTS_CSV = os.path.join(ANALYST_DIR, "bilbo_box_events.csv")
LOG_PATH = os.path.join(ANALYST_DIR, "bilbo_box_edge_validation_run.log")
JSON_PATH = os.path.join(ANALYST_DIR, "bilbo_box_edge_validation_summary.json")
TABLE_CSV_PATH = os.path.join(ANALYST_DIR, "bilbo_box_edge_validation_table.csv")

LOCKED_CUT = {
    "key": "3m_bull_x_10m_po",
    "label": "3m BULL × 10m PO bull_exp+rising",
    "bars_table": "ind_3m",
    "timeframe": "3m",
    "direction": "bull",
    "po_table": "ind_10m",
    "po_suffix": "10m",
    "po_minutes": 10,
    "expected_state_slope": "bull_exp+rising",
    "intraday_rth": True,
}
LOCKED_ENTRY_MODE = "immediate_touch"
LOCKED_VARIANT = "short_box_tight_atr_gap"

MAX_BARS = 15
TARGET_R_LOCKED = 1.0
STOP_R_LOCKED = 0.5
RR_LOCKED = TARGET_R_LOCKED / STOP_R_LOCKED          # 2.0
BREAKEVEN_HIT_RATE = 1.0 / (1.0 + RR_LOCKED)         # 33.33% for 2:1 R:R

N_BOOTSTRAP = 5_000
BOOTSTRAP_PATH_LEN = 1_000
BOOTSTRAP_SEED = 42

SLIPPAGE_PER_SIDE_PTS = 0.02
COMMISSION_PER_SIDE_PTS = 0.01
FRICTION_PER_TRADE_PTS = 2 * (SLIPPAGE_PER_SIDE_PTS + COMMISSION_PER_SIDE_PTS)

WALKFWD_MIN_TRADES = 50

SENSITIVITY_STOPS = (0.45, 0.50, 0.55)
SENSITIVITY_TARGETS = (0.95, 1.00, 1.05)

VERDICT_FULL_WIN_THRESH = 0.36
VERDICT_YR_PASS_RATIO = 0.60

# Single-bracket strategy: 1 contract, target=1R, stop=0.5R against entry.
SINGLE_BRACKET = StrategyParams(
    targets_R=(TARGET_R_LOCKED,),
    position_size=1,
    max_bars=MAX_BARS,
    initial_stop="tight_half_R",
    stop_after_t1="no_move",
    stop_after_t2="no_move",
    stop_after_t3="no_move",
)


# ───────────────────────── universe builder ─────────────────────────

# Compact column set produced by the single-target bracket. evaluate_universe in
# the tight-stop module assumes a 3-target shape (strategy_t1/t2/t3_*), so we
# call evaluate_event_strategy_pnl directly and copy across only what exists.
_SINGLE_BRACKET_COLS = (
    "strategy_pnl_points",
    "strategy_targets_hit",
    "strategy_stop_hit",
    "strategy_timeout",
    "strategy_resolution",
    "strategy_bars_to_resolution",
    "strategy_same_bar_conflicts",
    "strategy_t1_hit",
    "strategy_t1_bar",
)


def evaluate_single_bracket_universe(events_df, bars_df, entry_ts_col,
                                     entry_price_col, intraday_rth,
                                     params=None):
    """Single-contract / single-target wrapper around evaluate_event_strategy_pnl.

    Mirrors evaluate_universe in the tight-stop module but adapts to the 1-target
    column shape. Returns evaluated events with __entry_ts and __entry_price set.
    """
    if params is None:
        params = SINGLE_BRACKET
    if len(events_df) == 0:
        out = events_df.copy()
        for k in _SINGLE_BRACKET_COLS:
            out[k] = pd.Series(dtype="float64")
        out["__entry_price"] = pd.Series(dtype="float64")
        out["__entry_ts"] = pd.Series(dtype="datetime64[ns]")
        return out

    bars = bars_df.reset_index()
    bars_ts = bars["timestamp"].values.astype("datetime64[ns]")
    highs = bars["high"].values
    lows = bars["low"].values
    closes = bars["close"].values
    dates = bars["timestamp"].dt.date.values

    ev = events_df.reset_index(drop=True).copy()
    ev["__entry_ts"] = pd.to_datetime(ev[entry_ts_col])
    entry_ts_arr = ev["__entry_ts"].values.astype("datetime64[ns]")
    idx = np.searchsorted(bars_ts, entry_ts_arr)
    safe_idx = np.minimum(idx, len(bars_ts) - 1)
    ok = (idx < len(bars_ts)) & (bars_ts[safe_idx] == entry_ts_arr)

    entry_prices = ev[entry_price_col].astype(float).values
    box_highs = ev["box_high"].astype(float).values
    box_lows = ev["box_low"].astype(float).values
    directions = ev["direction"].values

    rows = []
    for i in range(len(ev)):
        if not ok[i]:
            rows.append(None)
            continue
        rows.append(evaluate_event_strategy_pnl(
            bars_ts, highs, lows, closes, dates,
            int(idx[i]), entry_prices[i], directions[i],
            box_highs[i], box_lows[i], params, intraday_rth,
        ))

    for k in _SINGLE_BRACKET_COLS:
        ev[k] = [r.get(k) if r is not None else np.nan for r in rows]
    ev["__entry_price"] = entry_prices
    ev = ev[ev["strategy_resolution"].notna()].copy()
    return ev


def build_locked_universe(events_all, conn):
    """Apply cut + PO confirmation + immediate entry + variant filter to events.

    Returns (ev_eval_filtered, bars_df, atr_threshold).
    """
    ev_cut = filter_cut_universe(events_all, LOCKED_CUT)
    bars = load_bars(conn, LOCKED_CUT["bars_table"],
                     intraday_rth=LOCKED_CUT["intraday_rth"])
    po = load_higher_tf_po(conn, LOCKED_CUT["po_table"],
                           bar_minutes=LOCKED_CUT["po_minutes"])
    ev_cut = attach_po(ev_cut, po, suffix=LOCKED_CUT["po_suffix"])
    ev_cut = filter_po_confirmed(ev_cut, LOCKED_CUT)

    ev_mode, ts_col, price_col = filter_entry_mode(ev_cut, LOCKED_ENTRY_MODE)
    ev_eval = evaluate_single_bracket_universe(
        ev_mode, bars, ts_col, price_col,
        intraday_rth=LOCKED_CUT["intraday_rth"],
        params=SINGLE_BRACKET,
    )

    atr_pop = ev_eval["box_width_atr"].astype(float).dropna()
    if len(atr_pop) < 8:
        raise SystemExit("Not enough ATR observations to derive within-cut threshold")
    atr_threshold = float(atr_pop.quantile(TIGHT_ATR_QUANTILE))

    ev_filtered, status = apply_variant_filter(ev_eval, LOCKED_VARIANT, atr_threshold)
    if status != "ok":
        raise SystemExit(f"Variant filter status: {status}")
    if len(ev_filtered) == 0:
        raise SystemExit("Locked variant returned 0 trades")
    return ev_filtered.reset_index(drop=True), bars, atr_threshold


def per_trade_R(ev):
    """Per-trade R outcome = pnl_points / box_height."""
    box_h = (ev["box_high"].astype(float) - ev["box_low"].astype(float)).values
    return ev["strategy_pnl_points"].astype(float).values / box_h


# ───────────────────────── headline ─────────────────────────

def max_consecutive(arr):
    """Max length of consecutive 1-runs in a 0/1 array."""
    best = cur = 0
    for v in arr:
        if v:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return int(best)


def headline_block(ev, R_arr):
    n = len(R_arr)
    if n == 0:
        return {"n": 0}
    targets_hit = ev["strategy_targets_hit"].astype(int).values
    stop_hit = ev["strategy_stop_hit"].astype(bool).values
    timeout = ev["strategy_timeout"].astype(bool).values

    pos_R = R_arr[R_arr > 0].sum()
    neg_R = abs(R_arr[R_arr < 0].sum())
    pf = float(pos_R / neg_R) if neg_R > 0 else float("inf")

    cum = np.cumsum(R_arr)
    rm = np.maximum.accumulate(cum)
    max_dd = float((cum - rm).min())

    return {
        "n": int(n),
        "t2_hit_rate": float((targets_hit >= 1).mean()),
        "stop_rate": float(stop_hit.mean()),
        "timeout_rate": float(timeout.mean()),
        "mean_R_per_trade": float(R_arr.mean()),
        "median_R_per_trade": float(np.median(R_arr)),
        "profit_factor": pf,
        "max_consecutive_losses": max_consecutive((R_arr < 0).astype(int)),
        "max_drawdown_R": max_dd,
        "expected_R_per_1000_trades": float(R_arr.mean() * 1000),
    }


# ───────────────────────── walk-forward by year ─────────────────────────

def walk_forward_by_year(ev, R_arr, min_n=WALKFWD_MIN_TRADES,
                         breakeven=BREAKEVEN_HIT_RATE):
    years = pd.to_datetime(ev["break_bar_ts"]).dt.year.values
    out = []
    for y in sorted(set(years.tolist())):
        mask = years == y
        rs = R_arr[mask]
        n = int(len(rs))
        full_year_n = n  # n is the qualifying count
        if n < min_n:
            out.append({
                "year": int(y),
                "n": n,
                "qualifying": False,
                "win_pct": float((rs > 0).mean()) if n > 0 else None,
                "avg_R": float(rs.mean()) if n > 0 else None,
                "profit_factor": None,
                "clears_breakeven": None,
            })
            continue
        win = float((rs > 0).mean())
        avg = float(rs.mean())
        pos = rs[rs > 0].sum()
        neg = abs(rs[rs < 0].sum())
        pf = float(pos / neg) if neg > 0 else float("inf")
        out.append({
            "year": int(y),
            "n": n,
            "qualifying": True,
            "win_pct": win,
            "avg_R": avg,
            "profit_factor": pf,
            "clears_breakeven": bool(win > breakeven),
        })
    return out


# ───────────────────────── bootstrap Monte Carlo ─────────────────────────

def bootstrap_mc(R_arr, n_paths=N_BOOTSTRAP, path_len=BOOTSTRAP_PATH_LEN,
                 seed=BOOTSTRAP_SEED):
    R = np.asarray(R_arr, dtype=float)
    R = R[~np.isnan(R)]
    if len(R) == 0:
        return None
    rng = np.random.default_rng(seed)
    samples = rng.choice(R, size=(n_paths, path_len), replace=True)
    cum = np.cumsum(samples, axis=1)
    finals = cum[:, -1]
    running_max = np.maximum.accumulate(cum, axis=1)
    max_dds = (cum - running_max).min(axis=1)
    return {
        "n_paths": int(n_paths),
        "path_len": int(path_len),
        "seed": int(seed),
        "median_final_R": float(np.median(finals)),
        "p10_final_R": float(np.percentile(finals, 10)),
        "p90_final_R": float(np.percentile(finals, 90)),
        "pct_positive": float((finals > 0).mean()),
        "pct_dd_worse_than_neg50R": float((max_dds < -50).mean()),
    }


# ───────────────────────── sensitivity grid ─────────────────────────

def evaluate_single_bracket_custom(ev, bars, stop_R, target_R,
                                   intraday_rth=True, max_bars=MAX_BARS):
    """Custom single-contract bracket walker with arbitrary stop_R / target_R.

    Same close-arbitration rule as evaluate_event_strategy_pnl:
      - intrabar stop+target conflict → defer to candle close
      - resolution priority: close-beyond-stop, then close-beyond-target
      - timeout marks-to-close at the last bar's close in R
    Returns array of per-trade R outcomes.
    """
    bars_idx = bars.reset_index()
    bars_ts = bars_idx["timestamp"].values.astype("datetime64[ns]")
    highs = bars_idx["high"].values
    lows = bars_idx["low"].values
    closes = bars_idx["close"].values
    dates = bars_idx["timestamp"].dt.date.values

    entry_ts = pd.to_datetime(ev["__entry_ts"]).values.astype("datetime64[ns]")
    idx = np.searchsorted(bars_ts, entry_ts)
    safe_idx = np.minimum(idx, len(bars_ts) - 1)
    ok = (idx < len(bars_ts)) & (bars_ts[safe_idx] == entry_ts)

    entry_prices = ev["__entry_price"].astype(float).values
    box_highs = ev["box_high"].astype(float).values
    box_lows = ev["box_low"].astype(float).values
    directions = ev["direction"].values

    out = np.full(len(ev), np.nan)
    n_bars = len(bars_ts)

    for i in range(len(ev)):
        if not ok[i]:
            continue
        R = box_highs[i] - box_lows[i]
        if R <= 0:
            continue
        ep = entry_prices[i]
        d = directions[i]
        if d == "bull":
            stop_lvl = ep - stop_R * R
            tgt_lvl = ep + target_R * R
        else:
            stop_lvl = ep + stop_R * R
            tgt_lvl = ep - target_R * R
        entry_date = dates[idx[i]]
        result_R = np.nan
        last_close = np.nan
        last_step = 0
        for step in range(1, max_bars + 1):
            j = idx[i] + step
            if j >= n_bars:
                break
            if intraday_rth and dates[j] != entry_date:
                break
            h, l, c = highs[j], lows[j], closes[j]
            last_step = step
            last_close = c
            if d == "bull":
                stop_in = l <= stop_lvl
                tgt_in = h >= tgt_lvl
                close_stops = c <= stop_lvl
                close_tgt = c >= tgt_lvl
            else:
                stop_in = h >= stop_lvl
                tgt_in = l <= tgt_lvl
                close_stops = c >= stop_lvl
                close_tgt = c <= tgt_lvl
            if stop_in and tgt_in:
                if close_stops:
                    result_R = -stop_R
                    break
                if close_tgt:
                    result_R = target_R
                    break
                continue
            if stop_in:
                result_R = -stop_R
                break
            if tgt_in:
                result_R = target_R
                break
        if np.isnan(result_R):
            if last_step > 0:
                result_R = (last_close - ep) / R if d == "bull" else (ep - last_close) / R
            else:
                result_R = 0.0
        out[i] = result_R
    return out


def sensitivity_grid(ev, bars, stops=SENSITIVITY_STOPS, targets=SENSITIVITY_TARGETS):
    rows = []
    for s in stops:
        for t in targets:
            R = evaluate_single_bracket_custom(ev, bars, s, t)
            R = R[~np.isnan(R)]
            n = int(len(R))
            if n == 0:
                rows.append({"stop_R": s, "target_R": t, "n": 0,
                             "win_pct": None, "avg_R": None, "ev_per_1000": None})
                continue
            rows.append({
                "stop_R": float(s),
                "target_R": float(t),
                "n": n,
                "win_pct": float((R > 0).mean()),
                "avg_R": float(R.mean()),
                "ev_per_1000": float(R.mean() * 1000),
            })
    return rows


# ───────────────────────── friction ─────────────────────────

def friction_test(ev, R_arr, friction_pts=FRICTION_PER_TRADE_PTS):
    box_h = (ev["box_high"].astype(float) - ev["box_low"].astype(float)).values
    cost_R = friction_pts / box_h
    R_after = R_arr - cost_R
    pos = R_after[R_after > 0].sum()
    neg = abs(R_after[R_after < 0].sum())
    pf = float(pos / neg) if neg > 0 else float("inf")
    return {
        "slippage_per_side_points": SLIPPAGE_PER_SIDE_PTS,
        "commission_per_side_points": COMMISSION_PER_SIDE_PTS,
        "friction_per_trade_points": float(friction_pts),
        "mean_cost_R_per_trade": float(cost_R.mean()),
        "median_cost_R_per_trade": float(np.median(cost_R)),
        "mean_R_after_friction": float(R_after.mean()),
        "profit_factor_after_friction": pf,
        "ev_per_1000_after_friction": float(R_after.mean() * 1000),
        "R_after_friction": R_after,
    }


# ───────────────────────── verdict ─────────────────────────

def assign_verdict(headline, walkfwd, mc, fric):
    qual = [y for y in walkfwd if y.get("qualifying")]
    n_qual = len(qual)
    n_pass = sum(1 for y in qual if y.get("clears_breakeven"))
    yr_pass_ratio = (n_pass / n_qual) if n_qual > 0 else 0.0

    c1 = bool(headline.get("t2_hit_rate") is not None
              and headline["t2_hit_rate"] > VERDICT_FULL_WIN_THRESH)
    c2 = bool(n_qual > 0 and yr_pass_ratio >= VERDICT_YR_PASS_RATIO)
    c3 = bool(mc is not None and mc.get("p10_final_R") is not None
              and mc["p10_final_R"] > 0)
    c4 = bool(fric is not None and fric.get("ev_per_1000_after_friction") is not None
              and fric["ev_per_1000_after_friction"] > 0)
    n_met = int(c1) + int(c2) + int(c3) + int(c4)
    if n_met == 4:
        v = "publishable"
    elif n_met == 3:
        v = "borderline"
    else:
        v = "not_publishable"
    return v, {
        "n_criteria_met": n_met,
        "full_win_pct_gt_36": c1,
        "year_pass_ratio_ge_60pct": c2,
        "mc_p10_positive": c3,
        "friction_ev_positive": c4,
        "qualifying_years": n_qual,
        "qualifying_years_passing": n_pass,
        "year_pass_ratio": float(yr_pass_ratio),
        "criteria_definitions": {
            "full_win_pct_gt_36": f"headline t2_hit_rate > {VERDICT_FULL_WIN_THRESH:.2f}",
            "year_pass_ratio_ge_60pct": (f">= {VERDICT_YR_PASS_RATIO*100:.0f}% of years"
                                          f" with n>={WALKFWD_MIN_TRADES} clear"
                                          f" {BREAKEVEN_HIT_RATE*100:.1f}%"),
            "mc_p10_positive": "Monte Carlo 10th percentile final R > 0",
            "friction_ev_positive": "EV per 1,000 trades after friction > 0",
        },
    }


# ───────────────────────── pretty printers ─────────────────────────

def fmt_pct(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "  n/a"
    return f"{x*100:6.2f}%"


def fmt_R(x, decimals=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "  n/a"
    return f"{x:+.{decimals}f}"


def print_headline(h):
    print("\n" + "=" * 88)
    print("  HEADLINE — full-sample stats (locked setup)")
    print("=" * 88)
    print(f"  n trades                : {h['n']:>6d}")
    print(f"  T2 (=1R) hit rate       : {fmt_pct(h['t2_hit_rate'])}"
          f"   (breakeven for 2:1 R:R = {BREAKEVEN_HIT_RATE*100:.2f}%)")
    print(f"  stop rate               : {fmt_pct(h['stop_rate'])}")
    print(f"  timeout rate            : {fmt_pct(h['timeout_rate'])}")
    print(f"  mean R per trade        : {fmt_R(h['mean_R_per_trade'])}")
    print(f"  median R per trade      : {fmt_R(h['median_R_per_trade'])}")
    print(f"  profit factor           : {h['profit_factor']:.3f}")
    print(f"  max consecutive losses  : {h['max_consecutive_losses']}")
    print(f"  max drawdown (R)        : {h['max_drawdown_R']:.2f}")
    print(f"  expected R per 1k trades: {h['expected_R_per_1000_trades']:+.2f}")


def print_walkfwd(rows):
    print("\n" + "=" * 88)
    print("  WALK-FORWARD by calendar year (qualifying = n >= "
          f"{WALKFWD_MIN_TRADES})")
    print("=" * 88)
    print(f"  {'year':>6}  {'n':>5}  {'win%':>7}  {'avg_R':>9}  "
          f"{'PF':>7}  {'breakeven cleared'}")
    for r in rows:
        if not r.get("qualifying"):
            print(f"  {r['year']:>6}  {r['n']:>5}  "
                  f"{fmt_pct(r.get('win_pct')):>7}  {'  n/a':>9}  "
                  f"{'  n/a':>7}  (below n threshold)")
            continue
        pf = r["profit_factor"]
        pf_s = f"{pf:7.3f}" if np.isfinite(pf) else "    inf"
        print(f"  {r['year']:>6}  {r['n']:>5}  "
              f"{fmt_pct(r['win_pct']):>7}  {r['avg_R']:>+9.4f}  "
              f"{pf_s}  {'YES' if r['clears_breakeven'] else 'no'}")


def print_mc(mc):
    print("\n" + "=" * 88)
    print(f"  MONTE CARLO — {mc['n_paths']:,} paths × "
          f"{mc['path_len']:,} trades, with replacement")
    print("=" * 88)
    print(f"  median final R          : {mc['median_final_R']:+.2f}")
    print(f"  p10 final R             : {mc['p10_final_R']:+.2f}")
    print(f"  p90 final R             : {mc['p90_final_R']:+.2f}")
    print(f"  pct of paths positive   : {fmt_pct(mc['pct_positive'])}")
    print(f"  pct DD worse than -50R  : {fmt_pct(mc['pct_dd_worse_than_neg50R'])}")


def print_sensitivity(rows):
    print("\n" + "=" * 88)
    print("  SENSITIVITY GRID — 3×3 cross-product (no re-tuning)")
    print("=" * 88)
    print(f"  {'stop_R':>7}  {'tgt_R':>6}  {'n':>5}  "
          f"{'win%':>7}  {'avg_R':>9}  {'EV/1k':>9}")
    for r in rows:
        n = r["n"]
        if n == 0:
            print(f"  {r['stop_R']:7.2f}  {r['target_R']:6.2f}  {n:>5}  "
                  f"{'  n/a':>7}  {'  n/a':>9}  {'  n/a':>9}")
            continue
        print(f"  {r['stop_R']:7.2f}  {r['target_R']:6.2f}  {n:>5}  "
              f"{fmt_pct(r['win_pct']):>7}  {r['avg_R']:>+9.4f}  "
              f"{r['ev_per_1000']:>+9.2f}")


def print_friction(f):
    print("\n" + "=" * 88)
    print(f"  FRICTION TEST — {SLIPPAGE_PER_SIDE_PTS} pts slippage + "
          f"{COMMISSION_PER_SIDE_PTS} pts commission per side")
    print("=" * 88)
    print(f"  total cost per trade    : {f['friction_per_trade_points']:.4f} SPY pts")
    print(f"  mean cost in R per trade: {f['mean_cost_R_per_trade']:.4f}")
    print(f"  mean R after friction   : {fmt_R(f['mean_R_after_friction'])}")
    print(f"  profit factor (post)    : {f['profit_factor_after_friction']:.3f}")
    print(f"  EV per 1k after friction: {f['ev_per_1000_after_friction']:+.2f}")


def print_verdict(verdict, criteria):
    print("\n" + "=" * 88)
    print(f"  VERDICT: {verdict.upper()}  ({criteria['n_criteria_met']}/4 criteria met)")
    print("=" * 88)
    for k, label in [("full_win_pct_gt_36",
                       f"headline win% > {VERDICT_FULL_WIN_THRESH*100:.0f}%"),
                      ("year_pass_ratio_ge_60pct",
                       f">= {VERDICT_YR_PASS_RATIO*100:.0f}% of qualifying years clear"),
                      ("mc_p10_positive", "Monte Carlo p10 final R > 0"),
                      ("friction_ev_positive", "Friction-adjusted EV > 0")]:
        ok = "PASS" if criteria[k] else "FAIL"
        print(f"  [{ok}] {label}")


# ───────────────────────── runner ─────────────────────────

def main():
    if not os.path.exists(EVENTS_CSV):
        raise SystemExit(f"Missing events CSV: {EVENTS_CSV}")
    print(f"Loading events from {EVENTS_CSV}...")
    ev_all = pd.read_csv(
        EVENTS_CSV,
        parse_dates=["break_bar_ts", "immediate_entry_ts",
                     "close_outside_entry_ts", "retest_entry_ts"],
        low_memory=False,
    )
    print(f"  {len(ev_all):,} total events across all timeframes")

    conn = sqlite3.connect(DB_PATH)
    try:
        ev, bars, atr_threshold = build_locked_universe(ev_all, conn)
    finally:
        conn.close()

    print(f"\nLocked universe built: n={len(ev):,} trades, "
          f"atr_threshold(q{TIGHT_ATR_QUANTILE:.2f})={atr_threshold:.4f}")
    yrs = pd.to_datetime(ev["break_bar_ts"]).dt.year
    print(f"  Date range: {ev['break_bar_ts'].min()} → "
          f"{ev['break_bar_ts'].max()}  "
          f"(years {int(yrs.min())}–{int(yrs.max())})")

    R_arr = per_trade_R(ev)

    headline = headline_block(ev, R_arr)
    print_headline(headline)

    walk = walk_forward_by_year(ev, R_arr)
    print_walkfwd(walk)

    print(f"\nRunning Monte Carlo: {N_BOOTSTRAP:,} paths × "
          f"{BOOTSTRAP_PATH_LEN:,} trades...", flush=True)
    mc = bootstrap_mc(R_arr)
    print_mc(mc)

    print("\nRunning sensitivity grid (3×3 = 9 cells)...", flush=True)
    sens = sensitivity_grid(ev, bars)
    print_sensitivity(sens)

    fric = friction_test(ev, R_arr)
    print_friction(fric)

    verdict, criteria = assign_verdict(headline, walk, mc, fric)
    print_verdict(verdict, criteria)

    # ── outputs ─────────────────────────────────────────────────────
    table_rows = []
    for r in walk:
        table_rows.append({
            "section": "walk_forward_year",
            "year": r["year"],
            "qualifying": r["qualifying"],
            "n": r["n"],
            "win_pct": r.get("win_pct"),
            "avg_R": r.get("avg_R"),
            "profit_factor": r.get("profit_factor"),
            "clears_breakeven": r.get("clears_breakeven"),
            "stop_R": None,
            "target_R": None,
            "ev_per_1000": None,
        })
    for r in sens:
        table_rows.append({
            "section": "sensitivity",
            "year": None,
            "qualifying": None,
            "n": r["n"],
            "win_pct": r.get("win_pct"),
            "avg_R": r.get("avg_R"),
            "profit_factor": None,
            "clears_breakeven": None,
            "stop_R": r["stop_R"],
            "target_R": r["target_R"],
            "ev_per_1000": r.get("ev_per_1000"),
        })
    pd.DataFrame(table_rows).to_csv(TABLE_CSV_PATH, index=False)
    print(f"\nSaved table → {TABLE_CSV_PATH}")

    summary = {
        "study": "bilbo_box_edge_validation",
        "locked_setup": {
            "cut": LOCKED_CUT["key"],
            "label": LOCKED_CUT["label"],
            "entry_mode": LOCKED_ENTRY_MODE,
            "variant": LOCKED_VARIANT,
            "initial_stop": "tight_half_R (0.5R against entry)",
            "target": "T2 = 1.0R (single-contract bracket)",
            "max_bars": MAX_BARS,
            "R_definition": "box_high - box_low",
            "tight_atr_quantile": TIGHT_ATR_QUANTILE,
            "atr_threshold_used": atr_threshold,
            "breakeven_hit_rate_for_2to1": BREAKEVEN_HIT_RATE,
        },
        "headline": headline,
        "walk_forward": walk,
        "walk_forward_min_trades_per_year": WALKFWD_MIN_TRADES,
        "monte_carlo": mc,
        "sensitivity_grid": sens,
        "friction": {k: v for k, v in fric.items() if k != "R_after_friction"},
        "verdict": verdict,
        "verdict_criteria": criteria,
    }
    with open(JSON_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved summary → {JSON_PATH}")

    # Final stdout summary block (also visible in the log).
    yrs_pass = sum(1 for y in walk if y.get("qualifying") and y.get("clears_breakeven"))
    yrs_qual = sum(1 for y in walk if y.get("qualifying"))
    print("\n" + "=" * 88)
    print("  FINAL SUMMARY")
    print("=" * 88)
    print(f"  verdict                 : {verdict}")
    print(f"  n trades                : {headline['n']}")
    print(f"  T2 hit rate             : {fmt_pct(headline['t2_hit_rate'])}")
    print(f"  mean R per trade        : {fmt_R(headline['mean_R_per_trade'])}")
    print(f"  profit factor           : {headline['profit_factor']:.3f}")
    print(f"  qualifying years passing: {yrs_pass}/{yrs_qual}")
    print(f"  MC pct positive         : {fmt_pct(mc['pct_positive'])}")
    print(f"  MC p10 final R          : {mc['p10_final_R']:+.2f}")
    print(f"  friction-adj EV / 1k    : {fric['ev_per_1000_after_friction']:+.2f}")


if __name__ == "__main__":
    logf = open(LOG_PATH, "w")

    class Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, s):
            for st in self.streams:
                try:
                    st.write(s)
                except ValueError:
                    pass

        def flush(self):
            for st in self.streams:
                try:
                    st.flush()
                except ValueError:
                    pass

    sys.stdout = Tee(sys.__stdout__, logf)
    try:
        main()
    finally:
        sys.stdout = sys.__stdout__
        logf.close()
