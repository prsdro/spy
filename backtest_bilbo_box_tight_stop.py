"""
Bilbo Box Tight-Stop Study
==========================

QUESTION
--------
Can the Bilbo box trade hit T2 (= +1R) ~50% of the time while preserving
≥ 2:1 reward:risk by using a tight initial stop = entry ± 0.5R, and does
candle-close confirmation beat immediate-break entry?

R UNIT
------
R = box_high - box_low (box HEIGHT in price points).

STRATEGY
--------
3 contracts. Targets T1=0.5R, T2=1.0R, T3=2.0R (one contract each).
Initial stop = entry ± 0.5R (symmetric, nominal 2:1 R:R to T2).
Stop does not move after T1.
After T2, final-contract stop moves to break-side box edge:
    bull → box_high   bear → box_low
15-bar timeout. Same-bar stop/target conflicts wait for candle close.

ENTRY MODES (compared head-to-head)
----------
1) immediate_touch — existing immediate_entry_ts/immediate_entry_price.
2) close_confirm   — only if BREAK CANDLE itself closes beyond the boundary
                     (close_outside_entry_ts == break_bar_ts). Entry = that
                     break candle's close. No future bars used.
3) retest          — existing retest_entry_ts/retest_entry_price (entry on
                     boundary touch after break).

CUTS
----
Cut 1: 3m bull breaks × 10m PO state_slope == bull_exp+rising
Cut 2: 10m bear breaks × 1h PO state_slope == bear_exp+falling
Both cuts drop ambiguous_outside events.

VARIANT FILTERS
---------------
A. base                       same-direction PO confirmation only
B. short_box                  box_bars ≤ 4
C. tight_atr                  box_width_atr in lowest quartile within (cut, mode)
D. short_box_tight_atr        intersection of B and C
E. gap_filter                 |entry - break_side_edge| / R ≤ 0.25
F. short_box_tight_atr_gap    intersection of B, C, and E

ATR CAVEAT
----------
box_width_atr = (box_high - box_low) / atr14_at_break, computed at break_bar
including the break bar's own true range. This is event-time (no future
bars), but is not strictly "prior" — within-cut quartile ranking is still
internally consistent.

TRAIN / HOLDOUT
---------------
break_bar_ts ≤ 2025-09-30  → train
break_bar_ts ≥ 2025-10-01  → holdout

PUBLISHABLE FLAGS
-----------------
publishable      = n ≥ 200 AND median_rr_to_t2 ≥ 2.0
strong_candidate = publishable AND t2_pct ≥ 0.50 AND
                   holdout_t2_pct ≥ 0.70 × train_t2_pct

REUSED HELPERS
--------------
load_bars, load_higher_tf_po, attach_po, evaluate_event_strategy_pnl,
StrategyParams — all from backtest_bilbo_box_htf_po_exits.

OUTPUTS
-------
- analyst/bilbo_box_tight_stop_run.log
- analyst/bilbo_box_tight_stop_summary.json
- analyst/bilbo_box_tight_stop_table.csv
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
ANALYST_DIR = os.path.join(BASE_DIR, "analyst")
EVENTS_CSV = os.path.join(ANALYST_DIR, "bilbo_box_events.csv")
LOG_PATH = os.path.join(ANALYST_DIR, "bilbo_box_tight_stop_run.log")
JSON_PATH = os.path.join(ANALYST_DIR, "bilbo_box_tight_stop_summary.json")
TABLE_CSV_PATH = os.path.join(ANALYST_DIR, "bilbo_box_tight_stop_table.csv")

MAX_BARS = 15
TARGETS_R = (0.5, 1.0, 2.0)
TRAIN_END = pd.Timestamp("2025-09-30 23:59:59")
HOLDOUT_START = pd.Timestamp("2025-10-01 00:00:00")
PUBLISHABLE_MIN_N = 200
PUBLISHABLE_MIN_RR = 2.0
STRONG_CANDIDATE_MIN_T2 = 0.50
STRONG_CANDIDATE_HOLDOUT_RATIO = 0.70
TIGHT_ATR_QUANTILE = 0.25
GAP_FILTER_MAX = 0.25

TIGHT_STRATEGY = StrategyParams(
    targets_R=TARGETS_R,
    position_size=3,
    max_bars=MAX_BARS,
    initial_stop="tight_half_R",
    stop_after_t1="no_move",
    stop_after_t2="box_break_side",
    stop_after_t3="box_break_side",
)

CUTS = [
    {
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
    },
    {
        "key": "10m_bear_x_1h_po",
        "label": "10m BEAR × 1h PO bear_exp+falling",
        "bars_table": "ind_10m",
        "timeframe": "10m",
        "direction": "bear",
        "po_table": "ind_1h",
        "po_suffix": "1h",
        "po_minutes": 60,
        "expected_state_slope": "bear_exp+falling",
        "intraday_rth": True,
    },
]

ENTRY_MODES = ["immediate_touch", "close_confirm", "retest"]
VARIANTS = ["base", "short_box", "tight_atr", "short_box_tight_atr",
            "gap_filter", "short_box_tight_atr_gap"]


# ───────────────────────── data prep ─────────────────────────

def filter_cut_universe(events_all, cut):
    """Clean events for a single cut: matching tf+direction, not ambiguous, immediate_fired
    (so the break is well-defined). Entry-mode-specific filtering happens later."""
    ev = events_all[
        (events_all["timeframe"] == cut["timeframe"])
        & (events_all["direction"] == cut["direction"])
        & (~events_all["ambiguous_outside"].astype(bool))
        & (events_all["immediate_fired"].astype(bool))
    ].copy()
    return ev


def filter_po_confirmed(events_with_po, cut):
    suffix = cut["po_suffix"]
    have_po = events_with_po[f"po_{suffix}"].notna()
    ev = events_with_po[have_po].copy()
    ev = ev[ev[f"state_slope_{suffix}"] == cut["expected_state_slope"]].copy()
    return ev


def filter_entry_mode(events_df, mode):
    """Return (filtered_ev, entry_ts_col, entry_price_col)."""
    if mode == "immediate_touch":
        ev = events_df[events_df["immediate_fired"].astype(bool)].copy()
        return ev, "immediate_entry_ts", "immediate_entry_price"
    if mode == "close_confirm":
        ev = events_df[events_df["close_outside_fired"].astype(bool)].copy()
        # Strict: only if break candle itself confirmed (no later-bar confirmation).
        ev["close_outside_entry_ts"] = pd.to_datetime(ev["close_outside_entry_ts"])
        ev["break_bar_ts"] = pd.to_datetime(ev["break_bar_ts"])
        ev = ev[ev["close_outside_entry_ts"] == ev["break_bar_ts"]].copy()
        return ev, "close_outside_entry_ts", "close_outside_entry_price"
    if mode == "retest":
        ev = events_df[events_df["retest_fired"].astype(bool)].copy()
        return ev, "retest_entry_ts", "retest_entry_price"
    raise ValueError(f"unknown entry mode: {mode}")


# ───────────────────────── evaluation ─────────────────────────

def evaluate_universe(events_df, bars_df, entry_ts_col, entry_price_col,
                      intraday_rth, params=TIGHT_STRATEGY):
    """Run the tight-stop bracket strategy on each event using the chosen entry."""
    if len(events_df) == 0:
        out = events_df.copy()
        for k in _strategy_cols():
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
    in_range = idx < len(bars_ts)
    safe_idx = np.minimum(idx, len(bars_ts) - 1)
    ok = in_range & (bars_ts[safe_idx] == entry_ts_arr)
    ev["bar_match"] = ok

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

    for k in _strategy_cols():
        ev[k] = [r[k] if r is not None else np.nan for r in rows]
    ev["__entry_price"] = entry_prices
    ev = ev[ev["strategy_resolution"].notna()].copy()
    return ev


def _strategy_cols():
    return [
        "strategy_pnl_points",
        "strategy_targets_hit",
        "strategy_stop_hit",
        "strategy_timeout",
        "strategy_resolution",
        "strategy_bars_to_resolution",
        "strategy_same_bar_conflicts",
        "strategy_t1_hit",
        "strategy_t2_hit",
        "strategy_t3_hit",
        "strategy_t1_bar",
        "strategy_t2_bar",
        "strategy_t3_bar",
    ]


# ───────────────────────── variant filters ─────────────────────────

def apply_variant_filter(ev, variant, atr_threshold):
    if variant == "base":
        return ev.copy(), "ok"

    if variant == "short_box":
        return ev[ev["box_bars"].astype(int) <= 4].copy(), "ok"

    if variant == "tight_atr":
        if atr_threshold is None or pd.isna(atr_threshold):
            return ev.iloc[0:0].copy(), "no_atr_threshold"
        sub = ev[ev["box_width_atr"].astype(float) <= atr_threshold].copy()
        return sub, "ok"

    if variant == "short_box_tight_atr":
        if atr_threshold is None or pd.isna(atr_threshold):
            return ev.iloc[0:0].copy(), "no_atr_threshold"
        sub = ev[(ev["box_bars"].astype(int) <= 4)
                 & (ev["box_width_atr"].astype(float) <= atr_threshold)].copy()
        return sub, "ok"

    if variant == "gap_filter":
        return _filter_gap(ev), "ok"

    if variant == "short_box_tight_atr_gap":
        if atr_threshold is None or pd.isna(atr_threshold):
            return ev.iloc[0:0].copy(), "no_atr_threshold"
        sub = ev[(ev["box_bars"].astype(int) <= 4)
                 & (ev["box_width_atr"].astype(float) <= atr_threshold)].copy()
        return _filter_gap(sub), "ok"

    raise ValueError(f"unknown variant: {variant}")


def _filter_gap(ev):
    if len(ev) == 0:
        return ev.copy()
    R = ev["box_high"].astype(float) - ev["box_low"].astype(float)
    edge = np.where(ev["direction"].values == "bull",
                    ev["box_high"].astype(float).values,
                    ev["box_low"].astype(float).values)
    overshoot = (ev["__entry_price"].astype(float).values - edge)
    overshoot_R = np.abs(overshoot) / R.values
    return ev[overshoot_R <= GAP_FILTER_MAX].copy()


# ───────────────────────── stats ─────────────────────────

def stats_for(ev):
    n = len(ev)
    if n == 0:
        return {
            "n": 0,
            "t1_count": 0, "t2_count": 0, "t3_count": 0,
            "stop_count": 0, "timeout_count": 0,
            "t1_pct": None, "t2_pct": None, "t3_pct": None,
            "stop_pct": None, "timeout_pct": None, "win_pct": None,
            "pnl_points_total": 0.0, "pnl_points_avg": None, "pnl_points_median": None,
            "median_box_height": None,
            "median_initial_risk_box_R": None,
            "median_rr_to_t2": None,
            "same_bar_conflict_count": 0, "same_bar_conflict_pct": None,
        }
    pnl = ev["strategy_pnl_points"].astype(float)
    stop = ev["strategy_stop_hit"].astype(bool)
    timeout = ev["strategy_timeout"].astype(bool)
    targets_hit = ev["strategy_targets_hit"].astype(int)
    same_bar = ev["strategy_same_bar_conflicts"].astype(float).fillna(0)
    box_height = (ev["box_high"].astype(float) - ev["box_low"].astype(float))

    # Tight stop is always 0.5R against direction by construction →
    #   realized initial risk = 0.5R, R:R to T2 = 1R / 0.5R = 2.0.
    # Reported per-row to make this explicit and to catch any drift if the
    # stop name is ever changed.
    initial_risk_box_R = pd.Series(0.5, index=ev.index)
    rr_to_t2 = pd.Series(2.0, index=ev.index)

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
        "win_pct": float((pnl > 0).mean()),
        "pnl_points_total": float(pnl.sum()),
        "pnl_points_avg": float(pnl.mean()),
        "pnl_points_median": float(pnl.median()),
        "median_box_height": float(box_height.median()),
        "median_initial_risk_box_R": float(initial_risk_box_R.median()),
        "median_rr_to_t2": float(rr_to_t2.median()),
        "same_bar_conflict_count": int((same_bar > 0).sum()),
        "same_bar_conflict_pct": float((same_bar > 0).mean()),
    }


def split_train_holdout(ev):
    ts = pd.to_datetime(ev["break_bar_ts"])
    return ev[ts <= TRAIN_END], ev[ts >= HOLDOUT_START]


def split_metrics(ev):
    train, holdout = split_train_holdout(ev)
    return {
        "train_n": int(len(train)),
        "train_t2_pct": (float((train["strategy_targets_hit"].astype(int) >= 2).mean())
                         if len(train) > 0 else None),
        "holdout_n": int(len(holdout)),
        "holdout_t2_pct": (float((holdout["strategy_targets_hit"].astype(int) >= 2).mean())
                           if len(holdout) > 0 else None),
    }


def is_publishable(stats):
    return (stats.get("n", 0) >= PUBLISHABLE_MIN_N
            and (stats.get("median_rr_to_t2") is not None)
            and stats["median_rr_to_t2"] >= PUBLISHABLE_MIN_RR)


def is_strong(stats, splits):
    if not is_publishable(stats):
        return False
    if (stats.get("t2_pct") is None) or stats["t2_pct"] < STRONG_CANDIDATE_MIN_T2:
        return False
    train_t2 = splits.get("train_t2_pct")
    holdout_t2 = splits.get("holdout_t2_pct")
    if train_t2 is None or holdout_t2 is None:
        return False
    return holdout_t2 >= STRONG_CANDIDATE_HOLDOUT_RATIO * train_t2


# ───────────────────────── runner ─────────────────────────

def fmt_pct(x):
    return f"{x*100:5.1f}%" if (x is not None and not (isinstance(x, float) and pd.isna(x))) else "  n/a"


def fmt_num(x, decimals=3):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "  n/a"
    return f"{x:+.{decimals}f}"


def run_cut(cut, events_all, conn):
    print("\n" + "=" * 110)
    print(f"  {cut['label']}  —  tight stop = entry ± 0.5R, T1=0.5R, T2=1R, T3=2R, 15-bar timeout")
    print("=" * 110)

    ev_cut = filter_cut_universe(events_all, cut)
    print(f"  Cut universe (clean breaks, immediate_fired, not ambiguous): {len(ev_cut):,}")

    print(f"  Loading {cut['bars_table']} bars (RTH={cut['intraday_rth']})...", flush=True)
    bars = load_bars(conn, cut["bars_table"], intraday_rth=cut["intraday_rth"])
    print(f"    {len(bars):,} bars")

    print(f"  Loading {cut['po_table']} PO (shifted +{cut['po_minutes']}m for lookahead safety)...", flush=True)
    po = load_higher_tf_po(conn, cut["po_table"], bar_minutes=cut["po_minutes"])
    ev_cut = attach_po(ev_cut, po, suffix=cut["po_suffix"])
    ev_cut = filter_po_confirmed(ev_cut, cut)
    print(f"  After PO confirmation ({cut['expected_state_slope']}): {len(ev_cut):,}")

    rows = []
    threshold_records = {}

    for mode in ENTRY_MODES:
        ev_mode, ts_col, price_col = filter_entry_mode(ev_cut, mode)
        print(f"\n  Entry mode = {mode:16s}  → {len(ev_mode):>5d} events before evaluation", flush=True)
        if len(ev_mode) == 0:
            continue

        ev_eval = evaluate_universe(ev_mode, bars, ts_col, price_col,
                                    intraday_rth=cut["intraday_rth"])
        print(f"    {len(ev_eval):>5d} events after bar-walk resolution", flush=True)

        atr_pop = ev_eval["box_width_atr"].astype(float).dropna()
        atr_threshold = float(atr_pop.quantile(TIGHT_ATR_QUANTILE)) if len(atr_pop) >= 8 else None
        threshold_records[f"{cut['key']}__{mode}"] = atr_threshold
        if atr_threshold is None:
            print(f"    [warn] not enough atr observations to build tight_atr threshold")
        else:
            print(f"    tight_atr threshold (q{TIGHT_ATR_QUANTILE:.2f}) box_width_atr ≤ {atr_threshold:.4f}")

        for variant in VARIANTS:
            sub, status = apply_variant_filter(ev_eval, variant, atr_threshold)
            stats = stats_for(sub)
            splits = split_metrics(sub) if stats["n"] > 0 else {
                "train_n": 0, "train_t2_pct": None, "holdout_n": 0, "holdout_t2_pct": None
            }
            row = {
                "cut": cut["key"],
                "entry_mode": mode,
                "variant": variant,
                "filter_status": status,
                "atr_threshold_q25": atr_threshold,
                **stats,
                **splits,
                "publishable": is_publishable(stats),
                "strong_candidate": is_strong(stats, splits),
            }
            rows.append(row)

            if stats["n"] == 0 or status != "ok":
                print(f"      {variant:26s} n=    0    [{status}]")
            else:
                print(
                    f"      {variant:26s} n={stats['n']:>5d}  "
                    f"T1={fmt_pct(stats['t1_pct'])}  T2={fmt_pct(stats['t2_pct'])}  "
                    f"T3={fmt_pct(stats['t3_pct'])}  Stop={fmt_pct(stats['stop_pct'])}  "
                    f"Tout={fmt_pct(stats['timeout_pct'])}  "
                    f"Win={fmt_pct(stats['win_pct'])}  "
                    f"Avg={fmt_num(stats['pnl_points_avg'], 3)}  "
                    f"Tot={fmt_num(stats['pnl_points_total'], 1)} pts  "
                    f"hold T2={fmt_pct(splits['holdout_t2_pct'])} (n={splits['holdout_n']})  "
                    f"{'PUBLISHABLE' if row['publishable'] else 'below_threshold'}"
                    f"{' STRONG' if row['strong_candidate'] else ''}"
                )

    return rows, threshold_records


def cross_mode_compact(rows):
    """Print a base-variant-only compact table comparing entry modes per cut."""
    print("\n" + "=" * 110)
    print("  COMPACT TAKEAWAY (variant=base, T2 hit% per entry mode)")
    print("=" * 110)
    cuts_seen = sorted({r["cut"] for r in rows})
    for cut in cuts_seen:
        print(f"  {cut}")
        for mode in ENTRY_MODES:
            match = next((r for r in rows
                          if r["cut"] == cut and r["entry_mode"] == mode and r["variant"] == "base"),
                         None)
            if not match or match["n"] == 0:
                print(f"    {mode:16s} — no events")
                continue
            print(f"    {mode:16s} n={match['n']:>5d}  "
                  f"T2={fmt_pct(match['t2_pct'])}  Win={fmt_pct(match['win_pct'])}  "
                  f"Avg={fmt_num(match['pnl_points_avg'], 3)}  "
                  f"Train T2={fmt_pct(match['train_t2_pct'])} (n={match['train_n']})  "
                  f"Hold T2={fmt_pct(match['holdout_t2_pct'])} (n={match['holdout_n']})")


def headline_candidates(rows):
    """List variants that meet 50% T2 publishable+strong criteria."""
    print("\n" + "=" * 110)
    print(f"  STRONG CANDIDATES (n≥{PUBLISHABLE_MIN_N}, R:R≥{PUBLISHABLE_MIN_RR}, "
          f"T2≥{STRONG_CANDIDATE_MIN_T2*100:.0f}%, holdout T2 ≥ {STRONG_CANDIDATE_HOLDOUT_RATIO*100:.0f}% of train)")
    print("=" * 110)
    strong = [r for r in rows if r.get("strong_candidate")]
    if not strong:
        print("  (none — no variant met all four thresholds)")
    else:
        for r in sorted(strong, key=lambda x: -x["t2_pct"]):
            print(f"  {r['cut']:18s} {r['entry_mode']:16s} {r['variant']:24s} "
                  f"n={r['n']:>5d} T2={fmt_pct(r['t2_pct'])} "
                  f"Train={fmt_pct(r['train_t2_pct'])} Hold={fmt_pct(r['holdout_t2_pct'])} "
                  f"Avg={fmt_num(r['pnl_points_avg'])}")
    print()
    print(f"  PUBLISHABLE-but-below-50% (n≥{PUBLISHABLE_MIN_N}, R:R≥{PUBLISHABLE_MIN_RR}, T2<50%):")
    pub = [r for r in rows if r.get("publishable") and not r.get("strong_candidate")
           and (r.get("t2_pct") is not None) and r["t2_pct"] < STRONG_CANDIDATE_MIN_T2]
    if not pub:
        print("  (none)")
    else:
        for r in sorted(pub, key=lambda x: -x["t2_pct"])[:20]:
            print(f"    {r['cut']:18s} {r['entry_mode']:16s} {r['variant']:24s} "
                  f"n={r['n']:>5d} T2={fmt_pct(r['t2_pct'])} Avg={fmt_num(r['pnl_points_avg'])}")


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
    all_rows = []
    all_thresholds = {}
    try:
        for cut in CUTS:
            rows, thresholds = run_cut(cut, ev_all, conn)
            all_rows.extend(rows)
            all_thresholds.update(thresholds)
    finally:
        conn.close()

    cross_mode_compact(all_rows)
    headline_candidates(all_rows)

    table = pd.DataFrame(all_rows)
    table.to_csv(TABLE_CSV_PATH, index=False)
    print(f"\nSaved table → {TABLE_CSV_PATH}")

    summary = {
        "study": "bilbo_box_tight_stop",
        "params": {
            "max_bars": MAX_BARS,
            "targets_R": list(TARGETS_R),
            "initial_stop": "tight_half_R",
            "stop_after_t1": "no_move",
            "stop_after_t2": "box_break_side",
            "position_size": 3,
            "R_definition": "box_high - box_low (box height in price points)",
            "tight_atr_quantile": TIGHT_ATR_QUANTILE,
            "gap_filter_max_overshoot_R": GAP_FILTER_MAX,
            "train_end": str(TRAIN_END.date()),
            "holdout_start": str(HOLDOUT_START.date()),
            "publishable_min_n": PUBLISHABLE_MIN_N,
            "publishable_min_rr_to_t2": PUBLISHABLE_MIN_RR,
            "strong_candidate_min_t2_pct": STRONG_CANDIDATE_MIN_T2,
            "strong_candidate_holdout_ratio": STRONG_CANDIDATE_HOLDOUT_RATIO,
            "atr_caveat": ("box_width_atr uses atr14_at_break (event-time, includes break bar's TR);"
                           " no future bars used, but not strictly prior."),
            "close_confirm_definition": ("Strict: only events whose break candle itself closed"
                                         " beyond the boundary, i.e. close_outside_entry_ts == break_bar_ts."),
        },
        "atr_thresholds_q25": all_thresholds,
        "rows": all_rows,
    }
    with open(JSON_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved summary → {JSON_PATH}")
    print("\nDone.")


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
