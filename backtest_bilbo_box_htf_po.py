"""
Bilbo Box Breakout × Higher-Timeframe Phase Oscillator
======================================================

WHAT THIS STUDIES
-----------------
Refines the Bilbo Box Breakout study (backtest_bilbo_box.py / studies §15)
by conditioning each break on the higher-timeframe Phase Oscillator state
captured at break time.

Two cuts:
  (1) 3m  bull breaks × latest fully-closed 10m PO  -> long continuation
  (2) 10m bear breaks × latest fully-closed 1h  PO  -> short continuation

For each cut, outcomes are grouped by:
  - state:  bull_exp | bear_exp | compression          (Saty grouping)
  - sign:   PO >= 0  | PO < 0
  - zone:   high (>61.8) | mid | low (<-61.8)
  - slope:  rising | falling
  - state×slope (e.g. bull_exp+rising)

Lookahead-safe: higher-TF timestamps are shifted forward by one bar duration
before merge_asof, so only fully-closed bars are used.

INPUT
-----
analyst/bilbo_box_events.csv produced by backtest_bilbo_box.py

OUTPUT
------
- stdout: tables for each cut
- analyst/bilbo_box_htf_po_summary.json: machine-readable rollup

CAVEAT
------
The 1h PO has a known accuracy gap vs TradingView (median |Δ| ~6 PO points,
~8-13% low bias post-clip; worse on tail bars). Treat 1h state buckets as
roughly correct directionally, not tick-for-tick. See KNOWLEDGE.md §5.
"""

import os
import json
import sqlite3
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy.db")
ANALYST_DIR = os.path.join(BASE_DIR, "analyst")
EVENTS_CSV = os.path.join(ANALYST_DIR, "bilbo_box_events.csv")

WINDOWS = [5, 10, 15]
MAIN_W = 10
MIN_REPORT = 20
FLAG_SAMPLE = 50


# ───────────────────────── classification ─────────────────────────

def classify(po, po_prev, compression):
    """Saty-style classification used in backtest_gg_with_po.py."""
    if compression == 1:
        state = "compression"
    elif po >= 0:
        state = "bull_exp"
    else:
        state = "bear_exp"
    sign  = "PO>=0" if po >= 0 else "PO<0"
    zone  = "high" if po > 61.8 else ("low" if po < -61.8 else "mid")
    slope = "rising" if (pd.notna(po_prev) and po > po_prev) else "falling"
    return state, sign, zone, slope


# ───────────────────────── data plumbing ─────────────────────────

def load_higher_tf_po(conn, table, bar_minutes):
    """Load PO + compression with timestamps shifted forward by bar duration so
    a backward merge_asof returns only bars that fully closed before lookup."""
    df = pd.read_sql_query(
        f"SELECT timestamp, phase_oscillator, compression FROM {table} ORDER BY timestamp",
        conn, parse_dates=["timestamp"]
    )
    df = df.dropna(subset=["phase_oscillator"])
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
    ev[f"po_{suffix}"]      = merged["phase_oscillator"].values
    ev[f"po_prev_{suffix}"] = merged["po_prev"].values
    ev[f"comp_{suffix}"]    = merged["compression"].values

    cls = [classify(p, pp, c) for p, pp, c in zip(
        ev[f"po_{suffix}"], ev[f"po_prev_{suffix}"], ev[f"comp_{suffix}"]
    )]
    ev[f"state_{suffix}"] = [c[0] for c in cls]
    ev[f"sign_{suffix}"]  = [c[1] for c in cls]
    ev[f"zone_{suffix}"]  = [c[2] for c in cls]
    ev[f"slope_{suffix}"] = [c[3] for c in cls]
    ev[f"state_slope_{suffix}"] = ev[f"state_{suffix}"] + "+" + ev[f"slope_{suffix}"]
    return ev


# ───────────────────────── stats ─────────────────────────

def stats_for(ev, variant="immediate", window=MAIN_W):
    if len(ev) == 0:
        return {"n": 0}
    fired = ev[f"{variant}_fired"].fillna(False).astype(bool)
    valid = ev[f"{variant}_w{window}_valid"].fillna(False).astype(bool) & fired
    elig  = ev[valid]
    n = len(elig)
    if n == 0:
        return {"n": 0, "trigger_rate": float(fired.sum() / len(ev))}

    R = elig["box_width_pts"].astype(float)
    net = elig[f"{variant}_w{window}_net_pts"].astype(float)
    mfe = elig[f"{variant}_w{window}_mfe_pts"].astype(float)
    mae = elig[f"{variant}_w{window}_mae_pts"].astype(float)
    stp = elig[f"{variant}_w{window}_stopped_out"].fillna(False).astype(bool)

    net_R = (net / R).replace([np.inf, -np.inf], np.nan)
    mfe_R = (mfe / R).replace([np.inf, -np.inf], np.nan)
    mae_R = (mae / R).replace([np.inf, -np.inf], np.nan)

    return {
        "n": int(n),
        "total": int(len(ev)),
        "trigger_rate": float(fired.sum() / len(ev)),
        "net_R_median": float(net_R.median()),
        "net_R_mean":   float(net_R.mean()),
        "mfe_R_median": float(mfe_R.median()),
        "mae_R_median": float(mae_R.median()),
        "net_pts_median": float(net.median()),
        "net_positive_rate": float((net > 0).sum() / n),
        "stopped_out_rate": float(stp.sum() / n),
    }


def print_row(label, s, indent="  "):
    if s["n"] < MIN_REPORT:
        print(f"{indent}{label:24s} {s['n']:>6d}   — insufficient sample —")
        return
    flag = " *" if s["n"] < FLAG_SAMPLE else ""
    print(f"{indent}{label:24s} {s['n']:>6d} {s['trigger_rate']*100:>6.1f}% "
          f"{s['net_R_median']:>9.3f} {s['net_R_mean']:>9.3f} "
          f"{s['mfe_R_median']:>7.2f} {s['mae_R_median']:>7.2f} "
          f"{s['net_positive_rate']*100:>6.1f}% "
          f"{s['stopped_out_rate']*100:>6.1f}%{flag}")


def print_header(title, indent="  "):
    print(f"\n{indent}{title}")
    print(f"{indent}{'Bucket':24s} {'n':>6s} {'Trig%':>7s} "
          f"{'Net_R med':>9s} {'Net_R avg':>9s} "
          f"{'MFE_R':>7s} {'MAE_R':>7s} {'Net+%':>7s} {'Stop%':>7s}")
    print(f"{indent}{'-'*97}")


# ───────────────────────── per-cut report ─────────────────────────

def run_cut(events_dir, suffix, htf_label, direction_label):
    print("\n" + "=" * 97)
    print(f"  {direction_label}  ×  {htf_label} Phase Oscillator")
    print("=" * 97)

    # PO availability
    have_po = events_dir[f"po_{suffix}"].notna()
    n_drop = int((~have_po).sum())
    if n_drop:
        print(f"  Dropped {n_drop} events with no fully-closed {htf_label} PO at break time")
    ev = events_dir[have_po].copy()

    summary = {"htf": htf_label, "direction": direction_label,
               "n_total": int(len(ev)),
               "windows": {}}

    # ── Universe baseline (all breaks in this direction) ──
    print_header(f"BASELINE — all {direction_label} breaks (immediate variant)")
    for w in WINDOWS:
        s = stats_for(ev, "immediate", w)
        print_row(f"w={w}", s)
        summary["windows"][f"w{w}_baseline"] = s

    # ── Group by state ──
    print_header(f"BY STATE (immediate, w={MAIN_W})")
    state_summary = {}
    for st in ["bull_exp", "bear_exp", "compression"]:
        mask = ev[f"state_{suffix}"] == st
        s = stats_for(ev[mask], "immediate", MAIN_W)
        print_row(st, s)
        state_summary[st] = s
    summary["by_state"] = state_summary

    # ── Group by sign ──
    print_header(f"BY SIGN (immediate, w={MAIN_W})")
    sign_summary = {}
    for sg in ["PO>=0", "PO<0"]:
        mask = ev[f"sign_{suffix}"] == sg
        s = stats_for(ev[mask], "immediate", MAIN_W)
        print_row(sg, s)
        sign_summary[sg] = s
    summary["by_sign"] = sign_summary

    # ── Group by zone ──
    print_header(f"BY ZONE (immediate, w={MAIN_W})")
    zone_summary = {}
    for z in ["high", "mid", "low"]:
        mask = ev[f"zone_{suffix}"] == z
        s = stats_for(ev[mask], "immediate", MAIN_W)
        print_row(z, s)
        zone_summary[z] = s
    summary["by_zone"] = zone_summary

    # ── Group by slope ──
    print_header(f"BY SLOPE (immediate, w={MAIN_W})")
    slope_summary = {}
    for sl in ["rising", "falling"]:
        mask = ev[f"slope_{suffix}"] == sl
        s = stats_for(ev[mask], "immediate", MAIN_W)
        print_row(sl, s)
        slope_summary[sl] = s
    summary["by_slope"] = slope_summary

    # ── State × slope combos ──
    print_header(f"BY STATE × SLOPE (immediate, w={MAIN_W})")
    combo_summary = {}
    for st in ["bull_exp", "bear_exp", "compression"]:
        for sl in ["rising", "falling"]:
            key = f"{st}+{sl}"
            mask = ev[f"state_slope_{suffix}"] == key
            s = stats_for(ev[mask], "immediate", MAIN_W)
            print_row(key, s)
            combo_summary[key] = s
    summary["by_state_slope"] = combo_summary

    # ── Cross-window for the headline state ──
    headline_state = "bull_exp" if "bull" in direction_label.lower() else "bear_exp"
    print_header(f"HEADLINE STATE = {headline_state}: 5/10/15-bar outcomes")
    head_mask = ev[f"state_{suffix}"] == headline_state
    head = ev[head_mask]
    headline_w = {}
    for w in WINDOWS:
        s = stats_for(head, "immediate", w)
        print_row(f"w={w}", s)
        headline_w[f"w{w}"] = s
    summary["headline_state_windows"] = {"state": headline_state, **headline_w}

    return summary


def main():
    if not os.path.exists(EVENTS_CSV):
        raise SystemExit(f"Missing events CSV: {EVENTS_CSV}.\n"
                         f"Run backtest_bilbo_box.py first to produce it.")

    print(f"Loading events from {EVENTS_CSV}...")
    ev_all = pd.read_csv(EVENTS_CSV, parse_dates=["break_bar_ts"], low_memory=False)
    print(f"  {len(ev_all):,} total events across all timeframes")

    conn = sqlite3.connect(DB_PATH)

    # ──────────── CUT 1: 3m bull breaks × 10m PO ────────────
    ev_3m_bull = ev_all[(ev_all["timeframe"] == "3m")
                        & (ev_all["direction"] == "bull")
                        & (~ev_all["ambiguous_outside"].astype(bool))].copy()
    print(f"\nCut 1 universe: {len(ev_3m_bull):,} clean 3m bull breaks")
    po_10m = load_higher_tf_po(conn, "ind_10m", bar_minutes=10)
    ev_3m_bull = attach_po(ev_3m_bull, po_10m, suffix="10m")
    summary_1 = run_cut(ev_3m_bull, suffix="10m",
                        htf_label="10m",
                        direction_label="3m BULL Bilbo breaks")

    # ──────────── CUT 2: 10m bear breaks × 1h PO ────────────
    ev_10m_bear = ev_all[(ev_all["timeframe"] == "10m")
                         & (ev_all["direction"] == "bear")
                         & (~ev_all["ambiguous_outside"].astype(bool))].copy()
    print(f"\nCut 2 universe: {len(ev_10m_bear):,} clean 10m bear breaks")
    po_1h = load_higher_tf_po(conn, "ind_1h", bar_minutes=60)
    ev_10m_bear = attach_po(ev_10m_bear, po_1h, suffix="1h")
    summary_2 = run_cut(ev_10m_bear, suffix="1h",
                        htf_label="1h",
                        direction_label="10m BEAR Bilbo breaks")

    conn.close()

    # ──────────── Persist ────────────
    out = {
        "study": "bilbo_box_htf_po",
        "windows": WINDOWS,
        "min_report": MIN_REPORT,
        "flag_sample": FLAG_SAMPLE,
        "cuts": {
            "3m_bull_x_10m_po": summary_1,
            "10m_bear_x_1h_po": summary_2,
        },
    }
    out_path = os.path.join(ANALYST_DIR, "bilbo_box_htf_po_summary.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved summary → {out_path}")

    # ──────────── Compact takeaway block ────────────
    print("\n" + "=" * 97)
    print("  COMPACT TAKEAWAY (immediate variant, R = box width)")
    print("=" * 97)
    for cut_name, cut in [("3m bull × 10m PO", summary_1),
                          ("10m bear × 1h PO", summary_2)]:
        base = cut["windows"][f"w{MAIN_W}_baseline"]
        head = cut["headline_state_windows"][f"w{MAIN_W}"]
        if base["n"] >= MIN_REPORT and head["n"] >= MIN_REPORT:
            d_net   = head["net_R_median"]      - base["net_R_median"]
            d_pos   = head["net_positive_rate"] - base["net_positive_rate"]
            d_stop  = head["stopped_out_rate"]  - base["stopped_out_rate"]
            print(f"  {cut_name:25s}  baseline n={base['n']:>5d} "
                  f"NetR_med={base['net_R_median']:+.3f} Net+%={base['net_positive_rate']*100:5.1f}% "
                  f"Stop%={base['stopped_out_rate']*100:5.1f}%")
            print(f"  {'  → ' + cut['headline_state_windows']['state']:25s}  filter   n={head['n']:>5d} "
                  f"NetR_med={head['net_R_median']:+.3f} Net+%={head['net_positive_rate']*100:5.1f}% "
                  f"Stop%={head['stopped_out_rate']*100:5.1f}%   "
                  f"Δ NetR={d_net:+.3f}  Δ Net+%={d_pos*100:+.1f}pp  Δ Stop%={d_stop*100:+.1f}pp")

    print("\nDone.")


if __name__ == "__main__":
    main()
