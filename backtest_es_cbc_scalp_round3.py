"""
CBC scalp round 3: 10m CBC confirm + improved entries with 1-min execution.

Pedro's request: after a CBC long confirm on the 10m chart (bar closes above
prior bar's high, ribbon-aligned), instead of buying the next 10m open:
  (a) rest a limit order 2 points below the confirm close
      (also ATR-scaled variants 0.15/0.30 x 10m ATR so it's era-comparable)
  (b) wait for a pullback to the 1-minute EMA 9 / 13 / 21 and enter there

Execution model:
  - Signal at 10m bar close. Entry order works for the next 20 minutes
    (two 10m bars), filled on 1-min data.
  - Order cancelled early if a 1-min close breaks the signal candle's low
    (setup invalidated) before the fill.
  - baseline variant = enter next 10m open (round-1 behaviour) for comparison.
  - After fill: initial stop = signal candle low - 1 tick, or 1.5 x ATR(10m).
    Stop checked on 1-min lows until the current 10m bar completes, then
    management continues on 10m bars: cbc_after_1r trail or close_against.
  - Forced flat at EOD, no entries in the last 3 10m bars, one position at
    a time. Shorts fully mirrored. Costs 0.31 pts RT (limit entries still
    charged full cost — conservative).

Also reports fill rate and the counterfactual: baseline P&L on the SAME
signals split by whether the pullback order would have filled (adverse
selection check).
"""

import os
import numpy as np
import pandas as pd

from backtest_es_cbc_scalp import (
    load_minute, build_tf, TICK, COST_PTS, NO_ENTRY_LAST_N, WARMUP_BARS,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_cbc_scalp_round3.csv")

WINDOW_MIN = 20          # minutes an entry order stays working
ENTRY_VARIANTS = ["baseline", "limit_2pt", "limit_0.15atr", "limit_0.30atr",
                  "ema9", "ema13", "ema21"]
STOPS = ["candle_low", "atr_1.5"]
EXITS = ["cbc_after_1r", "close_against"]


def build_arrays(df1m, side, rule="10min", bar_minutes=10):
    """Signal-TF frame + 1m frame + index mapping, sign-flipped for shorts."""
    tf = build_tf(df1m, rule)
    sgn = 1.0 if side == "long" else -1.0

    m = df1m.between_time("09:30", "15:59").copy()
    for span in (9, 13, 21):
        m[f"ema{span}"] = m["c"].ewm(span=span, adjust=False).mean()

    # map each 10m bar -> [start, end) positions in the 1m frame
    ts10 = tf.index.values
    ts1 = m.index.values
    starts = np.searchsorted(ts1, ts10, side="left")
    ends = np.searchsorted(ts1, ts10 + np.timedelta64(bar_minutes, "m"),
                           side="left")

    def flip(s):
        return (sgn * s).tolist()

    return {
        "o10": flip(tf["o"]), "h10": flip(tf["h" if side == "long" else "l"]),
        "l10": flip(tf["l" if side == "long" else "h"]), "c10": flip(tf["c"]),
        "e8": flip(tf["ema8"]), "e21_10": flip(tf["ema21"]),
        "atr": tf["atr14"].tolist(),
        "day": tf["day_id"].tolist(), "bars_left": tf["bars_left"].tolist(),
        "pos_in_day": tf["pos_in_day"].tolist(),
        "year": tf["year"].tolist(), "mod": tf["minute_of_day"].tolist(),
        "n": len(tf),
        "o1": flip(m["o"]), "h1": flip(m["h" if side == "long" else "l"]),
        "l1": flip(m["l" if side == "long" else "h"]), "c1": flip(m["c"]),
        "ema1": {9: flip(m["ema9"]), 13: flip(m["ema13"]), 21: flip(m["ema21"])},
        "n1": len(m),
        "starts": starts.tolist(), "ends": ends.tolist(),
    }


def try_fill(arr, sig_i, variant, sig_close, sig_low, atr_val):
    """Scan 1m bars for up to WINDOW_MIN minutes after signal bar close.
    Returns (fill_price, minute_pos, bar10_of_fill) or None.
    Cancels if a 1m close breaks the signal candle low first."""
    o1, h1, l1, c1 = arr["o1"], arr["h1"], arr["l1"], arr["c1"]
    day = arr["day"]
    start = arr["ends"][sig_i]          # first 1m bar after signal bar
    stop_scan = min(start + WINDOW_MIN, arr["n1"])

    if variant == "limit_2pt":
        limit = sig_close - 2.0
        ema_span = None
    elif variant == "limit_0.15atr":
        limit = sig_close - 0.15 * atr_val
        ema_span = None
    elif variant == "limit_0.30atr":
        limit = sig_close - 0.30 * atr_val
        ema_span = None
    else:
        limit = None
        ema_span = int(variant[3:])
        ema = arr["ema1"][ema_span]

    # signals require bars_left > 3, so a 20-min window never crosses EOD;
    # the fill bar is either sig_i+1 or sig_i+2
    ends = arr["ends"]
    e_next = ends[sig_i + 1] if sig_i + 1 < arr["n"] else arr["n1"]
    for k in range(start, stop_scan):
        lvl = limit if limit is not None else ema[k]
        if l1[k] <= lvl:
            fill = min(o1[k], lvl)
            j = sig_i + 1 if k < e_next else sig_i + 2
            if j >= arr["n"] or day[j] != day[sig_i]:
                return None
            return fill, k, j
        if c1[k] < sig_low:              # invalidated before fill
            return None
    return None


def simulate3(arr, variant, stop_mode, exit_mode):
    o10, h10, l10, c10 = arr["o10"], arr["h10"], arr["l10"], arr["c10"]
    e8, e21 = arr["e8"], arr["e21_10"]
    atr = arr["atr"]
    day, bars_left, pos_in_day = arr["day"], arr["bars_left"], arr["pos_in_day"]
    year, mod, n = arr["year"], arr["mod"], arr["n"]
    l1, ends = arr["l1"], arr["ends"]

    trades = []   # (year, mod, pnl, risk, bars, signal_i)
    n_signals = 0
    busy_until = -1   # 10m bar index we own until (position/order lifetime)

    for i in range(WARMUP_BARS, n):
        if i <= busy_until:
            continue
        if pos_in_day[i] < 1 or bars_left[i] <= NO_ENTRY_LAST_N:
            continue
        if not (c10[i] > h10[i - 1] and e8[i] > e21[i]):
            continue
        n_signals += 1
        sig_close, sig_low = c10[i], l10[i]
        atr_val = atr[i]

        if variant == "baseline":
            entry_px = o10[i + 1]
            entry_bar = i + 1
            fill_minute = None
        else:
            res = try_fill(arr, i, variant, sig_close, sig_low, atr_val)
            if res is None:
                continue
            entry_px, fill_minute, entry_bar = res
            if bars_left[entry_bar] < 1:
                continue

        if stop_mode == "candle_low":
            stop = sig_low - TICK
        else:
            stop = entry_px - 1.5 * atr_val
        risk = entry_px - stop
        if risk < TICK:
            continue

        # --- 1m stop check for the remainder of the entry 10m bar ---
        stopped = False
        pnl = None
        if fill_minute is not None:
            for k in range(fill_minute, ends[entry_bar]):
                if l1[k] <= stop:
                    pnl = stop - entry_px
                    stopped = True
                    break
        else:
            if l10[entry_bar] <= stop:
                fill = stop if o10[entry_bar] > stop else o10[entry_bar]
                pnl = fill - entry_px
                stopped = True

        if stopped:
            trades.append((year[entry_bar], mod[i], pnl, risk, 0, i))
            busy_until = entry_bar
            continue

        # trail state after entry bar completes
        trail_on = False
        if exit_mode == "cbc_after_1r" and c10[entry_bar] >= entry_px + risk:
            trail_on = True
            if l10[entry_bar] > stop:
                stop = l10[entry_bar]

        # --- manage on 10m bars ---
        j = entry_bar + 1
        while True:
            if l10[j] <= stop:
                fill = stop if o10[j] > stop else o10[j]
                trades.append((year[j], mod[i], fill - entry_px, risk, j - entry_bar, i))
                break
            if exit_mode == "close_against" and c10[j] < l10[j - 1]:
                trades.append((year[j], mod[i], c10[j] - entry_px, risk, j - entry_bar, i))
                break
            if bars_left[j] == 1:
                trades.append((year[j], mod[i], c10[j] - entry_px, risk, j - entry_bar, i))
                break
            if exit_mode == "cbc_after_1r":
                if not trail_on and c10[j] >= entry_px + risk:
                    trail_on = True
                if trail_on and l10[j] > stop:
                    stop = l10[j]
            j += 1
        busy_until = j
    return trades, n_signals


def summarize(trades, n_signals):
    if len(trades) < 50:
        return None
    a = np.array([(t[0], t[2], t[3]) for t in trades])
    pnl, risk = a[:, 1], a[:, 2]
    net_r = (pnl - COST_PTS) / risk
    years = a[:, 0].astype(int)
    yr_vals = np.array([net_r[years == y].sum() for y in np.unique(years)])
    pos = net_r[net_r > 0].sum()
    neg = -net_r[net_r < 0].sum()
    t = float(net_r.mean() / (net_r.std(ddof=1) / np.sqrt(len(net_r)))) \
        if net_r.std(ddof=1) > 0 else np.nan
    return {
        "n_signals": n_signals,
        "n_trades": len(trades),
        "fill_pct": round(100 * len(trades) / n_signals, 1) if n_signals else 0,
        "win_rate": round(float(((pnl - COST_PTS) > 0).mean()) * 100, 1),
        "avg_risk_pts": round(float(risk.mean()), 2),
        "avg_pnl_pts": round(float(pnl.mean()), 3),
        "avg_r_gross": round(float((pnl / risk).mean()), 4),
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
    rows = []
    trade_store = {}
    for side in ("long", "short"):
        arr = build_arrays(df1m, side)
        for variant in ENTRY_VARIANTS:
            for stop_mode in STOPS:
                for exit_mode in EXITS:
                    trades, n_sig = simulate3(arr, variant, stop_mode, exit_mode)
                    s = summarize(trades, n_sig)
                    if s:
                        rows.append({"side": side, "entry": variant,
                                     "stop": stop_mode, "exit": exit_mode, **s})
                    trade_store[(side, variant, stop_mode, exit_mode)] = trades
        print(f"done {side}")

    res = pd.DataFrame(rows)
    res.to_csv(OUT_CSV, index=False)
    print(f"wrote {len(res)} rows -> {OUT_CSV}")

    pd.set_option("display.width", 260)
    cols = ["side", "entry", "stop", "exit", "n_signals", "n_trades",
            "fill_pct", "win_rate", "avg_risk_pts", "avg_pnl_pts",
            "avg_r_gross", "avg_r_net", "total_r_net", "pf_net", "t_stat",
            "pos_years_pct", "r_2008_2019", "r_2020_2026"]

    print("\n=== ALL CONFIGS sorted by avg net R ===")
    print(res.sort_values("avg_r_net", ascending=False)[cols].to_string(index=False))

    # adverse selection: baseline outcome on signals where ema21 pullback filled vs not
    for side in ("long", "short"):
        base = trade_store[(side, "baseline", "candle_low", "cbc_after_1r")]
        pull = trade_store[(side, "ema21", "candle_low", "cbc_after_1r")]
        filled_sigs = set(t[5] for t in pull)
        b_fill = [t for t in base if t[5] in filled_sigs]
        b_nofill = [t for t in base if t[5] not in filled_sigs]
        for lbl, grp in (("pullback-filled", b_fill), ("no-fill", b_nofill)):
            if len(grp) < 50:
                continue
            a = np.array([(t[2], t[3]) for t in grp])
            r = (a[:, 0] - COST_PTS) / a[:, 1]
            print(f"[{side}] baseline on {lbl} signals: n={len(grp)}, "
                  f"avg_r_net={r.mean():.4f}")


if __name__ == "__main__":
    main()
