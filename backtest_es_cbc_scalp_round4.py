"""
CBC scalp round 4: tune the surviving candidate on the last 5 years.

Fixed core (the round-3 survivor):
  10m LONG CBC confirm (close > prior 10m high, EMA8>EMA21 ribbon on 10m),
  pullback entry filled on 1-min data, morning signals only, flat EOD,
  one position at a time, costs 0.31 pts RT, conservative stop-first fills.

Sample: signals from 2021-01-01 -> 2026-01-23 (~5.05y, indicators warmed up
on full history).

Tuning grid:
  entry  : ema9_touch | ema13_touch | ema21_touch | ema9_reclaim
           | limit_2pt | limit_0.30atr
           (reclaim = touch EMA then 1m close back above it; fill at that close)
  stop   : candle_low | 1.0 / 1.5 / 2.0 x ATR(10m)
  exit   : trail@0.5R | trail@1R | trail@1.5R
           | trail@1R + target 2R | trail@1R + target 3R
           | breakeven@1R + close-against
  window : 20 min order validity (10/30 sensitivity on the winner)
  tod    : signals 09:30-11:00 (variants on the winner)

Output: analyst/es_cbc_scalp_round4.csv + winner sensitivity tables.
"""

import os
import numpy as np
import pandas as pd

from backtest_es_cbc_scalp import load_minute, TICK, COST_PTS, NO_ENTRY_LAST_N
from backtest_es_cbc_scalp_round3 import build_arrays

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_cbc_scalp_round4.csv")

START_YEAR = 2021
PT_VALUE = 50.0
YEARS_SPAN = 5.05
# Absolute take-profit cap in ES points, applied on top of any R-target/trail
# (exit at entry + TAKE_PROFIT_PTS as soon as touched). None = uncapped.
TAKE_PROFIT_PTS = None

ENTRIES = ["ema9_touch", "ema13_touch", "ema21_touch", "ema9_reclaim",
           "limit_2pt", "limit_0.30atr"]
STOPS = ["candle_low", "atr_1.0", "atr_1.5", "atr_2.0"]
EXITS = ["trail_0.5r", "trail_1r", "trail_1.5r",
         "trail_1r_tgt2r", "trail_1r_tgt3r", "be_1r_closeagainst"]


def parse_exit(exit_mode):
    if exit_mode.startswith("trail_") and "tgt" not in exit_mode:
        return float(exit_mode.split("_")[1][:-1]), None, False
    if exit_mode == "trail_1r_tgt2r":
        return 1.0, 2.0, False
    if exit_mode == "trail_1r_tgt3r":
        return 1.0, 3.0, False
    return 1.0, None, True   # be_1r_closeagainst


def try_fill4(arr, sig_i, entry_mode, sig_close, sig_low, atr_val, window_min):
    o1, h1, l1, c1 = arr["o1"], arr["h1"], arr["l1"], arr["c1"]
    ends, day = arr["ends"], arr["day"]
    start = ends[sig_i]
    stop_scan = min(start + window_min, arr["n1"])

    limit = None
    ema = None
    if entry_mode == "limit_2pt":
        limit = sig_close - 2.0
    elif entry_mode == "limit_0.30atr":
        limit = sig_close - 0.30 * atr_val
    else:
        span = int(entry_mode.split("_")[0][3:])
        ema = arr["ema1"][span]
    reclaim = entry_mode.endswith("reclaim")

    touched = False
    for k in range(start, stop_scan):
        lvl = limit if limit is not None else ema[k]
        if not reclaim:
            if l1[k] <= lvl:
                return min(o1[k], lvl), k
            if c1[k] < sig_low:
                return None
        else:
            if not touched:
                if l1[k] <= lvl:
                    touched = True
                    # same-minute reclaim allowed
                    if c1[k] > lvl and c1[k] >= sig_low:
                        return c1[k], k
                if c1[k] < sig_low:
                    return None
            else:
                if c1[k] < sig_low:
                    return None
                if c1[k] > ema[k]:
                    return c1[k], k
    return None


def bar_of_minute(arr, k, sig_i):
    """10m bar index containing 1m position k (search forward from sig_i)."""
    starts = arr["starts"]
    j = sig_i
    n = arr["n"]
    while j + 1 < n and starts[j + 1] <= k:
        j += 1
    return j


def simulate4(arr, entry_mode, stop_mode, exit_mode,
              window_min=20, tod_lo=570, tod_hi=660):
    o10, h10, l10, c10 = arr["o10"], arr["h10"], arr["l10"], arr["c10"]
    e8, e21 = arr["e8"], arr["e21_10"]
    atr = arr["atr"]
    day, bars_left, pos_in_day = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]
    l1, h1, ends = arr["l1"], arr["h1"], arr["ends"]

    trail_act, target_r, be_mode = parse_exit(exit_mode)

    trades = []
    n_signals = 0
    busy_until = -1

    for i in range(n):
        if year[i] < START_YEAR or i <= busy_until:
            continue
        if pos_in_day[i] < 1 or bars_left[i] <= NO_ENTRY_LAST_N:
            continue
        if not (tod_lo <= mod[i] < tod_hi):
            continue
        if not (c10[i] > h10[i - 1] and e8[i] > e21[i]):
            continue
        n_signals += 1
        sig_close, sig_low, atr_val = c10[i], l10[i], atr[i]

        res = try_fill4(arr, i, entry_mode, sig_close, sig_low, atr_val,
                        window_min)
        if res is None:
            continue
        entry_px, fill_k = res
        entry_bar = bar_of_minute(arr, fill_k, i)
        if day[entry_bar] != day[i]:
            continue

        if stop_mode == "candle_low":
            stop = sig_low - TICK
        else:
            stop = entry_px - float(stop_mode.split("_")[1]) * atr_val
        risk = entry_px - stop
        if risk < TICK:
            continue
        target = entry_px + target_r * risk if target_r else None
        if TAKE_PROFIT_PTS is not None:
            tp = entry_px + TAKE_PROFIT_PTS
            target = tp if target is None else min(target, tp)

        # --- remainder of entry 10m bar on 1m data (stop first, then target)
        pnl = None
        for k in range(fill_k, ends[entry_bar]):
            if l1[k] <= stop:
                pnl = stop - entry_px
                break
            if target is not None and h1[k] >= target:
                pnl = target - entry_px
                break
        if pnl is None and bars_left[entry_bar] == 1:
            pnl = c10[entry_bar] - entry_px
        if pnl is not None:
            trades.append((year[entry_bar], mod[i], pnl, risk, 0))
            busy_until = entry_bar
            continue

        trail_on = False
        if c10[entry_bar] >= entry_px + trail_act * risk:
            trail_on = True
            if be_mode:
                if entry_px + TICK > stop:
                    stop = entry_px + TICK
            elif l10[entry_bar] > stop:
                stop = l10[entry_bar]

        j = entry_bar + 1
        while True:
            if l10[j] <= stop:
                fill = stop if o10[j] > stop else o10[j]
                trades.append((year[j], mod[i], fill - entry_px, risk,
                               j - entry_bar))
                break
            if target is not None and h10[j] >= target:
                trades.append((year[j], mod[i], target - entry_px, risk,
                               j - entry_bar))
                break
            if be_mode and c10[j] < l10[j - 1]:
                trades.append((year[j], mod[i], c10[j] - entry_px, risk,
                               j - entry_bar))
                break
            if bars_left[j] == 1:
                trades.append((year[j], mod[i], c10[j] - entry_px, risk,
                               j - entry_bar))
                break
            if not trail_on and c10[j] >= entry_px + trail_act * risk:
                trail_on = True
                if be_mode and entry_px + TICK > stop:
                    stop = entry_px + TICK
            if trail_on and not be_mode and l10[j] > stop:
                stop = l10[j]
            j += 1
        busy_until = j
    return trades, n_signals


def summarize4(trades, n_signals):
    if len(trades) < 60:
        return None
    a = np.array(trades)
    pnl, risk = a[:, 2], a[:, 3]
    net_pts = pnl - COST_PTS
    net_r = net_pts / risk
    years = a[:, 0].astype(int)
    uy = np.unique(years)
    yr_r = {int(y): round(float(net_r[years == y].sum()), 1) for y in uy}
    cum = np.cumsum(net_r)
    peak = np.maximum.accumulate(cum)
    maxdd = float((peak - cum).max())
    pos = net_r[net_r > 0].sum()
    neg = -net_r[net_r < 0].sum()
    t = float(net_r.mean() / (net_r.std(ddof=1) / np.sqrt(len(net_r)))) \
        if net_r.std(ddof=1) > 0 else np.nan
    return {
        "n_signals": n_signals,
        "n_trades": len(trades),
        "fill_pct": round(100 * len(trades) / n_signals, 1) if n_signals else 0,
        "trades_per_wk": round(len(trades) / (YEARS_SPAN * 52), 2),
        "win_rate": round(float((net_pts > 0).mean()) * 100, 1),
        "avg_risk_pts": round(float(risk.mean()), 2),
        "avg_net_pts": round(float(net_pts.mean()), 3),
        "avg_r_net": round(float(net_r.mean()), 4),
        "total_r_net": round(float(net_r.sum()), 1),
        "pf_net": round(float(pos / neg), 3) if neg > 0 else np.inf,
        "t_stat": round(t, 2),
        "max_dd_r": round(maxdd, 1),
        "ann_usd_1lot": int(net_pts.sum() * PT_VALUE / YEARS_SPAN),
        "yr_r": yr_r,
    }


def main():
    print("loading...")
    df1m = load_minute()
    arr = build_arrays(df1m, "long")

    rows = []
    for entry in ENTRIES:
        for stop_mode in STOPS:
            for exit_mode in EXITS:
                trades, n_sig = simulate4(arr, entry, stop_mode, exit_mode)
                s = summarize4(trades, n_sig)
                if s:
                    yr = s.pop("yr_r")
                    rows.append({"entry": entry, "stop": stop_mode,
                                 "exit": exit_mode, **s,
                                 **{f"r{y}": v for y, v in yr.items()}})
        print(f"done {entry}")

    res = pd.DataFrame(rows)
    res.to_csv(OUT_CSV, index=False)
    print(f"wrote {len(res)} configs -> {OUT_CSV}")

    pd.set_option("display.width", 300)
    cols = [c for c in res.columns]
    print("\n=== TOP 25 by avg net R (2021-2026, 09:30-11:00 signals) ===")
    print(res.sort_values("avg_r_net", ascending=False)
          .head(25).to_string(index=False))

    # --- sensitivity on the winner ---
    best = res.sort_values("avg_r_net", ascending=False).iloc[0]
    print(f"\n=== WINNER: {best['entry']} / {best['stop']} / {best['exit']} ===")
    print("\n-- order-window sensitivity --")
    for w in (10, 20, 30, 40):
        trades, n_sig = simulate4(arr, best["entry"], best["stop"],
                                  best["exit"], window_min=w)
        s = summarize4(trades, n_sig)
        if s:
            s.pop("yr_r")
            print(f"window={w:2d}min: " + " ".join(f"{k}={v}" for k, v in s.items()))
    print("\n-- time-of-day sensitivity --")
    for lbl, lo, hi in [("0930-1030", 570, 630), ("0930-1100", 570, 660),
                        ("0940-1100", 580, 660), ("0930-1200", 570, 720),
                        ("all-day", 570, 930)]:
        trades, n_sig = simulate4(arr, best["entry"], best["stop"],
                                  best["exit"], tod_lo=lo, tod_hi=hi)
        s = summarize4(trades, n_sig)
        if s:
            s.pop("yr_r")
            print(f"tod={lbl}: " + " ".join(f"{k}={v}" for k, v in s.items()))
    print("\n-- ribbon-filter check (winner without EMA8>EMA21) --")
    # quick hack: disable ribbon by monkeypatching e8/e21
    saved = arr["e8"]
    arr["e8"] = [x + 1e9 for x in arr["e21_10"]]
    trades, n_sig = simulate4(arr, best["entry"], best["stop"], best["exit"])
    arr["e8"] = saved
    s = summarize4(trades, n_sig)
    if s:
        s.pop("yr_r")
        print("no-ribbon: " + " ".join(f"{k}={v}" for k, v in s.items()))


if __name__ == "__main__":
    main()
