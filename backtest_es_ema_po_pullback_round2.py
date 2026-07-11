"""
Round 2 for the ES EMA/PO pullback strategy: parameter sweep + filters.

Same signal as backtest_es_ema_po_pullback.py (dual-TF bullish EMA stack,
3m Saty PO compression -> bullish expansion arm, limit entry at 3m EMA9).

Sweeps:
  A. fixed bracket grid: stop {3,4,5,6,8} x target {6,8,10,12,16}
  B. management variants at stop 5: breakeven, arm-then-trail, trail+target
  C. 3-unit MES scale-out (TP1 +4, TP2 +8, runner trails 4 after TP2,
     breakeven after TP1), MES friction 0.52 pts RT per unit
  D. environment filters on the base 5/8 bracket:
     price >= daily Saty put trigger / >= weekly (swing) put trigger / both
     (triggers recomputed Saty-spec from PRIOR period close/ATR14 Wilder)

Costs: ES 0.31 pts RT.  Output: analyst/es_ema_po_pullback_round2.csv
"""

import os
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = "/srv/ftp/ossicones/futures-data/ES_full_1min_continuous_ratio_adjusted.txt"
OUT_CSV = os.path.join(BASE_DIR, "analyst", "es_ema_po_pullback_round2.csv")

COST_ES = 0.31
COST_MES = 0.52          # per MES contract, in pts (higher comm share + slip)
PT_VALUE = 50.0
WARMUP_BARS = 100
WIN1 = (570, 720)        # [09:30, 12:00) ET
WIN2 = (900, 945)        # [15:00, 15:45) ET


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr_df(df, period=14):
    prev_c = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_c).abs(),
                    (df["low"] - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_phase_oscillator(df):
    price = df["close"]
    atr_14 = atr_df(df, 14)
    pivot = ema(price, 21)
    std_21 = price.rolling(21).std()
    raw_signal = ((price - pivot) / (3.0 * atr_14)) * 100
    df["phase_oscillator"] = ema(raw_signal, 3)

    above_pivot = price >= pivot
    bband_up = pivot + 2.0 * std_21
    bband_down = pivot - 2.0 * std_21
    compression_val = np.where(above_pivot,
                               bband_up - (pivot + 2.0 * atr_14),
                               (pivot - 2.0 * atr_14) - bband_down)
    in_exp = np.where(above_pivot,
                      bband_up - (pivot + 1.854 * atr_14),
                      (pivot - 1.854 * atr_14) - bband_down)
    comp_s = pd.Series(compression_val, index=df.index)
    exp_flag = (comp_s.shift(1) <= comp_s).values
    po_comp = np.zeros(len(df), dtype=int)
    for i in range(1, len(df)):
        if exp_flag[i] and in_exp[i] > 0:
            po_comp[i] = 0
        elif compression_val[i] <= 0:
            po_comp[i] = 1
    df["po_compression"] = po_comp
    return df


def build_tf(df1m, rule):
    o = df1m["o"].resample(rule, label="left", closed="left").first()
    h = df1m["h"].resample(rule, label="left", closed="left").max()
    l = df1m["l"].resample(rule, label="left", closed="left").min()
    c = df1m["c"].resample(rule, label="left", closed="left").last()
    tf = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).dropna()
    tf["ema9"] = ema(tf["close"], 9)
    tf["ema21"] = ema(tf["close"], 21)
    return tf


def prep():
    print("loading 1-min ES...", flush=True)
    df = pd.read_csv(DATA, header=None,
                     names=["ts", "o", "h", "l", "c", "v"],
                     parse_dates=["ts"])
    df = df.set_index("ts").sort_index()
    df = df.between_time("09:30", "15:59")
    rng_pct = (df["h"] - df["l"]) / df["c"]
    df = df[rng_pct <= 0.03]

    tf3 = compute_phase_oscillator(build_tf(df, "3min"))
    tf10 = build_tf(df, "10min")

    tf3 = tf3.reset_index().rename(columns={"ts": "start"})
    tf3["end"] = tf3["start"] + pd.Timedelta(minutes=3)
    tf10 = tf10.reset_index().rename(columns={"ts": "start"})
    tf10["end"] = tf10["start"] + pd.Timedelta(minutes=10)
    tf10["s21_10"] = tf10["ema21"].diff()
    tf10["s9_10"] = tf10["ema9"].diff()
    ten = tf10[["end", "ema9", "ema21", "s9_10", "s21_10"]].rename(
        columns={"ema9": "ema9_10", "ema21": "ema21_10"})
    tf3["s21_3"] = tf3["ema21"].diff()
    tf3["s9_3"] = tf3["ema9"].diff()
    tf3 = pd.merge_asof(tf3.sort_values("end"), ten.sort_values("end"),
                        on="end", direction="backward")
    tf3["cond_all"] = (
        (tf3["s21_10"] > 0) &
        (tf3["s9_10"] > 0) & (tf3["ema9_10"] > tf3["ema21_10"]) &
        (tf3["s21_3"] > 0) & (tf3["ema21"] > tf3["ema21_10"]) &
        (tf3["s9_3"] > 0) & (tf3["ema9"] > tf3["ema21"])
    )
    tf3["osc_rising"] = tf3["phase_oscillator"].diff() > 0
    tf3.loc[:WARMUP_BARS, "cond_all"] = False

    m1r = df.reset_index()
    m1r["mod"] = m1r["ts"].dt.hour * 60 + m1r["ts"].dt.minute
    m1r["day"] = pd.factorize(m1r["ts"].dt.date)[0]

    # ---- Saty daily & weekly (swing) put triggers, from PRIOR period ----
    day_ohlc = pd.DataFrame({
        "open": df["o"].resample("1D").first(),
        "high": df["h"].resample("1D").max(),
        "low": df["l"].resample("1D").min(),
        "close": df["c"].resample("1D").last()}).dropna()
    d_atr = atr_df(day_ohlc, 14)
    d_put = (day_ohlc["close"] - 0.236 * d_atr).shift(1)   # applies to NEXT day
    d_put.index = d_put.index.date
    m1r["day_put"] = pd.Series(m1r["ts"].dt.date.map(d_put.to_dict())).values

    wk_ohlc = pd.DataFrame({
        "open": df["o"].resample("W-FRI").first(),
        "high": df["h"].resample("W-FRI").max(),
        "low": df["l"].resample("W-FRI").min(),
        "close": df["c"].resample("W-FRI").last()}).dropna()
    w_atr = atr_df(wk_ohlc, 14)
    w_put = (wk_ohlc["close"] - 0.236 * w_atr).shift(1)
    wk_of = m1r["ts"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
    w_put.index = w_put.index.normalize()
    m1r["wk_put"] = wk_of.map(w_put.to_dict()).values

    idx3 = np.searchsorted(tf3["end"].values, m1r["ts"].values, side="right") - 1

    arrays = {
        "o": m1r["o"].values, "h": m1r["h"].values, "l": m1r["l"].values,
        "ts": m1r["ts"].values,
        "last_of_day": m1r["day"].ne(m1r["day"].shift(-1)).values,
        "in_win": (((m1r["mod"] >= WIN1[0]) & (m1r["mod"] < WIN1[1])) |
                   ((m1r["mod"] >= WIN2[0]) & (m1r["mod"] < WIN2[1]))).values,
        "idx3": idx3,
        "day_put": m1r["day_put"].values.astype(float),
        "wk_put": m1r["wk_put"].values.astype(float),
        "comp": tf3["po_compression"].values,
        "cond": tf3["cond_all"].values,
        "rising": tf3["osc_rising"].values,
        "e9_3": tf3["ema9"].values, "e21_3": tf3["ema21"].values,
        "c3": tf3["close"].values, "l3": tf3["low"].values,
        "end3": tf3["end"].values,
        "n": len(m1r),
    }
    return arrays


IDLE, WATCH, ARMED = 0, 1, 2


def simulate(A, stop_pts, tgt_pts, mgmt="fixed", be_arm=None,
             trail_arm=None, trail_dist=None, filt="none", scaleout=False):
    """mgmt: fixed | be (breakeven at +be_arm) | trail (stop->BE+ratchet
    high-trail_dist once +trail_arm reached). tgt_pts=None -> no target.
    scaleout: 3 units, TP1 +4, TP2 +8, runner BE after TP1 / trail 4 after TP2."""
    o1, h1, l1 = A["o"], A["h"], A["l"]
    ts1, last_of_day, in_win, idx3 = A["ts"], A["last_of_day"], A["in_win"], A["idx3"]
    comp, cond, rising = A["comp"], A["cond"], A["rising"]
    e9_3, e21_3, c3 = A["e9_3"], A["e21_3"], A["c3"]
    day_put, wk_put = A["day_put"], A["wk_put"]
    n = A["n"]

    state, seen3, in_pos = IDLE, -1, False
    trades = []
    entry_px = stop = tgt = hi = 0.0
    units = units_out = 0
    pnl_closed = 0.0
    entry_ts = None

    for i in range(n):
        j = idx3[i]

        if in_pos:
            done = False
            if not scaleout:
                exit_px = None; reason = None
                if last_of_day[i]:
                    exit_px, reason = o1[i], "eod"
                elif l1[i] <= stop:
                    exit_px, reason = min(o1[i], stop), "stop"
                elif tgt is not None and h1[i] >= tgt:
                    exit_px, reason = max(o1[i], tgt), "target"
                if exit_px is None and mgmt in ("be", "trail"):
                    hi = max(hi, h1[i])
                    if mgmt == "be" and hi >= entry_px + be_arm:
                        stop = max(stop, entry_px)
                    elif mgmt == "trail" and hi >= entry_px + trail_arm:
                        stop = max(stop, entry_px, hi - trail_dist)
                if exit_px is not None:
                    trades.append((entry_ts, ts1[i],
                                   exit_px - entry_px - COST_ES, reason))
                    in_pos = False; done = True
            else:
                # 3-unit MES scale-out
                if last_of_day[i]:
                    pnl_closed += units * (o1[i] - entry_px - COST_MES)
                    trades.append((entry_ts, ts1[i], pnl_closed, "eod"))
                    in_pos = False; done = True
                elif l1[i] <= stop:
                    px = min(o1[i], stop)
                    pnl_closed += units * (px - entry_px - COST_MES)
                    trades.append((entry_ts, ts1[i], pnl_closed, "stop"))
                    in_pos = False; done = True
                else:
                    if units_out < 1 and h1[i] >= entry_px + 4:
                        px = max(o1[i], entry_px + 4)
                        pnl_closed += px - entry_px - COST_MES
                        units -= 1; units_out = 1
                        stop = max(stop, entry_px)          # BE after TP1
                    if units_out < 2 and units > 0 and h1[i] >= entry_px + 8:
                        px = max(o1[i], entry_px + 8)
                        pnl_closed += px - entry_px - COST_MES
                        units -= 1; units_out = 2
                    if units_out >= 2:
                        hi = max(hi, h1[i])
                        stop = max(stop, hi - 4)
            if in_pos:
                continue
            if done:
                pass  # fall through to state catch-up, no same-minute re-entry

        if j > seen3:
            for k in range(max(seen3, 0) + 1, j + 1):
                if k < 1:
                    continue
                if comp[k] == 1:
                    state = WATCH
                elif state == WATCH:
                    state = ARMED if (rising[k] and cond[k]) else IDLE
                elif state == ARMED:
                    if (not cond[k]) or (c3[k] < e21_3[k]):
                        state = IDLE
            seen3 = j
            continue_entry = True

        if (not in_pos) and state == ARMED and in_win[i] and j >= 1:
            zone_top = e9_3[j]; zone_bot = e21_3[j]
            if zone_top > zone_bot and l1[i] <= zone_top:
                fill = min(o1[i], zone_top)
                if filt == "day_put" and not (fill >= day_put[i]):
                    continue
                if filt == "wk_put" and not (fill >= wk_put[i]):
                    continue
                if filt == "both" and not (fill >= day_put[i] and fill >= wk_put[i]):
                    continue
                in_pos = True
                entry_px = fill
                stop = fill - stop_pts
                tgt = (fill + tgt_pts) if tgt_pts is not None else None
                hi = fill
                entry_ts = ts1[i]
                pnl_closed = 0.0
                units, units_out = (3, 0) if scaleout else (1, 0)
                state = IDLE

    t = pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "pnl_pts", "reason"])
    return t


def stats(t, label):
    if len(t) == 0:
        return {"config": label, "n": 0}
    t = t.copy()
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    pnl = t["pnl_pts"]
    daily = t.groupby(t["entry_ts"].dt.date)["pnl_pts"].sum()
    tday = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl <= 0].sum()
    eq = pnl.cumsum() * PT_VALUE
    dd = (eq - eq.cummax()).min()
    last6 = t[t["entry_ts"] >= t["entry_ts"].max() - pd.Timedelta(days=182)]
    return {
        "config": label, "n": len(t),
        "win_pct": round((pnl > 0).mean() * 100, 1),
        "avg_pts": round(pnl.mean(), 3),
        "tot_pts": round(pnl.sum(), 1),
        "pf": round(wins / losses, 3) if losses > 0 else np.inf,
        "t_day": round(tday, 2),
        "max_dd_usd": round(dd, 0),
        "n_6m": len(last6),
        "pnl_6m_pts": round(last6["pnl_pts"].sum(), 1),
    }


def main():
    A = prep()
    rows = []

    print("grid A: fixed brackets...", flush=True)
    for sp in [3, 4, 5, 6, 8]:
        for tp in [6, 8, 10, 12, 16]:
            t = simulate(A, sp, tp)
            rows.append(stats(t, f"fixed s{sp}/t{tp}"))
            print(f"  s{sp}/t{tp}: {rows[-1]}", flush=True)

    print("grid B: management variants...", flush=True)
    for label, kw in [
        ("be4 s5/t8", dict(stop_pts=5, tgt_pts=8, mgmt="be", be_arm=4)),
        ("trail a4d4 s5/no-tgt", dict(stop_pts=5, tgt_pts=None, mgmt="trail", trail_arm=4, trail_dist=4)),
        ("trail a4d4 s5/t12", dict(stop_pts=5, tgt_pts=12, mgmt="trail", trail_arm=4, trail_dist=4)),
        ("trail a3d3 s5/t8", dict(stop_pts=5, tgt_pts=8, mgmt="trail", trail_arm=3, trail_dist=3)),
        ("trail a6d6 s5/no-tgt", dict(stop_pts=5, tgt_pts=None, mgmt="trail", trail_arm=6, trail_dist=6)),
    ]:
        t = simulate(A, **kw)
        rows.append(stats(t, label))
        print(f"  {label}: {rows[-1]}", flush=True)

    print("grid C: MES scale-out...", flush=True)
    t = simulate(A, 5, None, scaleout=True)
    rows.append(stats(t, "MES x3 scaleout s5 (pts/contract-sum)"))
    print(f"  {rows[-1]}", flush=True)

    print("grid D: filters on s5/t8...", flush=True)
    for f in ["day_put", "wk_put", "both"]:
        t = simulate(A, 5, 8, filt=f)
        rows.append(stats(t, f"fixed s5/t8 + {f} filter"))
        print(f"  {f}: {rows[-1]}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)
    print("\n", out.to_string(index=False))
    print(f"\nwritten to {OUT_CSV}")


if __name__ == "__main__":
    main()
