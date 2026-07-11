"""
CBC scalp round 2: targeted variants + time-of-day drill-down.

Round 1 (backtest_es_cbc_scalp.py) found: all 256 configs negative net of costs.
Best family: 10m close_confirm + ribbon + wide ATR stop + trail-after-1R.
Round 2 tests the variants scalpers actually lean on:
  - time-of-day buckets (is there a profitable window?)
  - pullback entry (signal only after a touch of EMA8 in the last 3 bars)
  - two consecutive directional candles entry
  - HTF filter for 3m entries (10m ribbon aligned)
  - breakeven-after-1R exit (let winners run to close_against / EOD)
Same conservative fills and 0.31 pt RT cost as round 1.
"""

import os
import numpy as np
import pandas as pd

from backtest_es_cbc_scalp import (
    load_minute, build_tf, prep_arrays, init_risk,
    TICK, COST_PTS, NO_ENTRY_LAST_N, WARMUP_BARS,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_TRADES = os.path.join(BASE_DIR, "analyst", "es_cbc_scalp_round2_trades.csv")
OUT_SUMMARY = os.path.join(BASE_DIR, "analyst", "es_cbc_scalp_round2.csv")


def simulate2(arr, entry_mode, exit_mode, stop_mode, htf_ok=None):
    """close_confirm-style entries only (best round-1 family), extended.

    entry_mode: confirm | pullback | two_consec
    exit_mode : cbc_after_1r | close_against | be_after_1r
    All entries require ribbon (e8 > e21) at signal close.
    htf_ok: optional list of bools per bar (higher-TF alignment at signal).
    """
    o, h, l, c = arr["o"], arr["h"], arr["l"], arr["c"]
    e8, e21, atr = arr["e8"], arr["e21"], arr["atr"]
    day, bars_left, pos_in_day = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]

    trades = []
    in_pos = False
    pending = False
    pend_low = 0.0
    entry_px = stop = risk = 0.0
    trail_on = False
    entry_i = 0

    i = WARMUP_BARS
    while i < n:
        if in_pos:
            exited = False
            pnl = 0.0
            if l[i] <= stop:
                fill = stop if o[i] > stop else o[i]
                pnl = fill - entry_px
                exited = True
            elif exit_mode in ("close_against", "be_after_1r") \
                    and pos_in_day[i] > 0 and c[i] < l[i - 1]:
                pnl = c[i] - entry_px
                exited = True
            elif bars_left[i] == 1:
                pnl = c[i] - entry_px
                exited = True
            if exited:
                trades.append((year[entry_i], mod[entry_i], pnl, risk, i - entry_i))
                in_pos = False
                i += 1
                continue
            if exit_mode == "cbc_after_1r":
                if not trail_on and c[i] >= entry_px + risk:
                    trail_on = True
                if trail_on and l[i] > stop:
                    stop = l[i]
            elif exit_mode == "be_after_1r":
                if not trail_on and c[i] >= entry_px + risk:
                    trail_on = True
                    if entry_px + TICK > stop:
                        stop = entry_px + TICK
            i += 1
            continue

        if pending:
            pending = False
            entry_px = o[i]
            entry_i = i
            stop, risk, _tgt, trail_on, ok = init_risk(
                entry_px, pend_low, atr[i - 1], stop_mode, "x")
            if ok:
                if l[i] <= stop:
                    fill = stop if o[i] > stop else o[i]
                    trades.append((year[i], mod[i], fill - entry_px, risk, 0))
                else:
                    in_pos = True
                    if exit_mode == "cbc_after_1r" and c[i] >= entry_px + risk:
                        trail_on = True
                        if l[i] > stop:
                            stop = l[i]
                    elif exit_mode == "be_after_1r" and c[i] >= entry_px + risk:
                        trail_on = True
                        if entry_px + TICK > stop:
                            stop = entry_px + TICK
            i += 1
            continue

        if pos_in_day[i] < 3 or bars_left[i] <= NO_ENTRY_LAST_N:
            i += 1
            continue

        sig = False
        if e8[i] > e21[i] and (htf_ok is None or htf_ok[i]):
            if entry_mode == "confirm":
                sig = c[i] > h[i - 1]
            elif entry_mode == "pullback":
                touched = (l[i] <= e8[i] or l[i - 1] <= e8[i - 1]
                           or l[i - 2] <= e8[i - 2])
                sig = touched and c[i] > h[i - 1]
            elif entry_mode == "two_consec":
                sig = c[i] > o[i] and c[i - 1] > o[i - 1] and c[i] > c[i - 1]
        if sig and bars_left[i] > 1:
            pending = True
            pend_low = l[i]
        i += 1

    return trades


def summarize(trades, n_days, tod_lo=None, tod_hi=None):
    if not trades:
        return None
    a = np.array(trades, dtype=float)
    if tod_lo is not None:
        m = (a[:, 1] >= tod_lo) & (a[:, 1] < tod_hi)
        a = a[m]
        if len(a) < 100:
            return None
    pnl, risk = a[:, 2], a[:, 3]
    net_r = (pnl - COST_PTS) / risk
    gross_r = pnl / risk
    years = a[:, 0].astype(int)
    yr_vals = np.array([net_r[years == y].sum() for y in np.unique(years)])
    pos = net_r[net_r > 0].sum()
    neg = -net_r[net_r < 0].sum()
    t = float(net_r.mean() / (net_r.std(ddof=1) / np.sqrt(len(net_r)))) \
        if len(net_r) > 2 and net_r.std(ddof=1) > 0 else np.nan
    return {
        "n_trades": len(a),
        "win_rate": round(float(((pnl - COST_PTS) > 0).mean()) * 100, 1),
        "avg_r_gross": round(float(gross_r.mean()), 4),
        "avg_r_net": round(float(net_r.mean()), 4),
        "total_r_net": round(float(net_r.sum()), 1),
        "pf_net": round(float(pos / neg), 3) if neg > 0 else np.inf,
        "t_stat": round(t, 2),
        "pos_years_pct": round(float((yr_vals > 0).mean()) * 100, 0),
        "r_2008_2019": round(float(net_r[years <= 2019].sum()), 1),
        "r_2020_2026": round(float(net_r[years >= 2020].sum()), 1),
    }


def main():
    print("loading...")
    df1m = load_minute()
    tf3 = build_tf(df1m, "3min")
    tf10 = build_tf(df1m, "10min")
    n_days = tf10["day_id"].iloc[-1] + 1

    # HTF alignment for 3m bars: 10m ribbon at the last completed 10m bar
    h10 = tf10[["ema8", "ema21"]].shift(1)
    h10.index.name = "ts"
    htf = pd.merge_asof(pd.DataFrame({"ts": tf3.index}),
                        h10.reset_index(), on="ts", direction="backward")
    htf_bull = (htf["ema8"] > htf["ema21"]).tolist()
    htf_bear = (htf["ema8"] < htf["ema21"]).tolist()

    arrs = {
        ("3m", "long"): prep_arrays(tf3, "long"),
        ("3m", "short"): prep_arrays(tf3, "short"),
        ("10m", "long"): prep_arrays(tf10, "long"),
        ("10m", "short"): prep_arrays(tf10, "short"),
    }
    htf_map = {("3m", "long"): htf_bull, ("3m", "short"): htf_bear}

    ENTRIES = ["confirm", "pullback", "two_consec"]
    EXITS = ["cbc_after_1r", "close_against", "be_after_1r"]
    STOPS = ["candle_low", "atr_1.0", "atr_1.5"]

    rows = []
    all_trades = []
    for (tf_name, side), arr in arrs.items():
        for entry in ENTRIES:
            for exit_mode in EXITS:
                for stop_mode in STOPS:
                    for use_htf in ([False, True] if tf_name == "3m" else [False]):
                        htf_ok = htf_map.get((tf_name, side)) if use_htf else None
                        trades = simulate2(arr, entry, exit_mode, stop_mode, htf_ok)
                        tag = dict(tf=tf_name, side=side, entry=entry,
                                   exit=exit_mode, stop=stop_mode,
                                   htf="10m_ribbon" if use_htf else "none")
                        s = summarize(trades, n_days)
                        if s:
                            rows.append({**tag, "tod": "all", **s})
                        # time-of-day buckets (ET minutes): open 9:30-11:00,
                        # midday 11:00-14:00, late 14:00-15:30
                        for lbl, lo, hi in [("0930-1100", 570, 660),
                                            ("1100-1400", 660, 840),
                                            ("1400-1530", 840, 930)]:
                            sb = summarize(trades, n_days, lo, hi)
                            if sb:
                                rows.append({**tag, "tod": lbl, **sb})
                        for t in trades:
                            all_trades.append((tf_name, side, entry, exit_mode,
                                               stop_mode, tag["htf"], *t))
        print(f"done {tf_name}")

    res = pd.DataFrame(rows)
    res.to_csv(OUT_SUMMARY, index=False)
    print(f"wrote {len(res)} rows -> {OUT_SUMMARY}")

    pd.set_option("display.width", 250)
    cols = ["tf", "side", "entry", "exit", "stop", "htf", "tod", "n_trades",
            "win_rate", "avg_r_gross", "avg_r_net", "total_r_net", "pf_net",
            "t_stat", "pos_years_pct", "r_2008_2019", "r_2020_2026"]

    print("\n=== TOP 20 by avg net R (n >= 300, all buckets) ===")
    top = res[res.n_trades >= 300].sort_values("avg_r_net", ascending=False)
    print(top[cols].head(20).to_string(index=False))

    print("\n=== Any config with avg_r_net > 0? ===")
    posr = res[(res.avg_r_net > 0) & (res.n_trades >= 100)]
    print(posr[cols].to_string(index=False) if len(posr) else "NONE")

    print("\n=== Time-of-day effect, best round-1 family "
          "(10m long confirm cbc_after_1r atr_1.5) ===")
    fam = res[(res.tf == "10m") & (res.side == "long") & (res.entry == "confirm")
              & (res["exit"] == "cbc_after_1r") & (res.stop == "atr_1.5")]
    print(fam[cols].to_string(index=False))


if __name__ == "__main__":
    main()
