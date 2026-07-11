"""
ES 3m Compression Drift -> Strategy layer
=========================================

Turns the event-study edges from backtest_es_po_comp_drift.py into simulated
trades with realistic execution, to see what survives friction.

SIGNALS (all live-knowable: compression flag + episode class are known at the
expansion bar's close; entry is next bar's open, same session only):
  flat_break     : flat episode -> LONG/SHORT in expansion direction
  aligned_cont   : drift episode, expansion aligned with drift -> with expansion
  antidrift_fade : drift episode, expansion OPPOSED to drift -> enter in the
                   DRIFT direction (fade the expansion print)
  antidrift_fade_cc : same but opposition defined by expansion candle color
                   (close<open against an up-drift, or close>open against a
                   down-drift) — the more robust definition from the study.

EXITS (grid):
  fix1/fix3/fix5/fix10/fix20 : exit at close k bars after entry (or EOD)
  eod                        : hold to last bar close of the session
  brk10                      : stop 1.0 ATR adverse, else EOD
  tp10sl10                   : target +1.0 ATR / stop -1.0 ATR, else EOD
  trail10                    : 1.0 ATR trailing stop from best price, else EOD
Conservative fills: if a bar could hit both stop and target, stop fills first;
stop checked against the bar's extreme before the trail is ratcheted.

COSTS: 0.31 ES points round trip (1 tick slippage + ~$3 commission at $50/pt),
same as backtest_es_cbc_scalp.py. $ figures at $50/pt (1 ES contract).

Output: analyst/es_po_comp_drift_strategy.csv + console summary.
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_es_po_comp_drift import load_3m, add_indicators

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EV_CSV = os.path.join(BASE_DIR, "analyst", "es_po_comp_drift_events.csv")
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_po_comp_drift_strategy.csv")

COST_PTS = 0.31
DOLLARS_PER_PT = 50.0
EXITS = ["fix1", "fix3", "fix5", "fix10", "fix20", "eod",
         "brk10", "tp10sl10", "trail10"]


def simulate_exit(o, h, l, c, i_entry, day_end, direction, atr, mode):
    """Entry at o[i_entry] in `direction` (+1/-1). day_end = last bar index of
    session (inclusive). Returns (exit_px, bars_held) or None if no bar."""
    entry = o[i_entry]
    # work in direction-signed space
    sgn = direction
    stop = target = None
    if mode == "brk10":
        stop = entry - sgn * 1.0 * atr
    elif mode == "tp10sl10":
        stop = entry - sgn * 1.0 * atr
        target = entry + sgn * 1.0 * atr
    elif mode == "trail10":
        stop = entry - sgn * 1.0 * atr
    fix_k = int(mode[3:]) if mode.startswith("fix") else None

    best = entry
    for j in range(i_entry, day_end + 1):
        # intrabar stop (checked first, conservative)
        if stop is not None:
            hit = l[j] <= stop if sgn == 1 else h[j] >= stop
            if hit:
                # gap through stop -> open fill
                fill = stop
                if (sgn == 1 and o[j] < stop) or (sgn == -1 and o[j] > stop):
                    fill = o[j]
                return fill, j - i_entry
        if target is not None:
            hit = h[j] >= target if sgn == 1 else l[j] <= target
            if hit:
                return target, j - i_entry
        if fix_k is not None and j - i_entry >= fix_k:
            # exit at close of the k-th bar after entry bar's open
            return c[j], j - i_entry
        if j == day_end:
            return c[j], j - i_entry
        if mode == "trail10":
            ext = h[j] if sgn == 1 else l[j]
            if (sgn == 1 and ext > best) or (sgn == -1 and ext < best):
                best = ext
                new_stop = best - sgn * 1.0 * atr
                if (sgn == 1 and new_stop > stop) or (sgn == -1 and new_stop < stop):
                    stop = new_stop
    return None


def summarize(pnl_pts, years):
    pnl = np.asarray(pnl_pts)
    net = pnl - COST_PTS
    n = len(net)
    if n < 10:
        return None
    t = net.mean() / (net.std(ddof=1) / np.sqrt(n)) if net.std(ddof=1) > 0 else np.nan
    yrs = np.asarray(years)
    yr_tot = {int(y): net[yrs == y].sum() for y in np.unique(yrs)}
    yv = np.array(list(yr_tot.values()))
    cum = np.cumsum(net)
    dd = float((np.maximum.accumulate(cum) - cum).max())
    half = len(net) // 2
    return {
        "n": n,
        "trades_yr": round(n / max(1, len(yv)), 1),
        "avg_gross_pts": round(float(pnl.mean()), 3),
        "avg_net_pts": round(float(net.mean()), 3),
        "avg_net_usd": round(float(net.mean()) * DOLLARS_PER_PT, 2),
        "win_pct": round(float((net > 0).mean()) * 100, 1),
        "t_stat": round(float(t), 2),
        "total_net_pts": round(float(net.sum()), 1),
        "max_dd_pts": round(dd, 1),
        "pos_years_pct": round(float((yv > 0).mean()) * 100, 0),
        "net_1st_half": round(float(net[:half].mean()), 3),
        "net_2nd_half": round(float(net[half:].mean()), 3),
    }


def main():
    print("loading bars...")
    tf = load_3m()
    tf = add_indicators(tf)
    tf["date"] = tf.index.date
    o = tf["o"].values; h = tf["h"].values
    l = tf["l"].values; c = tf["c"].values
    dates = tf["date"].values
    pos = {ts: i for i, ts in enumerate(tf.index)}
    # last bar index of each session
    day_end_map = {}
    for d, gi in pd.Series(range(len(tf)), index=dates).groupby(level=0):
        day_end_map[d] = int(gi.iloc[-1])

    ev = pd.read_csv(EV_CSV, parse_dates=["exp_ts"])
    ev["year"] = ev["exp_ts"].dt.year
    ev["drift_dir"] = np.where(ev["cls"] == "drift_up", 1,
                       np.where(ev["cls"] == "drift_dn", -1, 0))

    signals = {
        "flat_break": (ev["cls"] == "flat", "sign"),
        "aligned_cont": (ev["align"] == "aligned", "sign"),
        "antidrift_fade": (ev["align"] == "opposed", "drift_dir"),
        "antidrift_fade_cc": (
            (ev["drift_dir"] != 0) & (ev["dir_candle"] != 0)
            & (ev["dir_candle"] == -ev["drift_dir"]), "drift_dir"),
    }

    rows = []
    trade_logs = {}
    for sig_name, (mask, dir_col) in signals.items():
        sub = ev[mask]
        for mode in EXITS:
            pnls, yrs, held = [], [], []
            for _, e in sub.iterrows():
                i = pos.get(e["exp_ts"])
                if i is None:
                    continue
                d0 = dates[i]
                day_end = day_end_map[d0]
                if i + 1 > day_end:      # no bar after expansion bar
                    continue
                direction = int(e[dir_col])
                if direction == 0:
                    continue
                res = simulate_exit(o, h, l, c, i + 1, day_end,
                                    direction, e["atr"], mode)
                if res is None:
                    continue
                exit_px, nb = res
                pnls.append(direction * (exit_px - o[i + 1]))
                yrs.append(e["year"])
                held.append(nb)
            s = summarize(pnls, yrs)
            if s is None:
                continue
            s["avg_bars_held"] = round(float(np.mean(held)), 1)
            rows.append({"signal": sig_name, "exit": mode, **s})
            trade_logs[(sig_name, mode)] = (np.array(pnls) - COST_PTS,
                                            np.array(yrs))

    res = pd.DataFrame(rows)
    res.to_csv(OUT_CSV, index=False)
    pd.set_option("display.width", 250)
    cols = ["signal", "exit", "n", "trades_yr", "avg_bars_held",
            "avg_gross_pts", "avg_net_pts", "avg_net_usd", "win_pct",
            "t_stat", "total_net_pts", "max_dd_pts", "pos_years_pct",
            "net_1st_half", "net_2nd_half"]

    for sig in signals:
        print(f"\n=== {sig} ===")
        print(res[res.signal == sig][cols[1:]].to_string(index=False))

    print("\n=== ALL configs with avg_net_pts > 0, by t_stat ===")
    pos_res = res[res.avg_net_pts > 0].sort_values("t_stat", ascending=False)
    print(pos_res[cols].to_string(index=False) if len(pos_res) else "  (none)")

    # yearly P&L for the best net config, if any
    if len(pos_res):
        best = pos_res.iloc[0]
        key = (best["signal"], best["exit"])
        net, yrs = trade_logs[key]
        print(f"\n=== yearly net pts: {key[0]} / {key[1]} ===")
        for y in np.unique(yrs):
            m = yrs == y
            print(f"  {y}: {net[m].sum():+8.1f} pts over {m.sum()} trades")

    print(f"\nwrote {len(res)} configs -> {OUT_CSV}")


if __name__ == "__main__":
    main()
