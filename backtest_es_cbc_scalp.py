"""
CBC (Candle-by-Candle) scalping grid backtest on ES futures.

Data: FirstRateData ES 1-min continuous ratio-adjusted, 2008-01-02 -> 2026-01-23,
ET wall-clock, period-start timestamps.
/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt

Strategy family (long side described; shorts are mirrored via price negation):
  Entry triggers
    close_confirm : bar closes above prior bar's high -> enter next bar open
    break_stop    : intrabar buy-stop at prior bar high + 1 tick
  Trend filter
    none | ribbon (EMA8 > EMA21 at signal time)
  Exit management
    cbc_trail     : stop ratchets to each completed candle's low
    cbc_after_1r  : initial stop held until a close >= entry+1R, then CBC trail
    close_against : exit on close below prior candle's low (initial stop intrabar)
    target2r_trail: 2R fixed target + CBC trail
  Initial stop
    candle_low | 0.5 ATR | 1.0 ATR | 1.5 ATR   (ATR14 Wilder on same TF, RTH-only)

Sessions: RTH 09:30-15:59 ET bars only, forced flat on last bar of day,
no new entries in the last 3 bars of the day. One position at a time per config.

Conservative fill assumptions:
  - If a bar could hit both stop and target, stop fills first.
  - break_stop entries that see low <= stop in the entry bar are stopped same-bar.
  - Gap through stop -> filled at bar open.
Costs: 0.31 pts round trip (1 tick slippage + ~$3 commission at $50/pt).

Output: analyst/es_cbc_scalp_grid.csv + console summary.
P&L is reported in R (pnl / initial risk) to stay stationary across 18 years.
"""

import os
import itertools
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_cbc_scalp_grid.csv")

TICK = 0.25
COST_PTS = 0.31          # round-trip friction in ES points
NO_ENTRY_LAST_N = 3      # no new entries in last N bars of day
WARMUP_BARS = 60

TIMEFRAMES = {"3m": "3min", "10m": "10min"}
ENTRIES = ["close_confirm", "break_stop"]
FILTERS = ["none", "ribbon"]
EXITS = ["cbc_trail", "cbc_after_1r", "close_against", "target2r_trail"]
STOPS = ["candle_low", "atr_0.5", "atr_1.0", "atr_1.5"]
SIDES = ["long", "short"]


def load_minute():
    df = pd.read_csv(DATA, header=None,
                     names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index()
    df = df.between_time("09:30", "15:59")
    # sanity: drop absurd bars (bad ticks); range > 3% of close
    rng_pct = (df["h"] - df["l"]) / df["c"]
    bad = rng_pct > 0.03
    if bad.any():
        print(f"dropping {bad.sum()} 1-min bars with range > 3% of price")
        df = df[~bad]
    return df


def build_tf(df1m, rule):
    o = df1m["o"].resample(rule, label="left", closed="left").first()
    h = df1m["h"].resample(rule, label="left", closed="left").max()
    l = df1m["l"].resample(rule, label="left", closed="left").min()
    c = df1m["c"].resample(rule, label="left", closed="left").last()
    tf = pd.DataFrame({"o": o, "h": h, "l": l, "c": c}).dropna()

    tf["ema8"] = tf["c"].ewm(span=8, adjust=False).mean()
    tf["ema21"] = tf["c"].ewm(span=21, adjust=False).mean()
    prev_c = tf["c"].shift(1)
    tr = pd.concat([tf["h"] - tf["l"],
                    (tf["h"] - prev_c).abs(),
                    (tf["l"] - prev_c).abs()], axis=1).max(axis=1)
    tf["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    dates = tf.index.date
    day_id = pd.factorize(dates)[0]
    tf["day_id"] = day_id
    # bars remaining in day including current
    counts = np.bincount(day_id)
    pos_in_day = np.concatenate([np.arange(n) for n in counts])
    tf["bars_left"] = counts[day_id] - pos_in_day
    tf["pos_in_day"] = pos_in_day
    tf["year"] = tf.index.year
    tf["minute_of_day"] = tf.index.hour * 60 + tf.index.minute
    return tf


def prep_arrays(tf, side):
    """Return plain-list arrays; shorts are simulated as longs on negated prices."""
    if side == "long":
        o = tf["o"].tolist(); h = tf["h"].tolist()
        l = tf["l"].tolist(); c = tf["c"].tolist()
        e8 = tf["ema8"].tolist(); e21 = tf["ema21"].tolist()
    else:
        o = (-tf["o"]).tolist(); h = (-tf["l"]).tolist()
        l = (-tf["h"]).tolist(); c = (-tf["c"]).tolist()
        # ribbon filter for shorts: ema8 < ema21  <=>  -ema8 > -ema21
        e8 = (-tf["ema8"]).tolist(); e21 = (-tf["ema21"]).tolist()
    return {
        "o": o, "h": h, "l": l, "c": c, "e8": e8, "e21": e21,
        "atr": tf["atr14"].tolist(),
        "day": tf["day_id"].tolist(),
        "bars_left": tf["bars_left"].tolist(),
        "pos_in_day": tf["pos_in_day"].tolist(),
        "year": tf["year"].tolist(),
        "mod": tf["minute_of_day"].tolist(),
        "n": len(o),
    }


def simulate(arr, entry_mode, filt, exit_mode, stop_mode, collect_trades=False):
    o, h, l, c = arr["o"], arr["h"], arr["l"], arr["c"]
    e8, e21, atr = arr["e8"], arr["e21"], arr["atr"]
    day, bars_left, pos_in_day = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]

    trades = []          # (year, entry_mod, pnl_pts, risk_pts, bars_held)
    in_pos = False
    pending_open_entry = False   # close_confirm: enter at next bar open
    pending_stop_ref = 0.0       # signal candle low for pending entry
    entry_px = stop = risk = 0.0
    target = None
    trail_on = False
    entry_i = 0

    i = WARMUP_BARS
    while i < n:
        if in_pos:
            exited = False
            pnl = 0.0
            # 1) intrabar stop
            if l[i] <= stop:
                fill = stop if o[i] > stop else o[i]
                pnl = fill - entry_px
                exited = True
            # 2) fixed target (stop had priority)
            elif target is not None and h[i] >= target:
                pnl = target - entry_px
                exited = True
            # 3) close-against exit
            elif exit_mode == "close_against" and pos_in_day[i] > 0 and c[i] < l[i - 1]:
                pnl = c[i] - entry_px
                exited = True
            # 4) forced EOD flat
            elif bars_left[i] == 1:
                pnl = c[i] - entry_px
                exited = True

            if exited:
                trades.append((year[entry_i], mod[entry_i], pnl, risk,
                               i - entry_i))
                in_pos = False
                i += 1
                continue

            # update trail after bar completes
            if exit_mode in ("cbc_trail", "target2r_trail"):
                if l[i] > stop:
                    stop = l[i]
            elif exit_mode == "cbc_after_1r":
                if not trail_on and c[i] >= entry_px + risk:
                    trail_on = True
                if trail_on and l[i] > stop:
                    stop = l[i]
            i += 1
            continue

        # ---- flat: handle pending close_confirm entry ----
        if pending_open_entry:
            pending_open_entry = False
            # only if same day continues (bars_left of signal bar > 1 guaranteed)
            entry_px = o[i]
            stop0 = pending_stop_ref
            entry_i = i
            stop, risk, target, trail_on, ok = init_risk(
                entry_px, stop0, atr[i - 1], stop_mode, exit_mode)
            if ok:
                in_pos = True
                # same-bar stop check happens next loop iteration? No --
                # we are IN this bar. Handle same-bar stop conservatively:
                if l[i] <= stop:
                    fill = stop if o[i] > stop else o[i]
                    trades.append((year[i], mod[i], fill - entry_px, risk, 0))
                    in_pos = False
                elif target is not None and h[i] >= target:
                    trades.append((year[i], mod[i], target - entry_px, risk, 0))
                    in_pos = False
                else:
                    if exit_mode in ("cbc_trail", "target2r_trail") and l[i] > stop:
                        stop = l[i]
                    elif exit_mode == "cbc_after_1r":
                        if c[i] >= entry_px + risk:
                            trail_on = True
                            if l[i] > stop:
                                stop = l[i]
            i += 1
            continue

        # ---- flat: look for signals ----
        if pos_in_day[i] == 0 or bars_left[i] <= NO_ENTRY_LAST_N:
            i += 1
            continue

        if entry_mode == "close_confirm":
            if c[i] > h[i - 1] and (filt == "none" or e8[i] > e21[i]) \
                    and bars_left[i] > 1:
                pending_open_entry = True
                pending_stop_ref = l[i]
        else:  # break_stop, signal armed off bar i-1, filled intrabar i
            trigger = h[i - 1] + TICK
            if h[i] >= trigger and (filt == "none" or e8[i - 1] > e21[i - 1]):
                entry_px = trigger if o[i] < trigger else o[i]
                entry_i = i
                stop, risk, target, trail_on, ok = init_risk(
                    entry_px, l[i - 1], atr[i - 1], stop_mode, exit_mode)
                if ok:
                    if l[i] <= stop:  # conservative same-bar stop
                        fill = stop  # entry was intrabar; open-gap case n/a
                        trades.append((year[i], mod[i], fill - entry_px, risk, 0))
                    else:
                        in_pos = True
                        if exit_mode in ("cbc_trail", "target2r_trail") and l[i] > stop:
                            stop = l[i]
                        elif exit_mode == "cbc_after_1r" and c[i] >= entry_px + risk:
                            trail_on = True
                            if l[i] > stop:
                                stop = l[i]
        i += 1

    return trades


def init_risk(entry_px, candle_low, atr_val, stop_mode, exit_mode):
    if stop_mode == "candle_low":
        stop = candle_low - TICK
    elif stop_mode == "atr_0.5":
        stop = entry_px - 0.5 * atr_val
    elif stop_mode == "atr_1.0":
        stop = entry_px - 1.0 * atr_val
    else:
        stop = entry_px - 1.5 * atr_val
    risk = entry_px - stop
    if risk < TICK or not np.isfinite(risk):
        return 0.0, 0.0, None, False, False
    target = entry_px + 2.0 * risk if exit_mode == "target2r_trail" else None
    return stop, risk, target, False, True


def summarize(trades, n_days):
    if not trades:
        return None
    a = np.array([(t[2], t[3], t[4]) for t in trades])
    pnl, risk, bars = a[:, 0], a[:, 1], a[:, 2]
    net = pnl - COST_PTS
    r_net = net / risk
    r_gross = pnl / risk
    years = np.array([t[0] for t in trades])
    yr_r = {}
    for y in np.unique(years):
        yr_r[int(y)] = float(r_net[years == y].sum())
    yr_vals = np.array(list(yr_r.values()))
    cum = np.cumsum(r_net)
    peak = np.maximum.accumulate(cum)
    maxdd = float((peak - cum).max()) if len(cum) else 0.0
    pos = r_net[r_net > 0].sum()
    neg = -r_net[r_net < 0].sum()
    t_stat = float(r_net.mean() / (r_net.std(ddof=1) / np.sqrt(len(r_net)))) \
        if len(r_net) > 2 and r_net.std(ddof=1) > 0 else np.nan
    return {
        "n_trades": len(trades),
        "trades_per_day": round(len(trades) / n_days, 2),
        "win_rate": round(float((net > 0).mean()) * 100, 1),
        "avg_risk_pts": round(float(risk.mean()), 2),
        "avg_bars_held": round(float(bars.mean()), 1),
        "avg_r_gross": round(float(r_gross.mean()), 4),
        "avg_r_net": round(float(r_net.mean()), 4),
        "total_r_net": round(float(r_net.sum()), 1),
        "pf_net": round(float(pos / neg), 3) if neg > 0 else np.inf,
        "t_stat": round(t_stat, 2),
        "max_dd_r": round(maxdd, 1),
        "pos_years_pct": round(float((yr_vals > 0).mean()) * 100, 0),
        "n_years": len(yr_vals),
        "r_net_2008_2019": round(float(r_net[years <= 2019].sum()), 1),
        "r_net_2020_2026": round(float(r_net[years >= 2020].sum()), 1),
    }


def main():
    print("loading 1-min ES data...")
    df1m = load_minute()
    print(f"{len(df1m)} RTH 1-min bars, {df1m.index[0]} -> {df1m.index[-1]}")

    rows = []
    for tf_name, rule in TIMEFRAMES.items():
        tf = build_tf(df1m, rule)
        n_days = tf["day_id"].iloc[-1] + 1
        print(f"\n[{tf_name}] {len(tf)} bars, {n_days} sessions")
        arrs = {side: prep_arrays(tf, side) for side in SIDES}
        for side, entry, filt, exit_mode, stop_mode in itertools.product(
                SIDES, ENTRIES, FILTERS, EXITS, STOPS):
            trades = simulate(arrs[side], entry, filt, exit_mode, stop_mode)
            s = summarize(trades, n_days)
            if s is None:
                continue
            rows.append({"tf": tf_name, "side": side, "entry": entry,
                         "filter": filt, "exit": exit_mode, "stop": stop_mode,
                         **s})
        print(f"[{tf_name}] done ({len(rows)} configs so far)")

    res = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    res.to_csv(OUT_CSV, index=False)
    print(f"\nwrote {len(res)} configs -> {OUT_CSV}")

    pd.set_option("display.width", 250)
    cols = ["tf", "side", "entry", "filter", "exit", "stop", "n_trades",
            "trades_per_day", "win_rate", "avg_r_gross", "avg_r_net",
            "total_r_net", "pf_net", "t_stat", "pos_years_pct",
            "r_net_2008_2019", "r_net_2020_2026"]

    print("\n=== TOP 15 by avg net R/trade (n >= 500) ===")
    top = res[res.n_trades >= 500].sort_values("avg_r_net", ascending=False)
    print(top[cols].head(15).to_string(index=False))

    print("\n=== TOP 15 by total net R (n >= 500) ===")
    top2 = res[res.n_trades >= 500].sort_values("total_r_net", ascending=False)
    print(top2[cols].head(15).to_string(index=False))

    print("\n=== Best per (tf, side) by avg net R ===")
    best = res[res.n_trades >= 500].sort_values("avg_r_net", ascending=False) \
        .groupby(["tf", "side"]).head(1)
    print(best[cols].to_string(index=False))

    print("\n=== GROSS (pre-cost) top 10 — does raw edge exist at all? ===")
    topg = res[res.n_trades >= 500].sort_values("avg_r_gross", ascending=False)
    print(topg[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
